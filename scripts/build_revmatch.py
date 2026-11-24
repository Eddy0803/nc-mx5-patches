"""
Downshift rev-match, upshift hold and anti-stall for LFJ1EE (Mazda MX-5 NC, manual).
Hooks only factory code, so it works on a stock LFJ1EE ROM.

Every call (task lists via literals 0x11B00 / 0x134D4, which previously called the pedal copy 0x387F8):
  fr3 = real pedal [FFFF56C8]
  clutch up:   reload hold timer; detect gear from RPM/speed vs RPM-per-km/h table (+-8%), remember it.
  clutch down and Enable, brake (byte at table address == 1), real pedal <= MaxPedal, speed >= MinSpeed,
  hold timer > 0, remembered gear 2..6 with a non-zero table entry for gear-1:
      target = speed * K[gear-1] + Offset, capped at MaxTargetRPM
      pct    = Gain*(target - rpm) - DGain*(rpm - prev_rpm), clamped 0 .. min(MaxPct, 40)
      engine-side pedal [FFFF6CA4] = max(real, pct); flag mirror FFFFAC12 = 1; timer--
  otherwise: [FFFF6CA4] = real; FFFFAC12 = real cruise flag [FFFF585E]
  prev_rpm = rpm (always)
Throttle cross-check: literal 0xB61F0 (only user 0xB5FF0) -> FFFFAC12, as in the blip patch.

RAM (unused by the factory software): AC10 u16 hold timer, AC12 flag mirror, AC13 gear, AC14 f32 previous RPM.
Tables 0xFE300.. (see TBL). Code 0xFE400..
"""
import struct, sys, os, importlib.util

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('sh_asm', os.path.join(here, 'sh_asm.py'))
SA = importlib.util.module_from_spec(spec); spec.loader.exec_module(SA)
spec = importlib.util.spec_from_file_location('chain', os.path.join(here, 'chain.py'))
CH = importlib.util.module_from_spec(spec); spec.loader.exec_module(CH)
Asm = SA.Asm

CODE = 0xFE400
OLD_BLIP = 0xFE200
TBL = {'EN': 0xFE300, 'MAXPCT': 0xFE304, 'PMAX': 0xFE308, 'VMIN': 0xFE30C, 'BRK': 0xFE310, 'MAXT': 0xFE316,
       'GAIN': 0xFE318, 'DGAIN': 0xFE31C, 'OFS': 0xFE320, 'MAXRPM': 0xFE324, 'K': 0xFE328,
       'UPEN': 0xFE340, 'UPOFS': 0xFE344,
       'ASEN': 0xFE350, 'ASRPM': 0xFE354, 'ASGAIN': 0xFE358, 'ASMAX': 0xFE35C, 'ASVMAX': 0xFE360}
DEFAULTS = {'EN': 0.0, 'MAXPCT': 30.0, 'PMAX': 3.0, 'VMIN': 15.0, 'BRK': 0xFFFF70EE, 'MAXT': 270,
            'GAIN': 0.03, 'DGAIN': 0.3, 'OFS': 100.0, 'MAXRPM': 6000.0,
            'K': [113.8, 68.5, 48.3, 36.3, 29.5, 0.0], 'UPEN': 0.0, 'UPOFS': 150.0,
            'ASEN': 0.0, 'ASRPM': 850.0, 'ASGAIN': 0.03, 'ASMAX': 10.0, 'ASVMAX': 20.0}
FLOATS = ('EN', 'MAXPCT', 'PMAX', 'VMIN', 'GAIN', 'DGAIN', 'OFS', 'MAXRPM', 'UPEN', 'UPOFS',
          'ASEN', 'ASRPM', 'ASGAIN', 'ASMAX', 'ASVMAX')
CAP_AS, AS_RUNNING = 20.0, 300.0
CODE_END = 0xFE800
# Anti-stall (runs whenever rev-match is not active): speed <= ASVMAX, rpm > 300 (running, not cranking),
# rpm < ASRPM -> virtual pedal = ASGAIN*(ASRPM - rpm), clamped to min(ASMAX, 20); out = max(real, it).
# Mode while the clutch is down: brake ON  -> downshift: target gear = remembered gear - 1, offset OFS
#                                 brake OFF -> upshift  : target gear = remembered gear + 1, offset UPOFS (needs UPEN > 0)
CAP_PCT, CAP_T, GEAR_TOL = 40.0, 600, 0.08
RAM_STATE, RAM_FLAG = 0xFFFFAC10, 0xFFFFAC12
HOOKS = (0x11B00, 0x134D4)
FLAG_LIT, FLAG_ORIG = 0xB61F0, 0xFFFF585E
TC_CODE, TC_NEXT = 0xFE800, 0xFE3BC          # traction-control patch (build_tc.py)


def assemble():
    a = Asm(CODE)
    W = a.w
    a.lit('movl', 2, 'P_STATE')                       # r2 = &state
    a.lit('movl', 1, 'P_APPIN'); W(0xF318)            # fr3 = real pedal
    a.lit('movl', 1, 'P_RPM'); W(0xF418)              # fr4 = rpm
    a.lit('movl', 1, 'P_VSS'); W(0xF518)              # fr5 = speed
    a.lit('movl', 1, 'P_CLUTCH'); W(0x6010); W(0x8801); a.br('bt', 'CDOWN')
    # ---- clutch up: reload hold timer, detect gear
    a.lit('movl', 1, 'P_MAXT'); W(0x6011); W(0x600D)  # r0 = MaxHold (u16)
    a.lit('movl', 1, 'P_CAPT'); W(0x3016); a.br('bf', 'T1'); W(0x6013)   # if r0 > cap: r0 = cap
    a.L('T1'); W(0x2201)                              # mov.w r0,@r2  timer = r0
    a.lit('mova', 0, 'C_10'); W(0xF008)               # fr0 = 10.0
    W(0xF505); a.br('bf', 'NA1')                      # T = speed > 10 ? (fcmp/gt fr0,fr5)
    W(0xF14C); W(0xF153)                              # fr1 = rpm ; fr1 /= speed  -> ratio
    a.lit('mova', 0, 'C_TOL'); W(0xF708)              # fr7 = 0.08
    a.lit('movl', 1, 'P_K'); W(0xE301)                # r1 = &K[0] ; r3 = 1
    a.L('GLOOP'); W(0xF019)                           # fmov.s @r1+,fr0   K
    W(0xF68D); W(0xF065); a.br('bf', 'GNEXT')         # fldi0 fr6 ; T = K > 0
    W(0xF21C); W(0xF201); W(0xF25D)                   # fr2 = ratio - K ; fabs fr2
    W(0xF60C); W(0xF672)                              # fr6 = K ; fr6 *= tol
    W(0xF625); a.br('bf', 'GNEXT')                    # T = K*tol > |ratio-K|
    W(0x6033); W(0x8023)                              # gear = r3
    a.br('bra', 'NOTACT'); W(0x0009)
    a.L('GNEXT'); W(0x7301); W(0x6033); W(0x8807); a.br('bf', 'GLOOP')   # r3++ ; until 7
    a.L('NA1'); a.br('bra', 'NOTACT'); W(0x0009)      # (also a trampoline for far 'not active' branches below)
    # ---- clutch down
    a.L('CDOWN')
    a.lit('movl', 1, 'P_EN'); W(0xF018); W(0xF18D); W(0xF015); a.br('bf', 'NA1')   # Enable > 0
    a.lit('movl', 1, 'P_BRKTBL'); W(0x6112)           # r1 = brake address
    a.lit('movl', 3, 'P_HIMASK'); W(0x6013); W(0x2039); W(0x3030); a.br('bf', 'NA1')
    W(0x6010); W(0x8801); a.br('bt', 'BRK')           # brake byte == 1 -> downshift mode
    a.lit('movl', 1, 'P_UPEN'); W(0xF018); W(0xF18D); W(0xF015); a.br('bf', 'NA1')   # upshift: UpEnable > 0
    W(0xE300); a.br('bra', 'COMMON'); W(0x0009)       # r3 = 0 (upshift)
    a.L('BRK'); W(0xE301)                             # r3 = 1 (downshift)
    a.L('COMMON')
    a.lit('movl', 1, 'P_PMAX'); W(0xF018); W(0xF305); a.br('bt', 'NA1')   # real pedal > max -> no
    a.lit('movl', 1, 'P_VMIN'); W(0xF018); W(0xF055); a.br('bt', 'NA1')   # min > speed -> no
    W(0x6021); W(0x600D); W(0x2008); a.br('bt', 'NA1')                    # timer == 0 -> no
    W(0x70FF); W(0x2201)                              # timer--
    W(0x8423); W(0x600C)                              # r0 = remembered gear
    W(0x2338); a.br('bt', 'UPG')                      # tst r3,r3 : upshift?
    W(0xE102); W(0x3013); a.br('bf', 'NOTACT')        # down: gear >= 2
    W(0xE106); W(0x3017); a.br('bt', 'NOTACT')        #       gear <= 6
    W(0x70FE); a.br('bra', 'KIDX'); W(0x0009)         #       index = gear-2 (one gear lower)
    a.L('UPG')
    W(0xE101); W(0x3013); a.br('bf', 'NOTACT')        # up:   gear >= 1
    W(0xE105); W(0x3017); a.br('bt', 'NOTACT')        #       gear <= 5 ; index = gear (one gear higher)
    a.L('KIDX'); W(0x4008)                            # r0 = index*4
    a.lit('movl', 1, 'P_K'); W(0x310C); W(0xF018)     # fr0 = K[index]
    W(0xF18D); W(0xF015); a.br('bf', 'NOTACT')        # K > 0 (gear exists)
    W(0xF052)                                         # fr0 = speed * K
    W(0x2338); a.br('bt', 'UOFS')                     # upshift -> UpOffset
    a.lit('movl', 1, 'P_OFS'); a.br('bra', 'AOFS'); W(0x0009)
    a.L('UOFS'); a.lit('movl', 1, 'P_UPOFS')
    a.L('AOFS'); W(0xF118); W(0xF010)                 # + offset
    a.lit('movl', 1, 'P_MAXRPM'); W(0xF118); W(0xF015); a.br('bf', 'TOK'); W(0xF01C)  # cap
    a.L('TOK'); W(0xF041)                             # fr0 = target - rpm
    a.lit('movl', 1, 'P_GAIN'); W(0xF118); W(0xF012)  # fr0 *= gain
    W(0xE004); W(0xF126)                              # fr1 = prev rpm  (@(r0,r2), r0=4)
    W(0xF64C); W(0xF611)                              # fr6 = rpm - prev
    a.lit('movl', 1, 'P_DGAIN'); W(0xF118); W(0xF612); W(0xF061)   # fr0 -= dgain*fr6
    a.lit('movl', 1, 'P_MAXPCT'); W(0xF118)           # fr1 = MaxPct
    a.lit('mova', 0, 'C_CAP'); W(0xF608)              # fr6 = 40
    W(0xF165); a.br('bf', 'M1'); W(0xF16C)            # if MaxPct > 40: MaxPct = 40
    a.L('M1'); W(0xF015); a.br('bf', 'M2'); W(0xF01C) # if pct > max: pct = max
    a.L('M2'); W(0xF18D); W(0xF105); a.br('bf', 'M3'); W(0xF08D)   # if 0 > pct: pct = 0
    a.L('M3'); W(0xF035); a.br('bf', 'ACT'); W(0xF30C)             # out = max(real, pct)
    a.L('ACT'); W(0xE301); a.br('bra', 'MIRROR'); W(0x0009)
    # ---- anti-stall (rev-match not active)
    a.L('NOTACT')
    a.lit('movl', 1, 'P_ASEN'); W(0xF018); W(0xF18D); W(0xF015); a.br('bf', 'NOAS')   # AS enable > 0
    a.lit('movl', 1, 'P_ASVMAX'); W(0xF018); W(0xF505); a.br('bt', 'NOAS')           # speed > max -> no
    a.lit('mova', 0, 'C_RUN'); W(0xF008); W(0xF405); a.br('bf', 'NOAS')              # rpm > 300 (running)
    a.lit('movl', 1, 'P_ASRPM'); W(0xF018); W(0xF041)                                # fr0 = ASRPM - rpm
    W(0xF18D); W(0xF015); a.br('bf', 'NOAS')                                         # dip > 0
    a.lit('movl', 1, 'P_ASGAIN'); W(0xF118); W(0xF012)                               # fr0 *= gain
    a.lit('movl', 1, 'P_ASMAX'); W(0xF118)                                           # fr1 = ASMAX
    a.lit('mova', 0, 'C_ASCAP'); W(0xF608)                                           # fr6 = 20
    W(0xF165); a.br('bf', 'A1'); W(0xF16C)            # ASMAX capped at 20
    a.L('A1'); W(0xF015); a.br('bf', 'A2'); W(0xF01C) # pct capped at ASMAX
    a.L('A2'); W(0xF035); a.br('bf', 'NOAS')          # only if pct > real pedal
    W(0xF30C); W(0xE301); a.br('bra', 'MIRROR'); W(0x0009)   # out = pct ; flag 1
    a.L('NOAS'); a.lit('movl', 1, 'P_CRF'); W(0x6310)              # r3 = real cruise flag
    a.L('MIRROR'); W(0x6033); W(0x8022)               # flag mirror
    W(0xE004); W(0xF247)                              # prev rpm = rpm  (fmov.s fr4,@(r0,r2))
    a.lit('movl', 1, 'P_APPOUT'); W(0x000B); W(0xF13A)   # rts ; [FFFF6CA4] = fr3
    P = lambda v: struct.pack('>I', v); F = lambda v: struct.pack('>f', v)
    a.pool([('P_STATE', P(RAM_STATE)), ('P_APPIN', P(0xFFFF56C8)), ('P_RPM', P(0xFFFF6D5C)), ('P_VSS', P(0xFFFF6D04)),
            ('P_CLUTCH', P(0xFFFF7100)), ('P_MAXT', P(TBL['MAXT'])), ('P_CAPT', P(CAP_T)), ('C_10', F(10.0)),
            ('C_TOL', F(GEAR_TOL)), ('P_K', P(TBL['K'])), ('P_EN', P(TBL['EN'])), ('P_BRKTBL', P(TBL['BRK'])),
            ('P_HIMASK', P(0xFFFF0000)), ('P_PMAX', P(TBL['PMAX'])), ('P_VMIN', P(TBL['VMIN'])), ('P_OFS', P(TBL['OFS'])),
            ('P_MAXRPM', P(TBL['MAXRPM'])), ('P_GAIN', P(TBL['GAIN'])), ('P_DGAIN', P(TBL['DGAIN'])),
            ('P_MAXPCT', P(TBL['MAXPCT'])), ('C_CAP', F(CAP_PCT)), ('P_CRF', P(FLAG_ORIG)), ('P_APPOUT', P(0xFFFF6CA4)),
            ('P_UPEN', P(TBL['UPEN'])), ('P_UPOFS', P(TBL['UPOFS'])),
            ('P_ASEN', P(TBL['ASEN'])), ('P_ASVMAX', P(TBL['ASVMAX'])), ('C_RUN', F(AS_RUNNING)),
            ('P_ASRPM', P(TBL['ASRPM'])), ('P_ASGAIN', P(TBL['ASGAIN'])), ('P_ASMAX', P(TBL['ASMAX'])),
            ('C_ASCAP', F(CAP_AS))])
    code = a.assemble()
    assert CODE + len(code) <= CODE_END, hex(CODE + len(code))
    return code


def write_tables(rom, vals):
    for k in FLOATS:
        rom[TBL[k]:TBL[k] + 4] = struct.pack('>f', vals[k])
    rom[TBL['BRK']:TBL['BRK'] + 4] = struct.pack('>I', int(vals['BRK']))
    rom[0xFE314:0xFE316] = b'\xFF\xFF'
    rom[TBL['MAXT']:TBL['MAXT'] + 2] = struct.pack('>H', int(vals['MAXT']))
    for i, k in enumerate(vals['K']):
        rom[TBL['K'] + 4 * i:TBL['K'] + 4 * i + 4] = struct.pack('>f', k)


def install(rom, table_values=None, keep_common=True):
    """Install into an LFJ1EE ROM (or update an earlier version, keeping its table values)."""
    assert len(rom) == 0x100000 and rom[0xB8046:0xB804C] == b'LFJ1EE', 'not an LFJ1EE ROM'
    # with the traction-control patch the task literals point to TC (0xFE800), which calls our routine through
    # its ROM pointer 0xFE3BC -> update that pointer instead of the literals
    _, hook_sites, _ = CH.walk(rom)          # slots that call the bottom routine (below TC / map switch, if present)
    for lit in hook_sites:
        assert struct.unpack_from('>I', rom, lit)[0] in (0x000387F8, OLD_BLIP, CODE), f'task literal 0x{lit:05X} unexpected'
    assert struct.unpack_from('>I', rom, FLAG_LIT)[0] in (FLAG_ORIG, RAM_FLAG), 'flag literal unexpected'
    assert rom[0x387F8:0x38802] == bytes.fromhex('D32AF338D12A000BF13A'), 'pedal-copy routine differs'
    code = assemble()
    had_blip = struct.unpack_from('>I', rom, hook_sites[0])[0] == OLD_BLIP
    had_rev = struct.unpack_from('>I', rom, hook_sites[0])[0] == CODE
    assert all(b == 0xFF for b in rom[0xFE600:CODE_END]) or had_rev, 'code area not free'
    assert had_rev or all(b == 0xFF for b in rom[CODE:CODE_END]), 'code area not free'
    vals = dict(DEFAULTS)
    if had_rev and keep_common:    # already rev-match (any version): keep every current table value
        for k in FLOATS:
            v = struct.unpack_from('>f', rom, TBL[k])[0]
            if v == v:             # NaN (0xFFFFFFFF, table not present in older version) -> keep default
                vals[k] = v
        vals['BRK'] = struct.unpack_from('>I', rom, TBL['BRK'])[0]
        vals['MAXT'] = struct.unpack_from('>H', rom, TBL['MAXT'])[0]
        vals['K'] = [struct.unpack_from('>f', rom, TBL['K'] + 4 * i)[0] for i in range(6)]
    if had_blip and keep_common:   # keep the settings the user already tuned in the blip patch
        for k in ('EN', 'PMAX', 'VMIN'):
            vals[k] = struct.unpack_from('>f', rom, TBL[k])[0]
        vals['BRK'] = struct.unpack_from('>I', rom, TBL['BRK'])[0]
    vals.update(table_values or {})
    if had_blip:
        rom[OLD_BLIP:0xFE300] = b'\xFF' * 0x100        # remove an earlier one-shot blip version
    rom[0xFE300:0xFE380] = b'\xFF' * 0x80             # 0xFE380.. belongs to the traction-control patch
    rom[CODE:CODE_END] = b'\xFF' * (CODE_END - CODE)   # remove any older rev-match code
    write_tables(rom, vals)
    rom[CODE:CODE + len(code)] = code
    for lit in hook_sites:
        rom[lit:lit + 4] = struct.pack('>I', CODE)
    rom[FLAG_LIT:FLAG_LIT + 4] = struct.pack('>I', RAM_FLAG)
    return had_blip


def build(base_path, outdir):
    rom = bytearray(open(base_path, 'rb').read())
    assert struct.unpack_from('>I', rom, HOOKS[0])[0] == 0x000387F8, 'base already has a blip / rev-match patch'
    orig = bytes(rom)
    install(rom)
    delta = bytearray(a ^ b for a, b in zip(orig, rom)); delta[0:6] = b'LFJ1EE'
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(base_path))[0]
    open(os.path.join(outdir, f'{stem} - revmatch.bin'), 'wb').write(rom)
    open(os.path.join(outdir, 'lfj1ee_downshift_revmatch.patch'), 'wb').write(delta)
    print(f'changed {sum(1 for a, b in zip(orig, rom) if a != b)} bytes; code {len(assemble())} bytes')


if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2])


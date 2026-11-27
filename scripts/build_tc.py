"""
Spark-cut traction control (Mazda MX-5 NC, manual). Hooks only factory code; works on stock and romdrop ROMs.
Needs the ignition cut (build_igncut.py): its shared cut check cuts spark (short dwell + retard, the same cut as the rev
limiter and flat shift) whenever TC Enable (0xFE380) > 0 and the TC flag FFFFAC4B == 1. Without the ignition cut the flag
does nothing.

Task hook: the task-list literals (A['task_literals'], which call the factory pedal copy, or rev-match at 0xFE400 when it
is installed) point to TC (0xFE800). TC first calls the previous target (pointer kept in ROM at 0xFE3BC, NEXT), then:

  rate  = EMA of (rpm - previous rpm) per call:  rate += Alpha * (d - rate)
  clutch down        -> lockout = Lockout calls, gear forgotten, TC off
  lockout > 0        -> lockout--, TC off (lets the revs settle after a shift / launch)
  not holding        -> gear detection: rate < MinRate, speed > 10 and rpm/speed within +-8% of K[g] -> gear = g, age = 0;
                        no match -> age++ (saturates at 128)
  TC allowed only if Enable > 0, speed >= MinSpeed, real pedal >= MinPedal, rpm >= MinRPM, gear 1..6, K[gear] > 0
  threshold = max(K[gear] * MaxAccel(km/h/s), MinRate rpm/s) * CallTime(s)   (rpm per call possible with grip;
              the MinRate floor keeps driveline shunt in 3rd-5th from triggering it)
  rate > threshold and (holding or age <= MaxAge) -> hold = Hold calls (capped at 60 in code)
  hold > 0 -> hold--, flag = 1 (ignition cut), else flag = 0

Rev-match chains underneath it: rev-match installed after TC goes into NEXT instead of the task literals
(build_revmatch.install handles both orders), so every patch keeps running exactly as before.

RAM (zero and unused by stock and romdrop code in RAM dumps; port.py checks every calibration's code):
FFFFAC40 f32 previous rpm, AC44 f32 rate, AC48 u8 gear, AC49 u8 hold, AC4A u8 lockout, AC4B u8 TC flag (read by the
ignition cut), AC4C u8 gear age.  Code 0xFE800-0xFE9FF, tables 0xFE380-0xFE3BF.
"""
import struct, sys, os, importlib.util

here = os.path.dirname(os.path.abspath(__file__))
def _load(name):
    s = importlib.util.spec_from_file_location(name, os.path.join(here, name + '.py'))
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
SA, AD, IG = _load('sh_asm'), _load('addrs'), _load('build_igncut')
Asm = SA.Asm

CODE, CODE_END = 0xFE800, 0xFEA00
REVMATCH = 0xFE400                    # rev-match's code (build_revmatch.CODE)
TBL = {'EN': 0xFE380, 'AMAX': 0xFE384, 'DT': 0xFE388, 'ALPHA': 0xFE38C, 'VMIN': 0xFE390, 'PMIN': 0xFE394,
       'RPMMIN': 0xFE398, 'HOLD': 0xFE39C, 'LOCK': 0xFE39D, 'AGEMAX': 0xFE39E, 'K': 0xFE3A0, 'MINR': 0xFE3B8, 'NEXT': 0xFE3BC}
TBL_START, TBL_END = 0xFE380, 0xFE3C0
FLOATS = ('EN', 'AMAX', 'DT', 'ALPHA', 'VMIN', 'PMIN', 'RPMMIN', 'MINR')
BYTES = ('HOLD', 'LOCK', 'AGEMAX')
DEFAULTS = {'EN': 0.0, 'AMAX': 30.0, 'DT': 0.0055, 'ALPHA': 0.1, 'VMIN': 10.0, 'PMIN': 40.0, 'RPMMIN': 2000.0,
            'MINR': 2500.0, 'HOLD': 18, 'LOCK': 90, 'AGEMAX': 40, 'K': None}          # K: from the address set
LIMITS = {'EN': (0.0, 1.0), 'AMAX': (5.0, 80.0), 'DT': (0.002, 0.02), 'ALPHA': (0.01, 1.0), 'VMIN': (0.0, 100.0),
          'PMIN': (0.0, 100.0), 'RPMMIN': (1000.0, 7500.0), 'MINR': (0.0, 20000.0),     # = the NC Flash scalings' ranges
          'HOLD': (0, 60), 'LOCK': (0, 255), 'AGEMAX': (0, 127)}
CAP_HOLD, GEAR_TOL = 60, 0.08
RAM_STATE = 0xFFFFAC40
RAM = (0xFFFFAC40, 0xFFFFAC4D)
assert RAM_STATE + 11 == IG.TC_RAM_ACT and TBL['EN'] == IG.TC_TBL_EN


def available(A):
    """TC runs from the same task slot as rev-match (the factory pedal copy); a port sets tc_ok False if its RAM is taken"""
    return bool(A.get('task_literals')) and bool(A.get('pedal_copy')) and A.get('tc_ok', True) is not False


def assemble(A=None):
    A = A or AD.LFJ1EE
    a = Asm(CODE)
    W = a.w
    W(0x4F22)                                         # sts.l pr,@-r15
    a.lit('movl', 1, 'P_NEXT'); W(0x6112)             # r1 = [NEXT] previous task target
    W(0x410B); W(0x0009)                              # jsr @r1 (pedal copy / rev-match)
    a.lit('movl', 2, 'P_STATE')                       # r2 = &state
    a.lit('movl', 1, 'P_APP'); W(0xF318)              # fr3 = real pedal
    a.lit('movl', 1, 'P_RPM'); W(0xF418)              # fr4 = rpm
    a.lit('movl', 1, 'P_VSS'); W(0xF518)              # fr5 = speed
    # ---- rate EMA
    W(0xF028)                                         # fr0 = prev rpm
    W(0xF14C); W(0xF101)                              # fr1 = rpm - prev
    W(0xE004); W(0xF626)                              # fr6 = rate   (@(r0,r2), r0 = 4)
    W(0xF664); a.br('bt', 'RNUM'); W(0xF68D)          # NaN guard: if rate != rate -> 0
    a.L('RNUM'); W(0xF161)                            # fr1 = d - rate
    a.lit('movl', 1, 'P_ALPHA'); W(0xF018); W(0xF102); W(0xF610)   # rate += alpha * (d - rate)
    W(0xE004); W(0xF267)                              # store rate
    W(0xF24A)                                         # prev = rpm
    # ---- clutch / lockout
    a.lit('movl', 1, 'P_CLUTCH'); W(0x6010); W(0x8801); a.br('bf', 'CUP')
    a.lit('movl', 1, 'P_LOCK'); W(0x6010); W(0x802A)  # lockout = Lockout
    W(0xE000); W(0x8028)                              # gear = 0
    a.br('bra', 'OFF'); W(0x0009)
    a.L('CUP'); W(0x842A); W(0x600C); W(0x2008); a.br('bt', 'NOLOCK')
    W(0x70FF); W(0x802A); a.br('bra', 'OFF'); W(0x0009)          # lockout--
    a.L('NOLOCK'); W(0x8429); W(0x2008); a.br('bf', 'COND')       # holding -> skip gear detection
    # ---- gear detection (only while rpm changes slower than MinRate: a sweeping rev - neutral, clutch slip, spin -
    #      passes through other gears' ratios and must not re-arm the gear)
    a.lit('movl', 1, 'P_MINR'); W(0xF018); a.lit('movl', 1, 'P_DT'); W(0xF118); W(0xF012)
    W(0xF605); a.br('bt', 'NOMATCH')                  # rate > MinRate*CallTime -> no detection
    a.lit('mova', 0, 'C_10'); W(0xF008); W(0xF505); a.br('bf', 'NOMATCH')   # speed > 10
    W(0xF14C); W(0xF153)                              # fr1 = rpm / speed
    a.lit('mova', 0, 'C_TOL'); W(0xF708)              # fr7 = 0.08
    a.lit('movl', 1, 'P_K'); W(0xE301)                # r1 = &K[0] ; r3 = 1
    a.L('GLOOP'); W(0xF019)                           # fr0 = K, r1 += 4
    W(0xF68D); W(0xF065); a.br('bf', 'GNEXT')         # K > 0
    W(0xF21C); W(0xF201); W(0xF25D)                   # fr2 = |ratio - K|
    W(0xF60C); W(0xF672)                              # fr6 = K * tol
    W(0xF625); a.br('bf', 'GNEXT')                    # K*tol > |ratio - K|
    W(0x6033); W(0x8028)                              # gear = r3
    W(0xE000); W(0x802C)                              # age = 0
    a.br('bra', 'COND'); W(0x0009)
    a.L('GNEXT'); W(0x7301); W(0x6033); W(0x8807); a.br('bf', 'GLOOP')
    a.L('NOMATCH'); W(0x842C); W(0x4011); a.br('bf', 'COND')      # age < 128 ?
    W(0x7001); W(0x802C)                              # age++
    # ---- conditions
    a.L('COND')
    a.lit('movl', 1, 'P_EN'); W(0xF018); W(0xF18D); W(0xF015); a.br('bf', 'OFF')    # Enable > 0
    a.lit('movl', 1, 'P_VMIN'); W(0xF018); W(0xF055); a.br('bt', 'OFF')             # min speed > speed
    a.lit('movl', 1, 'P_PMIN'); W(0xF018); W(0xF035); a.br('bt', 'OFF')             # min pedal > pedal
    a.lit('movl', 1, 'P_RPMMIN'); W(0xF018); W(0xF045); a.br('bt', 'OFF')           # min rpm > rpm
    W(0x8428); W(0x600C)                              # r0 = gear
    W(0xE101); W(0x3012); a.br('bf', 'OFF')           # gear >= 1
    W(0xE106); W(0x3016); a.br('bt', 'OFF')           # gear <= 6
    W(0x70FF); W(0x4008)                              # r0 = (gear-1)*4
    a.lit('movl', 1, 'P_K'); W(0x310C); W(0xF018)     # fr0 = K[gear]
    W(0xF18D); W(0xF015); a.br('bf', 'OFF')           # K > 0
    a.lit('movl', 1, 'P_AMAX'); W(0xF118); W(0xF012)  # fr0 *= MaxAccel   (rpm/s)
    a.lit('movl', 1, 'P_MINR'); W(0xF118); W(0xF105); a.br('bf', 'MR'); W(0xF01C)   # floor: max(fr0, MinRate)
    a.L('MR')
    a.lit('movl', 1, 'P_DT'); W(0xF118); W(0xF012)    # fr0 *= CallTime -> threshold (rpm per call)
    W(0xE004); W(0xF626)                              # fr6 = rate
    W(0xF605); a.br('bf', 'HOLDCHK')                  # rate > threshold ?
    W(0x8429); W(0x2008); a.br('bf', 'TRIG')          # already holding -> retrigger
    a.lit('movl', 1, 'P_AGEMAX'); W(0x6110); W(0x611C)            # r1 = MaxAge
    W(0x842C); W(0x600C); W(0x3016); a.br('bt', 'HOLDCHK')        # age > MaxAge -> gear not trusted
    a.L('TRIG'); a.lit('movl', 1, 'P_HOLD'); W(0x6010); W(0x600C)  # r0 = Hold
    W(0xE13C); W(0x3016); a.br('bf', 'H1'); W(0x6013)              # cap at 60
    a.L('H1'); W(0x8029)                              # hold = r0
    a.L('HOLDCHK'); W(0x8429); W(0x600C); W(0x2008); a.br('bt', 'OFF')
    W(0x70FF); W(0x8029)                              # hold--
    W(0xE301); a.br('bra', 'END'); W(0x0009)          # flag = 1
    a.L('OFF'); W(0xE000); W(0x8029); W(0xE300)       # hold = 0 ; flag = 0
    a.L('END'); W(0x6033); W(0x802B)                  # [AC4B] = flag
    W(0x4F26); W(0x000B); W(0x0009)                   # lds.l @r15+,pr ; rts
    P = lambda v: struct.pack('>I', v); F = lambda v: struct.pack('>f', v)
    a.pool([('P_NEXT', P(TBL['NEXT'])), ('P_STATE', P(RAM_STATE)), ('P_APP', P(A['pedal_in'])), ('P_RPM', P(A['rpm'])),
            ('P_VSS', P(A['speed'])), ('P_ALPHA', P(TBL['ALPHA'])), ('P_CLUTCH', P(A['clutch'])), ('P_LOCK', P(TBL['LOCK'])),
            ('C_10', F(10.0)), ('C_TOL', F(GEAR_TOL)), ('P_K', P(TBL['K'])), ('P_EN', P(TBL['EN'])), ('P_VMIN', P(TBL['VMIN'])),
            ('P_PMIN', P(TBL['PMIN'])), ('P_RPMMIN', P(TBL['RPMMIN'])), ('P_AMAX', P(TBL['AMAX'])), ('P_DT', P(TBL['DT'])),
            ('P_AGEMAX', P(TBL['AGEMAX'])), ('P_MINR', P(TBL['MINR'])), ('P_HOLD', P(TBL['HOLD']))])
    code = a.assemble()
    assert CODE + len(code) <= CODE_END, hex(CODE + len(code))
    return code


def installed(rom, A):
    """TC is in the task chain"""
    return bool(A.get('task_literals')) and struct.unpack_from('>I', rom, A['task_literals'][0])[0] == CODE


def next_target(rom, A):
    """what the task slot runs underneath TC (or directly, without TC)"""
    t = struct.unpack_from('>I', rom, A['task_literals'][0])[0]
    return struct.unpack_from('>I', rom, TBL['NEXT'])[0] if t == CODE else t


def read_tables(rom):
    v = {k: struct.unpack_from('>f', rom, TBL[k])[0] for k in FLOATS}
    v.update({k: rom[TBL[k]] for k in BYTES})
    v['K'] = [struct.unpack_from('>f', rom, TBL['K'] + 4 * i)[0] for i in range(6)]
    return v


def write_tables(rom, vals):
    rom[TBL_START:TBL['NEXT']] = b'\xFF' * (TBL['NEXT'] - TBL_START)
    for k in FLOATS:
        lo, hi = LIMITS[k]; rom[TBL[k]:TBL[k] + 4] = struct.pack('>f', max(lo, min(hi, float(vals[k]))))
    for k in BYTES:
        lo, hi = LIMITS[k]; rom[TBL[k]] = max(lo, min(hi, int(vals[k])))
    for i, k in enumerate(list(vals['K'])[:6] + [0.0] * (6 - len(vals['K']))):
        rom[TBL['K'] + 4 * i:TBL['K'] + 4 * i + 4] = struct.pack('>f', max(0.0, min(400.0, float(k))))


def install(rom, table_values=None, keep_tables=True, A=None):
    """Install / update TC in an LFJ1EE (or ported calibration) ROM (bytearray). Returns notes."""
    assert len(rom) == 0x100000, 'ROM must be 1 MB'
    A = A or AD.for_rom(rom)
    assert AD.is_cal(rom, A), f"not a {A['cal']} ROM"
    AD.assert_not_automatic(rom)
    assert available(A), f"traction control is not available for {A['cal']} (no rev-match task slot; see docs/calibrations.md)"
    assert bytes(rom[A['dwell_site']:A['dwell_site'] + 26]) == AD.dwell_hook(A), \
        'traction control needs the ignition cut installed (it cuts spark through it)'
    hooks, pc = A['task_literals'], A['pedal_copy']
    targets = {struct.unpack_from('>I', rom, lit)[0] for lit in hooks}
    assert len(targets) == 1, 'the task literals point to different places - refusing'
    t = targets.pop()
    had = t == CODE
    if had:
        nxt = struct.unpack_from('>I', rom, TBL['NEXT'])[0]
    else:
        nxt = t
        assert all(b == 0xFF for b in rom[CODE:CODE_END]), 'TC code area 0xFE800-0xFE9FF is not empty - another patch is using it'
        assert all(b == 0xFF for b in rom[TBL_START:TBL_END]), 'TC table area 0xFE380-0xFE3BF is not empty - another patch is using it'
    assert nxt in (pc, REVMATCH), f'unexpected task target 0x{nxt:08X} - refusing'
    if nxt == pc:
        assert rom[pc:pc + len(bytes.fromhex(A['pedal_copy_orig']))] == bytes.fromhex(A['pedal_copy_orig']), 'pedal-copy routine differs'
    vals = dict(DEFAULTS); vals['K'] = list(A['gears'])
    if had and keep_tables:
        cur = read_tables(rom)
        for k in FLOATS:
            if cur[k] == cur[k] and LIMITS[k][0] <= cur[k] <= LIMITS[k][1]: vals[k] = cur[k]
        for k in BYTES:
            if LIMITS[k][0] <= cur[k] <= LIMITS[k][1]: vals[k] = cur[k]
        if all(k == k and 0 <= k <= 400 for k in cur['K']): vals['K'] = cur['K']
        notes = ['traction control already installed: code refreshed, settings kept']
    else:
        notes = [f'traction control installed (runs before {"rev-match" if nxt == REVMATCH else "the pedal copy"})']
    vals.update(table_values or {})
    write_tables(rom, vals)
    rom[CODE:CODE_END] = b'\xFF' * (CODE_END - CODE)
    code = assemble(A); rom[CODE:CODE + len(code)] = code
    rom[TBL['NEXT']:TBL['NEXT'] + 4] = struct.pack('>I', nxt)
    for lit in hooks:
        rom[lit:lit + 4] = struct.pack('>I', CODE)
    return notes


def remove(rom, A=None):
    """take TC out of the chain and erase it (whatever ran underneath it keeps running)"""
    A = A or AD.for_rom(rom)
    if not installed(rom, A): return False
    nxt = struct.unpack_from('>I', rom, TBL['NEXT'])[0]
    for lit in A['task_literals']:
        rom[lit:lit + 4] = struct.pack('>I', nxt)
    rom[TBL_START:TBL_END] = b'\xFF' * (TBL_END - TBL_START)
    rom[CODE:CODE_END] = b'\xFF' * (CODE_END - CODE)
    return True


def main(argv):
    """python build_tc.py <your.bin> [EN=1 AMAX=30 ...]   install / update TC (keeps your settings), or
       python build_tc.py <your.bin> remove                take it out again.
    There is no .patch file for TC: it shares the task slot with rev-match, so the bytes it changes depend on what is
    already installed. Writes "<your> - tc.bin" / "<your> - no tc.bin" next to the input; never changes the input."""
    if len(argv) < 2: sys.exit(main.__doc__)
    src = argv[1]; rom = bytearray(open(src, 'rb').read()); A = AD.for_rom(rom)
    if argv[2:] == ['remove']:
        if not remove(rom, A): sys.exit('this ROM has no traction control')
        out = os.path.splitext(src)[0] + ' - no tc.bin'
    else:
        vals = {}
        for kv in argv[2:]:
            k, v = kv.split('=', 1); k = k.upper()
            if k not in TBL or k in ('NEXT', 'K'): sys.exit(f'unknown table {k} (one of {", ".join(FLOATS + BYTES)})')
            vals[k] = float(v) if k in FLOATS else int(v)
        print('\n'.join(install(rom, vals, A=A)))
        out = os.path.splitext(src)[0] + ' - tc.bin'
    if os.path.exists(out): sys.exit(f'{out} already exists - move it first')
    open(out, 'wb').write(rom); print(f'wrote {out}')


if __name__ == '__main__':
    main(sys.argv)

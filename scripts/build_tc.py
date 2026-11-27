"""
Spark-cut traction control, v2: real wheel slip (Mazda MX-5 NC, manual). Hooks only factory code; works on stock and
romdrop ROMs.

Wheel speeds: the ABS unit sends all four wheel speeds to the ECU on CAN 0x4B0 (FL, FR, RL, RR; u16 each, km/h * 100 +
10000). The factory receive code copies all 8 bytes into a RAM buffer (A['wheel_speeds'], LFJ1EE FFFF6A80) and uses only
the rear two; TC reads all four there. The front wheels aren't driven, so they give the road speed.

Cut: the ignition cut (build_igncut.py) is needed. Its shared cut check cuts spark (short dwell + retard, the same cut as
the rev limiter and flat shift) whenever TC Enable (0xFE380) > 0 and the TC flag FFFFAC4B == 1.

Every call (task slot, ~5.5 ms; TC first runs what the slot ran before - rev-match or the pedal copy - via NEXT 0xFE3BC):
  stale:   the 8 wheel-speed bytes haven't changed for 100 calls (~0.55 s: CAN lost)        -> off
  clutch down -> lockout = Lockout calls, off;  lockout > 0 -> lockout--, off
  off unless Enable > 0, brake off, real pedal >= MinPedal, rpm >= MinRPM, every wheel speed valid (< 0xFFFE)
  front = (FL + FR) / 2;  off below MinSpeed (front; wheel sensors read 0 at walking pace, so launches start above it)
  slip  = max(RL - FL, RR - FR)          per side: a corner (outer wheels faster than inner) doesn't look like slip
  allowed = SlipKmh + SlipPct% * front   (km/h: a fixed margin plus a share of road speed)
  slip > allowed -> hold = Hold calls (capped at 60 in code), flag = 1
  else hold > 0 -> hold--, flag = 1;  else flag = 0

Rev-match chains underneath it (build_revmatch.install handles both install orders).
RAM (zero and unused by stock and romdrop code; port.py checks every calibration): FFFFAC40 u32 wheel-bytes signature,
AC44 u16 unchanged-calls counter, AC49 u8 hold, AC4A u8 lockout, AC4B u8 TC flag (read by the ignition cut).
Code 0xFE800-0xFE9FF, tables 0xFE380-0xFE3BF (FE39E = layout version 2).
v1 (0.9.29-0.9.30) detected slip from how fast the revs rose; installing v2 over it keeps Enable and changed pedal / rpm
settings, and resets the rest to the v2 defaults.
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
# two-path throttle software (address set has pedal_copy2 / task_literals2): TC's second entry, for the second task list,
# calls what that list ran before through NEXT2 (the second factory copy, or rev-match's second entry), then runs the same
# TC code (shared state, so it runs from both lists at LFJ1EE's rate)
ENTRY2, NEXT2 = 0xFE9C0, 0xFE3B8
REVMATCH2 = 0xFE7C0                   # rev-match's second entry (build_revmatch.ENTRY2)
TBL = {'EN': 0xFE380, 'SLIPKMH': 0xFE384, 'SLIPPCT': 0xFE388, 'VMIN': 0xFE390, 'PMIN': 0xFE394, 'RPMMIN': 0xFE398,
       'HOLD': 0xFE39C, 'LOCK': 0xFE39D, 'VER': 0xFE39E, 'NEXT': 0xFE3BC}
TBL_START, TBL_END = 0xFE380, 0xFE3C0
FLOATS = ('EN', 'SLIPKMH', 'SLIPPCT', 'VMIN', 'PMIN', 'RPMMIN')
BYTES = ('HOLD', 'LOCK')
VERSION = 2
DEFAULTS = {'EN': 0.0, 'SLIPKMH': 3.0, 'SLIPPCT': 10.0, 'VMIN': 5.0, 'PMIN': 20.0, 'RPMMIN': 2000.0, 'HOLD': 9, 'LOCK': 20}
LIMITS = {'EN': (0.0, 1.0), 'SLIPKMH': (0.0, 30.0), 'SLIPPCT': (0.0, 50.0), 'VMIN': (2.0, 100.0), 'PMIN': (0.0, 100.0),
          'RPMMIN': (1000.0, 7500.0), 'HOLD': (0, 60), 'LOCK': (0, 255)}              # = the NC Flash scalings' ranges
V1_DEFAULTS = {'PMIN': 40.0, 'RPMMIN': 2000.0}     # a v1 value different from these was set by the user: kept on upgrade
CAP_HOLD, STALE_CALLS = 60, 100
RAM_STATE = 0xFFFFAC40
RAM = (0xFFFFAC40, 0xFFFFAC4D)
assert RAM_STATE + 11 == IG.TC_RAM_ACT and TBL['EN'] == IG.TC_TBL_EN


def available(A):
    """same task slot as rev-match (the factory pedal copy), and the CAN wheel-speed buffer; a port sets tc_ok False if
    TC's RAM is used by that calibration's code"""
    return (bool(A.get('task_literals')) and bool(A.get('pedal_copy')) and bool(A.get('wheel_speeds'))
            and A.get('tc_ok', True) is not False)


def dual(A):
    return bool(A.get('pedal_copy2') and A.get('task_literals2'))


def assemble2(A):
    """second entry (two-path software): r1 = &NEXT2, then the shared TC code"""
    code, labels = _assemble(A)
    assert CODE + len(code) <= ENTRY2, 'TC code overlaps its second entry'
    a = Asm(ENTRY2); W = a.w
    a.labels['CALLN'] = labels['CALLN']
    W(0x4F22); a.lit('movl', 1, 'P_NEXT2'); a.br('bra', 'CALLN'); W(0x0009)
    a.pool([('P_NEXT2', struct.pack('>I', NEXT2))])
    stub = a.assemble()
    assert ENTRY2 + len(stub) <= CODE_END
    return stub


def assemble(A=None):
    return _assemble(A)[0]


def _assemble(A=None):
    A = A or AD.LFJ1EE
    a = Asm(CODE)
    W = a.w
    W(0x4F22)                                         # sts.l pr,@-r15
    a.lit('movl', 1, 'P_NEXT')
    a.L('CALLN'); W(0x6112)                           # r1 = [NEXT] previous task target (second entry joins here)
    W(0x410B); W(0x0009)                              # jsr @r1 (pedal copy / rev-match)
    a.lit('movl', 2, 'P_STATE')                       # r2 = &state (AC40)
    a.lit('movl', 3, 'P_WS')                          # r3 = &wheel-speed bytes
    # ---- stale check: signature = sum of the two 32-bit halves of the 8 wheel bytes
    W(0x6032); W(0x5131); W(0x301C)                   # r0 = [r3] + [r3+4]
    W(0x6122); W(0x3010); a.br('bt', 'SAME')          # same as last call?
    W(0x2202); W(0xE000); W(0x8122)                   # signature = r0 ; counter = 0
    a.br('bra', 'FRESH'); W(0x0009)
    a.L('SAME'); W(0x8522); W(0x600D)                 # r0 = counter
    W(0xE164); W(0x3012); a.br('bt', 'OFF')           # >= 100 calls unchanged -> CAN lost: off
    W(0x7001); W(0x8122)                              # counter++
    a.L('FRESH')
    # ---- clutch / lockout
    a.lit('movl', 1, 'P_CLUTCH'); W(0x6010); W(0x8801); a.br('bf', 'CUP')
    a.lit('movl', 1, 'P_LOCK'); W(0x6010); W(0x802A)  # lockout = Lockout
    a.br('bra', 'OFF'); W(0x0009)
    a.L('CUP'); W(0x842A); W(0x600C); W(0x2008); a.br('bt', 'NOLOCK')
    W(0x70FF); W(0x802A); a.br('bra', 'OFF'); W(0x0009)          # lockout--
    a.L('NOLOCK')
    # ---- conditions
    a.lit('movl', 1, 'P_EN'); W(0xF018); W(0xF18D); W(0xF015); a.br('bf', 'OFF')        # Enable > 0
    a.lit('movl', 1, 'P_BRAKE'); W(0x6010); W(0x8801); a.br('bt', 'OFF')                  # brake pressed
    a.lit('movl', 1, 'P_APP'); W(0xF318); a.lit('movl', 1, 'P_PMIN'); W(0xF018); W(0xF035); a.br('bt', 'OFF')     # MinPedal > pedal
    a.lit('movl', 1, 'P_RPM'); W(0xF418); a.lit('movl', 1, 'P_RPMMIN'); W(0xF018); W(0xF045); a.br('bt', 'OFF')   # MinRPM > rpm
    # ---- the four wheel speeds (raw: km/h * 100 + 10000) -> fr4 FL, fr5 FR, fr6 RL, fr7 RR; any >= 0xFFFE = invalid
    a.lit('movl', 1, 'C_FFFE')
    for k, fr in enumerate((4, 5, 6, 7)):
        W(0x8530 | k); W(0x600D)                      # r0 = u16 @(2k,r3)
        W(0x3012); a.br('bt', 'OFF')                  # r0 >= 0xFFFE -> invalid
        W(0x405A); W(0xF02D | fr << 8)                # fpul = r0 ; frN = float(fpul)
    # ---- slip per side (raw units = km/h * 100; the offset cancels)
    W(0xF641); W(0xF751)                              # fr6 = RL - FL ; fr7 = RR - FR
    W(0xF765); a.br('bf', 'S1'); W(0xF67C)            # fr6 = max(fr6, fr7)
    a.L('S1')
    W(0xF450)                                         # fr4 = FL + FR
    a.lit('mova', 0, 'C_HALF'); W(0xF008); W(0xF402)  # fr4 *= 0.5
    a.lit('mova', 0, 'C_OFS'); W(0xF008); W(0xF401)   # fr4 -= 10000 -> front speed * 100
    a.lit('mova', 0, 'C_100'); W(0xF108)              # fr1 = 100
    a.lit('movl', 1, 'P_VMIN'); W(0xF018); W(0xF012)  # fr0 = MinSpeed * 100
    W(0xF045); a.br('bt', 'OFF')                      # MinSpeed > front -> off
    a.lit('movl', 1, 'P_PCT'); W(0xF018); W(0xF042)   # fr0 = SlipPct * front100
    a.lit('mova', 0, 'C_001'); W(0xF208); W(0xF022)   # fr0 *= 0.01  -> (pct share) * 100
    a.lit('movl', 1, 'P_KMH'); W(0xF218); W(0xF212)   # fr2 = SlipKmh * 100
    W(0xF020)                                         # fr0 = allowed slip * 100
    W(0xF605); a.br('bf', 'HOLDCHK')                  # slip > allowed ?
    a.lit('movl', 1, 'P_HOLD'); W(0x6010); W(0x600C)  # r0 = Hold
    W(0xE13C); W(0x3016); a.br('bf', 'H1'); W(0x6013) # cap at 60
    a.L('H1'); W(0x8029)                              # hold = r0
    W(0xE301); a.br('bra', 'END'); W(0x0009)          # flag = 1
    a.L('HOLDCHK'); W(0x8429); W(0x600C); W(0x2008); a.br('bt', 'OFF')
    W(0x70FF); W(0x8029)                              # hold--
    W(0xE301); a.br('bra', 'END'); W(0x0009)          # flag = 1
    a.L('OFF'); W(0xE000); W(0x8029); W(0xE300)       # hold = 0 ; flag = 0
    a.L('END'); W(0x6033); W(0x802B)                  # [AC4B] = flag
    W(0x4F26); W(0x000B); W(0x0009)                   # lds.l @r15+,pr ; rts
    P = lambda v: struct.pack('>I', v); F = lambda v: struct.pack('>f', v)
    a.pool([('P_NEXT', P(TBL['NEXT'])), ('P_STATE', P(RAM_STATE)), ('P_WS', P(A['wheel_speeds'])),
            ('P_CLUTCH', P(A['clutch'])), ('P_LOCK', P(TBL['LOCK'])), ('P_EN', P(TBL['EN'])), ('P_BRAKE', P(A['brake'])),
            ('P_APP', P(A['pedal_in'])), ('P_PMIN', P(TBL['PMIN'])), ('P_RPM', P(A['rpm'])), ('P_RPMMIN', P(TBL['RPMMIN'])),
            ('C_FFFE', P(0xFFFE)), ('C_HALF', F(0.5)), ('C_OFS', F(10000.0)), ('C_100', F(100.0)), ('P_VMIN', P(TBL['VMIN'])),
            ('P_PCT', P(TBL['SLIPPCT'])), ('C_001', F(0.01)), ('P_KMH', P(TBL['SLIPKMH'])), ('P_HOLD', P(TBL['HOLD']))])
    code = a.assemble()
    assert CODE + len(code) <= CODE_END, hex(CODE + len(code))
    return code, dict(a.labels)


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
    v['VER'] = rom[TBL['VER']]
    return v


def write_tables(rom, vals):
    rom[TBL_START:TBL['NEXT']] = b'\xFF' * (TBL['NEXT'] - TBL_START)          # also erases v1's unused tables
    for k in FLOATS:
        lo, hi = LIMITS[k]; rom[TBL[k]:TBL[k] + 4] = struct.pack('>f', max(lo, min(hi, float(vals[k]))))
    for k in BYTES:
        lo, hi = LIMITS[k]; rom[TBL[k]] = max(lo, min(hi, int(vals[k])))
    rom[TBL['VER']] = VERSION


def install(rom, table_values=None, keep_tables=True, A=None):
    """Install / update TC in an LFJ1EE (or ported calibration) ROM (bytearray). Returns notes."""
    assert len(rom) == 0x100000, 'ROM must be 1 MB'
    A = A or AD.for_rom(rom)
    assert AD.is_cal(rom, A), f"not a {A['cal']} ROM"
    AD.assert_not_automatic(rom)
    assert available(A), f"traction control is not available for {A['cal']} (see docs/calibrations.md)"
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
    two = dual(A)
    if two:
        hooks2, pc2 = A['task_literals2'], A['pedal_copy2']
        t2 = {struct.unpack_from('>I', rom, lit)[0] for lit in hooks2}
        assert len(t2) == 1, 'the second task list literals point to different places - refusing'
        t2 = t2.pop()
        assert (t2 == ENTRY2) == had, 'traction control is only in one of the two task lists - refusing'
        nxt2 = struct.unpack_from('>I', rom, NEXT2)[0] if had else t2
        assert nxt2 in (pc2, REVMATCH2) and (nxt2 == REVMATCH2) == (nxt == REVMATCH), \
            f'unexpected second task target 0x{nxt2:08X} - refusing'
        if nxt2 == pc2:
            assert rom[pc2:pc2 + len(bytes.fromhex(A['pedal_copy2_orig']))] == bytes.fromhex(A['pedal_copy2_orig']), \
                'second pedal-copy routine differs'
    vals = dict(DEFAULTS)
    if had and keep_tables:
        cur = read_tables(rom)
        if cur['VER'] == VERSION:                     # v2: keep every valid setting
            for k in FLOATS + BYTES:
                if cur[k] == cur[k] and LIMITS[k][0] <= cur[k] <= LIMITS[k][1]: vals[k] = cur[k]
            notes = ['traction control already installed: code refreshed, settings kept']
        else:                                         # v1 (rev-rise detection): keep what still means the same
            if cur['EN'] == cur['EN'] and 0 <= cur['EN'] <= 1: vals['EN'] = cur['EN']
            for k, d in V1_DEFAULTS.items():
                if cur[k] == cur[k] and LIMITS[k][0] <= cur[k] <= LIMITS[k][1] and abs(cur[k] - d) > 1e-6: vals[k] = cur[k]
            notes = ['traction control upgraded to wheel-slip detection (v2): on/off kept, new slip settings at their defaults']
    else:
        notes = [f'traction control installed (runs before {"rev-match" if nxt == REVMATCH else "the pedal copy"})']
    vals.update(table_values or {})
    write_tables(rom, vals)
    rom[CODE:CODE_END] = b'\xFF' * (CODE_END - CODE)
    code = assemble(A); rom[CODE:CODE + len(code)] = code
    rom[TBL['NEXT']:TBL['NEXT'] + 4] = struct.pack('>I', nxt)
    for lit in hooks:
        rom[lit:lit + 4] = struct.pack('>I', CODE)
    if two:
        stub = assemble2(A); rom[ENTRY2:ENTRY2 + len(stub)] = stub
        rom[NEXT2:NEXT2 + 4] = struct.pack('>I', nxt2)
        for lit in hooks2:
            rom[lit:lit + 4] = struct.pack('>I', ENTRY2)
    return notes


def remove(rom, A=None):
    """take TC out of the chain and erase it (whatever ran underneath it keeps running)"""
    A = A or AD.for_rom(rom)
    if not installed(rom, A): return False
    nxt = struct.unpack_from('>I', rom, TBL['NEXT'])[0]
    for lit in A['task_literals']:
        rom[lit:lit + 4] = struct.pack('>I', nxt)
    if dual(A):
        nxt2 = struct.unpack_from('>I', rom, NEXT2)[0]
        for lit in A['task_literals2']:
            rom[lit:lit + 4] = struct.pack('>I', nxt2)
    rom[TBL_START:TBL_END] = b'\xFF' * (TBL_END - TBL_START)
    rom[CODE:CODE_END] = b'\xFF' * (CODE_END - CODE)
    return True


def main(argv):
    """python build_tc.py <your.bin> [EN=1 SLIPKMH=3 SLIPPCT=10 ...]   install / update TC (keeps your settings), or
       python build_tc.py <your.bin> remove                             take it out again.
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
            if k not in FLOATS + BYTES: sys.exit(f'unknown table {k} (one of {", ".join(FLOATS + BYTES)})')
            vals[k] = float(v) if k in FLOATS else int(v)
        print('\n'.join(install(rom, vals, A=A)))
        out = os.path.splitext(src)[0] + ' - tc.bin'
    if os.path.exists(out): sys.exit(f'{out} already exists - move it first')
    open(out, 'wb').write(rom); print(f'wrote {out}')


if __name__ == '__main__':
    main(sys.argv)

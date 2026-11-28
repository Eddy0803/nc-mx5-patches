"""
Traction control, v3: real wheel slip, scaled intervention (Mazda MX-5 NC, manual). Hooks only factory code; works on
stock and romdrop ROMs. Never a full cut.

Wheel speeds: the ABS unit sends all four wheel speeds to the ECU on CAN 0x4B0 (FL, FR, RL, RR; u16 each, km/h * 100 +
10000). The factory receive code copies all 8 bytes into a RAM buffer (A['wheel_speeds'], LFJ1EE FFFF6A80) and uses only
the rear two; TC reads all four there. The front wheels aren't driven, so they give the road speed.

The ignition cut (build_igncut.py) is needed: its shared cut check drops the spark (short dwell + retard) whenever TC
Enable (0xFE380) > 0 and the TC cut flag FFFFAC4B == 1, and TC's timing hook (SPARK, 0xFEA00) sits in front of its
spark-advance RETARD (the spark literal points to SPARK, which calls RETARD and then subtracts TC's timing pull).

Every call (task slot, ~5.5 ms; TC first runs what the slot ran before - rev-match or the pedal copy - via NEXT 0xFE3BC):
  stale:   the 8 wheel-speed bytes haven't changed for 100 calls (~0.55 s: CAN lost)        -> off
  clutch down -> lockout = Lockout calls, off;  lockout > 0 -> lockout--, off
  off unless Enable > 0, brake off, real pedal >= MinPedal, rpm >= MinRPM, every wheel speed valid (< 0xFFFE)
  front = (FL + FR) / 2;  off below MinSpeed (front; wheel sensors read 0 at walking pace, so launches start above it)
  slip  = max(RL - FL, RR - FR)          per side: a corner (outer wheels faster than inner) doesn't look like slip
  allowed = SlipKmh + SlipPct% * front   (km/h: a fixed margin plus a share of road speed; at least 1 km/h)
  then SCALE (0xFEA00 block):
  rest > 0 (after Max Intervention Time) -> off; rest counts down whenever TC is off
  target = clamp((slip / allowed - 1) / Full, 0, 1) * 255;  level = max(target, level - EaseOff)  (rises at once, eases off)
  level 0 -> idle.  Intervention calls + 1; more than Max Time -> rest = Rest calls, off
  timing:   SPARK pulls Timing Pull * level / 255 deg on every spark (capped at 10)
  sparks:   above Cut Start, share = (level - start) / (1 - start); q = share * 128 into an 8-bit counter, overflow =
            drop this call's spark. q <= 128, so at most 1 call in 2 and never two in a row: never a full cut
  throttle: engine-side pedal *= 1 - Throttle% * level / 255 (capped at 50%), after the factory pedal copy / rev-match
  off: level, counters, cut flag = 0 (no timing pulled, throttle untouched)

Rev-match chains underneath it (build_revmatch.install handles both install orders).
RAM (zero and unused by stock and romdrop code; port.py checks every calibration): FFFFAC40 u32 wheel-bytes signature,
AC44 u16 unchanged-calls counter, AC46 u8 intervention calls, AC47 u8 rest, AC48 u8 spark-cut counter, AC49 u8 level,
AC4A u8 lockout, AC4B u8 cut flag (read by the ignition cut), AC4C u8 level (read by SPARK).
Code 0xFE800-0xFE9FF and 0xFEA00-0xFEBFF, tables 0xFE380-0xFE3BF (FE39E = layout version 3).
v2 (0.9.31-0.9.41) cut every spark while slipping: installing v3 over it keeps Enable, the slip, condition and lockout
settings; its Hold (FE39C) is erased and the new settings start at their defaults.
v1 (0.9.29-0.9.30) detected slip from how fast the revs rose; installing over it keeps Enable and changed pedal / rpm
settings, and resets the rest to the defaults.
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
       'LOCK': 0xFE39D, 'VER': 0xFE39E, 'MAXACT': 0xFE3A0, 'REST': 0xFE3A1, 'DECAY': 0xFE3A2, 'TRET': 0xFE3A4,
       'FULL': 0xFE3A8, 'CUTST': 0xFE3AC, 'THR': 0xFE3B0, 'NEXT': 0xFE3BC}
TBL_START, TBL_END = 0xFE380, 0xFE3C0
FLOATS = ('EN', 'SLIPKMH', 'SLIPPCT', 'VMIN', 'PMIN', 'RPMMIN', 'TRET', 'FULL', 'CUTST', 'THR')
BYTES = ('LOCK', 'MAXACT', 'REST', 'DECAY')
VERSION = 3
SAME_LAYOUT = (2, 3)               # v2's slip, condition and lockout settings mean the same in v3 (v2's Hold is gone)
SPK, SPK_END = 0xFEA00, 0xFEC00     # timing hook + the scaled-intervention code
CAP_TRET, CAP_THR = 10.0, 50.0
assert SPK == IG.TC_SPARK
DEFAULTS = {'EN': 0.0, 'SLIPKMH': 3.0, 'SLIPPCT': 10.0, 'VMIN': 5.0, 'PMIN': 20.0, 'RPMMIN': 2000.0, 'LOCK': 20,
            'MAXACT': 180, 'REST': 30, 'DECAY': 4, 'TRET': 6.0, 'FULL': 1.0, 'CUTST': 40.0, 'THR': 25.0}
LIMITS = {'EN': (0.0, 1.0), 'SLIPKMH': (0.0, 30.0), 'SLIPPCT': (0.0, 50.0), 'VMIN': (2.0, 100.0), 'PMIN': (0.0, 100.0),
          'RPMMIN': (1000.0, 7500.0), 'LOCK': (0, 255),
          'MAXACT': (20, 255), 'REST': (5, 120), 'DECAY': (1, 50), 'TRET': (0.0, CAP_TRET), 'FULL': (0.2, 5.0),
          'CUTST': (0.0, 95.0), 'THR': (0.0, CAP_THR)}              # = the NC Flash scalings' ranges
V2_KEEP = ('EN', 'SLIPKMH', 'SLIPPCT', 'VMIN', 'PMIN', 'RPMMIN', 'LOCK')
V1_DEFAULTS = {'PMIN': 40.0, 'RPMMIN': 2000.0}     # a v1 value different from these was set by the user: kept on upgrade
STALE_CALLS = 100
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


def assemble_spark(A=None):
    """the 0xFEA00 block: SPARK (timing hook in front of the ignition cut's RETARD) and SCALE / SOFF (the end of TC's
    task call: turns slip into an intervention level and applies it). Returns (code, labels)"""
    A = A or AD.LFJ1EE
    a = Asm(SPK); W = a.w
    # ---- SPARK: fr1 = ignition cut's RETARD result - Timing Pull * level  (uses r0, r1, fr0, fr3; fpul saved)
    a.L('SPARK'); W(0x4F22)
    a.lit('movl', 1, 'P_IGRET'); W(0x410B); W(0x0009); W(0x4F26)
    a.lit('movl', 1, 'P_LVL'); W(0x6010); W(0x600C); W(0x2008); a.br('bt', 'SDONE')   # level 0 -> nothing
    W(0x4F52); W(0x405A); W(0xF02D); W(0x4F56)        # fr0 = float(level) (fpul saved and restored)
    a.lit('mova', 0, 'C_INV255'); W(0xF308); W(0xF032)                # fr0 *= 1/255
    a.lit('movl', 1, 'P_TRET'); W(0xF318); W(0xF032)  # fr0 *= Timing Pull
    W(0xF38D); W(0xF035); a.br('bf', 'SDONE')         # > 0 (NaN -> nothing)
    a.lit('mova', 0, 'C_CAPT'); W(0xF308); W(0xF035); a.br('bf', 'SOK'); W(0xF03C)   # cap 10 deg
    a.L('SOK'); W(0xF101)                             # fr1 -= pull
    a.L('SDONE'); W(0x000B); W(0x0009)
    # ---- exits of SCALE (placed before it so its short branches reach them)
    a.L('SEND'); W(0x4F26); W(0x000B); W(0x0009)      # lds.l @r15+,pr ; rts (returns from TC's task call)
    a.L('SIDLE'); W(0xE000); W(0x8026); W(0x8028); W(0x802B)          # level 0: no cut, counters 0
    a.br('bra', 'SEND'); W(0x0009)
    a.L('SREST'); a.lit('movl', 1, 'P_REST'); W(0x6010)
    a.br('bra', 'SOFFNR'); W(0x8027)                  # (slot) rest = Rest calls
    a.L('SOFF'); W(0x8427); W(0x600C); W(0x2008); a.br('bt', 'SOFFNR')
    W(0x70FF); W(0x8027)                              # rest--
    a.L('SOFFNR'); W(0xE000); W(0x8026); W(0x8028); W(0x8029); W(0x802B); W(0x802C)  # all 0
    a.br('bra', 'SEND'); W(0x0009)
    # ---- SCALE (bra from TC's main code; r2 = &state, fr6 = slip*100, fr0 = allowed*100, PR on the stack)
    a.L('SCALE')
    W(0x8427); W(0x600C); W(0x2008); a.br('bf', 'SOFF')                # resting after a long intervention -> off
    a.lit('mova', 0, 'C_100'); W(0xF108); W(0xF105); a.br('bf', 'A1'); W(0xF01C)   # allowed at least 1 km/h
    a.L('A1'); W(0xF26C); W(0xF203); W(0xF19D); W(0xF211)              # fr2 = slip / allowed - 1  (excess)
    a.lit('movl', 1, 'P_FULL'); W(0xF118)
    a.lit('mova', 0, 'C_01'); W(0xF308); W(0xF135); a.br('bt', 'A2'); W(0xF19D)    # Full Slip > 0.1, else 1
    a.L('A2'); W(0xF213)                              # fr2 = excess / Full Slip
    W(0xF38D); W(0xF235); a.br('bt', 'A3'); W(0xF23C) # < 0 (or NaN) -> 0
    a.L('A3'); W(0xF39D); W(0xF235); a.br('bf', 'A4'); W(0xF23C)      # > 1 -> 1
    a.L('A4'); a.lit('mova', 0, 'C_255'); W(0xF308); W(0xF232)
    W(0xF23D); W(0x035A)                              # r3 = target level 0..255
    W(0x8429); W(0x600C)                              # r0 = level
    a.lit('movl', 1, 'P_DECAY'); W(0x6110); W(0x611C); W(0x2118); a.br('bf', 'D1'); W(0xE101)   # Decay (0 -> 1)
    a.L('D1'); W(0x3018); W(0x4011); a.br('bt', 'D2'); W(0xE000)      # level - Decay, not below 0
    a.L('D2'); W(0x3307); a.br('bf', 'D3'); W(0x6033) # level = max(target, level - Decay)
    a.L('D3'); W(0x8029); W(0x802C)                   # store (AC49 level, AC4C for the timing hook)
    W(0x2008); a.br('bt', 'SIDLE')                    # level 0 -> idle
    # backstop: intervention longer than Max Time -> Rest
    W(0x8426); W(0x600C); W(0x7001)
    a.lit('movl', 1, 'P_MAXACT'); W(0x6110); W(0x611C); W(0x3016); a.br('bt', 'SREST')
    W(0x8026)
    # cuts: above Cut Start, a share q of 0..128 per call into an 8-bit accumulator; overflow = cut this call.
    # q <= 128, so never two cuts in a row (at most 1 in 2: never a full cut)
    W(0x8429); W(0x600C); W(0x405A); W(0xF22D)        # fr2 = level
    a.lit('mova', 0, 'C_INV255'); W(0xF308); W(0xF232)                # fr2 = level 0..1
    a.lit('movl', 1, 'P_CUTST'); W(0xF118)
    a.lit('mova', 0, 'C_001'); W(0xF308); W(0xF132)   # fr1 = Cut Start 0..1
    W(0xF211); W(0xF38D); W(0xF235); a.br('bf', 'NOCUT')              # level - start > 0 (NaN -> no cuts)
    W(0xF39D); W(0xF311); W(0xF48D); W(0xF345)       # fr3 = 1 - start ; > 0 ?
    a.br('bf', 'NOCUT'); W(0xF233)                    # fr2 = share 0..1
    a.lit('mova', 0, 'C_128'); W(0xF308); W(0xF232); W(0xF23D); W(0x015A)   # r1 = q 0..128
    W(0x8428); W(0x600C); W(0x301C)                   # r0 = acc + q
    W(0x630C); W(0x3300); W(0x6033); W(0x8028)        # acc = low byte ; T = no overflow
    W(0x0029); W(0xCA01); a.br('bra', 'SOUT'); W(0x6303)              # flag = overflow
    a.L('NOCUT'); W(0xE000); W(0x8028); W(0xE300)     # acc = 0 ; flag = 0
    a.L('SOUT'); W(0x6033); W(0x802B)                 # [AC4B] = cut flag (read by the ignition cut)
    # throttle: engine-side pedal *= 1 - Throttle% * level  (after the factory pedal copy / rev-match)
    W(0x8429); W(0x600C); W(0x405A); W(0xF22D)
    a.lit('mova', 0, 'C_INV255'); W(0xF308); W(0xF232)                # fr2 = level 0..1
    a.lit('movl', 1, 'P_THR'); W(0xF118); W(0xF38D); W(0xF135); a.br('bf', 'TEND')   # Throttle > 0 (NaN -> none)
    a.lit('mova', 0, 'C_CAPR'); W(0xF308); W(0xF135); a.br('bf', 'T1'); W(0xF13C)   # cap 50%
    a.L('T1'); a.lit('mova', 0, 'C_001'); W(0xF308); W(0xF132); W(0xF122)            # fr1 = share 0..0.5
    W(0xF39D); W(0xF311)                              # fr3 = factor
    a.lit('movl', 1, 'P_POUT'); W(0xF018); W(0xF032); W(0xF10A)       # pedal_out *= factor
    a.L('TEND'); W(0x4F26); W(0x000B); W(0x0009)      # lds.l @r15+,pr ; rts
    P = lambda v: struct.pack('>I', v); F = lambda v: struct.pack('>f', v)
    a.pool([('P_IGRET', P(IG.assemble(A)[2])), ('P_LVL', P(RAM_STATE + 12)), ('C_INV255', F(1 / 255)), ('P_TRET', P(TBL['TRET'])),
            ('C_CAPT', F(CAP_TRET)), ('C_100', F(100.0)), ('P_FULL', P(TBL['FULL'])), ('C_01', F(0.1)), ('C_255', F(255.0)),
            ('P_DECAY', P(TBL['DECAY'])), ('P_MAXACT', P(TBL['MAXACT'])), ('P_CUTST', P(TBL['CUTST'])), ('C_001', F(0.01)),
            ('C_128', F(128.0)), ('P_THR', P(TBL['THR'])), ('C_CAPR', F(CAP_THR)), ('P_POUT', P(A['pedal_out'])),
            ('P_REST', P(TBL['REST']))])
    code = a.assemble()
    assert a.labels['SPARK'] == SPK and SPK + len(code) <= SPK_END, hex(SPK + len(code))
    return code, dict(a.labels)


def _assemble(A=None):
    A = A or AD.LFJ1EE
    a = Asm(CODE)
    W = a.w
    sl = assemble_spark(A)[1]
    a.labels['SCALE'], a.labels['SOFF'] = sl['SCALE'], sl['SOFF']
    W(0x4F22)                                         # sts.l pr,@-r15
    a.lit('movl', 1, 'P_NEXT')
    a.L('CALLN'); W(0x6112)                           # r1 = [NEXT] previous task target (second entry joins here)
    W(0x410B); W(0x0009)                              # jsr @r1 (pedal copy / rev-match)
    a.lit('movl', 2, 'P_STATE')                       # r2 = &state (AC40)
    a.lit('movl', 3, 'P_WS')                          # r3 = &wheel-speed bytes
    # ---- stale check: signature = sum of the two 32-bit halves of the 8 wheel bytes
    W(0x6032); W(0x5131); W(0x301C)                   # r0 = [r3] + [r3+4]
    W(0x6122); W(0x3010); a.br('bt', 'SAME')          # same as last call?
    W(0x2202); W(0xE000)                              # signature = r0
    a.br('bra', 'FRESH'); W(0x8122)                   # (slot) counter = 0
    a.L('OFF_T'); a.br('bra', 'OFF'); W(0x0009)       # (not fallen into) stepping stone: OFF is out of bt/bf range here
    a.L('SAME'); W(0x8522); W(0x600D)                 # r0 = counter
    W(0xE164); W(0x3012); a.br('bt', 'OFF_T')           # >= 100 calls unchanged -> CAN lost: off
    W(0x7001); W(0x8122)                              # counter++
    a.L('FRESH')
    # ---- clutch / lockout
    a.lit('movl', 1, 'P_CLUTCH'); W(0x6010); W(0x8801); a.br('bf', 'CUP')
    a.lit('movl', 1, 'P_LOCK'); W(0x6010)
    a.br('bra', 'OFF'); W(0x802A)                     # (slot) lockout = Lockout
    a.L('CUP'); W(0x842A); W(0x600C); W(0x2008); a.br('bt', 'NOLOCK')
    W(0x70FF); a.br('bra', 'OFF'); W(0x802A)          # (slot) lockout--
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
    a.br('bra', 'SCALE'); W(0x0009)                   # fr6 = slip, fr0 = allowed (x100): scaled intervention (0xFEA00)
    a.L('OFF'); a.br('bra', 'SOFF'); W(0x0009)        # off: everything to 0 (the block returns for us)
    P = lambda v: struct.pack('>I', v); F = lambda v: struct.pack('>f', v)
    a.pool([('P_NEXT', P(TBL['NEXT'])), ('P_STATE', P(RAM_STATE)), ('P_WS', P(A['wheel_speeds'])),
            ('P_CLUTCH', P(A['clutch'])), ('P_LOCK', P(TBL['LOCK'])), ('P_EN', P(TBL['EN'])), ('P_BRAKE', P(A['brake'])),
            ('P_APP', P(A['pedal_in'])), ('P_PMIN', P(TBL['PMIN'])), ('P_RPM', P(A['rpm'])), ('P_RPMMIN', P(TBL['RPMMIN'])),
            ('C_FFFE', P(0xFFFE)), ('C_HALF', F(0.5)), ('C_OFS', F(10000.0)), ('C_100', F(100.0)), ('P_VMIN', P(TBL['VMIN'])),
            ('P_PCT', P(TBL['SLIPPCT'])), ('C_001', F(0.01)), ('P_KMH', P(TBL['SLIPKMH']))])
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
    sp_lit = AD.spark_info(A)['term_lit']; ig_ret = IG.assemble(A)[2]
    sl = struct.unpack_from('>I', rom, sp_lit)[0]
    assert sl in (ig_ret, SPK), f'the spark-advance hook points to 0x{sl:08X}, not the ignition cut - refusing'
    if sl != SPK:
        assert all(b == 0xFF for b in rom[SPK:SPK_END]), 'TC area 0xFEA00-0xFEBFF is not empty - another patch is using it'
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
        if cur['VER'] in SAME_LAYOUT:                 # v2 / v3: keep every valid setting (v2's new ones: defaults)
            for k in (FLOATS + BYTES if cur['VER'] == VERSION else V2_KEEP):
                if cur[k] == cur[k] and LIMITS[k][0] <= cur[k] <= LIMITS[k][1]: vals[k] = cur[k]
            notes = ['traction control already installed: code refreshed, settings kept' if cur['VER'] == VERSION else
                     'traction control updated to scaled intervention (timing, then partial cuts, then throttle; never a full cut): slip settings kept']
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
    rom[SPK:SPK_END] = b'\xFF' * (SPK_END - SPK)
    spk = assemble_spark(A)[0]; rom[SPK:SPK + len(spk)] = spk
    rom[sp_lit:sp_lit + 4] = struct.pack('>I', SPK)
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
    sp_lit = AD.spark_info(A)['term_lit']
    if struct.unpack_from('>I', rom, sp_lit)[0] == SPK:                    # timing hook back to the ignition cut
        rom[sp_lit:sp_lit + 4] = struct.pack('>I', IG.assemble(A)[2])
    rom[SPK:SPK_END] = b'\xFF' * (SPK_END - SPK)
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

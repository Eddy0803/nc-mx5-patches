"""
Timed overrun crackle (burble) for LFJ1EE (Mazda MX-5 NC, manual), with adjustable strength.
Standalone: hooks only factory code, so it works on a stock LFJ1EE ROM, with or without the other patches.

How it works
    On lift-off the factory decel fuel cut ramps a fuel multiplier (DFCO multiplier, RAM FFFF7560) from 1.0 down
    towards 0 and cuts fuel completely below 0.6. For a set time after lift-off this patch keeps fuelling at a lambda
    taken from a lambda-vs-RPM table (multiplier = 1/lambda; lambda limited to 0.8..1.2 in code) and retards the spark,
    so combustion finishes in the exhaust manifold: a crackle on the overrun, like the factory sport-mode burble on
    some modern cars. Default lambda table = a stock Ford sport-mode burble: 0.92 up to 3000 rpm, 1.0 from 4000 rpm.

    Arming / timing
        Pedal >= Arm pedal %          -> armed, timer = Duration (s). Nothing happens while you are on the pedal.
        Pedal <= Closed pedal %, armed, clutch up, Min RPM <= RPM <= Max RPM, speed >= Min speed (0 = any speed),
        coolant >= Min coolant temp, timer > 0
                                      -> ACTIVE: timer counts down; fuel multiplier = 1/lambda(RPM); spark retarded.
        Clutch pressed: allowed only below "Clutch pressed: allow below this speed" (0 = never; e.g. 3 km/h lets a
        standing rev with the clutch in crackle). Otherwise pressing the clutch ends the burst.
        Timer runs out, clutch pressed, RPM / speed / coolant outside the window -> disarmed until you press the pedal
        past Arm pedal % again. So each lift-off gives at most one burst of Duration seconds.
        Between Closed and Arm pedal % (part throttle) nothing happens and the state is kept.

    Strength (0-100 %) sets only how aggressive the spark is (like Ford's burble "tr_clip": 0.1 = mild, 0 = aggressive):
        Retard = Retard at 0 % + s * (Retard at 100 % - Retard at 0 %)   (code limit 0..45 deg)
    The fuel does not change with Strength: it always follows the lambda-vs-RPM table.
    Ford limits burble spark by torque ratio, which only very late spark gives, so the retard defaults are large
    estimates; set them from a datalog of ignition advance.

Hooks
    1) DFCO task call: the task literal (0x1384C) that called the factory DFCO routine (0x45940) now calls OVR, which
       runs the factory routine first and then, while active, overwrites the multiplier it produced.
    2) Spark-advance sum 0x4DA9C: the load of the factory term FFFF9F74 at 0x4DAF4 becomes a call to SPK (via literal
       0x4DCC8), which returns fr3 = [FFFF9F74] - Retard while active. (The ignition cut uses a different term, FFFF7D68.)

    Sport mode (Sport Mode Only > 0): bursts only while TCS is off (DSC button pressed once), or in "sport mode".
        Sport mode toggles when TCS goes off and back on within Sport Toggle Window seconds (press the button twice
        quickly). It starts OFF at every power-up. TCS state = (byte at TCS address & mask) == value, found on the car
        by NC Patcher's TCS capture; without a valid address the gate never allows a burst.

RAM (unused by the factory software): ACD0 f32 time left, ACD4 u8 armed, ACD5 u8 active (0x5A), ACD8 f32 retard,
ACDC u8 TCS off on the last call, ACDD u8 sport mode (0x5A = on), ACE0 f32 toggle window left (s).
Tables 0xFF000.. (see TBL). Code 0xFF080..0xFF400.
"""
import struct, sys, os, importlib.util

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('sh_asm', os.path.join(here, 'sh_asm.py'))
SA = importlib.util.module_from_spec(spec); spec.loader.exec_module(SA)
spec = importlib.util.spec_from_file_location('addrs', os.path.join(here, 'addrs.py'))
AD = importlib.util.module_from_spec(spec); spec.loader.exec_module(AD)

TBL_START, CODE, CODE_END = 0xFF000, 0xFF080, 0xFF400
OLD_BASE = 0xFE800                # 0.9.7-0.9.10 kept the overrun at 0xFE800-0xFEBFF (moved: clashed with romdrop-era add-ons)
TBL = {'EN': 0xFF000, 'STR': 0xFF004, 'DUR': 0xFF008, 'RMIN': 0xFF00C, 'RMAX': 0xFF010, 'VMIN': 0xFF014,
       'TMIN': 0xFF018, 'ARM': 0xFF01C, 'CLOSED': 0xFF020, 'RETLO': 0xFF024, 'RETHI': 0xFF028,
       'CLV': 0xFF02C, 'RATE': 0xFF034,              # 0xFF030-0xFF033 unused
       'SPEN': 0xFF060, 'SPWIN': 0xFF064}            # sport-mode gate: enable, off->on toggle window (s)
ARR = {'LAX': 0xFF040, 'LAM': 0xFF050}                # 4-point lambda-vs-RPM table: RPM axis, lambda
# TCS-off signal (found on the car by NC Patcher's TCS capture): RAM address (u32), mask (u8), value when TCS is off (u8)
TCS = {'TCSA': 0xFF068, 'TCSM': 0xFF06C, 'TCSV': 0xFF06D}
TCS_DEFAULTS = {'TCSA': 0xFFFFFFFF, 'TCSM': 0x00, 'TCSV': 0x00}   # no address yet
ARR_DEFAULTS = {'LAX': [2000.0, 3000.0, 4000.0, 5000.0], 'LAM': [0.92, 0.92, 1.0, 1.0]}   # stock Ford burble
ARR_LIMITS = {'LAX': (500.0, 8000.0), 'LAM': (0.8, 1.2)}
DEFAULTS = {'EN': 0.0, 'STR': 0.0, 'DUR': 2.0, 'RMIN': 2500.0, 'RMAX': 6500.0, 'VMIN': 0.0, 'TMIN': 50.0,
            'ARM': 20.0, 'CLOSED': 2.0, 'CLV': 0.0, 'RETLO': 25.0, 'RETHI': 40.0, 'RATE': 90.0,
            'SPEN': 0.0, 'SPWIN': 2.0}
LIMITS = {'EN': (0.0, 1.0), 'STR': (0.0, 100.0), 'DUR': (0.0, 5.0), 'RMIN': (1500.0, 7000.0), 'RMAX': (2000.0, 7500.0),
          'VMIN': (0.0, 200.0), 'TMIN': (40.0, 110.0), 'ARM': (5.0, 100.0), 'CLOSED': (0.0, 10.0), 'CLV': (0.0, 30.0),
          'RETLO': (0.0, 45.0), 'RETHI': (0.0, 45.0), 'RATE': (10.0, 1000.0), 'SPEN': (0.0, 1.0), 'SPWIN': (0.3, 5.0)}
SPORT = 0x5A                      # sport-mode byte value meaning "on"; anything else (power-up) = off
# lambda limited to 0.8 (rich: multiplier 1.25, keeps unburnt fuel in a hot exhaust in check) .. 1.2 (lean: multiplier
# 0.83, well above the factory's 0.6 full-cut point, so it never turns into a full cut)
RET_CAP, LAM_MIN, LAM_MAX, DUR_CAP = 45.0, 0.8, 1.2, 5.0
RAM_STATE = 0xFFFFACD0            # +0 f32 time left, +4 u8 armed, +5 u8 active magic, +8 f32 retard
MAGIC = 0x5A


def assemble(A=None):
    A = A or AD.LFJ1EE
    a = SA.Asm(CODE); W = a.w
    # ================= OVR: called from the DFCO task slot instead of the factory DFCO routine
    a.L('OVR')
    W(0x4F22); a.lit('movl', 0, 'P_FDFCO'); W(0x400B); W(0x0009); W(0x4F26)   # factory DFCO first
    a.lit('movl', 2, 'P_STATE')
    W(0xE000); W(0x8025)                               # active = 0  (mov.b r0,@(5,r2))
    # ---- sport-mode gate (Sport Mode Only > 0): crackle only while TCS is off, or in sport mode (TCS off-on quickly)
    a.lit('movl', 1, 'P_SPEN'); W(0xF018); W(0xF18D); W(0xF015); a.br('bf', 'SPOK')   # gate off -> always allowed
    a.lit('movl', 1, 'P_TCSA'); W(0x6112)              # r1 = TCS RAM address
    a.lit('movl', 3, 'P_HIMASK'); W(0x6013); W(0x2039); W(0x3030); a.br('bf', 'SPNO')  # not FFFFxxxx -> not allowed
    a.lit('movl', 3, 'P_RAMEND'); W(0x3132); a.br('bt', 'SPNO')                        # >= FFFFC000 (not RAM) -> not allowed
    W(0x6010)                                          # r0 = TCS byte
    a.lit('movl', 1, 'P_TCSM'); W(0x6310); W(0x633C); W(0x2039)   # r0 &= mask
    a.lit('movl', 1, 'P_TCSV'); W(0x6310); W(0x633C); W(0x3030)   # T = (r0 == value): TCS off
    W(0x0329)                                          # r3 = TCS off (0/1)
    W(0x842C); W(0x600C); W(0x6103)                    # r1 = TCS off on the last call
    W(0x6013); W(0x8800); a.br('bt', 'LOK'); W(0x8801); a.br('bt', 'LOK')
    W(0x6033); W(0x802C); W(0xF08D); W(0xE010); W(0xF207); a.br('bra', 'SGATE'); W(0x0009)   # not 0/1 (power-up): start
    a.L('LOK'); W(0x6033); W(0x802C)                   # last = now
    W(0x3130); a.br('bt', 'SWIN')                      # no change -> count the window down
    W(0x2338); a.br('bt', 'SON')                       # now on -> it went off -> on
    a.lit('movl', 1, 'P_SPWIN'); W(0xF018); W(0xE010); W(0xF207)   # went off: window = SPWIN seconds
    a.br('bra', 'SWIN'); W(0x0009)
    a.L('SON'); W(0xE010); W(0xF026)                   # back on: still inside the window?
    W(0xF18D); W(0xF015); a.br('bf', 'SWIN')
    W(0x842D); W(0x8800 | SPORT); a.br('bt', 'SOFF')   # toggle sport mode
    W(0xE000 | SPORT); a.br('bra', 'SSET'); W(0x0009)
    a.L('SOFF'); W(0xE000)
    a.L('SSET'); W(0x802D); W(0xF08D); W(0xE010); W(0xF207)   # sport = r0 ; window = 0
    a.L('SWIN'); W(0xE010); W(0xF026); W(0xF18D); W(0xF015); a.br('bf', 'SGATE')       # window > 0 ?
    a.lit('movl', 1, 'P_RATE'); W(0xF118); W(0xF69D); W(0xF165); a.br('bf', 'SGATE')   # rate > 1
    W(0xF613); W(0xF061); W(0xE010); W(0xF207)         # window -= 1 / rate
    a.L('SGATE'); W(0x2338); a.br('bf', 'SPOK')        # TCS off -> allowed
    W(0x842D); W(0x8800 | SPORT); a.br('bt', 'SPOK')   # sport mode -> allowed
    a.L('SPNO'); a.br('bra', 'DISARM'); W(0x0009)
    a.L('SPOK')
    a.lit('movl', 1, 'P_EN'); W(0xF018); W(0xF18D); W(0xF015); a.br('bf', 'DISARM')   # Enable > 0
    a.lit('movl', 1, 'P_CLUTCH'); W(0x6010); W(0x8801); a.br('bf', 'NOCL')            # clutch pressed?
    a.lit('movl', 1, 'P_VSS'); W(0xF518); a.lit('movl', 1, 'P_CLV'); W(0xF018); W(0xF055)
    a.br('bf', 'DISARM')                                                               # only below Clutch Speed
    a.L('NOCL')
    a.lit('movl', 1, 'P_APP'); W(0xF418)                                               # fr4 = pedal
    a.lit('movl', 1, 'P_ARM'); W(0xF018); W(0xF045); a.br('bt', 'NOARM')               # arm > pedal ?
    W(0xE001); W(0x8024)                               # armed = 1
    a.lit('movl', 1, 'P_DUR'); W(0xF018)
    a.lit('mova', 0, 'C_DURCAP'); W(0xF108); W(0xF015); a.br('bf', 'D1'); W(0xF01C)    # cap 5 s
    a.L('D1'); W(0x000B); W(0xF20A)                    # time left = duration ; return (on the pedal: inactive)
    a.L('NOARM')
    a.lit('movl', 1, 'P_CLOSED'); W(0xF018); W(0xF405); a.br('bt', 'EXIT')            # pedal > closed: part throttle
    W(0x8424); W(0x8801); a.br('bf', 'EXIT')           # armed?  (mov.b @(4,r2),r0)
    a.lit('movl', 1, 'P_RPM'); W(0xF518)
    a.lit('movl', 1, 'P_RMIN'); W(0xF018); W(0xF055); a.br('bt', 'DISARM')            # min > rpm
    a.lit('movl', 1, 'P_RMAX'); W(0xF018); W(0xF505); a.br('bt', 'DISARM')            # rpm > max
    a.lit('movl', 1, 'P_VSS'); W(0xF518)
    a.lit('movl', 1, 'P_VMIN'); W(0xF018); W(0xF055); a.br('bt', 'DISARM')            # min speed > speed
    a.lit('movl', 1, 'P_ECT'); W(0xF518)
    a.lit('movl', 1, 'P_TMIN'); W(0xF018); W(0xF055); a.br('bt', 'DISARM')            # min coolant > coolant
    W(0xF528); W(0xF18D); W(0xF515); a.br('bf', 'DISARM')                              # time left > 0 ?
    a.lit('movl', 1, 'P_RATE'); W(0xF018); W(0xF69D); W(0xF065); a.br('bf', 'DISARM')   # rate > 1 (no divide by 0)
    W(0xF603); W(0xF561); W(0xF25A)                                                    # time -= 1/rate
    # strength s = clamp(STR / 100, 0, 1) -> fr0
    a.lit('movl', 1, 'P_STR'); W(0xF018); a.lit('mova', 0, 'C_100'); W(0xF608); W(0xF063)
    W(0xF18D); W(0xF105); a.br('bf', 'S1'); W(0xF01C)                                  # 0 > s -> 0
    a.L('S1'); W(0xF19D); W(0xF015); a.br('bf', 'S2'); W(0xF01C)                       # s > 1 -> 1
    a.L('S2')
    # retard = lo + s*(hi-lo), limited 0..RET_CAP -> fr7, stored at state+8
    a.lit('movl', 1, 'P_RETLO'); W(0xF618); a.lit('movl', 1, 'P_RETHI'); W(0xF718)
    W(0xF761); W(0xF702); W(0xF760)
    a.lit('movl', 1, 'C_RETCAP_P'); W(0xF618); W(0xF765); a.br('bf', 'R1'); W(0xF76C)  # > cap -> cap
    a.L('R1'); W(0xF68D); W(0xF675); a.br('bf', 'R2'); W(0xF76C)                       # 0 > ret -> 0
    a.L('R2'); W(0xE008); W(0xF277)                    # retard -> @(8,r2)  (fmov.s fr7,@(r0,r2))
    W(0x4F22); a.br('bsr', 'LAMF'); W(0x0009); W(0x4F26)   # fr7 = lambda for this RPM (subroutine below)
    W(0xF774); a.br('bf', 'EXIT')                      # NaN guard (fcmp/eq fr7,fr7)
    a.lit('movl', 1, 'C_LAMLIM_P'); W(0xF618); W(0xF675); a.br('bf', 'C1'); W(0xF76C)  # lambda < 0.85 -> 0.85
    a.L('C1'); W(0xE004); W(0xF616); W(0xF765); a.br('bf', 'C2'); W(0xF76C)            # lambda > 1.5 -> 1.5
    a.L('C2'); W(0xF69D); W(0xF673)                    # fr6 = 1 / lambda  (fuel multiplier 0.667..1.176)
    a.lit('movl', 1, 'P_MULT'); W(0xF16A)              # DFCO multiplier = 1 / lambda
    W(0xE05A); W(0x000B); W(0x8025)                    # active = 0x5A ; return
    a.L('DISARM'); W(0xE000); W(0x8024)                # armed = 0
    a.L('EXIT'); W(0x000B); W(0x0009)
    # ================= LAMF: fr7 = lambda from the 4-point lambda-vs-RPM table (linear, flat outside)
    a.L('LAMF')
    a.lit('movl', 1, 'P_RPM'); W(0xF418)               # fr4 = rpm
    a.lit('movl', 1, 'P_LAX'); W(0xF518)               # fr5 = R0
    W(0xF545); a.br('bf', 'L1'); W(0xF45C)             # below the first point -> rpm = R0
    a.L('L1'); W(0xE303)                               # r3 = 3 segments
    a.L('LOOP'); W(0xF519); W(0xF618)                  # fr5 = R(i), r1 -> R(i+1) ; fr6 = R(i+1)
    W(0xF465); a.br('bf', 'SEG')                       # rpm > R(i+1)? no -> interpolate in this segment
    W(0x4310); a.br('bf', 'LOOP')                      # dt r3
    W(0xE010); W(0xF716); a.br('bra', 'LDONE'); W(0x0009)   # above the last point: lambda = L3
    a.L('SEG'); W(0xE010); W(0xF716)                   # fr7 = L(i+1)       (@(16,r1))
    W(0xF06C); W(0xF051)                               # fr0 = R(i+1) - R(i)
    W(0xF18D); W(0xF015); a.br('bf', 'LDONE')          # dR > 0, else L(i+1) (never divide by 0)
    W(0xE00C); W(0xF116); W(0xF711)                    # fr1 = L(i) ; fr7 = L(i+1) - L(i)
    W(0xF24C); W(0xF251); W(0xF272); W(0xF203)         # fr2 = (rpm - R(i)) * dL / dR
    W(0xF71C); W(0xF720)                               # fr7 = L(i) + fr2
    a.L('LDONE'); W(0x000B); W(0x0009)
    # ================= SPK: called from the spark-advance sum instead of the FFFF9F74 term load. fr3 = term - retard
    # (only r0, r1, r3, fr0, fr1, fr3 are used: they are free at that point of the factory routine)
    a.L('SPK')
    a.lit('movl', 1, 'P_TERM2'); W(0xF318)
    a.lit('movl', 1, 'P_STATE'); W(0x8415); W(0x885A); a.br('bf', 'SDONE')            # active?  (mov.b @(5,r1),r0)
    W(0xE008); W(0xF016)                               # fr0 = retard  (fmov.s @(r0,r1),fr0)
    W(0xF18D); W(0xF015); a.br('bf', 'SDONE')          # retard > 0   (NaN fails)
    a.lit('movl', 1, 'C_RETCAP_P'); W(0xF118); W(0xF015); a.br('bt', 'SDONE')         # retard > cap -> ignore (garbage)
    W(0xF301)                                          # fr3 -= retard
    a.L('SDONE'); W(0x000B); W(0x0009)
    P = lambda v: struct.pack('>I', v); F = lambda v: struct.pack('>f', v)
    a.pool([('P_FDFCO', P(A['dfco_routine'])), ('P_STATE', P(RAM_STATE)), ('P_EN', P(TBL['EN'])),
            ('P_CLUTCH', P(A['clutch'])), ('P_APP', P(A.get('igncut_pedal') or A['pedal_in'])), ('P_ARM', P(TBL['ARM'])), ('P_CLV', P(TBL['CLV'])),
            ('P_DUR', P(TBL['DUR'])), ('C_DURCAP', F(DUR_CAP)), ('P_CLOSED', P(TBL['CLOSED'])), ('P_RPM', P(A['rpm'])),
            ('P_RMIN', P(TBL['RMIN'])), ('P_RMAX', P(TBL['RMAX'])), ('P_VSS', P(A['speed'])), ('P_VMIN', P(TBL['VMIN'])),
            ('P_ECT', P(A['ect'])), ('P_TMIN', P(TBL['TMIN'])), ('P_RATE', P(TBL['RATE'])), ('P_STR', P(TBL['STR'])),
            ('C_100', F(100.0)), ('P_RETLO', P(TBL['RETLO'])), ('P_RETHI', P(TBL['RETHI'])),
            ('C_RETCAP_P', P(CODE_END - 8)), ('P_LAX', P(ARR['LAX'])),
            ('C_LAMLIM_P', P(CODE_END - 16)), ('P_MULT', P(A['dfco_mult'])), ('P_TERM2', P(A['spark2_term'])),
            ('P_SPEN', P(TBL['SPEN'])), ('P_TCSA', P(TCS['TCSA'])), ('P_HIMASK', P(0xFFFF0000)), ('P_TCSM', P(TCS['TCSM'])),
            ('P_TCSV', P(TCS['TCSV'])), ('P_SPWIN', P(TBL['SPWIN'])), ('P_RAMEND', P(0xFFFFC000))])
    code = a.assemble()
    assert a.labels['OVR'] == CODE and CODE + len(code) <= CODE_END - 16, hex(CODE + len(code))
    assert ARR['LAM'] == ARR['LAX'] + 16                # the code reads lambda at axis + 16
    body = code + b'\xFF' * (CODE_END - 16 - CODE - len(code)) + F(LAM_MIN) + F(LAM_MAX) + F(RET_CAP) + b'\xFF' * 4
    return body, a.labels['OVR'], a.labels['SPK']


def spark2_lit(A):
    s, w = A['spark2_site'], AD._w(A['spark2_orig'])
    assert len(w) == 4 and w[0] >> 8 == 0xD3 and w[1] == 0xF200 and w[2] >> 8 == 0xD2 and w[3] == 0xF338, 'unexpected spark code (term 2)'
    return AD._lit(s, w[0])


def spark2_hook(A):
    w = AD._w(A['spark2_orig'])
    return struct.pack('>HHHH', w[0], 0x430B, w[1], w[2])   # mov.l lit,r3 ; jsr @r3 ; fadd (delay) ; mov.l


def available(A):
    return all(A.get(k) is not None for k in ('dfco_routine', 'dfco_lit', 'dfco_mult', 'spark2_site', 'spark2_orig',
                                               'spark2_term', 'ect'))


def install(rom, table_values=None, keep_tables=True, A=None):
    """Install / update in an LFJ1EE (or ported calibration) image (bytearray). Returns notes."""
    assert len(rom) == 0x100000, 'ROM must be 1 MB'
    A = A or AD.for_rom(rom)
    assert AD.is_cal(rom, A), f"not a {A['cal']} ROM"
    AD.assert_not_automatic(rom)
    assert available(A), f"overrun is not available for {A['cal']} (port it again with this version)"
    code, ovr, spk = assemble(A)
    SITE, ORIG, LIT = A['spark2_site'], bytes.fromhex(A['spark2_orig']), spark2_lit(A)
    site = bytes(rom[SITE:SITE + 8]); slit = struct.unpack_from('>I', rom, LIT)[0]
    dlit = struct.unpack_from('>I', rom, A['dfco_lit'])[0]
    prev = bytes(rom[CODE:CODE_END])
    old = OLD_BASE + 0x80
    if site == spark2_hook(A) and OLD_BASE <= slit < OLD_BASE + 0x400 and dlit == old:
        # an earlier version at 0xFE800: carry its settings over, put the factory pointers back, erase it, install here
        table_values = dict(table_values or {})
        for k, adr in TBL.items():
            if k in ('SPEN', 'SPWIN'): continue        # did not exist then
            v = struct.unpack_from('>f', rom, adr - 0x800)[0]
            if k not in table_values and v == v and LIMITS[k][0] <= v <= LIMITS[k][1]: table_values[k] = v
        rom[SITE:SITE + 8] = ORIG; rom[LIT:LIT + 4] = struct.pack('>I', A['spark2_term'])
        rom[A['dfco_lit']:A['dfco_lit'] + 4] = struct.pack('>I', A['dfco_routine'])
        rom[OLD_BASE:OLD_BASE + 0x400] = b'\xFF' * 0x400
        site, slit, dlit, moved = ORIG, A['spark2_term'], A['dfco_routine'], True
    else:
        moved = False
    if site == ORIG and slit == A['spark2_term'] and dlit == A['dfco_routine']:
        assert all(b == 0xFF for b in rom[TBL_START:CODE_END]), 'overrun area 0xFF000-0xFF3FF is not empty - another patch is using it'
        notes = ['moved from 0xFE800 (settings kept)' if moved else 'fresh install']; fresh = True
    elif site == spark2_hook(A) and slit == spk and dlit == ovr and prev == code:
        notes = ['already installed: tables updated']; fresh = False
    elif site == spark2_hook(A) and CODE <= slit < CODE_END and dlit == CODE:
        notes = ['earlier overrun version updated (settings kept)']; fresh = False
    else:
        raise AssertionError('the overrun hook sites or code area hold something unexpected (a different patch, or a different '
                             'calibration) - refusing')
    for k, adr in TBL.items():
        cur = struct.unpack_from('>f', rom, adr)[0]
        if table_values and k in table_values: v = table_values[k]
        elif keep_tables and not fresh and cur == cur and LIMITS[k][0] <= cur <= LIMITS[k][1]: v = cur
        else: v = DEFAULTS[k]                      # (an older version's "fuel multiplier" there is not a lambda)
        lo, hi = LIMITS[k]; v = max(lo, min(hi, float(v)))
        rom[adr:adr + 4] = struct.pack('>f', v)
    for k, adr in ARR.items():
        cur = [struct.unpack_from('>f', rom, adr + 4 * i)[0] for i in range(4)]
        lo, hi = ARR_LIMITS[k]
        if table_values and k in table_values: v = list(table_values[k])
        elif keep_tables and not fresh and all(lo <= c <= hi for c in cur): v = cur
        elif keep_tables and not fresh and k == 'LAM' and all(0.5 <= c <= 2.0 for c in cur): v = cur   # older, wider limits: clamped below
        else: v = ARR_DEFAULTS[k]
        for i in range(4): rom[adr + 4 * i:adr + 4 * i + 4] = struct.pack('>f', max(lo, min(hi, float(v[i]))))
    tv = table_values or {}
    cur = {'TCSA': struct.unpack_from('>I', rom, TCS['TCSA'])[0], 'TCSM': rom[TCS['TCSM']], 'TCSV': rom[TCS['TCSV']]}
    keep = keep_tables and not fresh and (cur['TCSA'] >> 16) == 0xFFFF and cur['TCSA'] != 0xFFFFFFFF
    for k in TCS:
        v = int(tv[k]) if k in tv else cur[k] if keep else TCS_DEFAULTS[k]
        if k == 'TCSA': rom[TCS[k]:TCS[k] + 4] = struct.pack('>I', v & 0xFFFFFFFF)
        else: rom[TCS[k]] = v & 0xFF
    rom[TCS['TCSV'] + 1:TCS['TCSV'] + 3] = b'\xFF\xFF'
    rom[0xFF030:0xFF034] = b'\xFF' * 4            # unused
    rom[CODE:CODE_END] = code
    rom[SITE:SITE + 8] = spark2_hook(A); rom[LIT:LIT + 4] = struct.pack('>I', spk)
    rom[A['dfco_lit']:A['dfco_lit'] + 4] = struct.pack('>I', ovr)
    return notes


def build(stock_path, outdir, A=None):
    """Patch file (1 MB, 6-byte calibration ID + XOR delta) from a stock ROM of the calibration."""
    rom = bytearray(open(stock_path, 'rb').read()); orig = bytes(rom)
    A = A or AD.for_rom(rom)
    print(install(rom, keep_tables=False, A=A))
    delta = bytearray(a ^ b for a, b in zip(orig, rom)); delta[0:6] = A['cal'].encode()[:6].ljust(6, b' ')
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f"{A['cal'].lower()}_overrun.patch")
    open(out, 'wb').write(delta)
    print(f'changed {sum(1 for a, b in zip(orig, rom) if a != b)} bytes; code {len(assemble(A)[0].rstrip(bytes([0xFF])))} bytes')
    return out


if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2])

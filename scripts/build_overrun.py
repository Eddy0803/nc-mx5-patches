"""
Timed lean overrun crackle for LFJ1EE (Mazda MX-5 NC, manual), with adjustable strength.
Standalone: hooks only factory code, so it works on a stock LFJ1EE ROM, with or without the other patches.

How it works
    On lift-off the factory decel fuel cut ramps a fuel multiplier (DFCO multiplier, RAM FFFF7560) from 1.0 down
    towards 0 and cuts fuel completely below 0.6. For a set time after lift-off this patch holds that multiplier at a
    LEAN value (never above 1.0, never below 0.65) and retards the spark, so the late, lean combustion finishes in the
    exhaust manifold: a crackle on the overrun, like the factory sport-mode overrun on some modern cars.

    Arming / timing
        Pedal >= Arm pedal %          -> armed, timer = Duration (s). Nothing happens while you are on the pedal.
        Pedal <= Closed pedal %, armed, clutch up, Min RPM <= RPM <= Max RPM, speed >= Min speed,
        coolant >= Min coolant temp, timer > 0
                                      -> ACTIVE: timer counts down; fuel multiplier = Fuel; spark retarded by Retard.
        Timer runs out, clutch pressed, RPM / speed / coolant outside the window -> disarmed until you press the pedal
        past Arm pedal % again. So each lift-off gives at most one burst of Duration seconds.
        Between Closed and Arm pedal % (part throttle) nothing happens and the state is kept.

    Strength (0-100 %) blends between the "mild" and "strong" settings:
        Retard = Retard at 0 % + s * (Retard at 100 % - Retard at 0 %)   (code limit 0..30 deg)
        Fuel   = Fuel at 0 %   + s * (Fuel at 100 %   - Fuel at 0 %)     (code limit 0.65..1.0: lean or stoich, never rich)
    More retard and more fuel = louder; less of both = milder.

Hooks
    1) DFCO task call: the task literal (0x1384C) that called the factory DFCO routine (0x45940) now calls OVR, which
       runs the factory routine first and then, while active, overwrites the multiplier it produced.
    2) Spark-advance sum 0x4DA9C: the load of the factory term FFFF9F74 at 0x4DAF4 becomes a call to SPK (via literal
       0x4DCC8), which returns fr3 = [FFFF9F74] - Retard while active. (The ignition cut uses a different term, FFFF7D68.)

RAM (unused by the factory software): AC38 f32 time left, AC3C u8 armed, AC3D u8 active (0x5A), AC40 f32 retard.
Tables 0xFE800.. (see TBL). Code 0xFE880..0xFEC00.
"""
import struct, sys, os, importlib.util

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('sh_asm', os.path.join(here, 'sh_asm.py'))
SA = importlib.util.module_from_spec(spec); spec.loader.exec_module(SA)
spec = importlib.util.spec_from_file_location('addrs', os.path.join(here, 'addrs.py'))
AD = importlib.util.module_from_spec(spec); spec.loader.exec_module(AD)

TBL_START, CODE, CODE_END = 0xFE800, 0xFE880, 0xFEC00
TBL = {'EN': 0xFE800, 'STR': 0xFE804, 'DUR': 0xFE808, 'RMIN': 0xFE80C, 'RMAX': 0xFE810, 'VMIN': 0xFE814,
       'TMIN': 0xFE818, 'ARM': 0xFE81C, 'CLOSED': 0xFE820, 'RETLO': 0xFE824, 'RETHI': 0xFE828,
       'FUELLO': 0xFE82C, 'FUELHI': 0xFE830, 'RATE': 0xFE834}
DEFAULTS = {'EN': 0.0, 'STR': 50.0, 'DUR': 2.0, 'RMIN': 2500.0, 'RMAX': 6500.0, 'VMIN': 30.0, 'TMIN': 75.0,
            'ARM': 20.0, 'CLOSED': 2.0, 'RETLO': 6.0, 'RETHI': 20.0, 'FUELLO': 0.82, 'FUELHI': 0.95, 'RATE': 90.0}
LIMITS = {'EN': (0.0, 1.0), 'STR': (0.0, 100.0), 'DUR': (0.0, 5.0), 'RMIN': (1500.0, 7000.0), 'RMAX': (2000.0, 7500.0),
          'VMIN': (5.0, 200.0), 'TMIN': (40.0, 110.0), 'ARM': (5.0, 100.0), 'CLOSED': (0.0, 10.0),
          'RETLO': (0.0, 30.0), 'RETHI': (0.0, 30.0), 'FUELLO': (0.65, 1.0), 'FUELHI': (0.65, 1.0), 'RATE': (10.0, 1000.0)}
RET_CAP, FUEL_MIN, DUR_CAP = 30.0, 0.65, 5.0
RAM_STATE = 0xFFFFAC38            # +0 f32 time left, +4 u8 armed, +5 u8 active magic, +8 f32 retard
MAGIC = 0x5A


def assemble(A=None):
    A = A or AD.LFJ1EE
    a = SA.Asm(CODE); W = a.w
    # ================= OVR: called from the DFCO task slot instead of the factory DFCO routine
    a.L('OVR')
    W(0x4F22); a.lit('movl', 0, 'P_FDFCO'); W(0x400B); W(0x0009); W(0x4F26)   # factory DFCO first
    a.lit('movl', 2, 'P_STATE')
    W(0xE000); W(0x8025)                               # active = 0  (mov.b r0,@(5,r2))
    a.lit('movl', 1, 'P_EN'); W(0xF018); W(0xF18D); W(0xF015); a.br('bf', 'DISARM')   # Enable > 0
    a.lit('movl', 1, 'P_CLUTCH'); W(0x6010); W(0x8801); a.br('bt', 'DISARM')          # clutch pressed -> disarm
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
    a.lit('movl', 1, 'P_RATE'); W(0xF018); W(0xF69D); W(0xF603); W(0xF561); W(0xF25A)  # time -= 1/rate
    # strength s = clamp(STR / 100, 0, 1) -> fr0
    a.lit('movl', 1, 'P_STR'); W(0xF018); a.lit('mova', 0, 'C_100'); W(0xF608); W(0xF063)
    W(0xF18D); W(0xF105); a.br('bf', 'S1'); W(0xF01C)                                  # 0 > s -> 0
    a.L('S1'); W(0xF19D); W(0xF015); a.br('bf', 'S2'); W(0xF01C)                       # s > 1 -> 1
    a.L('S2')
    # retard = lo + s*(hi-lo), limited 0..30 -> fr7, stored at state+8
    a.lit('movl', 1, 'P_RETLO'); W(0xF618); a.lit('movl', 1, 'P_RETHI'); W(0xF718)
    W(0xF761); W(0xF702); W(0xF760)
    a.lit('movl', 1, 'C_RETCAP_P'); W(0xF618); W(0xF765); a.br('bf', 'R1'); W(0xF76C)  # > 30 -> 30
    a.L('R1'); W(0xF68D); W(0xF675); a.br('bf', 'R2'); W(0xF76C)                       # 0 > ret -> 0
    a.L('R2'); W(0xE008); W(0xF277)                    # retard -> @(8,r2)  (fmov.s fr7,@(r0,r2))
    # fuel = lo + s*(hi-lo), limited 0.65..1.0 -> fr7
    a.lit('movl', 1, 'P_FUELLO'); W(0xF618); a.lit('movl', 1, 'P_FUELHI'); W(0xF718)
    W(0xF761); W(0xF702); W(0xF760)
    W(0xF69D); W(0xF765); a.br('bf', 'F1'); W(0xF76C)                                  # > 1.0 -> 1.0
    a.L('F1'); a.lit('movl', 1, 'C_FMIN_P'); W(0xF618); W(0xF675); a.br('bf', 'F2'); W(0xF76C)   # 0.65 > f -> 0.65
    a.L('F2'); W(0xF774); a.br('bf', 'EXIT')           # NaN guard (fcmp/eq fr7,fr7)
    a.lit('movl', 1, 'P_MULT'); W(0xF17A)              # DFCO multiplier = fuel
    W(0xE05A); W(0x000B); W(0x8025)                    # active = 0x5A ; return
    a.L('DISARM'); W(0xE000); W(0x8024)                # armed = 0
    a.L('EXIT'); W(0x000B); W(0x0009)
    # ================= SPK: called from the spark-advance sum instead of the FFFF9F74 term load. fr3 = term - retard
    # (only r0, r1, r3, fr0, fr1, fr3 are used: they are free at that point of the factory routine)
    a.L('SPK')
    a.lit('movl', 1, 'P_TERM2'); W(0xF318)
    a.lit('movl', 1, 'P_STATE'); W(0x8415); W(0x885A); a.br('bf', 'SDONE')            # active?  (mov.b @(5,r1),r0)
    W(0xE008); W(0xF016)                               # fr0 = retard  (fmov.s @(r0,r1),fr0)
    W(0xF18D); W(0xF015); a.br('bf', 'SDONE')          # retard > 0   (NaN fails)
    a.lit('movl', 1, 'C_RETCAP_P'); W(0xF118); W(0xF105); a.br('bf', 'SDONE')         # 30 > retard (NaN / garbage fails)
    W(0xF301)                                          # fr3 -= retard
    a.L('SDONE'); W(0x000B); W(0x0009)
    P = lambda v: struct.pack('>I', v); F = lambda v: struct.pack('>f', v)
    a.pool([('P_FDFCO', P(A['dfco_routine'])), ('P_STATE', P(RAM_STATE)), ('P_EN', P(TBL['EN'])),
            ('P_CLUTCH', P(A['clutch'])), ('P_APP', P(A.get('igncut_pedal') or A['pedal_in'])), ('P_ARM', P(TBL['ARM'])),
            ('P_DUR', P(TBL['DUR'])), ('C_DURCAP', F(DUR_CAP)), ('P_CLOSED', P(TBL['CLOSED'])), ('P_RPM', P(A['rpm'])),
            ('P_RMIN', P(TBL['RMIN'])), ('P_RMAX', P(TBL['RMAX'])), ('P_VSS', P(A['speed'])), ('P_VMIN', P(TBL['VMIN'])),
            ('P_ECT', P(A['ect'])), ('P_TMIN', P(TBL['TMIN'])), ('P_RATE', P(TBL['RATE'])), ('P_STR', P(TBL['STR'])),
            ('C_100', F(100.0)), ('P_RETLO', P(TBL['RETLO'])), ('P_RETHI', P(TBL['RETHI'])),
            ('C_RETCAP_P', P(CODE_END - 8)), ('P_FUELLO', P(TBL['FUELLO'])), ('P_FUELHI', P(TBL['FUELHI'])),
            ('C_FMIN_P', P(CODE_END - 4)), ('P_MULT', P(A['dfco_mult'])), ('P_TERM2', P(A['spark2_term']))])
    code = a.assemble()
    assert a.labels['OVR'] == CODE and CODE + len(code) <= CODE_END - 8, hex(CODE + len(code))
    body = code + b'\xFF' * (CODE_END - 8 - CODE - len(code)) + F(RET_CAP) + F(FUEL_MIN)   # constants at the end
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
    if site == ORIG and slit == A['spark2_term'] and dlit == A['dfco_routine']:
        assert all(b == 0xFF for b in rom[TBL_START:CODE_END]), 'overrun area 0xFE800-0xFEBFF is not empty - another patch is using it'
        notes = ['fresh install']; fresh = True
    elif site == spark2_hook(A) and slit == spk and dlit == ovr and prev == code:
        notes = ['already installed: tables updated']; fresh = False
    else:
        raise AssertionError('the overrun hook sites or code area hold something unexpected (a different patch, or a different '
                             'calibration) - refusing')
    for k, adr in TBL.items():
        cur = struct.unpack_from('>f', rom, adr)[0]
        if table_values and k in table_values: v = table_values[k]
        elif keep_tables and not fresh and cur == cur: v = cur
        else: v = DEFAULTS[k]
        lo, hi = LIMITS[k]; v = max(lo, min(hi, float(v)))
        rom[adr:adr + 4] = struct.pack('>f', v)
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

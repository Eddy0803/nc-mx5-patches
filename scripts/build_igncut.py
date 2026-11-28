"""
Ignition-cut rev limiter with launch control and flat-foot shift, for LFJ1EE (Mazda MX-5 NC, manual).
Standalone: hooks only factory code, so it works on a stock LFJ1EE ROM.

Cut point (checked by CUTCHK, used by both hooks):
    clutch pressed and speed <  Split speed and Launch RPM > 0            -> Launch RPM
    clutch pressed and speed >= Split speed and Flat Shift RPM > 0
                   and pedal >= Flat Shift pedal %                        -> Flat Shift RPM
    otherwise                                                             -> RPM Fuel Cut table (0xC487C) + Offset
    overheat protection (optional, Overheat Enable > 0): coolant above Start temp lowers the cut point in a straight
    line from the cut point above (at Start temp) to Limited RPM (at Full temp and hotter); never below 3000 rpm.
    Applies to the normal limiter, launch and flat shift alike. Below Start temp nothing changes.
    cutting = Enable > 0 and RPM > cut point
    (also cutting when an optional traction-control add-on is enabled at 0xFE380 and raises flag FFFFAC4B;
     without it 0xFE380 is erased flash (NaN) and the check is ignored)

Hooks
    1) Coil dwell 0x50CFA: the factory short-dwell flag test at 0x50D00 becomes a call to DWELL (via literal 0x50DDC).
       DWELL keeps the factory short-dwell path; otherwise, while cutting, it returns T=1 and fr3 = cut dwell
       (floor 0.2 ms) so the coil cannot fire. Not cutting -> T=0, normal dwell map.
    2) Spark-advance sum 0x4DA9C: the load of the factory term FFFF7D68 at 0x4DAE8 becomes a call to RETARD
       (via literal 0x4DCC0), which returns fr1 = [FFFF7D68] - Retard while cutting.

Tables (float, big-endian)
    0xFE180 Enable                         1
    0xFE184 Offset from RPM Fuel Cut, rpm  -300
    0xFE188 Dwell while cutting, ms        0.3  (floor 0.2 in code)
    0xFE18C Timing retard while cutting    5 deg
    0xFE190 Flat Shift RPM (0 = off)       0
    0xFE194 Launch RPM (0 = off)           0
    0xFE198 Launch / flat-shift split speed 10 km/h
    0xFE19C Flat shift minimum pedal %      80
RAM read: RPM FFFF6D5C, speed FFFF6D04, pedal FFFF56C8, clutch switch byte FFFF7100 (1 = pressed),
factory dwell flag FFFF7346 bit 5, spark term FFFF7D68. Nothing is written to RAM.
"""
import struct, sys, os, importlib.util

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('sh_asm', os.path.join(here, 'sh_asm.py'))
SA = importlib.util.module_from_spec(spec); spec.loader.exec_module(SA)
spec = importlib.util.spec_from_file_location('addrs', os.path.join(here, 'addrs.py'))
AD = importlib.util.module_from_spec(spec); spec.loader.exec_module(AD)

CODE, CODE_END = 0xFE000, 0xFE180
TBL = {'EN': 0xFE180, 'OFS': 0xFE184, 'DW': 0xFE188, 'RET': 0xFE18C, 'FS': 0xFE190, 'LAUNCH': 0xFE194,
       'VSPLIT': 0xFE198, 'FSAPP': 0xFE19C}
TBL_END = 0xFE1A0
OH_TBL = {'OHEN': 0xFE1A0, 'OHT1': 0xFE1A4, 'OHT2': 0xFE1A8, 'OHRPM': 0xFE1AC}     # overheat rev limit
OH_DEFAULTS = {'OHEN': 0.0, 'OHT1': 110.0, 'OHT2': 120.0, 'OHRPM': 5000.0}
OH_LIMITS = {'OHEN': (0.0, 1.0), 'OHT1': (90.0, 130.0), 'OHT2': (95.0, 140.0), 'OHRPM': (3000.0, 7500.0)}
OH_CODE, OH_END = 0xFE200, 0xFE300
OH_FLOOR = 3000.0
OLD_RETARD = 0xFE0A4          # RETARD address of the version without overheat protection (0.9.x up to 0.9.13)
DEFAULTS = {'EN': 1.0, 'OFS': -300.0, 'DW': 0.3, 'RET': 5.0, 'FS': 0.0, 'LAUNCH': 0.0, 'VSPLIT': 10.0, 'FSAPP': 80.0}
LIMITS = {'DW': (0.2, 3.0), 'RET': (0.0, 15.0), 'OFS': (-1000.0, 0.0), 'FS': (0.0, 7500.0), 'LAUNCH': (0.0, 7500.0),
          'VSPLIT': (2.0, 40.0), 'FSAPP': (20.0, 100.0)}
MIN_DWELL = 0.2

# every calibration-specific address comes from an address set (scripts/addrs.py; LFJ1EE built in)
TC_TBL_EN, TC_RAM_ACT = 0xFE380, 0xFFFFAC4B
TC_SPARK = 0xFEA00          # traction control's timing hook (build_tc.SPK): when the spark literal points there, TC calls RETARD


def assemble(A=None):
    A = A or AD.LFJ1EE
    a = SA.Asm(CODE); W = a.w
    # ---- DWELL (called from the dwell routine instead of the factory flag test)
    a.L('DWELL')
    a.lit('movl', 0, 'P_FLAG'); W(0x6000); W(0xC820); a.br('bt', 'CHECK')     # factory short-dwell flag clear?
    a.lit('movl', 1, 'P_SLDW'); W(0xF318); W(0x000B); W(0x0018)               # factory path: fr3 = its dwell, T=1
    a.L('CHECK'); W(0x4F22); a.br('bsr', 'CUTCHK'); W(0x0009); W(0x4F26)      # (lds.l keeps T)
    a.br('bf', 'OFF')
    a.lit('movl', 1, 'P_DW'); W(0xF318)                                       # fr3 = cut dwell
    a.lit('mova', 0, 'C_MIN'); W(0xF208); W(0xF235); a.br('bf', 'OK'); W(0xF32C)   # floor 0.2 ms
    a.L('OK'); W(0x000B); W(0x0018)
    a.L('OFF'); W(0x000B); W(0x0008)
    # ---- CUTCHK: T = cutting.  clobbers r0, r1, fr0, fr3, fr5
    a.L('CUTCHK')
    a.lit('movl', 1, 'P_TCEN'); W(0xF018); W(0xF38D); W(0xF035); a.br('bf', 'NOTC')    # optional TC add-on
    a.lit('movl', 1, 'P_TCACT'); W(0x6010); W(0x8801); a.br('bf', 'NOTC'); W(0x000B); W(0x0018)
    a.L('NOTC')
    a.lit('movl', 1, 'P_EN'); W(0xF018); W(0xF38D); W(0xF035); a.br('bf', 'RET0')      # Enable > 0
    a.lit('movl', 1, 'P_FCUT'); W(0xF318); a.lit('movl', 1, 'P_OFS'); W(0xF518); W(0xF350)   # fr3 = fuel cut + offset
    a.lit('movl', 1, 'P_CLUTCH'); W(0x6010); W(0x8801); a.br('bf', 'CMP')             # clutch pressed?
    a.lit('movl', 1, 'P_VSS'); W(0xF018); a.lit('movl', 1, 'P_VSPLIT'); W(0xF518)
    W(0xF505); a.br('bf', 'MOVING')                                                    # split > speed -> stationary
    a.lit('movl', 1, 'P_LAUNCH'); W(0xF018); W(0xF58D); W(0xF055); a.br('bf', 'CMP')   # Launch RPM > 0
    W(0xF30C); a.br('bra', 'CMP'); W(0x0009)                                           # cut point = Launch RPM
    a.L('MOVING')
    a.lit('movl', 1, 'P_FS'); W(0xF018); W(0xF58D); W(0xF055); a.br('bf', 'CMP')       # Flat Shift RPM > 0
    a.lit('movl', 1, 'P_APP'); W(0xF018); a.lit('movl', 1, 'P_FSAPP'); W(0xF518)
    W(0xF505); a.br('bt', 'CMP')                                                       # pedal below min -> normal
    a.lit('movl', 1, 'P_FS'); W(0xF318)                                                # cut point = Flat Shift RPM
    a.L('CMP'); W(0x4F22); a.lit('movl', 0, 'P_OHLIM'); W(0x400B); W(0x0009); W(0x4F26)   # overheat cap on fr3
    a.lit('movl', 1, 'P_RPM'); W(0xF018); W(0x000B); W(0xF035)                         # T = rpm > cut point
    a.L('RET0'); W(0x000B); W(0x0008)
    # ---- RETARD (called from the spark-advance sum instead of the term load): fr1 = term - retard while cutting
    a.L('RETARD')
    a.lit('movl', 1, 'P_TERM'); W(0xF118); W(0x4F22); a.br('bsr', 'CUTCHK'); W(0x0009); W(0x4F26)
    a.br('bf', 'DONE'); a.lit('movl', 1, 'P_RET'); W(0xF018); W(0xF101)
    a.L('DONE'); W(0x000B); W(0x0009)
    P = lambda v: struct.pack('>I', v); F = lambda v: struct.pack('>f', v)
    a.pool([('P_FLAG', P(A['dwell_flag'])), ('P_SLDW', P(A['factory_short_dwell'])), ('P_DW', P(TBL['DW'])), ('C_MIN', F(MIN_DWELL)),
            ('P_TCEN', P(TC_TBL_EN)), ('P_TCACT', P(TC_RAM_ACT)), ('P_EN', P(TBL['EN'])), ('P_FCUT', P(A['fuel_cut_rpm'])),
            ('P_OFS', P(TBL['OFS'])), ('P_CLUTCH', P(A['clutch'])), ('P_VSS', P(A['speed'])), ('P_VSPLIT', P(TBL['VSPLIT'])),
            ('P_LAUNCH', P(TBL['LAUNCH'])), ('P_FS', P(TBL['FS'])), ('P_APP', P(A.get('igncut_pedal') or A['pedal_in'])), ('P_FSAPP', P(TBL['FSAPP'])),
            ('P_RPM', P(A['rpm'])), ('P_TERM', P(A['spark_term'])), ('P_RET', P(TBL['RET'])), ('P_OHLIM', P(OH_CODE))])
    code = a.assemble()
    assert a.labels['DWELL'] == CODE and CODE + len(code) <= CODE_END, hex(CODE + len(code))
    return code + b'\xFF' * (CODE_END - CODE - len(code)), a.labels['DWELL'], a.labels['RETARD']


def assemble_overheat(A=None):
    """OHLIM at 0xFE200: fr3 = cut point in / capped cut point out. Changes only r0, r1, fr0, fr5 (fr1, fr2 saved)."""
    A = A or AD.LFJ1EE
    a = SA.Asm(OH_CODE); W = a.w
    if A.get('ect') is None:                              # coolant temperature unknown in this port: no overheat cap
        W(0x000B); W(0x0009)
        code = a.assemble(); return code + b'\xFF' * (OH_END - OH_CODE - len(code))
    W(0xFF1B); W(0xFF2B)                                  # push fr1, fr2
    a.lit('movl', 1, 'P_EN'); W(0xF018); W(0xF58D); W(0xF055); a.br('bf', 'OX')       # Overheat Enable > 0
    a.lit('movl', 1, 'P_ECT'); W(0xF518)                  # fr5 = coolant temp
    a.lit('movl', 1, 'P_T1'); W(0xF118); W(0xF515); a.br('bf', 'OX')                 # coolant > Start temp (NaN fails)
    a.lit('movl', 1, 'P_T2'); W(0xF218); W(0xF211); W(0xF511)   # fr2 = Full - Start ; fr5 = coolant - Start
    W(0xF08D); W(0xF205); a.br('bf', 'OFULL')             # Full > Start, else full limit at once
    W(0xF523); W(0xF09D); W(0xF505); a.br('bf', 'OCALC')  # fr5 = fraction (0..1)
    a.L('OFULL'); W(0xF59D)                               # fraction = 1
    a.L('OCALC')
    a.lit('movl', 1, 'P_RPM'); W(0xF118)                  # fr1 = Limited RPM
    a.lit('movl', 1, 'C_FLOOR_P'); W(0xF018); W(0xF015); a.br('bf', 'OL'); W(0xF10C)   # never below 3000
    a.L('OL'); W(0xF23C); W(0xF211); W(0xF252)            # fr2 = (cut - limited) * fraction
    W(0xF03C); W(0xF021)                                  # fr0 = cut - fr2
    W(0xF305); a.br('bf', 'OX'); W(0xF30C)                # cut = min(cut, fr0)   (NaN never lowers it)
    a.L('OX'); W(0xF2F9); W(0xF1F9); W(0x000B); W(0x0009) # pop fr2, fr1 ; return
    P = lambda v: struct.pack('>I', v); F = lambda v: struct.pack('>f', v)
    a.pool([('P_EN', P(OH_TBL['OHEN'])), ('P_ECT', P(A['ect'])), ('P_T1', P(OH_TBL['OHT1'])), ('P_T2', P(OH_TBL['OHT2'])),
            ('P_RPM', P(OH_TBL['OHRPM'])), ('C_FLOOR_P', P(OH_END - 4))])
    code = a.assemble()
    assert OH_CODE + len(code) <= OH_END - 4, hex(OH_CODE + len(code))
    return code + b'\xFF' * (OH_END - 4 - OH_CODE - len(code)) + F(OH_FLOOR)


def install(rom, table_values=None, keep_tables=True, A=None):
    """Install / update in an LFJ1EE (or ported calibration) image (bytearray). Returns notes."""
    notes = []
    assert len(rom) == 0x100000, 'ROM must be 1 MB'
    A = A or AD.for_rom(rom)
    assert AD.is_cal(rom, A), f"not a {A['cal']} ROM"
    AD.assert_not_automatic(rom)
    code, dwell, retard = assemble(A)
    DW_HOOK, DW_ORIG = A['dwell_site'], bytes.fromhex(A['dwell_orig'])
    SP_HOOK, SP_ORIG = A['spark_site'], bytes.fromhex(A['spark_orig'])
    DW_LIT, SP_LIT = AD.dwell_info(A)['dwell_lit'], AD.spark_info(A)['term_lit']
    dw = bytes(rom[DW_HOOK:DW_HOOK + len(DW_ORIG)]); sp = bytes(rom[SP_HOOK:SP_HOOK + 8])
    lits = (struct.unpack_from('>I', rom, DW_LIT)[0], struct.unpack_from('>I', rom, SP_LIT)[0])
    via_tc = lits[1] == TC_SPARK                      # traction control's timing hook sits in front of RETARD: keep it
    if via_tc: lits = (lits[0], retard)
    prev = bytes(rom[CODE:CODE_END])
    ohcode = assemble_overheat(A)
    oh_empty = all(b == 0xFF for b in rom[OH_TBL['OHEN']:OH_END])
    if dw == DW_ORIG and sp == SP_ORIG and lits == (A['factory_short_dwell'], A['spark_term']):
        assert all(b == 0xFF for b in prev) and all(b == 0xFF for b in rom[CODE_END:TBL_END]) and oh_empty, \
            'code area 0xFE000-0xFE2FF is not empty - another patch is using it'
        notes.append('fresh install'); fresh = True
    elif dw == AD.dwell_hook(A) and sp == AD.spark_hook(A) and lits == (dwell, retard) and prev == code:
        notes.append('already installed: tables updated'); fresh = False
    elif dw == AD.dwell_hook(A) and sp == AD.spark_hook(A) and lits == (dwell, OLD_RETARD) and oh_empty:
        notes.append('updated from the version without overheat protection (settings kept)'); fresh = False
    else:
        raise AssertionError('the dwell / spark-advance hook sites or the code area hold something unexpected '
                             '(a different ignition-cut patch, or a different calibration) - refusing')
    for k, adr in TBL.items():
        cur = struct.unpack_from('>f', rom, adr)[0]
        if table_values and k in table_values:
            v = table_values[k]
        elif keep_tables and not fresh and cur == cur:
            v = cur
        else:
            v = DEFAULTS[k]
        lo, hi = LIMITS.get(k, (-1e9, 1e9)); v = max(lo, min(hi, v))
        rom[adr:adr + 4] = struct.pack('>f', v)
    for k, adr in OH_TBL.items():
        cur = struct.unpack_from('>f', rom, adr)[0]
        if table_values and k in table_values: v = table_values[k]
        elif keep_tables and not fresh and cur == cur: v = cur
        else: v = OH_DEFAULTS[k]
        lo, hi = OH_LIMITS[k]; v = max(lo, min(hi, float(v)))
        rom[adr:adr + 4] = struct.pack('>f', v)
    rom[OH_CODE:OH_END] = ohcode
    rom[CODE:CODE_END] = code
    rom[DW_HOOK:DW_HOOK + len(DW_ORIG)] = AD.dwell_hook(A); rom[DW_LIT:DW_LIT + 4] = struct.pack('>I', dwell)
    rom[SP_HOOK:SP_HOOK + 8] = AD.spark_hook(A)
    if not via_tc: rom[SP_LIT:SP_LIT + 4] = struct.pack('>I', retard)
    return notes


def build(stock_path, outdir, A=None):
    """Patch file (1 MB, 6-byte calibration ID + XOR delta) from a stock ROM of the calibration."""
    rom = bytearray(open(stock_path, 'rb').read()); orig = bytes(rom)
    A = A or AD.for_rom(rom)
    print(install(rom, keep_tables=False, A=A))
    delta = bytearray(a ^ b for a, b in zip(orig, rom)); delta[0:6] = A['cal'].encode()[:6].ljust(6, b' ')
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f"{A['cal'].lower()}_igncut.patch")
    open(out, 'wb').write(delta)
    print(f'changed {sum(1 for a, b in zip(orig, rom) if a != b)} bytes; code {len(assemble(A)[0].rstrip(bytes([0xFF])))} bytes')
    return out


if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2])

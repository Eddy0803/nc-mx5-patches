"""
Ignition-cut rev limiter with launch control and flat-foot shift, for LFJ1EE (Mazda MX-5 NC, manual).
Standalone: hooks only factory code, so it works on a stock LFJ1EE ROM.

Cut point (checked by CUTCHK, used by both hooks):
    clutch pressed and speed <  Split speed and Launch RPM > 0            -> Launch RPM
    clutch pressed and speed >= Split speed and Flat Shift RPM > 0
                   and pedal >= Flat Shift pedal %                        -> Flat Shift RPM
    otherwise                                                             -> RPM Fuel Cut table (0xC487C) + Offset
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

CODE, CODE_END = 0xFE000, 0xFE180
TBL = {'EN': 0xFE180, 'OFS': 0xFE184, 'DW': 0xFE188, 'RET': 0xFE18C, 'FS': 0xFE190, 'LAUNCH': 0xFE194,
       'VSPLIT': 0xFE198, 'FSAPP': 0xFE19C}
TBL_END = 0xFE1A0
DEFAULTS = {'EN': 1.0, 'OFS': -300.0, 'DW': 0.3, 'RET': 5.0, 'FS': 0.0, 'LAUNCH': 0.0, 'VSPLIT': 10.0, 'FSAPP': 80.0}
LIMITS = {'DW': (0.2, 3.0), 'RET': (0.0, 15.0), 'OFS': (-1000.0, 0.0), 'FS': (0.0, 7500.0), 'LAUNCH': (0.0, 7500.0),
          'VSPLIT': (2.0, 40.0), 'FSAPP': (20.0, 100.0)}
MIN_DWELL = 0.2

DW_HOOK, DW_LIT = 0x50D00, 0x50DDC
DW_ORIG = bytes.fromhex('D0356000C820002970FF600B88018F040009D332F338A00BFE3A')
SP_HOOK, SP_LIT = 0x4DAE8, 0x4DCC0
SP_ORIG = bytes.fromhex('D175F230D275F118')
RAM = {'FLAG': 0xFFFF7346, 'RPM': 0xFFFF6D5C, 'VSS': 0xFFFF6D04, 'APP': 0xFFFF56C8, 'CLUTCH': 0xFFFF7100,
       'TERM': 0xFFFF7D68}
CAL_SL_DWELL, CAL_FUELCUT = 0x000BB9FC, 0x000C487C
TC_TBL_EN, TC_RAM_ACT = 0xFE380, 0xFFFFAC4B


def assemble():
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
    a.L('CMP'); a.lit('movl', 1, 'P_RPM'); W(0xF018); W(0x000B); W(0xF035)             # T = rpm > cut point
    a.L('RET0'); W(0x000B); W(0x0008)
    # ---- RETARD (called from the spark-advance sum instead of the term load): fr1 = term - retard while cutting
    a.L('RETARD')
    a.lit('movl', 1, 'P_TERM'); W(0xF118); W(0x4F22); a.br('bsr', 'CUTCHK'); W(0x0009); W(0x4F26)
    a.br('bf', 'DONE'); a.lit('movl', 1, 'P_RET'); W(0xF018); W(0xF101)
    a.L('DONE'); W(0x000B); W(0x0009)
    P = lambda v: struct.pack('>I', v); F = lambda v: struct.pack('>f', v)
    a.pool([('P_FLAG', P(RAM['FLAG'])), ('P_SLDW', P(CAL_SL_DWELL)), ('P_DW', P(TBL['DW'])), ('C_MIN', F(MIN_DWELL)),
            ('P_TCEN', P(TC_TBL_EN)), ('P_TCACT', P(TC_RAM_ACT)), ('P_EN', P(TBL['EN'])), ('P_FCUT', P(CAL_FUELCUT)),
            ('P_OFS', P(TBL['OFS'])), ('P_CLUTCH', P(RAM['CLUTCH'])), ('P_VSS', P(RAM['VSS'])), ('P_VSPLIT', P(TBL['VSPLIT'])),
            ('P_LAUNCH', P(TBL['LAUNCH'])), ('P_FS', P(TBL['FS'])), ('P_APP', P(RAM['APP'])), ('P_FSAPP', P(TBL['FSAPP'])),
            ('P_RPM', P(RAM['RPM'])), ('P_TERM', P(RAM['TERM'])), ('P_RET', P(TBL['RET']))])
    code = a.assemble()
    assert a.labels['DWELL'] == CODE and CODE + len(code) <= CODE_END, hex(CODE + len(code))
    return code + b'\xFF' * (CODE_END - CODE - len(code)), a.labels['DWELL'], a.labels['RETARD']


def dwell_hook():
    # mov.l @(lit 0x50DDC),r3 ; jsr @r3 ; nop ; bf +8 (normal dwell map) ; bra to the factory short-dwell use ; nops
    ops = [0xD336, 0x430B, 0x0009, 0x8B08, 0xA012, 0xFE3A] + [0x0009] * 7
    return b''.join(struct.pack('>H', o) for o in ops)


def spark_hook():
    return struct.pack('>HHHH', 0xD175, 0x410B, 0xF230, 0xD275)   # mov.l lit,r1 ; jsr @r1 ; fadd (delay) ; mov.l


def install(rom, table_values=None, keep_tables=True):
    """Install / update in an LFJ1EE image (bytearray). Returns notes."""
    notes = []
    assert len(rom) == 0x100000 and rom[0xB8046:0xB804C] == b'LFJ1EE', 'not an LFJ1EE ROM'
    code, dwell, retard = assemble()
    dw = bytes(rom[DW_HOOK:DW_HOOK + len(DW_ORIG)]); sp = bytes(rom[SP_HOOK:SP_HOOK + 8])
    lits = (struct.unpack_from('>I', rom, DW_LIT)[0], struct.unpack_from('>I', rom, SP_LIT)[0])
    prev = bytes(rom[CODE:CODE_END])
    if dw == DW_ORIG and sp == SP_ORIG and lits == (CAL_SL_DWELL, RAM['TERM']):
        assert all(b == 0xFF for b in prev) and all(b == 0xFF for b in rom[CODE_END:TBL_END]), \
            'code area 0xFE000-0xFE19F is not empty - another patch is using it'
        notes.append('fresh install'); fresh = True
    elif dw == dwell_hook() and sp == spark_hook() and lits == (dwell, retard) and prev == code:
        notes.append('already installed: tables updated'); fresh = False
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
    rom[CODE:CODE_END] = code
    rom[DW_HOOK:DW_HOOK + len(DW_ORIG)] = dwell_hook(); rom[DW_LIT:DW_LIT + 4] = struct.pack('>I', dwell)
    rom[SP_HOOK:SP_HOOK + 8] = spark_hook(); rom[SP_LIT:SP_LIT + 4] = struct.pack('>I', retard)
    return notes


def build(stock_path, outdir):
    """Patch file (1 MB, 6-byte calibration ID + XOR delta) from a stock LFJ1EE ROM."""
    rom = bytearray(open(stock_path, 'rb').read()); orig = bytes(rom)
    print(install(rom, keep_tables=False))
    delta = bytearray(a ^ b for a, b in zip(orig, rom)); delta[0:6] = b'LFJ1EE'
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, 'lfj1ee_igncut.patch'), 'wb').write(delta)
    print(f'changed {sum(1 for a, b in zip(orig, rom) if a != b)} bytes; code {len(assemble()[0].rstrip(bytes([0xFF])))} bytes')


if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2])

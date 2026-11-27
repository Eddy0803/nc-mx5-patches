"""Per-calibration addresses used by the patches.

LFJ1EE is built in. Other calibrations are described by patches/<cal>/addresses.json, written by tools/port.py.
Everything the hooks need beyond these values (literal positions, branch targets, delay-slot instruction) is
decoded from the factory code bytes, so it always comes from the calibration's own code.
"""
import json, os, struct

HERE = os.path.dirname(os.path.abspath(__file__))
PATCHES = os.path.normpath(os.path.join(HERE, '..', 'patches'))

LFJ1EE = {
    'cal': 'LFJ1EE', 'id_offset': 0xB8046,
    # RAM
    'rpm': 0xFFFF6D5C, 'speed': 0xFFFF6D04, 'pedal_in': 0xFFFF56C8, 'pedal_out': 0xFFFF6CA4,
    'clutch': 0xFFFF7100, 'brake': 0xFFFF70EE, 'dwell_flag': 0xFFFF7346, 'spark_term': 0xFFFF7D68,
    'cruise_flag': 0xFFFF585E,
    # calibration tables
    'fuel_cut_rpm': 0x000C487C, 'factory_short_dwell': 0x000BB9FC,
    # code sites and their factory bytes
    'dwell_site': 0x50D00, 'dwell_orig': 'D0356000C820002970FF600B88018F040009D332F338A00BFE3A',
    'spark_site': 0x4DAE8, 'spark_orig': 'D175F230D275F118',
    'pedal_copy': 0x387F8, 'pedal_copy_orig': 'D32AF338D12A000BF13A',
    'task_literals': [0x11B00, 0x134D4],
    'crosscheck_lit': 0xB61F0,
    # overrun: coolant temp (f32 degC), decel fuel cut (DFCO) routine + its task literal + its fuel multiplier,
    # and the second spark-advance term load
    'ect': 0xFFFF6D44, 'dfco_routine': 0x45940, 'dfco_lit': 0x1384C, 'dfco_mult': 0xFFFF7560,
    'spark2_site': 0x4DAF4, 'spark2_orig': 'D374F200D274F338', 'spark2_term': 0xFFFF9F74,
    # rev-match default gearing (5-speed, 4.10 final drive, stock tyres)
    'gears': [113.8, 68.5, 48.3, 36.3, 29.5, 0.0], 'gearbox': '5MT',
    # CAN 0x4B0 receive buffer (from the ABS unit): 4 x u16 wheel speeds FL, FR, RL, RR, each km/h * 100 + 10000.
    # The factory code only uses the rear two; NC Patcher shows all four live (tab 1).
    'wheel_speeds': 0xFFFF6A80,
    'verified_on_car': True,
}
OPTIONAL = ('igncut_pedal', 'pedal_copy', 'crosscheck_lit', 'pedal_override',   # may be absent / None in a port
            'ect', 'dfco_routine', 'dfco_lit', 'dfco_mult', 'spark2_site', 'spark2_term', 'wheel_speeds',
            'pedal_copy2', 'pedal_copy2_orig', 'pedal_in2', 'task_literals2')
# Two-path throttle software (LFLM**, LFLP**, LFG***, LFF*ED, ... - 29 calibrations): the engine-side pedal is written by two
# plain copy routines, one per task list: pedal_copy (task_literals) copies pedal_in (the pedal stage, sensor or factory
# override), pedal_copy2 (task_literals2) copies pedal_in2 (a processed version of it). Rev-match and traction control then
# take over both copies (a second entry point each), so they run from both task lists, as on LFJ1EE.
# pedal_override: calibration byte of a factory pedal override inside the pedal-copy routine (e.g. LF9WEB). When it is
# non-zero rev-match hands every call straight back to the untouched factory routine.
HEX_KEYS = ('id_offset', 'rpm', 'speed', 'pedal_in', 'pedal_out', 'clutch', 'brake', 'dwell_flag', 'spark_term',
            'cruise_flag', 'fuel_cut_rpm', 'factory_short_dwell', 'dwell_site', 'spark_site', 'pedal_copy', 'crosscheck_lit',
            'pedal_override', 'ect', 'dfco_routine', 'dfco_lit', 'dfco_mult', 'spark2_site', 'spark2_term', 'wheel_speeds',
            'pedal_copy2', 'pedal_in2')


def to_json(A):
    d = dict(A)
    for k in HEX_KEYS + ('igncut_pedal',):
        if d.get(k) is not None: d[k] = f'0x{A[k]:X}'
    d['task_literals'] = [f'0x{v:X}' for v in A.get('task_literals') or []]
    if A.get('task_literals2'): d['task_literals2'] = [f'0x{v:X}' for v in A['task_literals2']]
    return json.dumps(d, indent=2)


def from_json(text):
    d = json.loads(text)
    for k in HEX_KEYS + ('igncut_pedal',):
        if isinstance(d.get(k), str): d[k] = int(d[k], 16)
    d['task_literals'] = [int(v, 16) for v in d.get('task_literals') or []]
    if d.get('task_literals2'): d['task_literals2'] = [int(v, 16) for v in d['task_literals2']]
    return d


def known():
    out = [LFJ1EE]
    extra = os.environ.get('NC_ADDRESSES')          # an addresses.json outside patches/ (tools/port.py, the app):
    if extra and os.path.exists(extra):             # it comes first, so it can also override a built-in set
        out.insert(0, from_json(open(extra, encoding='utf-8').read()))
    folder = os.environ.get('NC_PORTS_DIR')          # a folder of <cal>/addresses.json (used by the app)
    if folder and os.path.isdir(folder):
        for c in sorted(os.listdir(folder)):
            q = os.path.join(folder, c, 'addresses.json')
            if os.path.exists(q): out.append(from_json(open(q, encoding='utf-8').read()))
    if os.path.isdir(PATCHES):
        for c in sorted(os.listdir(PATCHES)):
            p = os.path.join(PATCHES, c, 'addresses.json')
            if os.path.exists(p) and c.upper() != 'LFJ1EE':
                out.append(from_json(open(p, encoding='utf-8').read()))
    return out


def is_cal(rom, A):
    return bytes(rom[A['id_offset']:A['id_offset'] + len(A['cal'])]) == A['cal'].encode()


def for_rom(rom):
    for A in known():
        if is_cal(rom, A):
            return A
    raise AssertionError('calibration not supported yet - port it with tools/port.py (see docs/porting.md)')


def for_cal(cal):
    for A in known():
        if A['cal'].upper() == cal.upper():
            return A
    raise AssertionError(f'no addresses for {cal} - port it with tools/port.py')


# ---- gearbox (the patches are for manual gearboxes only)
GEARBOXES = {3.136: ('5MT', '5-speed manual', 5), 3.815: ('6MT', '6-speed manual', 6), 3.538: ('6AT', '6-speed automatic', 6),
             # 6-speed manual with a lower 1st gear (3.709 / 2.190 / 1.536 / 1.177 / 1.000 / 0.832, final drive 3.727), in
             # LF9HED/EE, LFFCED, LFH9EC-EF, LFLEEC, LFLGEC (same table place and layout as LFJ1EE; all NC calibrations romdrop supports)
             3.709: ('6MT', '6-speed manual', 6)}
RPM_PER_KMH_FACTOR = 8.85      # rpm per km/h per unit of overall ratio, stock NC tyre size (LFJ1EE: 3.136 x 4.10 x 8.85 = 113.8)


def gearbox(rom):
    """find the gear-ratio table ([final drive][1st][2nd]...) and identify the gearbox by its 1st-gear ratio.
    -> {'type': '5MT'|'6MT'|'6AT', 'name', 'manual', 'final', 'ratios', 'addr'} or None if no NC table is found"""
    for a in range(0x80000, 0xF0000, 4):
        fd = struct.unpack_from('>f', rom, a)[0]
        if not 3.0 < fd < 5.0:
            continue
        g = [struct.unpack_from('>f', rom, a + 4 + 4 * i)[0] for i in range(6)]
        for first, (code, name, n) in GEARBOXES.items():
            if abs(g[0] - first) < 0.003 and all(g[i] > g[i + 1] for i in range(4)) and any(abs(v - 1.0) < 1e-4 for v in g[:5]):
                return {'type': code, 'name': name, 'manual': code != '6AT', 'final': fd, 'ratios': g[:n], 'addr': a}
    return None


def gears_from_rom(gb):
    """rev-match RPM-per-km/h table for gears 1-6 (0 = no such gear), from the ROM's own ratios and final drive"""
    k = [round(r * gb['final'] * RPM_PER_KMH_FACTOR, 1) for r in gb['ratios']]
    return (k + [0.0] * 6)[:6]


def assert_not_automatic(rom):
    gb = gearbox(rom)
    assert not (gb and not gb['manual']), 'this is an AUTOMATIC (6-speed auto) ROM - these patches are for manual gearboxes only'
    return gb


def find_wheel_speeds(rom):
    """RAM buffer of CAN message 0x4B0 (wheel speeds FL, FR, RL, RR), from the CAN mailbox table: a row
    [ID 0x4B0][receive flag 01, mailbox, DLC 8][RAM buffer FFFFxxxx][0 / 01000000]. None unless exactly one row matches.
    (Same layout in all 113 NC stock ROMs checked; their 0x4B0 handlers all read the rear two, bytes 4-7.)"""
    hits = []
    for a in range(0, len(rom) - 16, 4):
        if struct.unpack_from('>I', rom, a)[0] != 0x4B0: continue
        fl, buf, tail = struct.unpack_from('>III', rom, a + 4)
        if fl >> 24 == 1 and (fl >> 8) & 0xFF == 8 and buf >> 16 == 0xFFFF and tail in (0, 0x01000000):
            hits.append(buf)
    return hits[0] if len(hits) == 1 else None


def wheel_kmh(raw):
    """one wheel-speed field -> km/h, or None if the ABS unit marks it invalid / not received yet"""
    return None if raw >= 0xFFFE else (raw - 10000) / 100.0


# ---- decoded from factory code
def _w(hexstr):
    b = bytes.fromhex(hexstr); return [struct.unpack_from('>H', b, i)[0] for i in range(0, len(b), 2)]


def _lit(pc, w):
    assert w >> 12 == 0xD, f'expected mov.l @(disp,PC) at 0x{pc:05X}'
    return (pc & ~3) + 4 + (w & 0xFF) * 4


def _sx(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


def dwell_info(A):
    """factory short-dwell test: flag load, bf/s to the normal map, load of the factory short dwell, bra + store"""
    s, w = A['dwell_site'], _w(A['dwell_orig'])
    assert len(w) == 13 and w[1:7] == [0x6000, 0xC820, 0x0029, 0x70FF, 0x600B, 0x8801] and w[7] >> 8 == 0x8F \
        and w[8] == 0x0009 and w[9] >> 12 == 0xD and w[10] & 0xF0FF == 0xF038 and w[11] >> 12 == 0xA, 'unexpected dwell code'
    return {'flag_lit': _lit(s, w[0]), 'bf_target': s + 14 + 4 + _sx(w[7] & 0xFF, 8) * 2,
            'dwell_lit': _lit(s + 18, w[9]), 'bra_target': s + 22 + 4 + _sx(w[11] & 0xFFF, 12) * 2,
            'lit_reg': (w[9] >> 8) & 15, 'delay_word': w[12]}


def spark_info(A):
    s, w = A['spark_site'], _w(A['spark_orig'])
    assert len(w) == 4 and w[0] >> 8 == 0xD1 and w[1] == 0xF230 and w[2] >> 12 == 0xD and w[3] == 0xF118, 'unexpected spark code'
    return {'term_lit': _lit(s, w[0]), 'words': w}


def dwell_hook(A):
    """mov.l @(dwell literal),rN ; jsr @rN ; nop ; bf <normal map> ; bra <store> ; <factory delay slot> ; nops"""
    d, s = dwell_info(A), A['dwell_site']
    r = d['lit_reg']
    disp = (d['dwell_lit'] - ((s & ~3) + 4)) // 4
    bf = (d['bf_target'] - (s + 6) - 4) // 2
    bra = (d['bra_target'] - (s + 8) - 4) // 2
    assert 0 <= disp <= 255 and -128 <= bf <= 127 and -2048 <= bra <= 2047
    ops = [0xD000 | r << 8 | disp, 0x400B | r << 8, 0x0009, 0x8B00 | (bf & 0xFF), 0xA000 | (bra & 0xFFF), d['delay_word']]
    return b''.join(struct.pack('>H', o) for o in ops + [0x0009] * 7)


def spark_hook(A):
    w = spark_info(A)['words']
    return struct.pack('>HHHH', w[0], 0x410B, w[1], w[2])   # mov.l lit,r1 ; jsr @r1 ; fadd (delay) ; mov.l

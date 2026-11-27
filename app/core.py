"""Glue between the GUI and the patch code in scripts/ and tools/ (works from source and from the packaged .exe)."""
import importlib.util, json, os, re, struct, sys

BASE = getattr(sys, '_MEIPASS', None) or os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
DATA = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'NCPatcher')
PORTS = os.path.join(DATA, 'ports')
os.makedirs(PORTS, exist_ok=True)
os.environ['NC_PORTS_DIR'] = PORTS          # ported calibrations live here; scripts/addrs.py picks them up


def _load(rel, name):
    s = importlib.util.spec_from_file_location(name, os.path.join(BASE, rel))
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


AD = _load('scripts/addrs.py', 'addrs')
IG = _load('scripts/build_igncut.py', 'build_igncut')
RV = _load('scripts/build_revmatch.py', 'build_revmatch')
OV = _load('scripts/build_overrun.py', 'build_overrun')
TC = _load('scripts/build_tc.py', 'build_tc')
PORT = _load('tools/port.py', 'port')
DEFS = _load('tools/add_definitions.py', 'add_definitions')
CODE_RV = RV.CODE


def read_rom(path):
    b = open(path, 'rb').read()
    if len(b) != 0x100000:
        raise ValueError(f'{os.path.basename(path)} is {len(b)} bytes - an NC ECU file is exactly 1 MB (1,048,576 bytes)')
    return bytearray(b)


def guess_cal(rom):
    """calibration ID: one the app knows, else the LFJ1EE-style pair (same ID at X and X+0x46), else any ID-like string"""
    for A in AD.known():
        if AD.is_cal(rom, A): return A['cal'], A
    ids = {}
    for m in re.finditer(rb'L[A-Z0-9]{5}', bytes(rom[0xA0000:0xE0000])):
        ids.setdefault(m.group(0), []).append(0xA0000 + m.start())
    for k, offs in ids.items():
        if any(o + 0x46 in offs for o in offs): return k.decode(), None
    return (next(iter(ids)).decode() if ids else None), None


def state(rom, A):
    """which patches are installed and their current settings"""
    st = {'igncut': False, 'revmatch': False, 'overrun': False, 'tc': False, 'ig': {}, 'rv': {}, 'ov': {}, 'tcv': {}}
    try:
        if bytes(rom[A['dwell_site']:A['dwell_site'] + 26]) == AD.dwell_hook(A):
            st['igncut'] = True
            st['ig'] = {k: struct.unpack_from('>f', rom, a)[0] for k, a in IG.TBL.items()}
    except (AssertionError, KeyError):
        pass
    if A.get('task_literals') and TC.installed(rom, A):
        st['tc'] = True
        st['tcv'] = TC.read_tables(rom)
    if A.get('task_literals') and TC.next_target(rom, A) == CODE_RV:        # directly, or underneath traction control
        st['revmatch'] = True
        st['rv'] = {k: struct.unpack_from('>f', rom, RV.TBL[k])[0] for k in RV.FLOATS}
        st['rv']['BRK'] = struct.unpack_from('>I', rom, RV.TBL['BRK'])[0]
        st['rv'].update({k: struct.unpack_from('>H', rom, RV.TBL[k])[0] for k in RV.WORDS})   # 0xFFFF = not in that version
    if A.get('dfco_lit') and struct.unpack_from('>I', rom, A['dfco_lit'])[0] == OV.CODE:
        st['overrun'] = True
        st['ov'] = {k: struct.unpack_from('>f', rom, a)[0] for k, a in OV.TBL.items()}
        st['ov'].update({k: [struct.unpack_from('>f', rom, a + 4 * i)[0] for i in range(4)] for k, a in OV.ARR.items()})
        st['ov'].update({'TCSA': struct.unpack_from('>I', rom, OV.TCS['TCSA'])[0], 'TCSM': rom[OV.TCS['TCSM']],
                         'TCSV': rom[OV.TCS['TCSV']]})
    return st


def overrun_available(A):
    return OV.available(A)


def rev_available(A):
    return bool(A.get('task_literals')) and bool(A.get('pedal_copy')) and bool(A.get('crosscheck_lit'))


IG_CODE_SIG = 0xB0          # the first 0xB0 bytes of the ignition-cut code are instructions only (same for every calibration)


def is_this_igncut(rom, A):
    """the ROM's ignition-cut code is this standalone patch (perhaps built with other addresses)"""
    return bytes(rom[IG.CODE:IG.CODE + IG_CODE_SIG]) == IG.assemble(A)[0][:IG_CODE_SIG]


def remove_igncut(rom, A):
    """put the factory code back (only for this standalone patch)"""
    d, sp = AD.dwell_info(A), AD.spark_info(A)
    rom[A['dwell_site']:A['dwell_site'] + 26] = bytes.fromhex(A['dwell_orig'])
    rom[d['dwell_lit']:d['dwell_lit'] + 4] = struct.pack('>I', A['factory_short_dwell'])
    rom[A['spark_site']:A['spark_site'] + 8] = bytes.fromhex(A['spark_orig'])
    rom[sp['term_lit']:sp['term_lit'] + 4] = struct.pack('>I', A['spark_term'])
    rom[IG.CODE:IG.TBL_END] = b'\xFF' * (IG.TBL_END - IG.CODE)


def tc_available(A):
    return TC.available(A)


def patch(rom, A, igncut=None, revmatch=None, overrun=None, tc=None):
    """igncut / revmatch / overrun / tc: dict of table values (None = leave that patch alone). Returns notes.
    Traction control cuts spark through the ignition cut, so it needs that installed (now or already)."""
    notes = []
    if igncut is not None:
        try:
            notes += IG.install(rom, igncut, A=A)
        except AssertionError:
            if not is_this_igncut(rom, A):
                raise
            keep = {k: struct.unpack_from('>f', rom, a)[0] for k, a in IG.TBL.items()}
            keep.update(igncut)
            remove_igncut(rom, A)
            notes += IG.install(rom, keep, A=A)
            notes.append('ignition-cut code rebuilt for the current addresses (settings kept)')
    if revmatch is not None:
        if not rev_available(A): raise ValueError(f"rev-match is not available for {A['cal']}")
        had = RV.install(rom, revmatch, A=A)
        notes.append('rev-match settings updated' if had else 'rev-match installed')
    if overrun is not None:
        if not overrun_available(A): raise ValueError(f"overrun is not available for {A['cal']} (port it again with this version)")
        n = OV.install(rom, overrun, A=A)
        notes.append('overrun installed' if n == ['fresh install'] else 'overrun settings updated')
    if tc is not None:
        if not tc_available(A): raise ValueError(f"traction control is not available for {A['cal']}")
        if not state(rom, A)['igncut']:
            raise ValueError('traction control needs the ignition cut (it cuts spark through it): tick the ignition cut too')
        notes += TC.install(rom, tc, A=A)
    return notes


def addresses_json(A):
    p = os.path.join(PORTS, A['cal'].lower(), 'addresses.json')
    return p if os.path.exists(p) else ''


def emulate(rom, A, which):
    """run the emulators on a patched ROM in memory, with exactly the addresses it was patched with -> {test: (last line, failures)}"""
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix='.bin'); os.close(fd)
    fd, aj = tempfile.mkstemp(suffix='.json'); os.close(fd)
    try:
        open(tmp, 'wb').write(rom)
        open(aj, 'w', encoding='utf-8').write(AD.to_json(A))
        return {t: PORT.run_test(t, tmp, aj) for t in which}
    finally:
        os.remove(tmp); os.remove(aj)


# ---- the pedal switch addresses confirmed on the car (tab 1), remembered per calibration
SETTINGS = os.path.join(DATA, 'settings.json')


def settings():
    try:
        return json.load(open(SETTINGS, encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_settings(s):
    tmp = SETTINGS + '.tmp'
    open(tmp, 'w', encoding='utf-8').write(json.dumps(s, indent=2))
    os.replace(tmp, SETTINGS)


def remember_switches(cal, clutch, brake, source='car'):
    """source: 'car' (found by the car check) or 'entered' (typed in tab 2)"""
    import time
    s = settings()
    s.setdefault('switches', {})[cal.upper()] = {'clutch': f'0x{clutch:08X}', 'brake': f'0x{brake:08X}',
                                                 'checked': time.strftime('%Y-%m-%d'), 'source': source}
    if source == 'car': s['guide_done'] = True
    save_settings(s)


def remembered_switches(cal):
    """-> {'clutch': int, 'brake': int, 'checked': 'YYYY-MM-DD', 'source': 'car'|'entered'} or None"""
    d = (settings().get('switches') or {}).get((cal or '').upper())
    if not d: return None
    try:
        return {'clutch': int(d['clutch'], 16), 'brake': int(d['brake'], 16), 'checked': d.get('checked', ''),
                'source': d.get('source', 'car')}
    except (KeyError, ValueError, TypeError):
        return None


def remember_read_format(cal, fmt, skip):
    """the memory-read format the ECU answered on connect (tab 1); used to write the OpenPort SD-card logging file"""
    s = settings(); s.setdefault('read_format', {})[cal.upper()] = {'fmt': fmt, 'skip': skip}; save_settings(s)


def remembered_read_format(cal):
    return (settings().get('read_format') or {}).get(cal.upper())


# OpenPort 2.0 standalone logging (logcfg.txt): how each read format maps to its mode $23 settings
# (tx address bytes, tx length bytes, uds); the reply's echoed address bytes = the reader's skip
LOGCFG_MODE23 = {'A4S2': (4, 2, 0), 'A4S1': (4, 1, 0), 'A3S1': (3, 1, 0), 'A3S2': (3, 2, 0), 'U14': (4, 1, 1), 'U24': (4, 2, 1)}


def logcfg_text(A, fmt, skip, channels):
    """logcfg.txt for the OpenPort 2.0's microSD card: the same channels as tab 4, read by address (mode $23)"""
    tx, ln, uds = LOGCFG_MODE23[fmt]
    out = [f'; OpenPort 2.0 standalone logging for {A["cal"]} - made by NC Patcher.',
           '; Copy this file to the ROOT of the OpenPort\'s microSD card, named exactly logcfg.txt.',
           '; Plug the OpenPort into the car and turn the ignition on: it logs to the card by itself (no laptop).',
           f'; Read format {fmt} (the one your ECU answered in NC Patcher tab 1). Read-only: nothing is written to the ECU.',
           '', 'type=obd', 'protocolid=6 ; ISO15765 (CAN)',
           f'mode23txaddrwidth={tx}', f'mode23txlenwidth={ln}', f'mode23rxaddrwidth={skip}'] + (['mode23uds=1'] if uds else [])
    for name, addr, kind in channels:
        pname = re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_')
        if kind == 'f32':
            out += ['', f'paramname={pname}', 'mode=0x23', f'paramid=0x{addr:08X}', 'databits=32', 'isfloat=1']
        elif kind in ('u8', 'magic5A'):
            out += ['', f'paramname={pname}' + ('_raw_5A_is_on' if kind == 'magic5A' else ''), 'mode=0x23', f'paramid=0x{addr:08X}', 'databits=8']
        elif kind == 'wheel':
            for i, w in enumerate(('Front_left_kmh', 'Front_right_kmh', 'Rear_left_kmh', 'Rear_right_kmh')):
                out += ['', f'paramname={w}', 'mode=0x23', f'paramid=0x{addr + 2 * i:08X}', 'databits=16', 'scalingrpn=x,10000,-,100,/']
    return '\n'.join(out) + '\n'


LOGCFG_OBD = (('RPM', 0x0C, 16, 'x,4,/'), ('Speed_kmh', 0x0D, 8, 'x'), ('Coolant_C', 0x05, 8, 'x,40,-'),
              ('Intake_air_C', 0x0F, 8, 'x,40,-'), ('Throttle_pct', 0x11, 8, 'x,100,*,255,/'), ('Load_pct', 0x04, 8, 'x,100,*,255,/'),
              ('Timing_deg', 0x0E, 8, 'x,2,/,64,-'), ('STFT_pct', 0x06, 8, 'x,128,-,100,*,128,/'),
              ('LTFT_pct', 0x07, 8, 'x,128,-,100,*,128,/'), ('MAF_gs', 0x10, 16, 'x,100,/'))


def logcfg_obd_text(cal):
    """logcfg.txt using only standard OBD-II mode $01 PIDs every NC ECU supports (any calibration, automatics too)"""
    out = [f'; OpenPort 2.0 standalone logging, standard OBD-II (any NC ECU) - made by NC Patcher for {cal or "an NC"}.',
           '; Copy this file to the ROOT of the OpenPort\'s microSD card, named exactly logcfg.txt.',
           '; Plug the OpenPort into the car and turn the ignition on: it logs to the card by itself (no laptop).',
           '; Only standard mode $01 values that every NC ECU answers are listed (an unsupported one can stop the logging).',
           '', 'type=obd', 'protocolid=6 ; ISO15765 (CAN)']
    for name, pid, bits, rpn in LOGCFG_OBD:
        out += ['', f'paramname={name}', 'mode=0x01', f'paramid=0x{pid:02X}', f'databits={bits}', f'scalingrpn={rpn}']
    return '\n'.join(out) + '\n'


# ---- channel catalogue for a custom logcfg.txt: (group, name, mode, address / pid, databits, isfloat, scalingrpn, on by default)
OBD_LOGCFG = [  # standard mode $01 (any NC ECU); the ECU must support a PID or the OpenPort may stop logging
    ('RPM', 0x0C, 16, 'x,4,/', True), ('Speed km/h', 0x0D, 8, 'x', True), ('Coolant C', 0x05, 8, 'x,40,-', True),
    ('Intake air C', 0x0F, 8, 'x,40,-', True), ('Throttle %', 0x11, 8, 'x,100,*,255,/', True), ('Load %', 0x04, 8, 'x,100,*,255,/', True),
    ('Timing deg', 0x0E, 8, 'x,2,/,64,-', True), ('STFT %', 0x06, 8, 'x,128,-,100,*,128,/', True),
    ('LTFT %', 0x07, 8, 'x,128,-,100,*,128,/', True), ('MAF g/s', 0x10, 16, 'x,100,/', True),
    ('Pedal %', 0x49, 8, 'x,100,*,255,/', False), ('Battery V', 0x42, 16, 'x,1000,/', False),
    ('Commanded lambda', 0x44, 16, 'x,32768,/', False), ('Lambda front O2', 0x34, 32, 'x,65536,/,32768,/', False)]


def log_catalog(A=None, tcs=None):
    """every channel a logcfg.txt can hold for this calibration: RAM ones (mode $23) if A is known, standard OBD-II always.
    -> [dict(group, name, mode, id, bits, float, rpn, default)]"""
    cat = []
    def ram(group, name, addr, bits, flt=False, rpn=None, default=True):
        cat.append(dict(group=group, name=name, mode=0x23, id=addr, bits=bits, float=flt, rpn=rpn, default=default))
    if A:
        ram('Engine (RAM)', 'RPM', A['rpm'], 32, True); ram('Engine (RAM)', 'Speed km/h', A['speed'], 32, True)
        ram('Engine (RAM)', 'Pedal %', A.get('igncut_pedal') or A['pedal_in'], 32, True)
        ram('Engine (RAM)', 'Throttle request %', A['pedal_out'], 32, True)
        if A.get('ect'): ram('Engine (RAM)', 'Coolant C', A['ect'], 32, True)
        ram('Engine (RAM)', 'Clutch (1 = down)', A['clutch'], 8); ram('Engine (RAM)', 'Brake (1 = on)', A['brake'], 8)
        if A.get('wheel_speeds'):
            for i, w in enumerate(('Front left', 'Front right', 'Rear left', 'Rear right')):
                ram('Wheel speeds (ABS)', f'{w} km/h', A['wheel_speeds'] + 2 * i, 16, rpn='x,10000,-,100,/')
        P = 'Patches'
        ram(P, 'Rev-match / anti-stall acting (1)', 0xFFFFAC12, 8)
        ram(P, 'Rev-match remembered gear', 0xFFFFAC13, 8)
        ram(P, 'Rev-match hold time left, calls', 0xFFFFAC10, 16, default=False)
        ram(P, 'Rev-match downshift switch (23205 = on, 42330 = off)', 0xFFFFAC50, 16, default=False)
        ram(P, 'Clutch hold delay counter, calls', 0xFFFFAC58, 16, default=False)
        ram(P, 'TC cutting (1)', 0xFFFFAC4B, 8)
        ram(P, 'TC lockout after clutch, calls', 0xFFFFAC4A, 8, default=False)
        ram(P, 'Overrun burst (90 = on)', 0xFFFFACD5, 8)
        ram(P, 'Overrun time left, s', 0xFFFFACD0, 32, True, default=False)
        ram(P, 'Overrun retard, deg', 0xFFFFACD8, 32, True, default=False)
        ram(P, 'Overrun sport mode (90 = on)', 0xFFFFACDD, 8, default=False)
        if tcs: ram(P, f'TCS byte (off when & 0x{tcs["mask"]:02X} = 0x{tcs["val"]:02X})', tcs['addr'], 8, default=False)
    for name, pid, bits, rpn, d in OBD_LOGCFG:
        cat.append(dict(group='Standard OBD-II (any NC ECU)', name=name, mode=0x01, id=pid, bits=bits, float=False, rpn=rpn,
                        default=d and not A))
    return cat


def logcfg_custom_text(cal, picked, fmt=None, skip=0):
    """logcfg.txt with exactly the picked channels; RAM channels need the ECU's read format (fmt)"""
    ram = [c for c in picked if c['mode'] == 0x23]
    if ram and fmt not in LOGCFG_MODE23: raise ValueError('RAM channels need the ECU\'s read format: connect once in tab 1')
    out = [f'; OpenPort 2.0 standalone logging for {cal or "an NC"} - made by NC Patcher ({len(picked)} channels).',
           '; Copy this file to the ROOT of the OpenPort\'s microSD card, named exactly logcfg.txt.',
           '; Plug the OpenPort into the car and turn the ignition on: it logs to the card by itself (no laptop).',
           '; Read-only: nothing is written to the ECU. Fewer channels = more samples per second.',
           '', 'type=obd', 'protocolid=6 ; ISO15765 (CAN)']
    if ram:
        tx, ln, uds = LOGCFG_MODE23[fmt]
        out += [f'mode23txaddrwidth={tx}', f'mode23txlenwidth={ln}', f'mode23rxaddrwidth={skip}'] + (['mode23uds=1'] if uds else [])
    ram_names = {c['name'] for c in ram}
    for c in picked:
        pname = re.sub(r'[^A-Za-z0-9]+', '_', c['name']).strip('_') + ('_OBD' if c['mode'] == 0x01 and c['name'] in ram_names else '')
        out += ['', f'paramname={pname}', f'mode=0x{c["mode"]:02X}',
                f'paramid=0x{c["id"]:08X}' if c['mode'] == 0x23 else f'paramid=0x{c["id"]:02X}', f'databits={c["bits"]}']
        if c['float']: out.append('isfloat=1')
        if c['rpn'] and c['rpn'] != 'x': out.append(f'scalingrpn={c["rpn"]}')
    return '\n'.join(out) + '\n'


def remember_tcs(cal, addr, mask, val, source='car'):
    """the TCS-off signal (for the overrun sport mode): (byte at addr & mask) == val means TCS off.
    source: 'car' (TCS capture in tab 1) or 'entered' (typed in tab 2)"""
    import time
    s = settings()
    s.setdefault('tcs', {})[cal.upper()] = {'addr': f'0x{addr:08X}', 'mask': f'0x{mask:02X}', 'val': f'0x{val:02X}',
                                            'checked': time.strftime('%Y-%m-%d'), 'source': source}
    save_settings(s)


def remembered_tcs(cal):
    """-> {'addr': int, 'mask': int, 'val': int, 'checked': str, 'source': 'car'|'entered'} or None"""
    d = (settings().get('tcs') or {}).get((cal or '').upper())
    if not d: return None
    try:
        r = {'addr': int(d['addr'], 16), 'mask': int(d['mask'], 16), 'val': int(d['val'], 16), 'checked': d.get('checked', ''),
             'source': d.get('source', 'car')}
    except (KeyError, ValueError, TypeError):
        return None
    return r if ECU_RAM[0] <= r['addr'] < ECU_RAM[1] and r['mask'] else None


ECU_RAM = (0xFFFF0000, 0xFFFFC000)


def with_switches(A):
    """the address set with the clutch / brake confirmed on the car (if any) -> (A, remembered or None)"""
    m = remembered_switches(A['cal'])
    if not m: return A, None
    A2 = dict(A); A2['clutch'] = m['clutch']; A2['brake'] = m['brake']
    return A2, m


def defs_source(A):
    if A['cal'] == 'LFJ1EE': return os.path.join(BASE, 'ncflash', 'lfj1ee_custom_tables.xml')
    c = A['cal'].lower()
    for folder in (PORTS, os.path.join(BASE, 'patches')):          # the user's own port first, then the bundled one
        p = os.path.join(folder, c, f'{c}_custom_tables.xml')
        if os.path.exists(p): return p
    return None


def ncflash_definition(cal):
    p = os.path.join(os.environ.get('APPDATA', ''), 'NCFlash', 'metadata', f'{cal.lower()}.xml')
    return p if os.path.exists(p) else None


def add_definitions(xml_path, A):
    """-> (ok, message)"""
    import io, contextlib
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            DEFS.add(xml_path, A['cal'], None, defs_source(A))
        return True, buf.getvalue().strip()
    except SystemExit as e:
        return False, (buf.getvalue() + '\n' + str(e)).strip()


# ---- problem reports (sent to the project's Google Form when the user presses Submit; nothing is sent otherwise)
REPORTS = os.path.join(DATA, 'reports')
REPORT_FORM = {               # the project's Google Form (problem reports and feature requests); answers go to its sheet
    'action': 'https://docs.google.com/forms/d/e/1FAIpQLScf5L3S7sJ1amw2A6QYAsHmLpwREReAUpmB3ov8j_hIEFa6Fw/formResponse',
    'title': 'entry.1468369258', 'report': 'entry.2023629847'}
REPORT_LIMIT = 30000          # characters (Google Forms paragraph answers are kept well under their limits)


def needs_report(r):
    return PORT.needs_report(r)


def make_report(r, version):
    title, body = PORT.issue_report(r, tool=f'NC Patcher {version}')
    return title, body


def save_report(title, body, cal):
    import time
    os.makedirs(REPORTS, exist_ok=True)
    p = os.path.join(REPORTS, f'port-{(cal or "unknown").lower()}-{time.strftime("%Y%m%d-%H%M%S")}.md')
    open(p, 'w', encoding='utf-8').write(f'# {title}\n\n{body}\n')
    return p


def scrub(text, names=()):
    """remove anything that could identify the user from text that may be sent. ECU file names often contain names, plates
    or car details, so: the names of files the app opened (exact, even with spaces), whole paths (to the end of the line),
    home-folder paths, any remaining file names, and the Windows user name"""
    for n in sorted({n for n in names if n}, key=len, reverse=True):
        text = re.sub(re.escape(n), '<file>', text, flags=re.I)
    text = re.sub(r'(?i)\b[a-z]:[\\/][^\n"\']*', '<path>', text)                          # C:\... to the end of the line
    text = re.sub(r'(?i)(?<![\w])(~|%[a-z]+%)[\\/][^\n"\']*', '<path>', text)              # ~\...  %APPDATA%\...
    text = re.sub(r'\\\\[^\s\\]+\\[^\n"\']*', '<path>', text)                             # \\server\share\...
    text = PORT._private(text)                                                             # the user name anywhere else
    text = re.sub(r'(?i)(?<![\w.<])[^\s\\/:*?"<>|]+\.(bin|xml|csv|md|txt|bak|patch|json|log|hex)\b', '<file>', text)
    return text


def make_feedback(kind, title, description, details=None, log=None, contact=None, version='', names=()):
    """(form title, body) for a problem report or a feature request. Only what is passed in is included; paths and file
    names (names = the files the app opened) are removed from the log, the details and the user's own text."""
    tag = {'problem': 'Problem', 'feature': 'Feature request'}[kind]
    s = lambda x: scrub(x, names)
    t = f'[{tag}] {s(title.strip())[:150]}'
    lines = [f'Type: {tag}', f'App: NC Patcher {version}', '', s(description.strip())]
    if details:
        lines += ['', '--- Details ---'] + [f'- {k}: {s(str(v))}' for k, v in details.items()]
    if contact and contact.strip():
        lines += ['', f'Contact (given by the user for a reply): {contact.strip()[:200]}']
    if log and log.strip():
        lines += ['', '--- App log (file paths and names removed) ---', s(log.strip())[-8000:]]
    return t, '\n'.join(lines)


def submit_report(title, body):
    """send the report to the project's Google Form -> (ok, message)"""
    if not REPORT_FORM:
        return False, 'Report submission is not set up in this version of the app. Use "Save to file" instead.'
    import urllib.request, urllib.parse
    if len(body) > REPORT_LIMIT:
        body = body[:REPORT_LIMIT] + '\n\n[report cut short]'
    data = urllib.parse.urlencode({REPORT_FORM['title']: title, REPORT_FORM['report']: body}).encode('utf-8')
    req = urllib.request.Request(REPORT_FORM['action'], data=data, method='POST',
                                 headers={'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': 'NCPatcher'})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            ok = 200 <= resp.status < 300
    except Exception as e:
        return False, f'Could not send the report ({e}). Check your internet connection, or use "Save to file".'
    return (True, 'Report sent - thank you.') if ok else (False, 'The form did not accept the report.')


def port(ref_path, rom_path, cal, clutch=None, brake=None, allow_call_rate=False, log=print):
    out = os.path.join(PORTS, cal.lower())
    return PORT.run_port(ref_path, rom_path, cal, out, clutch, brake, allow_call_rate,
                         os.path.join(out, f'{cal.lower()}_custom_tables.xml'), log)


def confirm_switches(A, clutch=None, brake=None):
    """record clutch / brake addresses confirmed on the car (ported calibrations only)"""
    p = os.path.join(PORTS, A['cal'].lower(), 'addresses.json')
    if not os.path.exists(p): return False
    d = json.load(open(p, encoding='utf-8'))
    if clutch: d['clutch'] = f'0x{clutch:X}'
    if brake: d['brake'] = f'0x{brake:X}'
    d['switches_confirmed_on_car'] = True
    open(p, 'w', encoding='utf-8').write(json.dumps(d, indent=2))
    return True

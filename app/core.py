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
    st = {'igncut': False, 'revmatch': False, 'overrun': False, 'ig': {}, 'rv': {}, 'ov': {}}
    try:
        if bytes(rom[A['dwell_site']:A['dwell_site'] + 26]) == AD.dwell_hook(A):
            st['igncut'] = True
            st['ig'] = {k: struct.unpack_from('>f', rom, a)[0] for k, a in IG.TBL.items()}
    except (AssertionError, KeyError):
        pass
    if A.get('task_literals') and struct.unpack_from('>I', rom, A['task_literals'][0])[0] == CODE_RV:
        st['revmatch'] = True
        st['rv'] = {k: struct.unpack_from('>f', rom, RV.TBL[k])[0] for k in RV.FLOATS}
        st['rv']['BRK'] = struct.unpack_from('>I', rom, RV.TBL['BRK'])[0]
    if A.get('dfco_lit') and struct.unpack_from('>I', rom, A['dfco_lit'])[0] == OV.CODE:
        st['overrun'] = True
        st['ov'] = {k: struct.unpack_from('>f', rom, a)[0] for k, a in OV.TBL.items()}
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


def patch(rom, A, igncut=None, revmatch=None, overrun=None):
    """igncut / revmatch / overrun: dict of table values (None = leave that patch alone). Returns notes."""
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
    return notes


def addresses_json(A):
    p = os.path.join(PORTS, A['cal'].lower(), 'addresses.json')
    return p if os.path.exists(p) else ''


def emulate(rom, A, which):
    """run the emulators on a patched ROM in memory -> {test: (last line, failures)}"""
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix='.bin'); os.close(fd)
    try:
        open(tmp, 'wb').write(rom)
        return {t: PORT.run_test(t, tmp, addresses_json(A)) for t in which}
    finally:
        os.remove(tmp)


def defs_source(A):
    if A['cal'] == 'LFJ1EE': return os.path.join(BASE, 'ncflash', 'lfj1ee_custom_tables.xml')
    p = os.path.join(PORTS, A['cal'].lower(), f"{A['cal'].lower()}_custom_tables.xml")
    return p if os.path.exists(p) else None


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
REPORT_FORM = {               # the project's Google Form ("NC Patcher port problem reports"); answers go to its sheet
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

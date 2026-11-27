"""Add this repo's table definitions to an NC Flash or EcuFlash definition file, so the new tables show up.

Without this, NC Flash / EcuFlash only show the tables their definition file already knows about - the patch
settings are in the ROM but invisible.

usage:
  python tools/add_definitions.py <definition.xml> [--only igncut|revmatch|overrun|tc] [--cal LFJ1EE] [--source my_tables.xml]
      Adds the scalings and tables to the <rom> block for that calibration (default LFJ1EE).
      Makes a backup next to the file first (<name>.xml.<date-time>.bak), skips anything already present,
      keeps the file's formatting, and checks the result is still valid XML.
      Tables already present (same name and address) are moved to this repo's current category if it changed
      (e.g. rev-match split into Downshift Rev Match / Upshift Hold / Shared), and this repo's scalings already
      present are updated if they changed (e.g. the clutch hold delay's range).
      Entries earlier versions of these patches added and no longer use are removed: retired tables (matched by
      exact name and address, see RETIRED_TABLES), this repo's tables still at an old address, and retired scalings
      no table uses any more. Other patches' tables (e.g. a map switch) are never touched.
      --source: use your own table definitions (e.g. from porting to another calibration) instead of ncflash/lfj1ee_custom_tables.xml.
  python tools/add_definitions.py --find <folder> [--cal LFJ1EE]
      Lists the definition files in a folder (and its subfolders) that describe that calibration.

Where the definition files usually are:
  NC Flash : %APPDATA%\\NCFlash\\metadata\\lfj1ee.xml
  EcuFlash : the "rommetadata" folder in EcuFlash's install folder (search it with --find)
Close the program before running this, then reopen it.
"""
import os, re, sys, time
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.normpath(os.path.join(HERE, '..', 'ncflash', 'lfj1ee_custom_tables.xml'))
# Tables and scalings this project published earlier and no longer uses. They are removed from the definition when
# found with exactly this name AND address (so nothing else is touched: other patches' "(custom patch)" tables, e.g.
# traction control or a map switch, are left alone). A retired scaling is removed only if no table still uses it.
RETIRED_TABLES = {
    # pre-release downshift blip (replaced by rev-match at the same addresses)
    'Downshift Blip - Enable': 'fe300', 'Downshift Blip - Blip Pedal %': 'fe304',
    'Downshift Blip - Max Real Pedal % to Allow': 'fe308', 'Downshift Blip - Min Speed': 'fe30c',
    'Downshift Blip - Brake Switch RAM Address [hex]': 'fe310', 'Downshift Blip - Length': 'fe314',
    # pre-release ignition cut at 0xFE100 (now at 0xFE180)
    'RPM Ignition Cut - Enable': 'fe100', 'RPM Ignition Cut - Offset from Active Fuel Cut RPM': 'fe104',
    'RPM Ignition Cut - Coil Dwell While Cutting': 'fe108', 'RPM Ignition Cut - Timing Retard While Cutting': 'fe10c',
    'RPM Ignition Cut - Flat Shift Cut RPM, 0 = use offset': 'fe110',
    # overrun crackle before the lambda-vs-RPM fuel table
    'Overrun - Fuel at Strength 0 (custom patch)': 'fe82c', 'Overrun - Fuel at Strength 100 (custom patch)': 'fe830',
    'Overrun - Lambda during burst (custom patch)': 'fe82c', 'Overrun - Strength, 0 = mild 100 = strong (custom patch)': 'fe804',
}
RETIRED_SCALINGS = {'blip_len', 'igncut_flatrpm', 'ov_fuel'}
GROUPS = {'igncut': ('Engine Limiter - RPM Ignition Cut', 'Engine Limiter - Overheat Protection'),
          'revmatch': ('DBW - Downshift Rev Match', 'DBW - Upshift Hold', 'DBW - Rev Match / Upshift Hold - Shared',
                       'DBW - Anti-Stall'),
          'overrun': ('Spark - Overrun Crackle',),
          'tc': ('Traction Control - Spark Cut',)}


def read_source(only, source=SOURCE):
    src = open(source, encoding='utf-8-sig').read()
    lines = [l.strip() for l in src.splitlines()]
    cats = [c for g, cs in GROUPS.items() if only in (None, g) for c in cs]
    tables = [l for l in lines if l.startswith('<table') and any(f'category="{c}"' in l for c in cats)]
    used = {re.search(r'scaling="([^"]+)"', t).group(1) for t in tables}
    scalings = [l for l in lines if l.startswith('<scaling') and re.search(r'name="([^"]+)"', l).group(1) in used]
    assert tables and len(scalings) == len(used), 'source definitions incomplete'
    return scalings, tables


def rom_block(text, cal):
    """(start, end) of the <rom>...</rom> block whose internalidstring is cal"""
    for m in re.finditer(r'<rom\b[^>]*>.*?</rom>', text, re.S):
        if re.search(r'<internalidstring>\s*' + re.escape(cal) + r'\s*</internalidstring>', m.group(0)):
            return m.start(), m.end()
    return None


def find(folder, cal):
    hits = []
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith('.xml'):
                p = os.path.join(root, f)
                try:
                    t = open(p, encoding='utf-8-sig', errors='replace').read()
                except OSError:
                    continue
                if rom_block(t, cal):
                    hits.append(p)
    return hits


def add(path, cal, only, source=SOURCE):
    raw = open(path, 'rb').read()
    bom = raw.startswith(b'\xef\xbb\xbf')
    text = raw.decode('utf-8-sig')
    nl = '\r\n' if '\r\n' in text else '\n'
    blk = rom_block(text, cal)
    if not blk:
        sys.exit(f'{path} has no <rom> block with <internalidstring>{cal}</internalidstring> - wrong file? '
                 f'Use --find to locate the right one.')
    start, end = blk
    block = text[start:end]
    scalings, tables = read_source(only, source)
    attr = lambda t, k: re.search(k + r'="([^"]+)"', t).group(1)
    # remove what earlier versions of these patches added and is no longer used:
    #  - retired tables (exact name and address), and this repo's current tables found at an OLD address
    cur_addr = {attr(t, 'name'): attr(t, 'address').lower() for t in tables}
    removed = []
    for m in reversed(list(re.finditer(r'<table\b[^>]*>', block))):
        tag = m.group(0)
        n, a = re.search(r'\bname="([^"]+)"', tag), re.search(r'\baddress="([0-9a-fA-F]+)"', tag)
        if not (n and a): continue
        nm, ad = n.group(1), a.group(1).lower()
        if not (RETIRED_TABLES.get(nm) == ad or (nm in cur_addr and cur_addr[nm] != ad)): continue
        s, e = m.start(), m.end()
        if not tag.rstrip().endswith('/>'):                     # <table ...> ... </table>
            close = block.find('</table>', e)
            if close < 0: continue
            e = close + len('</table>')
        s = block.rfind('\n', 0, s) + 1 if block[block.rfind('\n', 0, s) + 1:s].strip() == '' else s
        if block[e:].startswith('\r\n'): e += 2
        elif block[e:].startswith('\n'): e += 1
        block = block[:s] + block[e:]
        removed.append(f'{nm} (0x{ad})')
    have_tb = {}
    for t in re.findall(r'<table\b[^>]*>', block):
        n, a = re.search(r'\bname="([^"]+)"', t), re.search(r'\baddress="([0-9a-fA-F]+)"', t)
        if n and a: have_tb[n.group(1)] = a.group(1).lower()
    #  - retired scalings no table uses any more
    rest = text[:start] + block + text[end:]
    used_sc = set(re.findall(r'<table\b[^>]*\bscaling="([^"]+)"', rest))
    for nm in sorted(RETIRED_SCALINGS - used_sc):
        m = re.search(r'[ \t]*<scaling\b[^>]*\bname="' + re.escape(nm) + r'"[^>]*/>\r?\n?', block)
        if m:
            block = block[:m.start()] + block[m.end():]
            removed.append(f'scaling {nm}')
    have_sc = set(re.findall(r'<scaling\b[^>]*\bname="([^"]+)"', text[:start] + block + text[end:]))
    # tables already present at the same address but filed under an older category: move them to the current one
    recat = []
    for t in tables:
        nm = attr(t, 'name')
        if nm not in have_tb: continue
        want = attr(t, 'category')
        m = re.search(r'<table\b[^>]*\bname="' + re.escape(nm) + r'"[^>]*>', block)
        cur = re.search(r'\bcategory="([^"]*)"', m.group(0))
        if cur and cur.group(1) != want:
            block = block[:m.start()] + m.group(0).replace(cur.group(0), f'category="{want}"', 1) + block[m.end():]
            recat.append(f'{nm}: {cur.group(1)} -> {want}')
    # this repo's scalings already present but from an older version (e.g. a new range or units): bring them up to date
    rescale = []
    for s in scalings:
        nm = attr(s, 'name')
        m = re.search(r'<scaling\b[^>]*\bname="' + re.escape(nm) + r'"[^>]*/>', block)
        if m and ' '.join(m.group(0).split()) != ' '.join(s.split()):
            block = block[:m.start()] + s + block[m.end():]
            rescale.append(nm)
    new_sc = [s for s in scalings if attr(s, 'name') not in have_sc]
    new_tb = [t for t in tables if attr(t, 'name') not in have_tb]
    clash = [t for t in new_tb if re.search(r'address="([0-9a-fA-F]+)"', t).group(1).lower()
             in {a.lower() for a in re.findall(r'<table\b[^>]*\baddress="([0-9a-fA-F]+)"', block)}]
    if clash:
        sys.exit('these addresses are already used by other tables in the definition - check before adding:\n  ' + '\n  '.join(clash))
    if not new_sc and not new_tb and not recat and not rescale and not removed:
        print('nothing to change - all tables are already in the definition and up to date; nothing old to remove'); return
    # indentation: copy the indent of the existing <romid> line, and use one level deeper for children
    m = re.search(r'([ \t]*)<romid>', block)
    ind = m.group(1) if m else '    '
    romid_end = block.find('</romid>')
    if romid_end < 0:
        sys.exit('no </romid> in the <rom> block - unexpected format')
    romid_end = block.find('>', romid_end) + 1
    sc_text = ''.join(nl + ind + s for s in new_sc)
    tb_text = ''.join(ind + t + nl for t in new_tb)
    close = block.rfind('</rom>')
    line_start = block.rfind('\n', 0, close) + 1
    new_block = block[:romid_end] + sc_text + block[romid_end:line_start] + tb_text + block[line_start:]
    out = text[:start] + new_block + text[end:]
    ET.fromstring(out.encode('utf-8'))                          # still valid XML?
    backup = path + time.strftime('.%Y%m%d-%H%M%S.bak')     # not .xml, so NC Flash / EcuFlash don't load it as a definition
    open(backup, 'wb').write(raw)
    open(path, 'wb').write((b'\xef\xbb\xbf' if bom else b'') + out.encode('utf-8'))
    print(f'backup: {backup}')
    print(f'added {len(new_sc)} scalings and {len(new_tb)} tables to {path}')
    if removed:
        print(f'removed {len(removed)} old entries from earlier versions that are no longer used:')
        for r in removed: print('   ', r)
    if rescale:
        print(f'updated {len(rescale)} existing scalings to the current version: ' + ', '.join(rescale))
    if recat:
        print(f'moved {len(recat)} existing tables to their current category:')
        for r in recat: print('   ', r)
    for t in new_tb:
        print('   ', re.search(r'category="([^"]+)"', t).group(1), '/', re.search(r'name="([^"]+)"', t).group(1))
    print('Reopen NC Flash / EcuFlash and open your patched ROM to see them.')


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cal = a[a.index('--cal') + 1] if '--cal' in a else 'LFJ1EE'
    only = a[a.index('--only') + 1] if '--only' in a else None
    if only not in (None, *GROUPS):
        sys.exit('--only must be igncut, revmatch, overrun or tc')
    if a[0] == '--find':
        hits = find(a[1], cal)
        print('\n'.join(hits) if hits else f'no definition for {cal} found under {a[1]}')
        return
    source = a[a.index('--source') + 1] if '--source' in a else SOURCE
    add(a[0], cal, only, source)


if __name__ == '__main__':
    main()

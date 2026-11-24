"""Add this repo's table definitions to an NC Flash or EcuFlash definition file, so the new tables show up.

Without this, NC Flash / EcuFlash only show the tables their definition file already knows about - the patch
settings are in the ROM but invisible.

usage:
  python tools/add_definitions.py <definition.xml> [--only igncut|revmatch|overrun] [--cal LFJ1EE] [--source my_tables.xml]
      Adds the scalings and tables to the <rom> block for that calibration (default LFJ1EE).
      Makes a backup next to the file first (<name>.xml.<date-time>.bak), skips anything already present,
      keeps the file's formatting, and checks the result is still valid XML.
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
GROUPS = {'igncut': ('Engine Limiter - RPM Ignition Cut',),
          'revmatch': ('DBW - Downshift Rev Match', 'DBW - Upshift Hold', 'DBW - Rev Match / Upshift Hold - Shared',
                       'DBW - Anti-Stall'),
          'overrun': ('Spark - Overrun Crackle',)}


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
    have_sc = set(re.findall(r'<scaling\b[^>]*\bname="([^"]+)"', text))
    have_tb = {}
    for t in re.findall(r'<table\b[^>]*>', block):
        n, a = re.search(r'\bname="([^"]+)"', t), re.search(r'\baddress="([0-9a-fA-F]+)"', t)
        if n and a: have_tb[n.group(1)] = a.group(1).lower()
    attr = lambda t, k: re.search(k + r'="([^"]+)"', t).group(1)
    moved = [f'{attr(t, "name")}: definition has 0x{have_tb[attr(t, "name")]}, this patch uses 0x{attr(t, "address").lower()}'
             for t in tables if attr(t, 'name') in have_tb and have_tb[attr(t, 'name')] != attr(t, 'address').lower()]
    if moved:
        sys.exit('these tables are already in the definition at a DIFFERENT address (an older version of a patch?).\n'
                 'NC Flash / EcuFlash would show the wrong bytes. Remove those old <table> lines (or restore the original\n'
                 'definition file), then run this again:\n  ' + '\n  '.join(moved))
    new_sc = [s for s in scalings if attr(s, 'name') not in have_sc]
    new_tb = [t for t in tables if attr(t, 'name') not in have_tb]
    clash = [t for t in new_tb if re.search(r'address="([0-9a-fA-F]+)"', t).group(1).lower()
             in {a.lower() for a in re.findall(r'<table\b[^>]*\baddress="([0-9a-fA-F]+)"', block)}]
    if clash:
        sys.exit('these addresses are already used by other tables in the definition - check before adding:\n  ' + '\n  '.join(clash))
    if not new_sc and not new_tb:
        print('nothing to add - all tables are already in the definition'); return
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
    for t in new_tb:
        print('   ', re.search(r'category="([^"]+)"', t).group(1), '/', re.search(r'name="([^"]+)"', t).group(1))
    print('Reopen NC Flash / EcuFlash and open your patched ROM to see them.')


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cal = a[a.index('--cal') + 1] if '--cal' in a else 'LFJ1EE'
    only = a[a.index('--only') + 1] if '--only' in a else None
    if only not in (None, 'igncut', 'revmatch', 'overrun'):
        sys.exit('--only must be igncut, revmatch or overrun')
    if a[0] == '--find':
        hits = find(a[1], cal)
        print('\n'.join(hits) if hits else f'no definition for {cal} found under {a[1]}')
        return
    source = a[a.index('--source') + 1] if '--source' in a else SOURCE
    add(a[0], cal, only, source)


if __name__ == '__main__':
    main()

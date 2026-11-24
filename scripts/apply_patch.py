"""Apply (or remove) a patch from this repo on a .bin of its calibration (stock, or already tuned).

usage:  python apply_patch.py <your.bin> <patch file>
Patches (patches/<calibration>/):
        <cal>_igncut.patch               ignition-cut rev limiter + launch control + flat-foot shift
        <cal>_downshift_revmatch.patch   downshift rev-match, upshift hold, anti-stall (Enable defaults to 0)
        <cal>_overrun.patch              timed lean overrun crackle (Enable defaults to 0)
The calibration comes from the patch file's header; its addresses from scripts/addrs.py (LFJ1EE) or
patches/<cal>/addresses.json (calibrations ported with tools/port.py).
The patches are independent and can be applied in any order.

Writes "<your> - <suffix>.bin" next to the input and never modifies the input.
Running it on a bin that already has the patch writes an un-patched copy instead.
It checks the bytes at the patch site first and refuses if they are neither the original nor the patched code.
Checksums are not updated here: flash with a tool that recalculates them (NC Flash does).
"""
import os, sys, struct, importlib.util

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('addrs', os.path.join(here, 'addrs.py'))
AD = importlib.util.module_from_spec(spec); spec.loader.exec_module(AD)

# patch kind (from the file name) -> (suffix, table ranges: settings you may have changed, skipped when checking
# a ROM before removal and erased on removal)
KINDS = {'_igncut.patch': ('igncut', [(0xFE180, 0xFE1A0)]),
         '_downshift_revmatch.patch': ('revmatch', [(0xFE300, 0xFE380)]),
         '_overrun.patch': ('overrun', [(0xFF000, 0xFF060)])}
FREE = (0xFE000, 0xFF400)       # where the patches' code and tables live: erased (0xFF) in a stock ROM


def signature(kind, A):
    """an address the patch changes, and the factory bytes there"""
    if kind == 'igncut':
        return A['dwell_site'], bytes.fromhex(A['dwell_orig'])
    if kind == 'overrun':
        assert A.get('dfco_lit'), f"overrun is not available for {A['cal']} - port it again with this version"
        return A['dfco_lit'], struct.pack('>I', A['dfco_routine'])
    return A['task_literals'][0], struct.pack('>I', A['pedal_copy'])


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, pat = sys.argv[1], sys.argv[2]
    name = os.path.basename(pat).lower()
    kind = next((k for k in KINDS if name.endswith(k)), None)
    if not kind:
        sys.exit(f'unknown patch {name}: expected <calibration>_igncut.patch, _downshift_revmatch.patch or _overrun.patch')
    tag, tables = KINDS[kind]

    rom = bytearray(open(src, 'rb').read())
    delta = open(pat, 'rb').read()
    if len(rom) != 0x100000 or len(delta) != 0x100000:
        sys.exit('ROM and patch must both be 1 MB')
    cal = delta[:6].decode('ascii', 'replace').strip()
    try:
        A = AD.for_cal(cal)
    except AssertionError as e:
        sys.exit(str(e))
    if not AD.is_cal(rom, A):
        sys.exit(f'this ROM is not {cal} (the patch is for {cal}) - see docs/porting.md')
    site, orig = signature(tag, A)
    patched = bytes(a ^ b for a, b in zip(orig, delta[site:site + len(orig)]))
    cur = bytes(rom[site:site + len(orig)])
    if cur == orig:
        mode, suffix = 'apply', f' - {tag}'
    elif cur == patched:
        mode, suffix = 'remove', f' - no {tag}'
    else:
        sys.exit('patch site does not match the factory or the patched code - refusing '
                 '(another patch there, or a different calibration)')
    in_tables = lambda i: any(a <= i < b for a, b in tables)
    area = [i for i in range(*FREE) if delta[i] or in_tables(i)]
    if mode == 'apply':     # the patch's code / table area must still be empty (erased flash)
        if any(rom[i] != 0xFF for i in area):
            sys.exit('the free area this patch uses is not empty in your ROM - another patch is using it; refusing')
    else:                   # removing: the code must be exactly this patch's code, or XOR-ing would corrupt the ROM
        if any(rom[i] ^ delta[i] != 0xFF for i in area if not in_tables(i)):
            sys.exit('this ROM has a different version of this patch (or another patch in the same place) - '
                     'removing it with this file would corrupt it; refusing')

    for i in range(6, len(rom)):
        if in_tables(i) and FREE[0] <= i < FREE[1]:
            rom[i] = 0xFF if mode == 'remove' else rom[i] ^ delta[i]
        elif delta[i]:
            rom[i] ^= delta[i]
    out = os.path.splitext(src)[0] + suffix + '.bin'
    if os.path.exists(out):
        sys.exit(f'{out} already exists - move it first')
    open(out, 'wb').write(rom)
    print(f'{mode}: wrote {out}')


if __name__ == '__main__':
    main()

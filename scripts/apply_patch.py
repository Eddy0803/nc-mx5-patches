"""Apply (or remove) a patch from this repo on an LFJ1EE .bin (stock, or already tuned).

usage:  python apply_patch.py <your.bin> <patch file>
Known patches:
        lfj1ee_igncut.patch               ignition-cut rev limiter + launch control + flat-foot shift
        lfj1ee_downshift_revmatch.patch   downshift rev-match, upshift hold, anti-stall (Enable defaults to 0)
The two patches are independent and can be applied in either order.

Writes "<your> - <suffix>.bin" next to the input and never modifies the input.
Running it on a bin that already has the patch writes an un-patched copy instead.
It checks the bytes at the patch site first and refuses if they are neither the original nor the patched code.
Checksums are not updated here: flash with a tool that recalculates them (NC Flash does).
"""
import os, sys

# patch name -> (suffix, signature address, original factory bytes at that address)
SIGS = {
    'lfj1ee_igncut.patch': ('igncut', 0x50D00, bytes.fromhex('D0356000C820002970FF600B88018F040009D332F338A00BFE3A')),
    'lfj1ee_downshift_revmatch.patch': ('revmatch', 0x11B00, bytes.fromhex('000387F8')),
}
# table ranges (settings you may have changed): skipped when checking a ROM before removal, erased on removal
TABLES = {
    'lfj1ee_igncut.patch': [(0xFE180, 0xFE1A0)],
    'lfj1ee_downshift_revmatch.patch': [(0xFE300, 0xFE380)],
}
FREE = (0xFB000, 0xFF650)       # factory-unused flash: erased (0xFF) in a stock ROM


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, pat = sys.argv[1], sys.argv[2]
    name = os.path.basename(pat).lower()
    if name not in SIGS:
        sys.exit(f'unknown patch {name}; known: {", ".join(SIGS)}')
    tag, site, orig = SIGS[name]

    rom = bytearray(open(src, 'rb').read())
    delta = open(pat, 'rb').read()
    if len(rom) != 0x100000 or len(delta) != 0x100000:
        sys.exit('ROM and patch must both be 1 MB')
    if rom[0xB8046:0xB804C] != b'LFJ1EE' or delta[:6] != b'LFJ1EE':
        sys.exit('not an LFJ1EE ROM / patch - see docs/porting.md')

    patched = bytes(a ^ b for a, b in zip(orig, delta[site:site + len(orig)]))
    cur = bytes(rom[site:site + len(orig)])
    if cur == orig:
        mode, suffix = 'apply', f' - {tag}'
    elif cur == patched:
        mode, suffix = 'remove', f' - no {tag}'
    else:
        sys.exit('patch site does not match the factory or the patched code - refusing '
                 '(another patch there, or a different calibration)')
    in_tables = lambda i: any(a <= i < b for a, b in TABLES[name])
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

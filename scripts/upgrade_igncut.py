"""Install the ignition-cut rev limiter (with launch control and flat-foot shift) into an LFJ1EE .bin,
or change the settings of one that already has it.

usage: python upgrade_igncut.py <your.bin> [TABLE=value ...]
  TABLE: EN OFS DW RET FS LAUNCH VSPLIT FSAPP   (see docs/ignition-cut.md)
  example: python upgrade_igncut.py tune.bin LAUNCH=4500 FS=5300
Existing values are kept unless given; a fresh install gets the defaults.
Writes "<your> - igncut.bin" next to the input and never modifies the input.
"""
import os, sys, struct, importlib.util

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('build_igncut', os.path.join(here, 'build_igncut.py'))
B = importlib.util.module_from_spec(spec); spec.loader.exec_module(B)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    rom = bytearray(open(src, 'rb').read())
    vals = {}
    for arg in sys.argv[2:]:
        k, v = arg.split('=', 1); k = k.upper()
        if k not in B.TBL:
            sys.exit(f'unknown table {k}; known: {" ".join(B.TBL)}')
        vals[k] = float(v)
    try:
        notes = B.install(rom, vals)
    except AssertionError as e:
        sys.exit(f'refusing: {e}')
    out = os.path.splitext(src)[0] + ' - igncut.bin'
    if os.path.exists(out):
        sys.exit(f'{out} already exists - move it first')
    open(out, 'wb').write(rom)
    for n in notes: print(' -', n)
    print(f'wrote {out}\n  ' + ', '.join(f'{k}={struct.unpack_from(">f", rom, a)[0]:g}' for k, a in B.TBL.items()))


if __name__ == '__main__':
    main()

"""Install the downshift rev-match into an LFJ1EE .bin, or change the settings of one that already has it.
usage: python upgrade_revmatch.py <your.bin> [KEY=value ...]
  KEY: EN MAXPCT PMAX VMIN GAIN DGAIN OFS MAXRPM (numbers), MAXT (calls), BRK (hex), K1..K6 (rpm per km/h per gear)
  Upgrading from the blip keeps Enable, Max Pedal, Min Speed and the brake address.
Writes "<your> - revmatch.bin"; never modifies the input. NC Flash recalculates checksums when it flashes."""
import os, sys, struct, importlib.util
here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('build_revmatch', os.path.join(here, 'build_revmatch.py'))
RM = importlib.util.module_from_spec(spec); spec.loader.exec_module(RM)

def main():
    src = sys.argv[1]
    vals = {}
    for arg in sys.argv[2:]:
        k, v = arg.split('='); k = k.upper()
        if k == 'BRK': vals[k] = int(v, 16)
        elif k == 'MAXT': vals[k] = int(v)
        elif k.startswith('K') and k[1:].isdigit():
            vals.setdefault('Kn', {})[int(k[1:]) - 1] = float(v)
        else: vals[k] = float(v)
    rom = bytearray(open(src, 'rb').read())
    if 'Kn' in vals:   # per-gear overrides on top of the ROM's current (or default) K table
        cur = RM.DEFAULTS['K'][:]
        if struct.unpack_from('>I', rom, RM.HOOKS[0])[0] == RM.CODE:
            cur = [struct.unpack_from('>f', rom, RM.TBL['K'] + 4 * i)[0] for i in range(6)]
        for i, v in vals.pop('Kn').items(): cur[i] = v
        vals['K'] = cur
    had_blip = RM.install(rom, vals)
    out = os.path.splitext(src)[0] + ' - revmatch.bin'
    if os.path.exists(out): sys.exit(f'{out} already exists - move it first')
    open(out, 'wb').write(rom)
    f = lambda a: struct.unpack_from('>f', rom, a)[0]
    print(('upgraded one-shot blip -> rev-match' if had_blip else 'installed rev-match') + f'\nwrote {out}')
    print(f'enable {f(0xFE300):g}, max pedal out {f(0xFE304):g}%, max real pedal {f(0xFE308):g}%, min speed {f(0xFE30C):g}, '
          f'brake 0x{struct.unpack_from(">I", rom, 0xFE310)[0]:08X}, max hold {struct.unpack_from(">H", rom, 0xFE316)[0]} calls, '
          f'gain {f(0xFE318):g}, damping {f(0xFE31C):g}, offset {f(0xFE320):g}, max target {f(0xFE324):g}, '
          f'K {[round(f(0xFE328 + 4 * i), 1) for i in range(6)]}')

if __name__ == '__main__':
    main()

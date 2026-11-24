"""Emulate the ignition-cut routines (dwell 0xFE000 and retard hook) from a ROM with its <cal>_igncut.patch applied.
usage: python igncut_emu.py rom_with_igncut.bin"""
import sys, struct, os

here = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(here, 'revemu.py'), encoding='utf-8-sig').read()
exec(src[:src.index('\nrom = bytearray')])          # f2b, b2f, CPU (SH-2E subset)


class ICPU(CPU):
    def step(self, pc, slot=False):
        op = struct.unpack_from('>H', self.rom, pc)[0]; n = (op >> 8) & 15
        if op & 0xF0FF == 0x4022:                                     # sts.l pr,@-rn
            self.setr(n, self.r[n] - 4); self.wmem(self.r[n], struct.pack('>I', self.PR)); return pc + 2
        if op & 0xF0FF == 0x4026:                                     # lds.l @rn+,pr
            self.PR = struct.unpack('>I', self.mem(self.r[n], 4))[0]; self.setr(n, self.r[n] + 4); return pc + 2
        if op >> 12 == 0xB:                                           # bsr
            assert not slot; d = op & 0xFFF; d = d - 4096 if d & 0x800 else d
            self.PR = pc + 4; self.step(pc + 2, True); return pc + 4 + d * 2
        if op >> 8 == 0xC8: self.T = int((self.r[0] & (op & 0xFF)) == 0); return pc + 2   # tst #imm,r0
        if op == 0x0018: self.T = 1; return pc + 2                     # sett
        if op == 0x0008: self.T = 0; return pc + 2                     # clrt
        return super().step(pc, slot)


rom = bytearray(open(sys.argv[1], 'rb').read())
_sp = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts', 'addrs.py')
import importlib.util as _iu
_s = _iu.spec_from_file_location('addrs', _sp); AD = _iu.module_from_spec(_s); _s.loader.exec_module(AD)
A = AD.for_rom(rom)
ram = bytearray(0x10000)
S = lambda a, d: ram.__setitem__(slice(a - 0xFFFF0000, a - 0xFFFF0000 + len(d)), d)
DWELL = 0xFE000
RETARD = struct.unpack_from('>I', rom, AD.spark_info(A)['term_lit'])[0]
assert struct.unpack_from('>I', rom, AD.dwell_info(A)['dwell_lit'])[0] == DWELL, 'ignition cut not installed in this ROM'


def tables(en=1.0, ofs=-300.0, dw=0.3, ret=5.0, fs=0.0, launch=0.0, vsplit=10.0, fsapp=80.0, fuelcut=7000.0, tc=None):
    for a, v in ((0xFE180, en), (0xFE184, ofs), (0xFE188, dw), (0xFE18C, ret), (0xFE190, fs), (0xFE194, launch),
                 (0xFE198, vsplit), (0xFE19C, fsapp), (A['fuel_cut_rpm'], fuelcut)):
        rom[a:a + 4] = f2b(v)
    rom[0xFE380:0xFE384] = b'\xFF\xFF\xFF\xFF' if tc is None else f2b(tc)


def run(entry, rpm, vss=0.0, clutch=0, pedal=0.0, flag=0, term=0.0, tcflag=0, **tb):
    tables(**tb); ram[:] = bytes(0x10000)
    S(A['rpm'], f2b(rpm)); S(A['speed'], f2b(vss)); S(A.get('igncut_pedal') or A['pedal_in'], f2b(pedal)); S(A['clutch'], bytes([clutch]))
    S(A['dwell_flag'], bytes([flag])); S(A['spark_term'], f2b(term)); S(0xFFFFAC4B, bytes([tcflag]))
    c = ICPU(rom, ram); c.r[15] = 0xFFFFE000
    for k in (2, 4, 13, 14): c.fr[k] = 111.0 + k
    c.r[4] = 0x1234; c.call(entry)
    assert c.r[15] == 0xFFFFE000, 'stack not balanced'
    assert c.tr <= {0, 1, 15} and c.tf <= {0, 1, 2, 3, 5}, (c.tr, c.tf)
    return c


ok = True
def check(name, cond, info=''):
    global ok; ok &= bool(cond); print(f'{"PASS" if cond else "FAIL"}  {name} {info}')


D, R = DWELL, RETARD
c = run(D, 1000, flag=0x20); check('factory short-dwell flag set -> factory dwell kept', c.T == 1 and abs(c.fr[3] - b2f(bytes(rom[A['factory_short_dwell']:A['factory_short_dwell'] + 4]))) < 1e-6)
c = run(D, 1000); check('idle -> normal dwell map', c.T == 0)
c = run(D, 6750, fuelcut=7000); check('rev limiter: 6750 > 7000-300 -> cut, dwell 0.3', c.T == 1 and abs(c.fr[3] - 0.3) < 1e-6, f'fr3={c.fr[3]:.3f}')
c = run(D, 6650, fuelcut=7000); check('6650 below 6700 -> no cut', c.T == 0)
c = run(D, 7050, fuelcut=7300); check('follows the RPM Fuel Cut table (7300 -> cut at 7000): 7050 cuts', c.T == 1)
c = run(D, 6950, fuelcut=7300); check('... 6950 does not', c.T == 0)
c = run(D, 6750, en=0.0); check('Enable 0 -> no cut', c.T == 0)
c = run(D, 6750, dw=0.05); check('dwell floor 0.2 ms', abs(c.fr[3] - 0.2) < 1e-6, f'fr3={c.fr[3]:.3f}')
# launch
c = run(D, 4600, vss=0.0, clutch=1, launch=0.0); check('launch off: clutch in, stationary, 4600 -> no cut', c.T == 0)
c = run(D, 4600, vss=0.0, clutch=1, launch=4500); check('launch 4500: clutch in, stationary, 4600 -> cut', c.T == 1)
c = run(D, 4400, vss=0.0, clutch=1, launch=4500); check('launch 4500: 4400 -> no cut', c.T == 0)
c = run(D, 4600, vss=0.0, clutch=0, launch=4500); check('launch 4500: clutch up (neutral rev) -> no cut', c.T == 0)
c = run(D, 4600, vss=9.0, clutch=1, launch=4500); check('launch applies below the split speed (9 < 10 km/h)', c.T == 1)
# flat shift
c = run(D, 5400, vss=60.0, clutch=1, pedal=100.0, fs=5300); check('flat shift 5300: 60 km/h, clutch in, pedal 100, 5400 -> cut', c.T == 1)
c = run(D, 5200, vss=60.0, clutch=1, pedal=100.0, fs=5300); check('flat shift 5300: 5200 -> no cut', c.T == 0)
c = run(D, 6600, vss=60.0, clutch=1, pedal=100.0, fs=5300); check('flat shift from 6600 -> cut (no fuel cut involved)', c.T == 1)
c = run(D, 5400, vss=60.0, clutch=1, pedal=50.0, fs=5300); check('normal shift (pedal 50 < 80) -> no cut', c.T == 0)
c = run(D, 5400, vss=60.0, clutch=0, pedal=100.0, fs=5300); check('clutch up at full throttle -> normal limiter only', c.T == 0)
c = run(D, 5400, vss=60.0, clutch=1, pedal=100.0, fs=0.0); check('flat shift off (0) -> no cut', c.T == 0)
c = run(D, 4600, vss=60.0, clutch=1, pedal=100.0, launch=4500, fs=0.0); check('launch RPM not used when moving', c.T == 0)
c = run(D, 5400, vss=5.0, clutch=1, pedal=100.0, fs=5300); check('flat shift RPM not used when stationary', c.T == 0)
# optional TC input
c = run(D, 2500, tcflag=1, tc=None); check('TC add-on absent (erased flash): its flag ignored', c.T == 0)
c = run(D, 2500, tcflag=1, tc=1.0); check('TC add-on enabled + flag -> cut', c.T == 1)
# retard
c = run(R, 1000, term=2.5); check('retard: not cutting -> term unchanged', abs(c.fr[1] - 2.5) < 1e-6, f'fr1={c.fr[1]}')
c = run(R, 6750, term=0.0, ret=5.0); check('retard: cutting -> -5', abs(c.fr[1] + 5.0) < 1e-6, f'fr1={c.fr[1]}')
c = run(R, 4600, vss=0.0, clutch=1, launch=4500, term=1.0, ret=5.0); check('retard during launch -> 1-5 = -4', abs(c.fr[1] + 4.0) < 1e-6)
c = run(R, 6750, term=0.0); check('caller registers fr2/fr4/fr13/fr14 and r4 preserved (retard path)',
                                   c.fr[2] == 113.0 and c.fr[4] == 115.0 and c.fr[13] == 124.0 and c.r[4] == 0x1234)
c = run(D, 6750); check('caller fr4/fr13/fr14 and r4 preserved (dwell path)', c.fr[4] == 115.0 and c.fr[13] == 124.0 and c.r[4] == 0x1234)
print('ALL PASS' if ok else 'SOME FAILED')

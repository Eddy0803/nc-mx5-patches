"""Emulate the overrun patch (OVR in the DFCO task slot, SPK in the spark-advance sum). usage: overrun_emu.py rom.bin
The factory DFCO routine is replaced by a stub that writes a chosen multiplier (it is factory code we do not change)."""
import sys, struct, os, importlib.util

f2b = lambda v: struct.pack('>f', v)
b2f = lambda b: struct.unpack('>f', b)[0]

_here = os.path.dirname(os.path.abspath(__file__))
def _load(name):
    s = importlib.util.spec_from_file_location(name, os.path.join(_here, '..', 'scripts', name + '.py'))
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
AD = _load('addrs'); OV = _load('build_overrun')

rom = bytearray(open(sys.argv[1], 'rb').read())
A = AD.for_rom(rom)
ram = bytearray(0x10000)
S = lambda a, d: ram.__setitem__(slice(a - 0xFFFF0000, a - 0xFFFF0000 + len(d)), d)
R = lambda a, n: bytes(ram[a - 0xFFFF0000:a - 0xFFFF0000 + n])
ST = OV.RAM_STATE
factory_mult = [0.0]


class CPU:
    def __init__(self):
        self.r = [0] * 16; self.fr = [0.0] * 16; self.T = 0; self.PR = 0
        self.r[15] = 0xFFFFB000; self.tr, self.tf = set(), set()
    def mem(self, a, n):
        a &= 0xFFFFFFFF
        if a < 0x100000: return bytes(rom[a:a + n])
        assert a >= 0xFFFF0000, hex(a); return R(a, n)
    def wmem(self, a, d):
        a &= 0xFFFFFFFF; assert a >= 0xFFFF0000, f'write to 0x{a:08X}'; S(a, d)
    def setr(self, n, v): self.r[n] = v & 0xFFFFFFFF; self.tr.add(n)
    def setf(self, n, v): self.fr[n] = b2f(f2b(v)); self.tf.add(n)
    sx8 = staticmethod(lambda b: b - 256 if b & 0x80 else b)
    def step(self, pc, slot=False):
        op = struct.unpack_from('>H', rom, pc)[0]; n, m, d = (op >> 8) & 15, (op >> 4) & 15, op & 0xFF; hi = op >> 12; nx = pc + 2
        if hi == 0xD: self.setr(n, struct.unpack('>I', self.mem((pc & ~3) + 4 + d * 4, 4))[0])
        elif op >> 8 == 0xC7: self.setr(0, (pc & ~3) + 4 + d * 4)
        elif hi == 0xE: self.setr(n, self.sx8(d))
        elif op & 0xF00F == 0x6000: self.setr(n, self.sx8(self.mem(self.r[m], 1)[0]))
        elif op >> 8 == 0x84: self.setr(0, self.sx8(self.mem(self.r[(op >> 4) & 15] + (op & 15), 1)[0]))
        elif op >> 8 == 0x80: self.wmem(self.r[(op >> 4) & 15] + (op & 15), bytes([self.r[0] & 0xFF]))
        elif op >> 8 == 0x88: self.T = int(self.r[0] == (self.sx8(d) & 0xFFFFFFFF))
        elif op == 0x0009: pass
        elif op == 0x4F22: self.setr(15, self.r[15] - 4); self.wmem(self.r[15], struct.pack('>I', self.PR))
        elif op == 0x4F26: self.PR = struct.unpack('>I', self.mem(self.r[15], 4))[0]; self.setr(15, self.r[15] + 4)
        elif op & 0xF00F == 0xF008: self.setf(n, b2f(self.mem(self.r[m], 4)))
        elif op & 0xF00F == 0xF006: self.setf(n, b2f(self.mem(self.r[0] + self.r[m], 4)))
        elif op & 0xF00F == 0xF007: self.wmem(self.r[0] + self.r[n], f2b(self.fr[m]))
        elif op & 0xF00F == 0xF00A: self.wmem(self.r[n], f2b(self.fr[m]))
        elif op & 0xF0FF == 0xF08D: self.setf(n, 0.0)
        elif op & 0xF0FF == 0xF09D: self.setf(n, 1.0)
        elif op & 0xF00F == 0xF005: self.T = int(self.fr[n] > self.fr[m])
        elif op & 0xF00F == 0xF004: self.T = int(self.fr[n] == self.fr[m])
        elif op & 0xF00F == 0xF00C: self.setf(n, self.fr[m])
        elif op & 0xF00F == 0xF000: self.setf(n, self.fr[n] + self.fr[m])
        elif op & 0xF00F == 0xF001: self.setf(n, self.fr[n] - self.fr[m])
        elif op & 0xF00F == 0xF002: self.setf(n, self.fr[n] * self.fr[m])
        elif op & 0xF00F == 0xF003:
            self.setf(n, self.fr[n] / self.fr[m] if self.fr[m] else float('inf'))
        elif op >> 8 in (0x89, 0x8B):
            assert not slot; take = self.T == (1 if op >> 8 == 0x89 else 0)
            return pc + 4 + self.sx8(d) * 2 if take else nx
        elif op & 0xF0FF == 0x400B:                                   # jsr @Rn
            t = self.r[n]; self.step(pc + 2, True)
            if t == A['dfco_routine']:                                # factory DFCO: stub
                S(A['dfco_mult'], f2b(factory_mult[0])); return pc + 4
            self.PR = pc + 4; return t
        elif op == 0x000B: t = self.PR; self.step(pc + 2, True); return t
        else: raise NotImplementedError(f'{op:04X} @ {pc:05X}')
        return nx
    def call(self, a):
        self.PR = 0xDEAD0; pc = a; k = 0
        while pc != 0xDEAD0:
            pc = self.step(pc); k += 1; assert k < 600
        return self


OVR = struct.unpack_from('>I', rom, A['dfco_lit'])[0]
SPK = struct.unpack_from('>I', rom, OV.spark2_lit(A))[0]

def tables(**kw):
    v = dict(OV.DEFAULTS); v['EN'] = 1.0; v.update(kw)
    for k, adr in OV.TBL.items(): rom[adr:adr + 4] = f2b(v[k])
def inputs(pedal=0.0, rpm=4000.0, vss=60.0, ect=90.0, clutch=0, dfco=0.7):
    S(A.get('igncut_pedal') or A['pedal_in'], f2b(pedal)); S(A['rpm'], f2b(rpm)); S(A['speed'], f2b(vss))
    S(A['ect'], f2b(ect)); S(A['clutch'], bytes([clutch])); factory_mult[0] = dfco
def tick():
    c = CPU().call(OVR)
    assert c.tr <= {0, 1, 2, 15} and c.tf <= set(range(8)), (c.tr, c.tf)
    assert c.r[15] == 0xFFFFB000, 'stack not balanced'
    return b2f(R(A['dfco_mult'], 4)), R(ST + 5, 1)[0] == OV.MAGIC, R(ST + 4, 1)[0], b2f(R(ST, 4)), b2f(R(ST + 8, 4))
def spark(term=3.0):
    S(A['spark2_term'], f2b(term)); c = CPU(); c.fr[3] = 99.0; c.call(SPK)
    assert c.tr <= {0, 1, 3} and c.tf <= {0, 1, 3}, (c.tr, c.tf)
    return c.fr[3]

ok = True
def check(name, cond, info=''):
    global ok; ok &= bool(cond); print(f'{"PASS" if cond else "FAIL"}  {name} {info}')
near = lambda a, b, e=1e-4: abs(a - b) < e

# ---- hook bytes
w = struct.unpack_from('>4H', rom, A['spark2_site'])
orig = AD._w(A['spark2_orig'])
check('spark hook: mov.l (now -> SPK), jsr @r3, factory fadd in the delay slot, mov.l',
      w == (orig[0], 0x430B, orig[1], orig[2]) and SPK > A['dfco_routine'], str([hex(x) for x in w]))
check('DFCO task literal now calls OVR', OVR == OV.CODE, hex(OVR))

# ---- sequence
tables(); inputs(pedal=0.0, dfco=0.7); S(ST + 4, b'\x00'); o = tick()
check('not armed, pedal closed: factory multiplier untouched, inactive', near(o[0], 0.7) and not o[1], str(o))
inputs(pedal=40.0, dfco=1.0); o = tick()
check('pedal 40% >= arm 20%: armed, timer = 2.0 s, inactive', o[2] == 1 and near(o[3], 2.0) and not o[1] and near(o[0], 1.0), str(o))
check('  spark untouched while inactive', near(spark(3.0), 3.0))
inputs(pedal=0.0, dfco=0.985); o = tick()
# strength 50%: retard 6 + 0.5*14 = 13 ; fuel 0.82 + 0.5*0.13 = 0.885
check('lift-off: active, fuel multiplier held at 0.885 (lean), retard 13 deg', o[1] and near(o[0], 0.885) and near(o[4], 13.0), str(o))
check('  spark term 3.0 -> -10.0 (13 deg retard)', near(spark(3.0), -10.0), str(spark(3.0)))
n = 1
while True:
    inputs(pedal=0.0, dfco=0.6); o = tick()
    if not o[1]: break
    n += 1; assert n < 1000
check('timed: active for 2.0 s x 90 calls/s = 180 calls, then off', abs(n - 180) <= 1, f'{n} calls')
check('  after the burst: disarmed, factory fuel cut takes over (multiplier from factory)', o[2] == 0 and near(o[0], 0.6), str(o))
check('  spark back to normal', near(spark(3.0), 3.0))
for _ in range(5): o = tick()
check('stays off until the pedal passes arm again', not o[1] and o[2] == 0, str(o))
inputs(pedal=10.0); o = tick()
check('part throttle 10% does not re-arm', o[2] == 0, str(o))
inputs(pedal=25.0); tick(); inputs(pedal=10.0); o = tick()
check('re-armed at 25%, then part throttle 10%: inactive, still armed', not o[1] and o[2] == 1, str(o))
inputs(pedal=1.0); o = tick()
check('pedal 1% (<= closed 2%): active', o[1], str(o))
inputs(pedal=0.0, clutch=1); o = tick()
check('clutch pressed: off and disarmed', not o[1] and o[2] == 0, str(o))
for name, kw in (('RPM 2000 < min 2500', {'rpm': 2000.0}), ('RPM 7000 > max 6500', {'rpm': 7000.0}),
                 ('speed 20 < min 30', {'vss': 20.0}), ('coolant 60 < min 75', {'ect': 60.0})):
    inputs(pedal=40.0); tick(); inputs(pedal=0.0, **kw); o = tick()
    check(f'{name}: off and disarmed', not o[1] and o[2] == 0 and near(o[0], 0.7), str(o))
tables(EN=0.0); inputs(pedal=40.0); tick(); inputs(pedal=0.0); o = tick()
check('Enable 0: nothing', not o[1] and near(o[0], 0.7), str(o))
# ---- strength
for st, ret, fuel in ((0.0, 6.0, 0.82), (100.0, 20.0, 0.95), (150.0, 20.0, 0.95), (-20.0, 6.0, 0.82)):
    tables(STR=st); inputs(pedal=40.0); tick(); inputs(pedal=0.0); o = tick()
    check(f'strength {st:g}%: retard {ret}, fuel {fuel}', o[1] and near(o[4], ret) and near(o[0], fuel), str(o))
tables(RETHI=50.0, STR=100.0); inputs(pedal=40.0); tick(); inputs(pedal=0.0); o = tick()
check('retard table 50 capped at 30 in code', near(o[4], 30.0), str(o))
tables(FUELLO=0.3, STR=0.0); inputs(pedal=40.0); tick(); inputs(pedal=0.0); o = tick()
check('fuel 0.3 raised to 0.65 in code (stays above the 0.6 full-cut threshold)', near(o[0], 0.65), str(o))
tables(FUELHI=1.3, STR=100.0); inputs(pedal=40.0); tick(); inputs(pedal=0.0); o = tick()
check('fuel 1.3 limited to 1.0 (never rich)', near(o[0], 1.0), str(o))
tables(DUR=30.0); inputs(pedal=40.0); o = tick()
check('duration 30 s capped at 5 s in code', near(o[3], 5.0), str(o))
# ---- spark guards (garbage RAM at power-up)
S(ST + 5, bytes([OV.MAGIC])); S(ST + 8, b'\xFF\xFF\xFF\xFF')
check('SPK: active byte set but retard NaN -> term unchanged', near(spark(3.0), 3.0))
S(ST + 8, f2b(1e30))
check('SPK: retard 1e30 -> term unchanged', near(spark(3.0), 3.0))
S(ST + 8, f2b(-5.0))
check('SPK: negative retard -> term unchanged', near(spark(3.0), 3.0))
# ---- erased tables (not installed properly): nothing happens
for k, adr in OV.TBL.items(): rom[adr:adr + 4] = b'\xFF' * 4
S(ST + 5, b'\x00'); inputs(pedal=40.0); tick(); inputs(pedal=0.0); o = tick()
check('erased tables (NaN): nothing happens', not o[1] and near(o[0], 0.7), str(o))
print('ALL PASS' if ok else 'SOME FAILED')

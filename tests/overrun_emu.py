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
            assert self.fr[m] != 0.0, f'division by zero at {pc:05X}'
            self.setf(n, self.fr[n] / self.fr[m])
        elif op >> 8 in (0x89, 0x8B):
            assert not slot; take = self.T == (1 if op >> 8 == 0x89 else 0)
            return pc + 4 + self.sx8(d) * 2 if take else nx
        elif op & 0xF0FF == 0x400B:                                   # jsr @Rn
            t = self.r[n]; self.step(pc + 2, True)
            if t == A['dfco_routine']:                                # factory DFCO: stub
                S(A['dfco_mult'], f2b(factory_mult[0])); return pc + 4
            self.PR = pc + 4; return t
        elif op == 0x000B: t = self.PR; self.step(pc + 2, True); return t
        elif hi == 0xB:                                                # bsr
            dd = op & 0xFFF; dd = dd - 4096 if dd & 0x800 else dd; self.PR = pc + 4; self.step(pc + 2, True); return pc + 4 + dd * 2
        elif op & 0xF00F == 0xF009: self.setf(n, b2f(self.mem(self.r[m], 4))); self.setr(m, self.r[m] + 4)
        elif op & 0xF0FF == 0x4010: self.setr(n, self.r[n] - 1); self.T = int(self.r[n] == 0)   # dt
        elif hi == 0xA:
            dd = op & 0xFFF; dd = dd - 4096 if dd & 0x800 else dd; self.step(pc + 2, True); return pc + 4 + dd * 2
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
    for k, adr in OV.ARR.items():
        for i, x in enumerate(kw.get(k, OV.ARR_DEFAULTS[k])): rom[adr + 4 * i:adr + 4 * i + 4] = f2b(x)
def lam(rpm, ax=None, lm=None):
    ax = ax or OV.ARR_DEFAULTS['LAX']; lm = lm or OV.ARR_DEFAULTS['LAM']
    if rpm <= ax[0]: return lm[0]
    for i in range(3):
        if rpm <= ax[i + 1]: return lm[i] + (rpm - ax[i]) * (lm[i + 1] - lm[i]) / (ax[i + 1] - ax[i])
    return lm[3]
def inputs(pedal=0.0, rpm=4000.0, vss=60.0, ect=90.0, clutch=0, dfco=0.7):
    S(A.get('igncut_pedal') or A['pedal_in'], f2b(pedal)); S(A['rpm'], f2b(rpm)); S(A['speed'], f2b(vss))
    S(A['ect'], f2b(ect)); S(A['clutch'], bytes([clutch])); factory_mult[0] = dfco
def tick():
    c = CPU().call(OVR)
    assert c.tr <= {0, 1, 2, 3, 15} and c.tf <= set(range(8)), (c.tr, c.tf)
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
D = OV.DEFAULTS; s0 = D['STR'] / 100
RET0 = D['RETLO'] + s0 * (D['RETHI'] - D['RETLO']); FUEL0 = 1.0 / lam(4000.0)
check(f'lift-off at 4000 rpm: active, fuel multiplier {FUEL0:g} (lambda {lam(4000.0):g}), retard {RET0:g} deg', o[1] and near(o[0], FUEL0) and near(o[4], RET0), str(o))
check(f'  spark term 3.0 -> {3.0 - RET0:g} (retarded)', near(spark(3.0), 3.0 - RET0), str(spark(3.0)))
tables(STR=50.0); inputs(pedal=40.0); tick(); inputs(pedal=0.0); o = tick()
check('strength 50%: retard halfway, fuel unchanged (lambda only)', near(o[4], (D['RETLO'] + D['RETHI']) / 2) and near(o[0], FUEL0), str(o))
tables(); inputs(pedal=40.0); tick(); inputs(pedal=0.0); tick()
n = 2
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
tables(CLV=3.0); inputs(pedal=40.0, vss=0.0, clutch=1); o = tick()
check('clutch-pressed speed 3: standing rev with the clutch in arms', o[2] == 1, str(o))
inputs(pedal=0.0, vss=0.0, clutch=1); o = tick()
check('  ... and lifting off crackles (stationary, clutch in)', o[1], str(o))
inputs(pedal=40.0, vss=0.0, clutch=1); tick(); inputs(pedal=0.0, vss=20.0, clutch=1); o = tick()
check('  clutch pressed while moving (20 km/h): off and disarmed', not o[1] and o[2] == 0, str(o))
tables(); inputs(pedal=40.0, vss=0.0, clutch=1); o = tick()
check('default (0): clutch pressed at a standstill still blocks it', o[2] == 0 and not o[1], str(o))
inputs(vss=60.0, clutch=0)
for name, kw in (('RPM 2000 < min 2500', {'rpm': 2000.0}), ('RPM 7000 > max 6500', {'rpm': 7000.0}),
                 ('coolant 45 < min 50', {'ect': 45.0})):
    inputs(pedal=40.0); tick(); inputs(pedal=0.0, **kw); o = tick()
    check(f'{name}: off and disarmed', not o[1] and o[2] == 0 and near(o[0], 0.7), str(o))
inputs(pedal=40.0, vss=0.0); tick(); inputs(pedal=0.0, vss=0.0); o = tick()
check('default min speed 0: works stationary (free rev, clutch up in neutral)', o[1], str(o))
tables(VMIN=30.0); inputs(pedal=40.0); tick(); inputs(pedal=0.0, vss=20.0); o = tick()
check('min speed set to 30: off at 20 km/h', not o[1] and o[2] == 0, str(o))
inputs(pedal=40.0, ect=50.0); tick(); inputs(pedal=0.0, ect=50.0); tables(); o = tick()
check('coolant 50 = min 50: active', o[1], str(o))
inputs(ect=90.0)
tables(EN=0.0); inputs(pedal=40.0); tick(); inputs(pedal=0.0); o = tick()
check('Enable 0: nothing', not o[1] and near(o[0], 0.7), str(o))
# ---- strength
for st, ret, fuel in ((0.0, D['RETLO'], FUEL0), (100.0, D['RETHI'], FUEL0), (150.0, D['RETHI'], FUEL0),
                      (-20.0, D['RETLO'], FUEL0)):
    tables(STR=st); inputs(pedal=40.0); tick(); inputs(pedal=0.0); o = tick()
    check(f'strength {st:g}%: retard {ret}, fuel {fuel}', o[1] and near(o[4], ret) and near(o[0], fuel), str(o))
tables(RETHI=60.0, STR=100.0); inputs(pedal=40.0); tick(); inputs(pedal=0.0); o = tick()
check(f'retard table 60 capped at {OV.RET_CAP:g} in code', near(o[4], OV.RET_CAP), str(o))
check(f'  spark hook accepts the full {OV.RET_CAP:g} deg', near(spark(3.0), 3.0 - OV.RET_CAP), str(spark(3.0)))
# ---- lambda vs RPM (stock Ford burble: 0.92 to 3000 rpm, 1.0 from 4000 rpm)
tables(RMIN=1500.0, RMAX=7000.0)
for rpm in (1600.0, 2000.0, 2500.0, 3000.0, 3250.0, 3500.0, 3999.0, 4000.0, 4500.0, 5000.0, 6500.0):
    inputs(pedal=40.0, rpm=rpm); tick(); inputs(pedal=0.0, rpm=rpm); o = tick()
    check(f'{rpm:g} rpm: lambda {lam(rpm):.4f} -> fuel multiplier {1 / lam(rpm):.4f}', o[1] and near(o[0], 1 / lam(rpm), 2e-4), str(o))
tables(LAM=[0.5, 0.5, 3.0, 3.0]); inputs(pedal=40.0, rpm=2500.0); tick(); inputs(pedal=0.0, rpm=2500.0); o = tick()
check('lambda 0.5 -> limited to 0.85 in code (multiplier 1.176)', near(o[0], 1 / 0.85), str(o))
inputs(pedal=40.0, rpm=4500.0); tick(); inputs(pedal=0.0, rpm=4500.0); o = tick()
check('lambda 3.0 -> limited to 1.5 (multiplier 0.667, above the 0.6 full-cut threshold)', near(o[0], 1 / 1.5), str(o))
tables(LAM=[0.0, 0.0, 0.0, 0.0]); inputs(pedal=40.0); tick(); inputs(pedal=0.0); o = tick()
check('lambda 0 -> limited to 0.85, no division by zero', near(o[0], 1 / 0.85), str(o))
tables(LAX=[3000.0, 3000.0, 3000.0, 3000.0], LAM=[0.9, 0.95, 1.0, 1.05]); inputs(pedal=40.0, rpm=3000.0); tick(); inputs(pedal=0.0, rpm=3000.0); o = tick()
check('RPM axis points all equal: no division by zero', o[1] and o[0] == o[0], str(o))
tables(LAX=[5000.0, 4000.0, 3000.0, 2000.0]); inputs(pedal=40.0, rpm=3500.0); tick(); inputs(pedal=0.0, rpm=3500.0); o = tick()
check('RPM axis backwards: no division by zero, lambda within limits', o[1] and 1 / 1.5 - 1e-4 <= o[0] <= 1 / 0.85 + 1e-4, str(o))
tables(LAM=[float('nan')] * 4); inputs(pedal=40.0); tick(); inputs(pedal=0.0); o = tick()
check('lambda table erased (NaN): fuel left to the factory, no burst', near(o[0], 0.7) and not o[1], str(o))
tables(); inputs(rpm=4000.0)
tables(RATE=0.0); inputs(pedal=40.0); tick(); inputs(pedal=0.0); o = tick()
check('calls per second 0 -> no division, burst ends (disarmed)', not o[1] and o[2] == 0, str(o))
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

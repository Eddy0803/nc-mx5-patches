"""Emulate traction control (0xFE800), chained in front of rev-match / the factory pedal copy: logic checks, the chain with
rev-match, install order / removal, and a closed-loop wheelspin simulation.  usage: tc_emu.py rom_with_tc.bin"""
import sys, struct, os, math, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, 'revemu.py'), encoding='utf-8-sig').read()
exec(src[:src.index('rom = bytearray')])          # f2b, b2f, CPU (shared SH-2E subset)
def _load(name):
    s = importlib.util.spec_from_file_location(name, os.path.join(HERE, '..', 'scripts', name + '.py'))
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
AD, TC, RV, IG = _load('addrs'), _load('build_tc'), _load('build_revmatch'), _load('build_igncut')

rom = bytearray(open(sys.argv[1], 'rb').read())
A = AD.for_rom(rom)
OVR = A.get('pedal_override')

class TCPU(CPU):
    def step(self, pc, slot=False):
        if OVR and pc == A['pedal_copy'] and not slot:          # factory routine with an override: emulate the plain copy
            self.wmem(A['pedal_out'], self.mem(A['pedal_in'], 4)); return self.PR
        op = struct.unpack_from('>H', self.rom, pc)[0]; n, m = (op >> 8) & 15, (op >> 4) & 15
        if op & 0xF0FF == 0x4022:   # sts.l pr,@-rn
            self.setr(n, self.r[n] - 4); self.wmem(self.r[n], struct.pack('>I', self.PR)); return pc + 2
        if op & 0xF0FF == 0x4026:   # lds.l @rn+,pr
            self.PR = struct.unpack('>I', self.mem(self.r[n], 4))[0]; self.setr(n, self.r[n] + 4); return pc + 2
        if op & 0xF0FF == 0x400B:   # jsr @rn
            assert not slot; t = self.r[n]; self.PR = pc + 4; self.step(pc + 2, True); return t
        if op & 0xF00F == 0xF004:   # fcmp/eq
            self.T = int(self.fr[n] == self.fr[m]); return pc + 2
        if op & 0xF0FF == 0x4011:   # cmp/pz
            self.T = int(self.s32(self.r[n]) >= 0); return pc + 2
        return super().step(pc, slot)

ok = True
def check(name, cond, info=''):
    global ok; ok &= bool(cond); print(f'{"PASS" if cond else "FAIL"}  {name} {info}')

# ---------- static: chain, tables, install order, removal ----------
nxt = TC.next_target(rom, A)
check('TC in the task slot (task literals -> 0xFE800)', TC.installed(rom, A),
      f'-> 0x{struct.unpack_from(">I", rom, A["task_literals"][0])[0]:05X}')
check('TC calls rev-match or the factory pedal copy underneath', nxt in (A['pedal_copy'], TC.REVMATCH), f'NEXT 0x{nxt:05X}')
check('TC code is this version', bytes(rom[TC.CODE:TC.CODE + len(TC.assemble(A))]) == TC.assemble(A))
check('ignition cut installed (TC cuts spark through it)', bytes(rom[A['dwell_site']:A['dwell_site'] + 26]) == AD.dwell_hook(A))
c = bytearray(rom); TC.install(c, A=A); check('reinstalling TC changes nothing (settings kept)', c == rom)
c = bytearray(rom); TC.remove(c, A); t = struct.unpack_from('>I', c, A['task_literals'][0])[0]
check('removing TC puts the slot back to what ran underneath', t == nxt and all(b == 0xFF for b in c[TC.CODE:TC.CODE_END])
      and all(b == 0xFF for b in c[TC.TBL_START:TC.TBL_END]))
if nxt == TC.REVMATCH:
    keep = bytes(c[0xFE300:0xFE380]); c2 = bytearray(c); TC.install(c2, A=A)
    check('TC removed and installed again: rev-match untouched, chain back', c2[0xFE300:0xFE380] == keep and TC.next_target(c2, A) == TC.REVMATCH)
    c3 = bytearray(rom); RV.install(c3, A=A)
    check('rev-match reinstalled on a TC file: goes under TC (NEXT), TC kept, nothing else changed', c3 == rom)
elif RV.TC_CODE == TC.CODE and A.get('crosscheck_lit'):
    c3 = bytearray(rom); RV.install(c3, A=A)
    check('rev-match installed after TC: goes under TC (NEXT), TC tables kept', TC.installed(c3, A) and TC.next_target(c3, A) == TC.REVMATCH
          and c3[TC.TBL_START:TC.TBL['NEXT']] == rom[TC.TBL_START:TC.TBL['NEXT']])
c = bytearray(rom); IG.install(c, A=A); check('ignition cut reinstalled: TC untouched', c[TC.TBL_START:TC.TBL_END] == rom[TC.TBL_START:TC.TBL_END]
                                             and c[TC.CODE:TC.CODE_END] == rom[TC.CODE:TC.CODE_END] and TC.installed(c, A))

# ---------- dynamic ----------
ram = bytearray(0x10000)
S = lambda a, d: ram.__setitem__(slice(a - 0xFFFF0000, a - 0xFFFF0000 + len(d)), d)
R = lambda a, n: bytes(ram[a - 0xFFFF0000:a - 0xFFFF0000 + n])
K = [k for k in TC.read_tables(rom)['K'] if k > 0]
DT = 0.0055
ROMDROP_RAM = ((0xFFFFAC00, 0xFFFFAC0E), (0xFFFFAC18, 0xFFFFAC3C))   # romdrop's own RAM: never written by TC

def tables(en=1.0, amax=30.0, dt=DT, alpha=0.1, vmin=10.0, pmin=40.0, rpmmin=2000.0, minr=2500.0, hold=18, lock=90, agemax=40):
    for a, v in ((0xFE380, en), (0xFE384, amax), (0xFE388, dt), (0xFE38C, alpha), (0xFE390, vmin), (0xFE394, pmin),
                 (0xFE398, rpmmin), (0xFE3B8, minr)):
        rom[a:a + 4] = f2b(v)
    rom[0xFE39C], rom[0xFE39D], rom[0xFE39E] = hold, lock, agemax
    if nxt == TC.REVMATCH: rom[0xFE378:0xFE37A] = struct.pack('>H', 0)    # no clutch-hold delay for the rev-match check

def reset():
    ram[:] = bytes(0x10000)
    for a, b in ROMDROP_RAM: S(a, bytes([0xA5]) * (b - a))

def inputs(clutch, pedal, rpm, vss, brake=0):
    S(A['clutch'], bytes([clutch])); S(A['brake'], bytes([brake]))
    S(A['pedal_in'], f2b(pedal)); S(A['rpm'], f2b(rpm)); S(A['speed'], f2b(vss))

def tick():
    c = TCPU(rom, ram); c.r[15] = 0xFFFFE000; sp = c.r[15]; c.call(0xFE800)
    assert c.r[15] == sp, 'stack unbalanced'
    assert c.tr <= {0, 1, 2, 3, 15} and c.tf <= set(range(8)), (c.tr, c.tf)
    return R(0xFFFFAC4B, 1)[0]

st = lambda: dict(rate=b2f(R(0xFFFFAC44, 4)), gear=R(0xFFFFAC48, 1)[0], hold=R(0xFFFFAC49, 1)[0], lock=R(0xFFFFAC4A, 1)[0], age=R(0xFFFFAC4C, 1)[0])

def drive(gear, v0, acc_kmhs, calls, pedal=100.0, clutch=0, rpm0=None, spin_rate=0.0, prime=False):
    """grip pull (or spin: rpm rises spin_rate rpm/s regardless of speed). returns list of flags."""
    out = []; v = v0; rpm = rpm0 if rpm0 is not None else v0 * K[gear - 1]
    if prime:                                    # settle the filter at the start state (RAM starts at 0)
        for i in range(60): inputs(1, 0.0, rpm, v); tick()
    for i in range(calls):
        inputs(clutch, pedal, rpm, v)
        out.append(tick())
        v += acc_kmhs * DT
        rpm = rpm + spin_rate * DT if spin_rate else v * K[gear - 1]
    return out

tables(); reset()
f = drive(2, 40, 18, 300, prime=True); check('2nd WOT grip pull 18 km/h/s -> no cut', sum(f) == 0, f'gear={st()["gear"]}')
reset(); f = drive(1, 15, 21, 300, prime=True); check('1st WOT grip pull 21 km/h/s -> no cut', sum(f) == 0)
for g in range(3, len(K) + 1):
    reset(); f = drive(g, 60, 12, 300, prime=True); check(f'gear {g} WOT grip pull -> no cut', sum(f) == 0)
reset(); drive(4, 70, 0, 60, prime=True); fl = []; v = 70.0
for i in range(300):
    t = i * DT; v += 10 * DT; inputs(0, 100.0, v * K[3] + 60 * math.sin(2 * math.pi * 8 * t), v); fl.append(tick())
check('4th WOT with +-60 rpm 8 Hz driveline shunt -> no cut', sum(fl) == 0, f'{sum(fl)} cut calls')
reset(); drive(2, 45, 15, 100, prime=True); rpm0 = b2f(R(A['rpm'], 4)); v0 = b2f(R(A['speed'], 4))
f = drive(2, v0, 3, 60, rpm0=rpm0, spin_rate=8000)
first = f.index(1) if 1 in f else None
check('2nd gear wheelspin 8000 rpm/s -> cut', first is not None and first <= 6, f'first cut after {first} calls ({(first or 0) * DT * 1000:.0f} ms)')
check('cut held while spinning', all(f[first:]) if first is not None else False, f'{sum(f)}/{len(f)} calls')
v = b2f(R(A['speed'], 4)); rpm = b2f(R(A['rpm'], 4)); fl = []
for i in range(60): inputs(0, 100, rpm, v); fl.append(tick())
n_hold = fl.index(0) if 0 in fl else None
check('rpm stops rising -> cut released after hold (~18 calls + filter decay)', n_hold is not None and 15 <= n_hold <= 45, f'released after {n_hold} calls')
reset(); drive(4, 80, 8, 100, prime=True); f = drive(4, b2f(R(A['speed'], 4)), 2, 60, rpm0=b2f(R(A['rpm'], 4)), spin_rate=5000)
check('4th gear spin 5000 rpm/s -> cut', 1 in f and f.index(1) <= 8, f'first after {f.index(1) if 1 in f else None} calls')
for name, kw, tb in [('clutch down', dict(clutch=1), {}), ('pedal 30% (< 40)', dict(pedal=30.0), {}), ('Enable 0', {}, dict(en=0.0))]:
    tables(**tb); reset(); drive(2, 45, 15, 100, prime=True)
    f = drive(2, b2f(R(A['speed'], 4)), 3, 60, rpm0=b2f(R(A['rpm'], 4)), spin_rate=8000, **kw)
    check(f'spin but {name} -> no cut', sum(f) == 0)
tables()
reset(); drive(1, 8, 15, 40)
f = drive(1, 8, 0, 40, rpm0=1500, spin_rate=8000); check('spin below min speed/rpm -> no cut', sum(f[:20]) == 0)
reset(); drive(2, 25, 15, 100, prime=True); f = drive(2, b2f(R(A['speed'], 4)), 0, 60, rpm0=1600, spin_rate=6000)
check('spin starting at 1600 rpm: no cut below 2000, cuts once above', sum(f[:5]) == 0 and 1 in f, f'first at {f.index(1) if 1 in f else None}')
reset(); drive(2, 45, 15, 100, prime=True); drive(2, b2f(R(A['speed'], 4)), 0, 20, clutch=1)
v, rpm = b2f(R(A['speed'], 4)), b2f(R(A['rpm'], 4))
f = drive(2, v, 0, 80, rpm0=rpm, spin_rate=8000)
check('clutch just released (launch / shift): spin ignored during lockout (90 calls)', sum(f) == 0, f'lock now {st()["lock"]}')
reset(); drive(3, 60, 5, 100, prime=True); v = b2f(R(A['speed'], 4))
for i in range(60): inputs(0, 10.0, 1200 + i, v); tick()
f = drive(3, v, 0, 40, rpm0=1300, spin_rate=9000, pedal=100.0)
check('neutral rev while rolling (no gear match for >40 calls) -> no cut', sum(f) == 0, f'age {st()["age"]}')
reset(); drive(2, 45, 15, 20); S(0xFFFFAC44, b'\xFF\xFF\xFF\xFF'); drive(2, 48, 15, 5)
check('NaN in rate RAM recovers', st()['rate'] == st()['rate'], f'rate {st()["rate"]:.2f}')
tables(hold=200); reset(); drive(2, 45, 15, 100, prime=True); drive(2, b2f(R(A['speed'], 4)), 0, 20, rpm0=b2f(R(A['rpm'], 4)), spin_rate=8000)
check('Hold table 200 capped at 60 in code', st()['hold'] <= 60, f'hold {st()["hold"]}')
tables()
reset(); inputs(0, 37.5, 3000, 40); tick()
check('pedal copy still done underneath (engine-side pedal = real pedal)', abs(b2f(R(A['pedal_out'], 4)) - 37.5) < 1e-4, f'{b2f(R(A["pedal_out"], 4))}')
if nxt == TC.REVMATCH and struct.unpack_from('>f', rom, 0xFE300)[0] > 0:
    reset(); drive(4, 60, 0, 30); out = []
    for i in range(40):
        inputs(1, 0.0, 1500, 60, brake=1); tick(); out.append(b2f(R(A['pedal_out'], 4)))
    check('rev-match still active underneath (clutch + brake -> throttle blip)', max(out) > 5, f'max pedal {max(out):.1f}%')
check("romdrop's RAM never written", all(R(a, b - a) == bytes([0xA5]) * (b - a) for a, b in ROMDROP_RAM))

def sim(tc, T=1.6):
    tables(en=1.0 if tc else 0.0); reset()
    g, v, rpm = 2, 45.0, 45 * K[1]; slip_max = 0.0; cuts = 0; t = 0.0
    for i in range(60): inputs(1, 0.0, rpm, v); tick()
    for i in range(100): inputs(0, 100.0, rpm, v); tick()   # past the clutch lockout
    while t < T:
        inputs(0, 100.0, rpm, v); cut = tick(); cuts += cut
        sync = v * K[g - 1]
        if 0.3 <= t < 1.3:
            rpm += (-4000.0 if cut else 8000.0) * DT    # tyre breaks loose; spark cut drops the revs
            rpm = max(rpm, sync); v += 4.0 * DT
        else:
            rpm += (-6000.0 if rpm > sync * 1.01 else 0) * DT
            rpm = max(rpm, sync) if rpm > sync * 1.01 else sync
            v += (0.0 if cut else 15.0) * DT
        rpm = min(rpm, 7300.0)
        slip_max = max(slip_max, rpm / sync - 1); t += DT
    return slip_max, cuts, v
s0 = sim(False); s1 = sim(True)
print(f'low-grip sim (1 s patch, 2nd gear, WOT): TC off -> max slip {s0[0] * 100:.1f}%; TC on -> {s1[0] * 100:.1f}% ({s1[1]} cut calls)')
check('TC limits slip in the low-grip sim', s1[0] < 0.5 * s0[0], f'{s1[0] * 100:.1f}% vs {s0[0] * 100:.1f}%')
print('ALL PASS' if ok else 'SOME FAILED')

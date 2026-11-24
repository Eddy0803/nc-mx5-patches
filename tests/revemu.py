"""Emulate the rev-match routine (0xFE400): logic checks + closed-loop downshift simulation. usage: revemu.py rom.bin"""
import sys, struct

f2b = lambda v: struct.pack('>f', v)
b2f = lambda b: struct.unpack('>f', b)[0]

class CPU:
    def __init__(self, rom, ram):
        self.rom, self.ram = rom, ram
        self.r = [0] * 16; self.fr = [0.0] * 16; self.T = 0; self.PR = 0; self.tr, self.tf = set(), set()
    def mem(self, a, n):
        a &= 0xFFFFFFFF
        if a < 0x100000: return bytes(self.rom[a:a + n])
        assert a >= 0xFFFF0000, hex(a); o = a - 0xFFFF0000; return bytes(self.ram[o:o + n])
    def wmem(self, a, d):
        a &= 0xFFFFFFFF; assert a >= 0xFFFF0000, f'write to 0x{a:08X}'; o = a - 0xFFFF0000; self.ram[o:o + len(d)] = d
    def setr(self, n, v): self.r[n] = v & 0xFFFFFFFF; self.tr.add(n)
    def setf(self, n, v): self.fr[n] = b2f(f2b(v)); self.tf.add(n)
    sx8 = staticmethod(lambda b: b - 256 if b & 0x80 else b)
    def s32(self, v): return v - (1 << 32) if v & 0x80000000 else v
    def step(self, pc, slot=False):
        op = struct.unpack_from('>H', self.rom, pc)[0]; n, m, d = (op >> 8) & 15, (op >> 4) & 15, op & 0xFF; hi = op >> 12; nx = pc + 2
        if hi == 0xD: self.setr(n, struct.unpack('>I', self.mem((pc & ~3) + 4 + d * 4, 4))[0])
        elif op >> 8 == 0xC7: self.setr(0, (pc & ~3) + 4 + d * 4)
        elif hi == 0xE: self.setr(n, self.sx8(d))
        elif op & 0xF00F == 0x6000: self.setr(n, self.sx8(self.mem(self.r[m], 1)[0]))
        elif op & 0xF00F == 0x6001: w = struct.unpack('>H', self.mem(self.r[m], 2))[0]; self.setr(n, w - 65536 if w & 0x8000 else w)
        elif op & 0xF00F == 0x6002: self.setr(n, struct.unpack('>I', self.mem(self.r[m], 4))[0])
        elif op & 0xF00F == 0x6003: self.setr(n, self.r[m])
        elif op & 0xF00F == 0x600C: self.setr(n, self.r[m] & 0xFF)
        elif op & 0xF00F == 0x600D: self.setr(n, self.r[m] & 0xFFFF)
        elif op & 0xF00F == 0x2000: self.wmem(self.r[n], bytes([self.r[m] & 0xFF]))
        elif op & 0xF00F == 0x2001: self.wmem(self.r[n], struct.pack('>H', self.r[m] & 0xFFFF))
        elif op & 0xF00F == 0x2009: self.setr(n, self.r[n] & self.r[m])
        elif op & 0xF00F == 0x2008: self.T = int((self.r[n] & self.r[m]) == 0)
        elif op & 0xF00F == 0x3000: self.T = int(self.r[n] == self.r[m])
        elif op & 0xF00F == 0x3003: self.T = int(self.s32(self.r[n]) >= self.s32(self.r[m]))
        elif op & 0xF00F == 0x3006: self.T = int(self.r[n] > self.r[m])
        elif op & 0xF00F == 0x3007: self.T = int(self.s32(self.r[n]) > self.s32(self.r[m]))
        elif op & 0xF00F == 0x300C: self.setr(n, self.r[n] + self.r[m])
        elif op & 0xF0FF == 0x4008: self.setr(n, self.r[n] << 2)
        elif op >> 8 == 0x88: self.T = int(self.r[0] == (self.sx8(d) & 0xFFFFFFFF))
        elif op >> 8 == 0x84: self.setr(0, self.sx8(self.mem(self.r[(op >> 4) & 15] + (op & 15), 1)[0]))
        elif op >> 8 == 0x80: self.wmem(self.r[(op >> 4) & 15] + (op & 15), bytes([self.r[0] & 0xFF]))
        elif hi == 0x7: self.setr(n, self.r[n] + self.sx8(d))
        elif op == 0x0009: pass
        elif op & 0xF00F == 0xF008: self.setf(n, b2f(self.mem(self.r[m], 4)))
        elif op & 0xF00F == 0xF009: self.setf(n, b2f(self.mem(self.r[m], 4))); self.setr(m, self.r[m] + 4)
        elif op & 0xF00F == 0xF006: self.setf(n, b2f(self.mem(self.r[0] + self.r[m], 4)))
        elif op & 0xF00F == 0xF007: self.wmem(self.r[0] + self.r[n], f2b(self.fr[m]))
        elif op & 0xF00F == 0xF00A: self.wmem(self.r[n], f2b(self.fr[m]))
        elif op & 0xF0FF == 0xF08D: self.setf(n, 0.0)
        elif op & 0xF0FF == 0xF05D: self.setf(n, abs(self.fr[n]))
        elif op & 0xF00F == 0xF005: self.T = int(self.fr[n] > self.fr[m])
        elif op & 0xF00F == 0xF00C: self.setf(n, self.fr[m])
        elif op & 0xF00F == 0xF000: self.setf(n, self.fr[n] + self.fr[m])
        elif op & 0xF00F == 0xF001: self.setf(n, self.fr[n] - self.fr[m])
        elif op & 0xF00F == 0xF002: self.setf(n, self.fr[n] * self.fr[m])
        elif op & 0xF00F == 0xF003: self.setf(n, self.fr[n] / self.fr[m])
        elif op >> 8 in (0x89, 0x8B):
            assert not slot; take = self.T == (1 if op >> 8 == 0x89 else 0)
            return pc + 4 + self.sx8(d) * 2 if take else nx
        elif hi == 0xA:
            dd = op & 0xFFF; dd = dd - 4096 if dd & 0x800 else dd; self.step(pc + 2, True); return pc + 4 + dd * 2
        elif op == 0x000B: t = self.PR; self.step(pc + 2, True); return t
        else: raise NotImplementedError(f'{op:04X} @ {pc:05X}')
        return nx
    def call(self, a):
        self.PR = 0xDEAD0; pc = a; k = 0
        while pc != 0xDEAD0:
            pc = self.step(pc); k += 1; assert k < 800
        return self

rom = bytearray(open(sys.argv[1], 'rb').read())
ram = bytearray(0x10000)
S = lambda a, d: ram.__setitem__(slice(a - 0xFFFF0000, a - 0xFFFF0000 + len(d)), d)
R = lambda a, n: bytes(ram[a - 0xFFFF0000:a - 0xFFFF0000 + n])
def tables(en=1.0, maxpct=30.0, pmax=3.0, vmin=15.0, brk=0xFFFF70EE, maxt=270, gain=0.03, dgain=0.3, ofs=0.0, maxrpm=6000.0,
           K=(113.8, 68.5, 48.3, 36.3, 29.5, 0.0), upen=0.0, upofs=0.0,
           asen=0.0, asrpm=850.0, asgain=0.03, asmax=10.0, asvmax=20.0):
    for a, v in ((0xFE300, en), (0xFE304, maxpct), (0xFE308, pmax), (0xFE30C, vmin), (0xFE318, gain), (0xFE31C, dgain),
                 (0xFE320, ofs), (0xFE324, maxrpm), (0xFE340, upen), (0xFE344, upofs),
                 (0xFE350, asen), (0xFE354, asrpm), (0xFE358, asgain), (0xFE35C, asmax), (0xFE360, asvmax)):
        rom[a:a + 4] = f2b(v)
    rom[0xFE310:0xFE314] = struct.pack('>I', brk); rom[0xFE316:0xFE318] = struct.pack('>H', maxt)
    for i, k in enumerate(K): rom[0xFE328 + 4 * i:0xFE32C + 4 * i] = f2b(k)
def inputs(clutch, brake, pedal, rpm, vss, cruise=0):
    S(0xFFFF7100, bytes([clutch])); S(0xFFFF70EE, bytes([brake])); S(0xFFFF7106, bytes([1]))
    S(0xFFFF56C8, f2b(pedal)); S(0xFFFF6D5C, f2b(rpm)); S(0xFFFF6D04, f2b(vss)); S(0xFFFF585E, bytes([cruise]))
def tick():
    c = CPU(rom, ram); c.call(0xFE400)
    assert c.tr <= {0, 1, 2, 3} and c.tf <= set(range(8)), (c.tr, c.tf)
    return b2f(R(0xFFFF6CA4, 4)), R(0xFFFFAC12, 1)[0], struct.unpack('>H', R(0xFFFFAC10, 2))[0], R(0xFFFFAC13, 1)[0]

ok = True
def check(name, cond, info=''):
    global ok; ok &= bool(cond); print(f'{"PASS" if cond else "FAIL"}  {name} {info}')

tables()
inputs(0, 0, 20.0, 2000.0, 2000 / 48.3); o = tick()
check('clutch up in 3rd: gear 3 detected, timer loaded 270, pedal passes', o[3] == 3 and o[2] == 270 and o[0] == 20.0 and o[1] == 0, str(o))
inputs(0, 0, 20.0, 2000.0, 2000 / 58.0); o = tick()
check('between gears (ratio 58): gear kept at 3', o[3] == 3, str(o))
inputs(0, 0, 20.0, 2000.0, 8.0); o = tick()
check('speed < 10: gear kept', o[3] == 3, str(o))
inputs(0, 0, 0.0, 1700.0, 40.0); tick()          # prev rpm = 1700
inputs(1, 1, 0.0, 1700.0, 40.0); o = tick()
# target = 40*68.5 = 2740 ; err 1040 ; pct = 31.2 -> capped 30
check('3->2 at 40 km/h, rpm 1700: pedal = 30 (capped), flag 1, timer 269', abs(o[0] - 30.0) < 1e-4 and o[1] == 1 and o[2] == 269, str(o))
inputs(1, 1, 0.0, 2600.0, 40.0); o = tick()
# pct = 0.03*140 - 0.3*(2600-1700) = 4.2 - 270 -> 0 -> real 0
check('rpm rising fast near target: damping cuts pedal to 0 (real)', o[0] == 0.0 and o[1] == 1, str(o))
inputs(1, 1, 0.0, 2600.0, 40.0); o = tick()
check('steady 140 below target: pedal 4.2', abs(o[0] - 4.2) < 1e-3, str(o))
inputs(1, 1, 0.0, 2900.0, 40.0); tick(); inputs(1, 1, 0.0, 2900.0, 40.0); o = tick()
check('above target: pedal 0 (no negative)', o[0] == 0.0 and o[1] == 1, str(o))
inputs(1, 0, 0.0, 2000.0, 40.0); o = tick()
check('brake released: inactive, flag = cruise (0)', o[0] == 0.0 and o[1] == 0, str(o))
inputs(1, 1, 5.0, 2000.0, 40.0); o = tick()
check('real pedal 5 > 3: inactive, real pedal out', o[0] == 5.0 and o[1] == 0, str(o))
inputs(1, 1, 0.0, 2000.0, 12.0); o = tick()
check('speed 12 < 15: inactive', o[0] == 0.0 and o[1] == 0, str(o))
tables(en=0.0); inputs(1, 1, 0.0, 2000.0, 40.0); o = tick()
check('Enable 0: inactive', o[0] == 0.0 and o[1] == 0, str(o))
tables(brk=0x000F0000); inputs(1, 1, 0.0, 2000.0, 40.0); o = tick()
check('brake address not RAM: inactive', o[0] == 0.0, str(o))
tables(); inputs(0, 0, 0.0, 2000.0, 2000 / 113.8); tick()   # 1st gear
inputs(1, 1, 0.0, 2000.0, 2000 / 113.8 + 0.0); o = tick()
check('in 1st (no lower gear): inactive', o[0] == 0.0 and o[1] == 0, str(o))
inputs(0, 0, 0.0, 3000.0, 3000 / 29.5); tick(); inputs(1, 1, 0.0, 3000.0, 3000 / 29.5); o = tick()
check('5th -> 4th target uses K[4th]=36.3', o[1] == 1 and o[0] > 0, str(o))
tables(maxpct=80.0); inputs(0, 0, 0.0, 1500.0, 40.0 * 48.3 / 48.3 * 1500 / 1500 * 1500 / (40 * 48.3) * 40); tick()
S(0xFFFFAC13, bytes([3])); inputs(1, 1, 0.0, 1000.0, 40.0); S(0xFFFFAC14, f2b(1000.0)); o = tick()
check('MaxPct 80 capped at 40', abs(o[0] - 40.0) < 1e-4, str(o))
tables(); S(0xFFFFAC13, bytes([2])); inputs(1, 1, 0.0, 3000.0, 100.0); S(0xFFFFAC14, f2b(3000.0)); o = tick()
# 2->1 at 100 km/h: 11380 -> capped 6000 ; err 3000 -> 90 -> 30
check('2->1 at 100 km/h: target capped at 6000 (pedal limited to 30)', abs(o[0] - 30.0) < 1e-4, str(o))
S(0xFFFFAC13, bytes([9])); inputs(1, 1, 0.0, 2000.0, 40.0); o = tick()
check('garbage gear 9: inactive', o[0] == 0.0 and o[1] == 0, str(o))
tables(maxt=1000); inputs(0, 0, 0.0, 2000.0, 2000 / 48.3); o = tick()
check('MaxHold 1000 capped at 600 calls', o[2] == 600, str(o))
tables(maxt=5); inputs(0, 0, 0.0, 2000.0, 2000 / 48.3); tick()
outs = []
for _ in range(8):
    inputs(1, 1, 0.0, 1700.0, 40.0); outs.append(tick())
check('hold time 5 calls then inactive for rest of press', [o[1] for o in outs] == [1] * 5 + [0] * 3, str([o[1] for o in outs]))
inputs(0, 0, 0.0, 2000.0, 2000 / 48.3); o = tick()
check('clutch up reloads timer', o[2] == 5, str(o))

# ---------------- upshift (dashpot) mode ----------------
tables(upen=1.0, upofs=0.0); inputs(0, 0, 40.0, 2740.0, 40.0); tick()                 # in 2nd at 40 km/h, gear 2
inputs(1, 0, 0.0, 1700.0, 40.0); S(0xFFFFAC14, f2b(1700.0)); o = tick()
# target 3rd = 40*48.3 = 1932 ; err 232 ; pct = 6.96
check('upshift 2->3, no brake, rpm 1700 below 3rd target 1932: pedal ~6.96, flag 1', abs(o[0] - 6.96) < 0.01 and o[1] == 1, str(o))
inputs(1, 0, 0.0, 2500.0, 40.0); S(0xFFFFAC14, f2b(2500.0)); o = tick()
check('upshift: rpm above next-gear target -> no throttle (cannot pull down)', o[0] == 0.0 and o[1] == 1, str(o))
tables(upen=1.0, upofs=-150.0); inputs(1, 0, 0.0, 1700.0, 40.0); S(0xFFFFAC14, f2b(1700.0)); o = tick()
check('upshift offset -150 used (not the downshift offset): pedal ~2.46', abs(o[0] - 0.03 * (1932 - 150 - 1700)) < 0.01, str(o))
inputs(1, 1, 0.0, 1700.0, 40.0); S(0xFFFFAC14, f2b(1700.0)); o = tick()
# brake on -> downshift target 1st: 40*113.8 + 100 = 4652 -> pct capped 30
check('brake on -> downshift mode (2->1 target), offset +100', abs(o[0] - 30.0) < 1e-4, str(o))
tables(upen=0.0); inputs(1, 0, 0.0, 1700.0, 40.0); o = tick()
check('UpEnable 0, no brake: inactive (old behaviour)', o[0] == 0.0 and o[1] == 0, str(o))
tables(upen=1.0); inputs(1, 0, 80.0, 1700.0, 40.0); o = tick()
check('flat-foot shift (pedal 80%): upshift hold stays off, real pedal passes', o[0] == 80.0 and o[1] == 0, str(o))
tables(upen=1.0); inputs(0, 0, 20.0, 3000.0, 3000 / 29.5); tick(); inputs(1, 0, 0.0, 2000.0, 3000 / 29.5); o = tick()
check('in 5th: no 6th gear -> inactive', o[0] == 0.0 and o[1] == 0, str(o))
tables(upen=1.0, K=(113.8, 68.5, 48.3, 36.3, 29.5, 25.0)); inputs(0, 0, 20.0, 3000.0, 3000 / 29.5); tick()
inputs(1, 0, 0.0, 2000.0, 3000 / 29.5); S(0xFFFFAC14, f2b(2000.0)); o = tick()
check('6-speed table (K6 25.0): 5->6 active', o[1] == 1 and o[0] > 0, str(o))
tables(upen=1.0); inputs(0, 0, 20.0, 2000.0, 2000 / 113.8); tick()
inputs(1, 0, 0.0, 1000.0, 2000 / 113.8 if 2000 / 113.8 >= 15 else 20.0); S(0xFFFFAC14, f2b(1000.0)); o = tick()
check('upshift 1->2 works (gear 1 allowed for up)', o[1] == 1, str(o))

def simulate_up(gain, dgain, maxpct, upofs, v=55.0, g_from=2, calls=200, dt=0.0055):
    tables(gain=gain, dgain=dgain, maxpct=maxpct, upen=1.0, upofs=upofs)
    rpm = v * 68.5
    inputs(0, 0, 60.0, rpm, v); tick()
    tp, hist, pipe = 40.0, [], [0.0] * 4
    for k in range(calls):
        inputs(1, 0, 0.0, rpm, v)
        ped, flag, _, _ = tick()
        pipe.append(ped); cmd = pipe.pop(0)
        tp += (12.0 + 0.75 * cmd - tp) * min(1.0, dt / 0.04)
        acc = 900.0 * (tp - 12.0) - 2.2 * (rpm - 850.0)
        rpm = max(700.0, rpm + acc * dt)
        hist.append((k * dt, v * 48.3 + upofs, rpm, ped))
    return hist
h = simulate_up(0.04, 0.15, 35.0, 0.0)
low = min(r - t for _, t, r, _ in h)
fin = [r - t for tt, t, r, _ in h if tt > 0.6]
print(f'SIM upshift 2->3 at 55 km/h (from {55*68.5:.0f} to target {55*48.3:.0f}): lowest vs target {low:+.0f} rpm, '
      f'after 0.6 s {min(fin):+.0f}..{max(fin):+.0f} rpm, max pedal {max(p for *_, p in h):.1f}')
for t, tg, r, p in h[::25]:
    print(f'      t={t:5.2f}s target {tg:6.0f} rpm {r:6.0f} pedal {p:5.1f}')
check('upshift sim: never drops more than 250 rpm below target, holds within -150..+150 after 0.6 s',
      low > -250 and min(fin) > -150 and max(fin) < 150)

# ---------------- anti-stall ----------------
tables(asen=1.0)
inputs(0, 0, 0.0, 700.0, 5.0); o = tick()
check('anti-stall: rpm 700 at 5 km/h -> pedal 0.03*150 = 4.5, flag 1', abs(o[0] - 4.5) < 1e-3 and o[1] == 1, str(o))
inputs(0, 0, 0.0, 1000.0, 5.0); o = tick()
check('anti-stall: normal idle 1000 -> nothing', o[0] == 0.0 and o[1] == 0, str(o))
inputs(0, 0, 0.0, 700.0, 30.0); o = tick()
check('anti-stall: above 20 km/h -> nothing', o[0] == 0.0 and o[1] == 0, str(o))
inputs(0, 0, 0.0, 200.0, 0.0); o = tick()
check('anti-stall: cranking / stalled (rpm 200) -> nothing', o[0] == 0.0 and o[1] == 0, str(o))
inputs(0, 0, 0.0, 400.0, 3.0); o = tick()
check('anti-stall: deep dip 400 -> capped at ASMAX 10', abs(o[0] - 10.0) < 1e-4, str(o))
tables(asen=1.0, asmax=50.0, asgain=0.1); inputs(0, 0, 0.0, 400.0, 3.0); o = tick()
check('anti-stall: ASMAX 50 capped at 20 in code (gain 0.1, dip 450 -> 45 -> 20)', abs(o[0] - 20.0) < 1e-4, str(o))
tables(asen=1.0, asgain=0.1); inputs(0, 0, 0.0, 400.0, 3.0); o = tick()
check('anti-stall: gain 0.1, dip 450 -> 45 -> capped at ASMAX 10', abs(o[0] - 10.0) < 1e-4, str(o))
tables(asen=1.0); inputs(0, 0, 8.0, 700.0, 5.0); o = tick()
check('anti-stall: driver pedal 8 > 4.5 -> real pedal, flag not set', o[0] == 8.0 and o[1] == 0, str(o))
tables(asen=0.0); inputs(0, 0, 0.0, 700.0, 5.0); o = tick()
check('anti-stall disabled -> nothing', o[0] == 0.0 and o[1] == 0, str(o))
tables(asen=1.0, upen=1.0); inputs(0, 0, 40.0, 2740.0, 40.0); tick()
inputs(1, 1, 0.0, 1700.0, 40.0); S(0xFFFFAC14, f2b(1700.0)); o = tick()
check('rev-match still takes priority (downshift pedal 30)', abs(o[0] - 30.0) < 1e-4 and o[1] == 1, str(o))

def stall_sim(asen, calls=400, dt=0.0055):
    """Pull away: clutch bites over 0.6 s and loads the engine; driver gives a little throttle (3%)."""
    tables(asen=asen)
    rpm, tp, pipe, low, hist = 1000.0, 12.0, [0.0] * 4, 9999.0, []
    for k in range(calls):
        t = k * dt
        load = min(1.0, t / 0.6) * 3400.0 if t < 1.6 else 800.0       # clutch engagement load (rpm/s)
        inputs(0, 0, 1.5, rpm, min(15.0, t * 6.0))
        ped, flag, _, _ = tick()
        pipe.append(ped); cmd = pipe.pop(0)
        tp += (12.0 + 0.75 * cmd - tp) * min(1.0, dt / 0.04)
        acc = 900.0 * (tp - 12.0) - 2.2 * (rpm - 1000.0) - load + 1.6 * max(0.0, 1000.0 - rpm)  # idle control helps a bit
        rpm = max(0.0, rpm + acc * dt)
        low = min(low, rpm); hist.append((t, rpm, ped))
        if rpm < 350: return low, True, hist
    return low, False, hist
lo0, st0, _ = stall_sim(0.0)
lo1, st1, h1 = stall_sim(1.0)
print(f'SIM pull-away: without anti-stall lowest rpm {lo0:.0f} stalled={st0}; with anti-stall lowest {lo1:.0f} stalled={st1}, '
      f'max pedal {max(p for _, _, p in h1):.1f}')
check('anti-stall sim: bogging pull-away lifted by > 250 rpm and kept above 650, pedal <= 10',
      (lo1 - lo0) > 250 and lo1 > 650 and not st1 and max(p for _, _, p in h1) <= 10.0)

# ---------------- closed-loop simulation ----------------
def simulate(gain, dgain, maxpct, v0=40.0, rpm0=1700.0, gear=3, calls=330, dt=0.0055, ofs=100.0):
    tables(gain=gain, dgain=dgain, maxpct=maxpct, ofs=ofs)
    inputs(0, 0, 0.0, rpm0, rpm0 / (48.3 if gear == 3 else 68.5)); tick()
    rpm, tp, hist = rpm0, 12.0, []
    pipe = [0.0] * 4            # ~22 ms transport delay pedal -> throttle
    for k in range(calls):
        v = v0 - 8.0 * k * dt   # braking ~ 8 km/h per second
        inputs(1, 1, 0.0, rpm, v)
        ped, flag, _, _ = tick()
        pipe.append(ped); cmd = pipe.pop(0)
        tp_target = 12.0 + 0.75 * cmd                      # 15 % pedal -> ~11 % throttle above idle (from the log)
        tp += (tp_target - tp) * min(1.0, dt / 0.04)       # 40 ms throttle response
        acc = 900.0 * (tp - 12.0) - 2.2 * (rpm - 850.0)    # rpm/s: throttle torque vs friction (fits stationary blips)
        rpm = max(700.0, rpm + acc * dt)
        hist.append((k * dt, v * 68.5, rpm, ped, flag))
    return hist
for gain, dgain, mx in ((0.03, 0.3, 30.0), (0.05, 0.3, 30.0), (0.03, 0.0, 30.0)):
    h = [(t, tgt, r, p) for t, tgt, r, p, fl in simulate(gain, dgain, mx)]
    active = [x for x, (*_, fl) in zip(h, simulate(gain, dgain, mx)) if fl == 1]
    reach = next((t for t, tgt, r, p in h if r >= tgt - 150), None)
    tail = [x for x in active if x[0] > 0.4]          # after the initial rise, while the hold is active
    err = max(abs(r - tgt) for t, tgt, r, p in tail)
    over = max(r - tgt for t, tgt, r, p in h)
    print(f'SIM gain {gain} dgain {dgain}: reaches target-150 at {reach if reach is None else round(reach, 3)} s; '
          f'max overshoot {over:.0f} rpm; worst error 2nd half {err:.0f} rpm; max pedal {max(p for *_, p in h):.1f}')
    if (gain, dgain) == (0.03, 0.3):
        check('default tuning: reaches target within 0.6 s, settles within +-250 rpm, pedal <= 30',
              reach is not None and reach < 0.6 and err < 250 and max(p for *_, p in h) <= 30.0)
        for t, tgt, r, p in h[::30]:
            print(f'      t={t:5.2f}s target {tgt:6.0f} rpm {r:6.0f} pedal {p:5.1f}')
print('ALL PASS' if ok else 'SOME FAILED')


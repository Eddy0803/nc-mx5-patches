"""Emulate the rev-match routine (0xFE400): logic checks + closed-loop downshift simulation. usage: revemu.py rom.bin"""
import sys, struct, os

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
        elif op & 0xF00F == 0x3002: self.T = int(self.r[n] >= self.r[m])
        elif op & 0xF00F == 0x3003: self.T = int(self.s32(self.r[n]) >= self.s32(self.r[m]))
        elif op & 0xF00F == 0x3006: self.T = int(self.r[n] > self.r[m])
        elif op & 0xF00F == 0x3007: self.T = int(self.s32(self.r[n]) > self.s32(self.r[m]))
        elif op & 0xF00F == 0x300C: self.setr(n, self.r[n] + self.r[m])
        elif op & 0xF0FF == 0x4008: self.setr(n, self.r[n] << 2)
        elif op >> 8 == 0x88: self.T = int(self.r[0] == (self.sx8(d) & 0xFFFFFFFF))
        elif op >> 8 == 0x84: self.setr(0, self.sx8(self.mem(self.r[(op >> 4) & 15] + (op & 15), 1)[0]))
        elif op >> 8 == 0x80: self.wmem(self.r[(op >> 4) & 15] + (op & 15), bytes([self.r[0] & 0xFF]))
        elif op >> 8 == 0x85:
            w = struct.unpack('>H', self.mem(self.r[(op >> 4) & 15] + (op & 15) * 2, 2))[0]; self.setr(0, w - 65536 if w & 0x8000 else w)
        elif op >> 8 == 0x81: self.wmem(self.r[(op >> 4) & 15] + (op & 15) * 2, struct.pack('>H', self.r[0] & 0xFFFF))
        elif op & 0xF0FF == 0x0029: self.setr(n, self.T)
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
        elif op & 0xF0FF == 0x402B: t = self.r[n]; self.step(pc + 2, True); return t   # jmp @Rn
        else: raise NotImplementedError(f'{op:04X} @ {pc:05X}')
        return nx
    def call(self, a, stop_at=None):
        self.PR = 0xDEAD0; pc = a; k = 0; self.stopped = False
        while pc != 0xDEAD0:
            if pc == stop_at: self.stopped = True; break       # handed over to the factory routine
            pc = self.step(pc); k += 1; assert k < 800
        return self

rom = bytearray(open(sys.argv[1], 'rb').read())
_sp = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts', 'addrs.py')
import importlib.util as _iu
_s = _iu.spec_from_file_location('addrs', _sp); AD = _iu.module_from_spec(_s); _s.loader.exec_module(AD)
A = AD.for_rom(rom)
ram = bytearray(0x10000)
S = lambda a, d: ram.__setitem__(slice(a - 0xFFFF0000, a - 0xFFFF0000 + len(d)), d)
R = lambda a, n: bytes(ram[a - 0xFFFF0000:a - 0xFFFF0000 + n])
def tables(en=1.0, maxpct=30.0, pmax=3.0, vmin=15.0, brk=None, maxt=270, gain=0.03, dgain=0.3, ofs=0.0, maxrpm=6000.0,
           K=(113.8, 68.5, 48.3, 36.3, 29.5, 0.0), upen=0.0, upofs=0.0,   # tests use the 5-speed gearing
           asen=0.0, asrpm=850.0, asgain=0.03, asmax=10.0, asvmax=20.0,
           tgen=0.0, tdef=1.0, tfon=2000.0, tfoff=1500.0, twin=364, tfbt=545, cdly=27):
    for a, v in ((0xFE300, en), (0xFE304, maxpct), (0xFE308, pmax), (0xFE30C, vmin), (0xFE318, gain), (0xFE31C, dgain),
                 (0xFE320, ofs), (0xFE324, maxrpm), (0xFE340, upen), (0xFE344, upofs),
                 (0xFE350, asen), (0xFE354, asrpm), (0xFE358, asgain), (0xFE35C, asmax), (0xFE360, asvmax),
                 (0xFE364, tgen), (0xFE368, tdef), (0xFE36C, tfon), (0xFE370, tfoff)):
        rom[a:a + 4] = f2b(v)
    rom[0xFE374:0xFE376] = struct.pack('>H', twin); rom[0xFE376:0xFE378] = struct.pack('>H', tfbt)
    rom[0xFE378:0xFE37A] = struct.pack('>H', cdly)
    rom[0xFE310:0xFE314] = struct.pack('>I', A['brake'] if brk is None else brk); rom[0xFE316:0xFE318] = struct.pack('>H', maxt)
    for i, k in enumerate(K): rom[0xFE328 + 4 * i:0xFE32C + 4 * i] = f2b(k)
def inputs(clutch, brake, pedal, rpm, vss, cruise=0):
    S(A['clutch'], bytes([clutch])); S(A['brake'], bytes([brake]))
    S(A['pedal_in'], f2b(pedal)); S(A['rpm'], f2b(rpm)); S(A['speed'], f2b(vss)); S(A['cruise_flag'], bytes([cruise]))
NODELAY = True       # most checks look at the behaviour once the clutch-hold delay has passed (own checks below)
def tick():
    if NODELAY: S(0xFFFFAC58, b'\xFF\xFF')
    c = CPU(rom, ram); c.call(0xFE400, stop_at=A.get('pedal_copy') if A.get('pedal_override') else None)
    assert not c.stopped, 'handed over to the factory pedal routine'
    assert c.tr <= {0, 1, 2, 3} and c.tf <= set(range(8)), (c.tr, c.tf)
    return b2f(R(A['pedal_out'], 4)), R(0xFFFFAC12, 1)[0], struct.unpack('>H', R(0xFFFFAC10, 2))[0], R(0xFFFFAC13, 1)[0]

ROMDROP_RAM = ((0xFFFFAC08, 0xFFFFAC0C), (0xFFFFAC18, 0xFFFFAC22))   # romdrop's own RAM: flex fuel AC08-0B, VOLEFF AC18, VOLFLOW AC1C, FS/LC AC20-21
for _a, _b in ROMDROP_RAM: S(_a, bytes([0xA5]) * (_b - _a))          # marker: the patch must never write there
ok = True
def check(name, cond, info=''):
    global ok; ok &= bool(cond); print(f'{"PASS" if cond else "FAIL"}  {name} {info}')

if A.get('pedal_override'):    # calibrations whose pedal copy has a factory override (e.g. LF9WEB)
    ovr = A['pedal_override']
    if rom[ovr]:
        print(f'NOTE  factory pedal override byte 0x{ovr:05X} = {rom[ovr]} in this ROM: rev-match stays off until it is 0 '
              '(the tests below run with it at 0)')
    rom[ovr] = 1
    c = CPU(rom, ram); c.call(0xFE400, stop_at=A['pedal_copy'])
    check('override byte set: hands over to the untouched factory routine, nothing written', c.stopped and c.tr <= {0, 1}
          and not c.tf and rom[A['pedal_copy']:A['pedal_copy'] + len(A['pedal_copy_orig']) // 2].hex().upper() == A['pedal_copy_orig'],
          f'stopped={c.stopped}')
    rom[ovr] = 0                # in memory only

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

# ---------------- on/off switch (clutch down + 3 brake taps while stopped) ----------------
SW = lambda: struct.unpack('>H', R(0xFFFFAC50, 2))[0]
FBT = lambda: struct.unpack('>H', R(0xFFFFAC56, 2))[0]
def sw_reset(word=0): S(0xFFFFAC50, struct.pack('>H', word)); S(0xFFFFAC52, bytes(6))
def taps(n, rpm=850.0, vss=0.0, gap=10):
    """n brake taps, clutch down, stopped; returns the last tick output"""
    o = None
    for _ in range(n):
        for b in [1] * gap + [0] * gap:
            inputs(1, b, 0.0, rpm, vss); S(0xFFFFAC14, f2b(rpm)); o = tick()
    return o
def downshift_active():
    inputs(0, 0, 0.0, 2000.0, 2000 / 48.3); tick()                # 3rd gear remembered
    inputs(1, 1, 0.0, 1700.0, 40.0); S(0xFFFFAC14, f2b(1700.0)); return tick()[1] == 1
tables(); sw_reset(0xBEEF); inputs(0, 0, 0.0, 850.0, 0.0); tick()
check('switch: garbage word at power-up -> set from SwDefault 1 (on)', SW() == 0x5AA5, hex(SW()))
tables(tdef=0.0); sw_reset(0); inputs(0, 0, 0.0, 850.0, 0.0); tick()
check('switch: SwDefault 0 -> starts off, downshift inactive', SW() == 0xA55A and not downshift_active(), hex(SW()))
tables(); sw_reset(); taps(3)
check('switch: SwEnable 0 (default) -> 3 taps do nothing', SW() == 0x5AA5 and FBT() == 0, hex(SW()))
tables(tgen=1.0); sw_reset(); taps(2)
check('switch: 2 taps -> not toggled yet', SW() == 0x5AA5 and FBT() == 0, hex(SW()))
o = taps(1)
check('switch: 3rd tap -> OFF, confirmation running (timer 545 minus the 20 calls of that tap, flag 1, throttle opened)',
      SW() == 0xA55A and 520 <= FBT() <= 545 and o[1] == 1 and o[0] > 0, f'{hex(SW())} {FBT()} {o}')
inputs(1, 0, 0.0, 1300.0, 0.0); S(0xFFFFAC14, f2b(1300.0)); o = tick()
check('switch: OFF confirmation target 1500: at 1300 pedal = 0.03*200 = 6', abs(o[0] - 6.0) < 1e-3, str(o))
for _ in range(600): inputs(1, 0, 0.0, 850.0, 0.0); o = tick()
check('switch: confirmation ends after its time, back to idle (pedal 0, flag 0)', FBT() == 0 and o[0] == 0.0 and o[1] == 0, str(o))
check('switch: OFF -> downshift rev-match inactive', not downshift_active())
tables(tgen=1.0, upen=1.0, upofs=0.0); inputs(0, 0, 40.0, 2740.0, 40.0); tick()
inputs(1, 0, 0.0, 1700.0, 40.0); S(0xFFFFAC14, f2b(1700.0)); o = tick()
check('switch: OFF does not affect upshift hold', o[1] == 1 and abs(o[0] - 6.96) < 0.01, str(o))
tables(tgen=1.0, asen=1.0); inputs(0, 0, 0.0, 700.0, 5.0); o = tick()
check('switch: OFF does not affect anti-stall', abs(o[0] - 4.5) < 1e-3, str(o))
tables(tgen=1.0); taps(3)
inputs(1, 0, 0.0, 1800.0, 0.0); S(0xFFFFAC14, f2b(1800.0)); o = tick()
check('switch: 3 more taps -> ON, confirmation target 2000 (pedal 0.03*200 = 6 at 1800)',
      SW() == 0x5AA5 and abs(o[0] - 6.0) < 1e-3, f'{hex(SW())} {o}')
inputs(0, 0, 0.0, 1800.0, 0.0); o = tick()
check('switch: clutch up during confirmation -> stops at once', FBT() == 0 and o[0] == 0.0 and o[1] == 0, f'{FBT()} {o}')
check('switch: ON -> downshift rev-match works again', downshift_active())
tables(tgen=1.0); sw_reset(); taps(3)
inputs(1, 0, 0.0, 1300.0, 5.0); o = tick()
check('switch: car moving (5 km/h) during confirmation -> stops', FBT() == 0 and o[0] == 0.0, f'{FBT()} {o}')
tables(tgen=1.0); sw_reset(); taps(3, vss=5.0)
check('switch: taps while moving (5 km/h) ignored', SW() == 0x5AA5 and FBT() == 0, hex(SW()))
tables(tgen=1.0); sw_reset()
for b in [1] * 200 + [0] * 5: inputs(1, b, 0.0, 850.0, 0.0); tick()
check('switch: brake held down counts as one tap', R(0xFFFFAC52, 1)[0] == 1 and SW() == 0x5AA5, str(R(0xFFFFAC52, 1)))
tables(tgen=1.0, twin=50); sw_reset(); taps(2)
for _ in range(60): inputs(1, 0, 0.0, 850.0, 0.0); tick()
taps(1)
check('switch: taps further apart than TapWindow do not count together', SW() == 0x5AA5 and R(0xFFFFAC52, 1)[0] == 1, hex(SW()))
tables(tgen=1.0); sw_reset(); taps(2); inputs(0, 0, 0.0, 850.0, 0.0); tick(); taps(1)
check('switch: clutch up between taps resets the count', SW() == 0x5AA5, hex(SW()))
tables(tgen=1.0, tfoff=7000.0); sw_reset(); taps(3)
inputs(1, 0, 0.0, 3900.0, 0.0); S(0xFFFFAC14, f2b(3900.0)); o = tick()
check('switch: confirmation RPM 7000 capped at 4000 in code (pedal 0.03*100 = 3 at 3900)', abs(o[0] - 3.0) < 1e-3, str(o))
tables(tgen=1.0, tfbt=5000); sw_reset(); taps(3)
check('switch: confirmation time 5000 capped at 1100 calls', 1075 <= FBT() <= 1100, str(FBT()))
tables(tgen=1.0, tfbt=0xFFFF); sw_reset(); taps(3)
check('switch: erased confirmation time (0xFFFF) capped at 1100 calls', 1075 <= FBT() <= 1100, str(FBT()))

def confirm_sim(target_on, dt=0.0055):
    """stationary, clutch down: 3 brake taps, then the engine (stationary blip model) follows the confirmation"""
    tables(tgen=1.0); sw_reset(0xA55A if target_on else 0x5AA5)
    rpm, tp, pipe, hist = 850.0, 12.0, [0.0] * 4, []
    seq = ([1] * 10 + [0] * 10) * 3 + [0] * 1000
    for k, b in enumerate(seq):
        inputs(1, b, 0.0, rpm, 0.0)
        ped, flag, _, _ = tick()
        pipe.append(ped); cmd = pipe.pop(0)
        tp += (12.0 + 0.75 * cmd - tp) * min(1.0, dt / 0.04)
        acc = 900.0 * (tp - 12.0) - 2.2 * (rpm - 850.0)
        rpm = max(700.0, rpm + acc * dt)
        hist.append((k * dt, rpm, ped))
    return hist
for on, tgt in ((True, 2000.0), (False, 1500.0)):
    h = confirm_sim(on)
    t0 = 0.33                                   # 3rd tap
    held = [r for t, r, p in h if t0 + 1.0 < t < t0 + 2.9]
    after = [r for t, r, p in h if t > t0 + 4.6]
    over = max(r for t, r, p in h) - tgt
    print(f'SIM confirmation {"ON" if on else "OFF"} (target {tgt:.0f}): overshoot {over:+.0f} rpm, held {min(held):.0f}..{max(held):.0f}, '
          f'after {max(after):.0f}, max pedal {max(p for *_, p in h):.1f}')
    check(f'confirmation {"ON" if on else "OFF"} sim: holds {tgt:.0f} +-150 from 1 s, overshoot < 250, back to idle after',
          min(held) > tgt - 150 and max(held) < tgt + 150 and over < 250 and max(after) < 950)
sw_reset()

# ---------------- clutch hold delay ----------------
NODELAY = False
def press(n, brake=1, pedal=0.0, rpm=1700.0, vss=40.0):
    """3rd gear learned (clutch up), then n calls clutch down; returns the outputs"""
    inputs(0, 0, 0.0, 2000.0, 2000 / 48.3); tick()
    out = []
    for _ in range(n):
        inputs(1, brake, pedal, rpm, vss); S(0xFFFFAC14, f2b(rpm)); out.append(tick())
    return out
def first_active(outs): return next((i for i, o in enumerate(outs) if o[1] == 1), None)
tables(); o = press(40)
check('delay 27 calls (~150 ms): inactive for 27 calls, then active', first_active(o) == 27 and all(x[0] == 0.0 for x in o[:27]),
      str(first_active(o)))
check('delay: hold timer not used during the delay (269 on the first active call)', o[27][2] == 269, str(o[27]))
inputs(0, 0, 0.0, 2000.0, 2000 / 48.3); tick(); o = press(20)
inputs(0, 0, 0.0, 2000.0, 2000 / 48.3); tick(); o = press(40)
check('delay: clutch up before the delay is over -> starts again from 0', first_active(o) == 27, str(first_active(o)))
for v, want, name in ((0, 0, '0 = no delay (acts on the first call, old behaviour)'), (5, 5, '5 calls'),
                      (73, 73, '73 (~400 ms)'), (91, 91, '91 (~500 ms) allowed'), (500, 91, '500 -> capped at 91 (~500 ms)'),
                      (0xFFFF, 91, 'erased 0xFFFF -> capped at 91')):
    tables(cdly=v); o = press(110)
    check(f'delay table {name}', first_active(o) == want, str(first_active(o)))
tables(upen=1.0, upofs=0.0); inputs(0, 0, 40.0, 2740.0, 40.0); tick()
outs = []
for _ in range(40): inputs(1, 0, 0.0, 1700.0, 40.0); S(0xFFFFAC14, f2b(1700.0)); outs.append(tick())
check('delay: upshift hold waits too', first_active(outs) == 27, str(first_active(outs)))
tables(); o = press(40, brake=0); inputs(1, 1, 0.0, 1700.0, 40.0); S(0xFFFFAC14, f2b(1700.0)); o2 = tick()
check('delay: clutch already down long enough, brake pressed later -> active at once', o2[1] == 1, str(o2))
tables(asen=1.0); o = press(10, brake=0, rpm=700.0, vss=5.0)
check('delay: anti-stall still works during the delay', abs(o[5][0] - 4.5) < 1e-3, str(o[5]))
tables(tgen=1.0); sw_reset(); taps(3)
check('delay: on/off gesture and its confirmation not delayed', SW() == 0xA55A and FBT() > 0, f'{hex(SW())} {FBT()}')
sw_reset()

# ---------------- closed-loop simulation ----------------
def simulate(gain, dgain, maxpct, v0=40.0, rpm0=1700.0, gear=3, calls=330, dt=0.0055, ofs=100.0, cdly=None):
    global NODELAY
    NODELAY = cdly is None
    tables(gain=gain, dgain=dgain, maxpct=maxpct, ofs=ofs, cdly=cdly or 27)
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
for cd in (9, 27, 73, 91):
    h = simulate(0.03, 0.3, 30.0, cdly=cd)
    start = next(t for t, tgt, r, p, fl in h if fl == 1)
    reach = next((t for t, tgt, r, p, fl in h if r >= tgt - 150), None)
    print(f'SIM with clutch delay {cd} calls ({cd * 5.5:.0f} ms): throttle starts at {start:.3f} s, reaches target-150 at {reach} s')
    check(f'delay {cd} sim: no throttle before the delay, target reached within delay + 0.6 s',
          all(p == 0.0 for t, tgt, r, p, fl in h if t < cd * 0.0055 - 1e-9) and reach is not None and reach < cd * 0.0055 + 0.6)
NODELAY = True
check('never wrote romdrop RAM (AC08-AC0B, AC18-AC21 still the marker)',
      all(R(_a, _b - _a) == bytes([0xA5]) * (_b - _a) for _a, _b in ROMDROP_RAM))
print('ALL PASS' if ok else 'SOME FAILED')


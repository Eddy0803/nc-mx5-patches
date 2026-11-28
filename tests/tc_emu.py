"""Emulate traction control v2 (0xFE800, wheel slip), chained in front of rev-match / the factory pedal copy: logic checks,
the chain with rev-match, install order / removal / v1 upgrade, and a closed-loop wheelspin simulation.
usage: tc_emu.py rom_with_tc.bin"""
import sys, struct, os, importlib.util

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
DUAL = TC.dual(A)                 # two-path software: TC has a second entry (0xFE9C0) for the second task list

class TCPU(CPU):
    FPUL = 0
    def step(self, pc, slot=False):
        if OVR and pc == A['pedal_copy'] and not slot:          # factory routine with an override: emulate the plain copy
            self.wmem(A['pedal_out'], self.mem(A['pedal_in'], 4)); return self.PR
        if OVR and DUAL and pc == A['pedal_copy2'] and not slot:
            self.wmem(A['pedal_out'], self.mem(A['pedal_in2'], 4)); return self.PR
        if pc == IG.OH_CODE and not slot:                  # ignition cut's overheat cap on its cut point: not tested here
            return self.PR                                 # (spark() runs at 3000 rpm, far below any cut point)
        op = struct.unpack_from('>H', self.rom, pc)[0]; n, m = (op >> 8) & 15, (op >> 4) & 15
        if op & 0xF0FF == 0x4022:   # sts.l pr,@-rn
            self.setr(n, self.r[n] - 4); self.wmem(self.r[n], struct.pack('>I', self.PR)); return pc + 2
        if op & 0xF0FF == 0x4026:   # lds.l @rn+,pr
            self.PR = struct.unpack('>I', self.mem(self.r[n], 4))[0]; self.setr(n, self.r[n] + 4); return pc + 2
        if op & 0xF0FF == 0x400B:   # jsr @rn
            assert not slot; t = self.r[n]; self.PR = pc + 4; self.step(pc + 2, True); return t
        if op >> 8 == 0xCA:         # xor #imm,r0
            self.setr(0, self.r[0] ^ (op & 0xFF)); return pc + 2
        if op >> 8 == 0xC9:         # and #imm,r0
            self.setr(0, self.r[0] & (op & 0xFF)); return pc + 2
        if op & 0xF00F == 0xF004:   # fcmp/eq
            self.T = int(self.fr[n] == self.fr[m]); return pc + 2
        if op & 0xF0FF == 0x4011:   # cmp/pz
            self.T = int(self.s32(self.r[n]) >= 0); return pc + 2
        if op >> 12 == 0x5:         # mov.l @(disp,rm),rn
            self.setr(n, struct.unpack('>I', self.mem(self.r[m] + (op & 15) * 4, 4))[0]); return pc + 2
        if op & 0xF00F == 0x2002:   # mov.l rm,@rn
            self.wmem(self.r[n], struct.pack('>I', self.r[m])); return pc + 2
        if op & 0xF0FF == 0x405A:   # lds rm,fpul  (rm in the n field)
            self.FPUL = self.r[n]; return pc + 2
        if op & 0xF0FF == 0xF02D:   # float fpul,frn
            self.setf(n, float(self.s32(self.FPUL))); return pc + 2
        if op in (0x0018, 0x0008):  # sett / clrt
            self.T = int(op == 0x0018); return pc + 2
        if op & 0xF0FF == 0xF03D:   # ftrc frn,fpul
            self.FPUL = int(self.fr[n]) & 0xFFFFFFFF; return pc + 2
        if op & 0xF0FF == 0x005A:   # sts fpul,rn
            self.setr(n, self.FPUL); return pc + 2
        if op & 0xF0FF == 0xF09D:   # fldi1
            self.setf(n, 1.0); return pc + 2
        if op & 0xF00F == 0x3008:   # sub rm,rn
            self.setr(n, self.r[n] - self.r[m]); return pc + 2
        if op == 0x4F52:            # sts.l fpul,@-r15
            self.setr(15, self.r[15] - 4); self.wmem(self.r[15], struct.pack('>I', self.FPUL & 0xFFFFFFFF)); return pc + 2
        if op == 0x4F56:            # lds.l @r15+,fpul
            self.FPUL = struct.unpack('>I', self.mem(self.r[15], 4))[0]; self.setr(15, self.r[15] + 4); return pc + 2
        if op >> 12 == 0xB:         # bsr
            assert not slot; dd = op & 0xFFF; dd = dd - 4096 if dd & 0x800 else dd
            self.PR = pc + 4; self.step(pc + 2, True); return pc + 4 + dd * 2
        return super().step(pc, slot)

ok = True
def check(name, cond, info=''):
    global ok; ok &= bool(cond); print(f'{"PASS" if cond else "FAIL"}  {name} {info}')

# ---------- static: chain, tables, install order, removal ----------
nxt = TC.next_target(rom, A)
check('TC in the task slot (task literals -> 0xFE800)', TC.installed(rom, A),
      f'-> 0x{struct.unpack_from(">I", rom, A["task_literals"][0])[0]:05X}')
check('TC calls rev-match or the factory pedal copy underneath', nxt in (A['pedal_copy'], TC.REVMATCH), f'NEXT 0x{nxt:05X}')
SPL = AD.spark_info(A)['term_lit']; IGR = IG.assemble(A)[2]
check('TC code is this version (scaled intervention, table layout 3) and the timing hook is in front of the ignition cut',
      bytes(rom[TC.SPK:TC.SPK + len(TC.assemble_spark(A)[0])]) == TC.assemble_spark(A)[0] and struct.unpack_from('>I', rom, SPL)[0] == TC.SPK
      and bytes(rom[TC.CODE:TC.CODE + len(TC.assemble(A))]) == TC.assemble(A)
      and rom[TC.TBL['VER']] == TC.VERSION)
check('ignition cut installed (TC cuts spark through it)', bytes(rom[A['dwell_site']:A['dwell_site'] + 26]) == AD.dwell_hook(A))
c = bytearray(rom); TC.install(c, A=A); check('reinstalling TC changes nothing (settings kept)', c == rom)
if DUAL:
    nxt2 = struct.unpack_from('>I', rom, TC.NEXT2)[0]
    check('two-path: second task list -> TC second entry, which calls the second copy or rev-match second entry',
          all(struct.unpack_from('>I', rom, x)[0] == TC.ENTRY2 for x in A['task_literals2']) and nxt2 in (A['pedal_copy2'], TC.REVMATCH2)
          and (nxt2 == TC.REVMATCH2) == (nxt == TC.REVMATCH) and bytes(rom[TC.ENTRY2:TC.ENTRY2 + len(TC.assemble2(A))]) == TC.assemble2(A),
          f'NEXT2 0x{nxt2:05X}')
c = bytearray(rom); TC.remove(c, A); t = struct.unpack_from('>I', c, A['task_literals'][0])[0]
check('removing TC puts the slot back to what ran underneath', t == nxt and all(b == 0xFF for b in c[TC.CODE:TC.CODE_END])
      and all(b == 0xFF for b in c[TC.TBL_START:TC.TBL_END]) and all(b == 0xFF for b in c[TC.SPK:TC.SPK_END])
      and struct.unpack_from('>I', c, SPL)[0] == IGR
      and (not DUAL or all(struct.unpack_from('>I', c, x)[0] == nxt2 for x in A['task_literals2'])))
if nxt == TC.REVMATCH:
    keep = bytes(c[0xFE300:0xFE380]); c2 = bytearray(c); TC.install(c2, A=A)
    check('TC removed and installed again: rev-match untouched, chain back', c2[0xFE300:0xFE380] == keep and TC.next_target(c2, A) == TC.REVMATCH)
    c3 = bytearray(rom); RV.install(c3, A=A)
    check('rev-match reinstalled on a TC file: goes under TC (NEXT), TC kept, nothing else changed', c3 == rom)
c = bytearray(rom); IG.install(c, A=A); check('ignition cut reinstalled: TC and its timing hook untouched', c == rom and c[TC.TBL_START:TC.TBL_END] == rom[TC.TBL_START:TC.TBL_END]
                                             and c[TC.CODE:TC.CODE_END] == rom[TC.CODE:TC.CODE_END] and TC.installed(c, A))
# upgrade from v1 (rev-rise detection, 0.9.29-0.9.30): Enable and user-changed pedal kept, the rest v2 defaults, v1 tables erased
# (v1 only ever existed on single-path calibrations; on two-path ones 0xFE3B8 is NEXT2)
def v1_upgrade_check():
    c = bytearray(rom)
    c[0xFE380:0xFE3BC] = b'\xFF' * 0x3C
    for a, v in ((0xFE380, 1.0), (0xFE384, 30.0), (0xFE388, 0.0055), (0xFE38C, 0.1), (0xFE390, 10.0), (0xFE394, 55.0),
                 (0xFE398, 2000.0), (0xFE3B8, 2500.0)): c[a:a + 4] = f2b(v)
    c[0xFE39C], c[0xFE39D], c[0xFE39E] = 18, 90, 40
    for i in range(6): c[0xFE3A0 + 4 * i:0xFE3A4 + 4 * i] = f2b(50.0)
    notes = TC.install(c, A=A); tv = TC.read_tables(c)
    check('v1 settings upgraded: on/off and a changed pedal kept, new settings at defaults, old tables erased',
          tv['EN'] == 1.0 and tv['PMIN'] == 55.0 and tv['SLIPKMH'] == TC.DEFAULTS['SLIPKMH'] and tv['LOCK'] == TC.DEFAULTS['LOCK']
          and tv['VER'] == TC.VERSION and all(tv[k] == TC.DEFAULTS[k] for k in ('MAXACT', 'REST', 'DECAY', 'TRET', 'FULL', 'CUTST', 'THR'))
          and c[0xFE39C] == 0xFF and c[0xFE39F] == 0xFF and c[0xFE3A3] == 0xFF and all(b == 0xFF for b in c[0xFE3B4:0xFE3B8]), str(notes))
# upgrade from v2 (0.9.31-0.9.41): slip / condition / lockout settings kept, its Hold erased, the new settings at defaults
c = bytearray(rom); c[TC.TBL['VER']] = 2; c[0xFE3A0:0xFE3B4] = bytes([0xFF]) * 0x14; c[0xFE39C] = 12
c[TC.TBL['SLIPKMH']:TC.TBL['SLIPKMH'] + 4] = f2b(4.5); c[TC.TBL['LOCK']] = 33
notes = TC.install(c, A=A); tv = TC.read_tables(c)
check('v2 upgraded: slip and lockout settings kept, Hold erased, new settings at defaults', tv['SLIPKMH'] == 4.5 and tv['LOCK'] == 33
      and tv['VER'] == TC.VERSION and c[0xFE39C] == 0xFF and all(tv[k] == TC.DEFAULTS[k] for k in ('MAXACT', 'REST', 'DECAY', 'TRET', 'FULL', 'CUTST', 'THR')), str(notes))
if DUAL: print('(v1 upgrade check: not applicable - v1 never existed on two-path calibrations)')
else: v1_upgrade_check()

# ---------- dynamic ----------
ram = bytearray(0x10000)
S = lambda a, d: ram.__setitem__(slice(a - 0xFFFF0000, a - 0xFFFF0000 + len(d)), d)
R = lambda a, n: bytes(ram[a - 0xFFFF0000:a - 0xFFFF0000 + n])
DT = 0.0055
ROMDROP_RAM = ((0xFFFFAC00, 0xFFFFAC0E), (0xFFFFAC18, 0xFFFFAC3C))   # romdrop's own RAM: never written by TC
WS = A['wheel_speeds']
enc = lambda kmh: struct.pack('>H', max(0, min(0xFFFD, int(round(kmh * 100 + 10000)))))
jit = [0]
LVL, ACC, FLAG = 0xFFFFAC49, 0xFFFFAC48, 0xFFFFAC4B

def tables(en=1.0, slipkmh=3.0, slippct=10.0, vmin=5.0, pmin=20.0, rpmmin=2000.0, lock=20, maxact=180, rest=30, decay=4,
           tret=6.0, full=1.0, cutst=40.0, thr=25.0):
    for k, v in (('EN', en), ('SLIPKMH', slipkmh), ('SLIPPCT', slippct), ('VMIN', vmin), ('PMIN', pmin), ('RPMMIN', rpmmin),
                 ('TRET', tret), ('FULL', full), ('CUTST', cutst), ('THR', thr)):
        rom[TC.TBL[k]:TC.TBL[k] + 4] = f2b(v)
    for k, v in (('LOCK', lock), ('MAXACT', maxact), ('REST', rest), ('DECAY', decay)): rom[TC.TBL[k]] = v
    if nxt == TC.REVMATCH: rom[0xFE378:0xFE37A] = struct.pack('>H', 0)    # no clutch-hold delay for the rev-match check

def reset():
    ram[:] = bytes(0x10000)
    for a, b in ROMDROP_RAM: S(a, bytes([0xA5]) * (b - a))

def inputs(fl, fr, rl, rr, clutch=0, brake=0, pedal=80.0, rpm=4000.0, raw=None, frozen=False):
    """wheel speeds as the ABS unit sends them; they jitter by 0.01 km/h like real data unless frozen (CAN lost)"""
    if not frozen: jit[0] ^= 1
    S(WS, raw if raw is not None else enc(fl + 0.01 * jit[0]) + enc(fr) + enc(rl) + enc(rr))
    S(A['clutch'], bytes([clutch])); S(A['brake'], bytes([brake]))
    S(A['pedal_in'], f2b(pedal)); S(A['rpm'], f2b(rpm)); S(A['speed'], f2b((rl + rr) / 2))
    if DUAL: S(A['pedal_in2'], f2b(pedal))

ENTRY = [0]
def tick():
    """one task call; returns (cut flag, level 0..255, engine-side pedal)"""
    second = DUAL and ENTRY[0] % 2 == 1; ENTRY[0] += 1      # two-path software: alternate the two task lists
    c = TCPU(rom, ram); c.r[15] = 0xFFFFE000; sp = c.r[15]; c.call(TC.ENTRY2 if second else 0xFE800)
    assert c.r[15] == sp, 'stack unbalanced'
    assert c.tr <= {0, 1, 2, 3, 15} and c.tf <= set(range(8)), (c.tr, c.tf)
    return R(FLAG, 1)[0], R(LVL, 1)[0], b2f(R(A['pedal_out'], 4))

def run(calls, *w, **kw):
    out = []
    for _ in range(calls): inputs(*w, **kw); out.append(tick())
    return out
cuts = lambda o: [x[0] for x in o]
lvls = lambda o: [x[1] for x in o]
no_two = lambda f: all(not (f[i] and f[i + 1]) for i in range(len(f) - 1))

def spark(term=10.0):
    """the timing hook as the spark-advance sum calls it: returns fr1 (the ignition cut not cutting: rpm low)"""
    S(A['spark_term'], f2b(term)); S(A['rpm'], f2b(3000.0)); S(FLAG, bytes(1))   # a skipped call: only TC's timing pull
    c = TCPU(rom, ram); c.r[15] = 0xFFFFE000; c.call(TC.SPK); assert c.r[15] == 0xFFFFE000
    return c.fr[1]

tables(); reset()
o = run(200, 50, 50, 50, 50)
check('grip, straight: no intervention (level 0, no cut, pedal untouched, timing untouched)',
      sum(cuts(o)) == 0 and max(lvls(o)) == 0 and abs(o[-1][2] - 80.0) < 1e-4 and abs(spark() - 10.0) < 1e-6)
o = run(200, 50, 50, 57.5, 57.5); check('rears 7.5 km/h faster at 50 (allowed 3 + 10% = 8): no intervention', max(lvls(o)) == 0)
reset(); o = run(200, 46, 54, 47, 55); check('cornering: outer wheels 8 km/h faster than inner, each side gripping: none', max(lvls(o)) == 0)
# small slip: timing and throttle only
reset(); o = run(40, 50, 50, 60, 60); L = o[-1][1]                  # excess 2/8 = 25% -> level 64
pull = 10.0 - spark()
check('small slip (rears 10 at 50, 25% over): level ~25%, timing pull ~1.5 deg, throttle -6%, no cuts',
      60 <= L <= 66 and sum(cuts(o)) == 0 and abs(pull - 6.0 * L / 255) < 1e-3 and abs(o[-1][2] - 80.0 * (1 - 0.25 * L / 255)) < 1e-3,
      f'level {L}, pull {pull:.2f}, pedal {o[-1][2]:.2f}')
# medium slip: some cuts
reset(); o = run(170, 50, 50, 64.4, 64.4); L = o[-1][1]; f = cuts(o)    # excess 6.4/8 = 80% -> level ~204
ratio = sum(f[50:]) / len(f[50:])
check('medium slip (80% over): level ~80%, cuts about 1 call in 3, never two in a row', 195 <= L <= 210 and 0.25 < ratio < 0.42 and no_two(f),
      f'level {L}, cut ratio {ratio:.2f}')
# big slip: the most it ever does
reset(); o = run(170, 50, 50, 80, 80); f = cuts(o); pull = 10.0 - spark()
check('big slip (rears 30 faster): full level: cut exactly 1 call in 2, never a full cut',
      o[-1][1] == 255 and abs(sum(f[20:]) / len(f[20:]) - 0.5) < 0.02 and no_two(f), f'ratio {sum(f[20:]) / len(f[20:]):.2f}')
check('  ... timing pull 6 deg, throttle -25%', abs(pull - 6.0) < 1e-3 and abs(o[-1][2] - 60.0) < 1e-3, f'pull {pull:.2f}, pedal {o[-1][2]:.2f}')
reset(); f = cuts(run(20, 50, 50, 80, 50)); check('one rear spinning (left), other gripping: intervenes (per side)', sum(f) > 0)
reset(); f = cuts(run(20, 50, 50, 50, 80)); check('right rear spinning: intervenes', sum(f) > 0)
# recovery: eases off
reset(); run(40, 50, 50, 80, 80); o = run(100, 50, 50, 50, 50); l = lvls(o)
n0 = l.index(0) if 0 in l else None; f = cuts(o)
last_cut = max([i for i, x in enumerate(f) if x] or [-1])
check('slip ends: level eases off by 4 a call (0 after ~64 calls, ~0.35 s), cuts stop first, then timing, then throttle back',
      n0 is not None and 60 <= n0 <= 66 and all(l[i] >= l[i + 1] for i in range(99)) and last_cut < n0 and abs(o[-1][2] - 80.0) < 1e-4,
      f'level 0 after {n0} calls, last cut at {last_cut}')
# never two cuts in a row, whatever the slip does
import random; rnd = random.Random(7); reset(); f = []
for i in range(1500):
    inputs(50, 50, 50 + rnd.choice((0, 5, 9, 12, 16, 25, 40)), 50 + rnd.choice((0, 8, 30))); f.append(tick()[0])
check('random slip, 1500 calls: never two cuts in a row (never a full cut)', no_two(f) and sum(f) > 0, f'{sum(f)} cut calls')
# backstop
reset(); o = run(400, 50, 50, 80, 80); l = lvls(o); act = [x > 0 for x in l]
first_off = act.index(False) if False in act else None
check('slip that never ends (stuck sensor): after Max Time (180 calls, ~1 s) a Rest of 30 calls with no intervention',
      first_off == 180 and not any(act[180:211]) and act[211] and sum(cuts(o)[180:211]) == 0, f'first gap at {first_off}')
reset(); o = run(300, 50, 49, 50, 60); f = cuts(o)
check('one front sensor reading 10 km/h low: bounded, never two cuts in a row', no_two(f) and not all(x > 0 for x in lvls(o)[175:215]))
# conditions: everything to 0 at once
for name, kw, tb in [('clutch down', dict(clutch=1), {}), ('brake pressed', dict(brake=1), {}), ('pedal 15% (< 20)', dict(pedal=15.0), {}),
                     ('rpm 1800 (< 2000)', dict(rpm=1800.0), {}), ('Enable 0', {}, dict(en=0.0))]:
    tables(**tb); reset(); run(20, 50, 50, 80, 80) if not tb else None; o = run(30, 50, 50, 80, 80, **kw)
    check(f'spinning but {name}: nothing (level 0 at once)', sum(cuts(o)) == 0 and max(lvls(o)) == 0 and abs(10.0 - spark()) < 1e-6)
tables()
reset(); o = run(30, 3, 3, 15, 15); check('launch: fronts below 5 km/h: nothing', max(lvls(o)) == 0)
reset(); run(10, 50, 50, 50, 50, clutch=1); o = run(40, 50, 50, 80, 80); l = lvls(o)
check('clutch just released: lockout (20 calls, ~110 ms) then intervenes', max(l[:20]) == 0 and l[20] == 255, f'first at {next((i for i, x in enumerate(l) if x), None)}')
reset(); o = run(30, 50, 50, 70, 70, raw=enc(50) + enc(50) + b'\xFF\xFE' + enc(70)); check('a wheel speed invalid (FFFE): nothing', max(lvls(o)) == 0)
reset(); run(5, 50, 50, 80, 80); o = run(150, 50, 50, 80, 80, frozen=True)
check('wheel data frozen (CAN lost): stops within ~100 calls', o[-1][1] == 0 and o[-1][0] == 0)
# bad tables / RAM
for name, tb in [('Timing Pull NaN', dict(tret=float('nan'))), ('Throttle NaN', dict(thr=float('nan'))), ('Cut Start NaN', dict(cutst=float('nan'))),
                 ('Full Slip NaN', dict(full=float('nan'))), ('Full Slip 0', dict(full=0.0))]:
    tables(**tb); reset(); o = run(60, 50, 50, 80, 80); f = cuts(o); s = spark()
    check(f'{name}: still bounded (no NaN timing or pedal, never two cuts in a row)', s == s and 4.0 <= s <= 10.0 and all(x[2] == x[2] and 40.0 <= x[2] <= 80.0 for x in o)
          and no_two(f), f'timing {s:.2f}, pedal {o[-1][2]:.2f}')
tables(tret=50.0, thr=90.0); reset(); o = run(60, 50, 50, 80, 80)
check('Timing Pull 50 / Throttle 90 in the tables: capped at 10 deg / 50%', abs(10.0 - spark() - 10.0) < 1e-3 and abs(o[-1][2] - 40.0) < 1e-3)
tables(decay=0); reset(); run(40, 50, 50, 80, 80); l = lvls(run(400, 50, 50, 50, 50))
check('Decay 0 in the table: treated as 1, still eases off', l[-1] == 0 and l[100] > 0)
tables(maxact=0xFF, rest=0xFF, decay=0xFF); reset(); o = run(600, 50, 50, 80, 80); act = [x[1] > 0 for x in o]
check('erased bytes (FF): Max Time 255, Rest 255 - still bounded', act.index(False) == 255 and not any(act[255:510]))
tables(); reset(); ram[0xAC46:0xAC4D] = bytes([0xC8, 0xC8, 0x77, 0xF0, 0, 0, 0x99]); o = run(400, 50, 50, 80, 80)
check('garbage counters at power-up: never two cuts in a row', no_two(cuts(o)))
reset(); inputs(50, 50, 50, 50, pedal=37.5); tick()
check('pedal copy still done underneath (engine-side pedal = real pedal)', abs(b2f(R(A['pedal_out'], 4)) - 37.5) < 1e-4, f'{b2f(R(A["pedal_out"], 4))}')
if nxt == TC.REVMATCH and struct.unpack_from('>f', rom, 0xFE300)[0] > 0:
    reset(); run(30, 60, 60, 60, 60, pedal=0.0, rpm=2200.0); out = []
    for i in range(40):
        inputs(60, 60, 60, 60, clutch=1, brake=1, pedal=0.0, rpm=1500.0); tick(); out.append(b2f(R(A['pedal_out'], 4)))
    check('rev-match still active underneath (clutch + brake -> throttle blip)', max(out) > 5, f'max pedal {max(out):.1f}%')
check("romdrop's RAM never written", all(R(a, b - a) == bytes([0xA5]) * (b - a) for a, b in ROMDROP_RAM))

# ---------- closed loop: 1 s low-grip patch at full throttle in 2nd ----------
# rough model: drive torque = pedal share x timing factor (about 3% less per degree pulled), and 0 on a cut call
def sim(tc, T=1.8):
    tables(en=1.0 if tc else 0.0); reset()
    v, vr, t, peak, ncut = 40.0, 40.0, 0.0, 0.0, 0
    run(40, v, v, vr, vr)                                    # past the clutch lockout
    while t < T:
        inputs(v, v, vr, vr, pedal=100.0, rpm=4000.0); cut, lv, ped = tick(); ncut += cut
        torque = 0.0 if cut else (ped / 100.0) * (1 - 0.03 * 6.0 * lv / 255)
        if 0.3 <= t < 1.3:                                   # wet patch: the rears break loose unless torque comes down
            vr += (110.0 * torque - 50.0) * DT; vr = max(vr, v); v += 3.0 * DT
        else:                                                # grip: the rears are pulled back to road speed
            vr = max(v, vr - 80.0 * DT); v += 12.0 * torque * DT
        peak = max(peak, vr - v); t += DT
    return peak, ncut, v
s0, s1 = sim(False), sim(True)
print(f'low-grip sim (1 s wet patch, full throttle): TC off -> peak slip {s0[0]:.1f} km/h; TC on -> {s1[0]:.1f} km/h ({s1[1]} cut calls)')
allowed40 = 3.0 + 0.10 * 40.0                            # allowed slip at the sim's road speed, defaults
check('TC cuts the wheelspin by more than 70% and holds it within ~2x the allowed slip (full intervention point)',
      s1[0] < 0.3 * s0[0] and s1[0] < 2.2 * allowed40, f'{s1[0]:.1f} vs {s0[0]:.1f} km/h (allowed {allowed40:.1f})')
print('ALL PASS' if ok else 'SOME FAILED')

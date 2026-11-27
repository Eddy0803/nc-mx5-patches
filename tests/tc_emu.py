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
        if op >> 12 == 0x5:         # mov.l @(disp,rm),rn
            self.setr(n, struct.unpack('>I', self.mem(self.r[m] + (op & 15) * 4, 4))[0]); return pc + 2
        if op & 0xF00F == 0x2002:   # mov.l rm,@rn
            self.wmem(self.r[n], struct.pack('>I', self.r[m])); return pc + 2
        if op & 0xF0FF == 0x405A:   # lds rm,fpul  (rm in the n field)
            self.FPUL = self.r[n]; return pc + 2
        if op & 0xF0FF == 0xF02D:   # float fpul,frn
            self.setf(n, float(self.s32(self.FPUL))); return pc + 2
        return super().step(pc, slot)

ok = True
def check(name, cond, info=''):
    global ok; ok &= bool(cond); print(f'{"PASS" if cond else "FAIL"}  {name} {info}')

# ---------- static: chain, tables, install order, removal ----------
nxt = TC.next_target(rom, A)
check('TC in the task slot (task literals -> 0xFE800)', TC.installed(rom, A),
      f'-> 0x{struct.unpack_from(">I", rom, A["task_literals"][0])[0]:05X}')
check('TC calls rev-match or the factory pedal copy underneath', nxt in (A['pedal_copy'], TC.REVMATCH), f'NEXT 0x{nxt:05X}')
check('TC code is this version (wheel slip, table layout 2)', bytes(rom[TC.CODE:TC.CODE + len(TC.assemble(A))]) == TC.assemble(A)
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
      and all(b == 0xFF for b in c[TC.TBL_START:TC.TBL_END])
      and (not DUAL or all(struct.unpack_from('>I', c, x)[0] == nxt2 for x in A['task_literals2'])))
if nxt == TC.REVMATCH:
    keep = bytes(c[0xFE300:0xFE380]); c2 = bytearray(c); TC.install(c2, A=A)
    check('TC removed and installed again: rev-match untouched, chain back', c2[0xFE300:0xFE380] == keep and TC.next_target(c2, A) == TC.REVMATCH)
    c3 = bytearray(rom); RV.install(c3, A=A)
    check('rev-match reinstalled on a TC file: goes under TC (NEXT), TC kept, nothing else changed', c3 == rom)
c = bytearray(rom); IG.install(c, A=A); check('ignition cut reinstalled: TC untouched', c[TC.TBL_START:TC.TBL_END] == rom[TC.TBL_START:TC.TBL_END]
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
    check('v1 settings upgraded: on/off and a changed pedal kept, new slip settings at defaults, old tables erased',
          tv['EN'] == 1.0 and tv['PMIN'] == 55.0 and tv['SLIPKMH'] == TC.DEFAULTS['SLIPKMH'] and tv['HOLD'] == TC.DEFAULTS['HOLD']
          and tv['LOCK'] == TC.DEFAULTS['LOCK'] and tv['VER'] == TC.VERSION and all(b == 0xFF for b in c[0xFE39F:0xFE3BC]), str(notes))
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

def tables(en=1.0, slipkmh=3.0, slippct=10.0, vmin=5.0, pmin=20.0, rpmmin=2000.0, hold=9, lock=20):
    for k, v in (('EN', en), ('SLIPKMH', slipkmh), ('SLIPPCT', slippct), ('VMIN', vmin), ('PMIN', pmin), ('RPMMIN', rpmmin)):
        rom[TC.TBL[k]:TC.TBL[k] + 4] = f2b(v)
    rom[TC.TBL['HOLD']], rom[TC.TBL['LOCK']] = hold, lock
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
    second = DUAL and ENTRY[0] % 2 == 1; ENTRY[0] += 1      # two-path software: alternate the two task lists
    c = TCPU(rom, ram); c.r[15] = 0xFFFFE000; sp = c.r[15]; c.call(TC.ENTRY2 if second else 0xFE800)
    assert c.r[15] == sp, 'stack unbalanced'
    assert c.tr <= {0, 1, 2, 3, 15} and c.tf <= set(range(8)), (c.tr, c.tf)
    return R(0xFFFFAC4B, 1)[0]

def run(calls, *w, **kw):
    out = []
    for _ in range(calls): inputs(*w, **kw); out.append(tick())
    return out

tables(); reset()
f = run(200, 50, 50, 50, 50); check('grip, straight (all four 50 km/h) -> no cut', sum(f) == 0)
f = run(200, 50, 50, 57.5, 57.5); check('rears 7.5 km/h faster at 50 (allowed 3 + 10% = 8) -> no cut', sum(f) == 0)
f = run(20, 50, 50, 60, 60); check('rears 10 km/h faster at 50 -> cut at once', f[0] == 1 and all(f), f'{sum(f)}/20')
reset(); f = run(20, 50, 50, 70, 50); check('one rear spinning (left), other gripping -> cut (per side)', all(f))
reset(); f = run(20, 50, 50, 50, 70); check('right rear spinning -> cut', all(f))
reset(); f = run(200, 46, 54, 47, 55); check('cornering: outer wheels 8 km/h faster than inner, each side gripping -> no cut', sum(f) == 0)
reset(); f = run(200, 120, 120, 131, 131); check('120 km/h, rears 11 km/h faster (allowed 3 + 12 = 15) -> no cut', sum(f) == 0)
reset(); f = run(20, 120, 120, 140, 140); check('120 km/h, rears 20 km/h faster -> cut', all(f))
# hold after the slip ends, and the code cap
reset(); run(10, 50, 50, 65, 65); f = run(30, 50, 50, 50, 50)
n_hold = f.index(0) if 0 in f else None
check('slip ends -> cut held for Hold calls (9) then released', n_hold == 9, f'released after {n_hold} calls')
tables(hold=200); reset(); run(5, 50, 50, 65, 65); check('Hold table 200 capped at 60 in code', R(0xFFFFAC49, 1)[0] == 60)
tables()
# conditions
for name, kw, tb in [('clutch down', dict(clutch=1), {}), ('brake pressed', dict(brake=1), {}), ('pedal 15% (< 20)', dict(pedal=15.0), {}),
                     ('rpm 1800 (< 2000)', dict(rpm=1800.0), {}), ('Enable 0', {}, dict(en=0.0))]:
    tables(**tb); reset(); f = run(30, 50, 50, 70, 70, **kw); check(f'spin but {name} -> no cut', sum(f) == 0)
tables()
reset(); f = run(30, 3, 3, 15, 15); check('launch: fronts below 5 km/h (sensors read ~0 at walking pace) -> no cut', sum(f) == 0)
reset(); f = run(30, 8, 8, 20, 20); check('just after launch: fronts 8 km/h, rears 20 -> cut', all(f))
reset(); run(10, 50, 50, 50, 50, clutch=1); f = run(40, 50, 50, 70, 70)
check('clutch just released: lockout (20 calls, ~110 ms) then cut', sum(f[:20]) == 0 and all(f[20:]), f'first at {f.index(1) if 1 in f else None}')
reset(); f = run(30, 50, 50, 70, 70, raw=enc(50) + enc(50) + b'\xFF\xFE' + enc(70)); check('a wheel speed invalid (FFFE) -> no cut', sum(f) == 0)
reset(); run(5, 50, 50, 70, 70); f = run(150, 50, 50, 70, 70, frozen=True)
check('wheel data frozen (CAN lost) -> cut stops within ~100 calls', f[-1] == 0 and 1 in f, f'stopped after {f.index(0) if 0 in f else None}')
reset(); inputs(50, 50, 50, 50, pedal=37.5); tick()
check('pedal copy still done underneath (engine-side pedal = real pedal)', abs(b2f(R(A['pedal_out'], 4)) - 37.5) < 1e-4, f'{b2f(R(A["pedal_out"], 4))}')
if nxt == TC.REVMATCH and struct.unpack_from('>f', rom, 0xFE300)[0] > 0:
    reset(); run(30, 60, 60, 60, 60, pedal=0.0, rpm=2200.0); out = []
    for i in range(40):
        inputs(60, 60, 60, 60, clutch=1, brake=1, pedal=0.0, rpm=1500.0); tick(); out.append(b2f(R(A['pedal_out'], 4)))
    check('rev-match still active underneath (clutch + brake -> throttle blip)', max(out) > 5, f'max pedal {max(out):.1f}%')
check("romdrop's RAM never written", all(R(a, b - a) == bytes([0xA5]) * (b - a) for a, b in ROMDROP_RAM))

# ---------- closed loop: 1 s low-grip patch at full throttle in 2nd ----------
def sim(tc, T=1.8):
    tables(en=1.0 if tc else 0.0); reset()
    v, vr, t, peak, cuts = 40.0, 40.0, 0.0, 0.0, 0
    run(40, v, v, vr, vr)                                    # past the clutch lockout
    while t < T:
        inputs(v, v, vr, vr, pedal=100.0, rpm=4000.0); cut = tick(); cuts += cut
        if 0.3 <= t < 1.3:                                   # wet patch: the rears break loose unless the spark is cut
            vr += (-50.0 if cut else 60.0) * DT; vr = max(vr, v); v += 3.0 * DT
        else:                                                # grip: the rears are pulled back to road speed
            vr = max(v, vr - 80.0 * DT); v += (0.0 if cut else 12.0) * DT
        peak = max(peak, vr - v); t += DT
    return peak, cuts, v
s0, s1 = sim(False), sim(True)
print(f'low-grip sim (1 s wet patch, full throttle): TC off -> peak slip {s0[0]:.1f} km/h; TC on -> {s1[0]:.1f} km/h ({s1[1]} cut calls)')
check('TC limits wheelspin in the low-grip sim (to about the allowed slip)', s1[0] < 0.3 * s0[0] and s1[0] < 10, f'{s1[0]:.1f} vs {s0[0]:.1f} km/h')
print('ALL PASS' if ok else 'SOME FAILED')

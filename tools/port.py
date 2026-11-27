"""Port the patches to another NC calibration automatically.

usage:
  python tools/port.py --ref <stock LFJ1EE.bin> --rom <your stock ROM.bin> --cal <your calibration ID>
                       [--clutch 0x...] [--brake 0x...] [--allow-call-rate] [--out <folder>]

What it does (the same steps as docs/porting-with-claude.md, automated):
  1. finds your calibration ID, checks the flash areas the patches use are free and not checksummed
  2. finds every code site the patches hook in YOUR ROM, by masked instruction patterns from the LFJ1EE
     reference (bits that change between software builds are masked), and checks each site's shape
  3. finds every RAM / table address by "voting": each place the LFJ1EE code uses an address is located in your
     ROM and votes for the address used there; values that can be read straight from a hook site are taken
     from the site and must agree with the vote
  4. stops if anything is missing, ambiguous or below the confidence threshold - it never guesses
  5. writes patches/<cal>/addresses.json, builds <cal>_igncut.patch and <cal>_downshift_revmatch.patch,
     writes ncflash/<cal>_custom_tables.xml, applies both patches to a copy of your ROM, runs both emulators,
     and writes PORT_REPORT.md
What it cannot do: confirm on your car that the clutch / brake addresses are right (do the RAM check in
docs/porting-with-claude.md step 5), or know your gearing (set the RPM-per-km/h table). The report says so.
"""
import argparse, collections, datetime, json, os, re, shutil, struct, subprocess, sys, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..'))


def _load(name):
    s = importlib.util.spec_from_file_location(name, os.path.join(REPO, 'scripts', name + '.py'))
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


AD = _load('addrs')
REF = AD.LFJ1EE
u16 = lambda b, a: struct.unpack_from('>H', b, a)[0]
u32 = lambda b, a: struct.unpack_from('>I', b, a)[0]

VOTE_KEYS = ('rpm', 'speed', 'pedal_in', 'pedal_out', 'clutch', 'brake', 'dwell_flag', 'spark_term', 'cruise_flag',
             'fuel_cut_rpm', 'factory_short_dwell', 'ect', 'dfco_mult', 'spark2_term')
SITE_KEYS = {'spark_site': 0x4DAE8, 'crosscheck_load': 0xB5FF0, 'fuelcut_load': 0x41432}
WINDOWS = [(16, 16), (12, 12), (8, 12), (12, 8), (8, 8), (6, 6), (4, 8), (8, 4), (4, 4),
           (0, 16), (0, 12), (0, 8), (16, 1), (12, 1), (8, 1)]          # centred, then starting / ending at the site
MIN_SHARE, MIN_AGREE = 0.75, 2
PATCH_AREAS = [(0xFE000, 0xFE300), (0xFE300, 0xFE800)]


# ---------------------------------------------------------------- masked pattern search
def mask_of(w):
    if w >> 12 in (0xD, 0x9) or w >> 8 in (0xC7, 0x89, 0x8B, 0x8D, 0x8F): return 0xFF00
    if w >> 12 in (0xA, 0xB): return 0xF000
    return 0xFFFF


def search(tgt, pat):
    best, cur = (0, 0), 0
    for i, (w, m) in enumerate(pat):
        cur = cur + 1 if m == 0xFFFF else 0
        if cur > best[1]: best = (i - cur + 1, cur)
    k0, kn = best
    if kn < 2: return None
    key = b''.join(struct.pack('>H', w) for w, _ in pat[k0:k0 + kn])
    hits, pos = [], tgt.find(key)
    while pos >= 0:
        s = pos - 2 * k0
        if pos % 2 == 0 and s >= 0 and s + 2 * len(pat) <= len(tgt) and \
                all((u16(tgt, s + 2 * i) & m) == (w & m) for i, (w, m) in enumerate(pat)):
            hits.append(s)
        pos = tgt.find(key, pos + 1)
    return hits


def map_addr(ref, tgt, addr):
    """address in tgt of the code at ref addr: first window giving exactly one match"""
    for b, a in WINDOWS:
        start = addr - 2 * b
        if start < 0: continue
        pat = [(u16(ref, start + 2 * i), mask_of(u16(ref, start + 2 * i))) for i in range(b + a)]
        hits = search(tgt, pat)
        if hits and len(hits) == 1:
            return hits[0] + 2 * b
    return None


def lit_of(rom, pc):
    w = u16(rom, pc)
    if w >> 12 != 0xD: return None, None
    la = (pc & ~3) + 4 + (w & 0xFF) * 4
    return la, u32(rom, la)


def users(rom, value, limit=40):
    pat = struct.pack('>I', value); out, i = [], rom.find(pat)
    while i >= 0 and len(out) < limit:
        if i % 4 == 0:
            for pc in range(max(0, i - 1020), i, 2):
                w = u16(rom, pc)
                if w >> 12 == 0xD and (pc & ~3) + 4 + (w & 0xFF) * 4 == i: out.append(pc)
        i = rom.find(pat, i + 1)
    return out[:limit]


# ---------------------------------------------------------------- the port
class Fail(Exception):
    pass


def vote(ref, tgt, value):
    tally, mapped = collections.Counter(), 0
    for u in users(ref, value):
        t = map_addr(ref, tgt, u)
        if t is None or u16(tgt, t) >> 8 != u16(ref, u) >> 8: continue
        la, v = lit_of(tgt, t)
        if la is None: continue
        mapped += 1; tally[v] += 1
    best = tally.most_common(1)
    return (best[0][0], best[0][1], mapped) if best else (None, 0, mapped)


def find_id(tgt, cal):
    c = cal.encode(); hits, i = [], tgt.find(c)
    while i >= 0: hits.append(i); i = tgt.find(c, i + 1)
    if not hits: raise Fail(f'calibration ID {cal} not found in the ROM - is it the right file / ID?')
    paired = [h for h in hits if h - 0x46 in hits]                   # LFJ1EE-style: ID at X and X+0x46
    if len(hits) == 1: return hits[0]
    if len(paired) == 1: return paired[0]
    raise Fail(f'calibration ID found at several places ({", ".join(hex(h) for h in hits)}) - cannot tell which one is checked')


def find_pedal_copy(tgt, pout):
    """tiny routines that copy a float into the engine-side pedal (whatever their exact shape) -> [(pc, source)]"""
    found = []
    for pc in range(0, len(tgt) - 10, 2):
        w = [u16(tgt, pc + 2 * i) for i in range(5)]
        if w[3] != 0x000B: continue
        movs = [i for i in range(3) if w[i] >> 12 == 0xD]
        if len(movs) != 2: continue
        lits = {i: lit_of(tgt, pc + 2 * i)[1] for i in movs}
        regs = {i: (w[i] >> 8) & 15 for i in movs}
        load = [i for i in range(3) if w[i] & 0xF00F == 0xF008]           # fmov.s @Rm,FRn
        if len(load) != 1: continue
        lw, sw = w[load[0]], w[4]
        if sw & 0xF00F != 0xF00A: continue                                 # fmov.s FRm,@Rn (delay slot)
        src_reg, frn = (lw >> 4) & 15, (lw >> 8) & 15
        dst_reg, frm = (sw >> 8) & 15, (sw >> 4) & 15
        if frn != frm: continue
        src = [lits[i] for i in movs if regs[i] == src_reg and i < load[0]]
        dst = [lits[i] for i in movs if regs[i] == dst_reg]
        if len(src) == 1 and dst == [pout] and src[0] >> 16 == 0xFFFF:
            found.append((pc, src[0]))
    return found


# pedal copy with a factory override (LF9WEB and ~50 other calibrations): if calibration byte != 0 and a switch reads 0,
# the engine-side pedal is forced to a calibration constant; otherwise it is a plain copy. (word, mask); FF00 = mov.l literal
OVERRIDE_SHAPE = [(0x4F22, 0xFFFF), (0xD100, 0xFF00), (0x6310, 0xFFFF), (0x2338, 0xFFFF), (0x8D0D, 0xFFFF), (0x0009, 0xFFFF),
                  (0xD400, 0xFF00), (0xD300, 0xFF00), (0x430B, 0xFFFF), (0x0009, 0xFFFF), (0x600C, 0xFFFF), (0x2008, 0xFFFF),
                  (0x8F05, 0xFFFF), (0x0009, 0xFFFF), (0xD300, 0xFF00), (0xD200, 0xFF00), (0xF338, 0xFFFF), (0xA004, 0xFFFF),
                  (0xF23A, 0xFFFF), (0xD100, 0xFF00), (0xF318, 0xFFFF), (0xD000, 0xFF00), (0xF03A, 0xFFFF), (0x4F26, 0xFFFF),
                  (0x000B, 0xFFFF), (0x0009, 0xFFFF)]


def find_pedal_override(tgt, pout):
    """pedal-copy routines with the factory override -> [(pc, source, override_byte_addr)]"""
    found, i = [], tgt.find(b'\x4F\x22')
    while i >= 0:
        if i % 2 == 0 and i + 2 * len(OVERRIDE_SHAPE) <= len(tgt) and \
                all(u16(tgt, i + 2 * k) & m == v for k, (v, m) in enumerate(OVERRIDE_SHAPE)):
            L = lambda k: lit_of(tgt, i + 2 * k)[1]
            ovr, sw, const, d1, src, d2 = L(1), L(6), L(14), L(15), L(19), L(21)
            if d1 == d2 == pout and src >> 16 == 0xFFFF and sw >> 16 == 0xFFFF and ovr < 0x100000 and const < 0x100000:
                found.append((i, src, ovr))
        i = tgt.find(b'\x4F\x22', i + 1)
    return found


OVERRUN_AREA = (0xFF000, 0xFF400)
OVERRUN_RAM = range(0xFFFFACD0, 0xFFFFACE4)
DFCO_MULT_LOAD = 0x4595C          # LFJ1EE: mov.l of the multiplier address into r14, in the DFCO routine


def ram_refs(tgt, addrs):
    """places that reference RAM in addrs (32-bit literals, or mov.w of the low half)"""
    hits = []
    for a in addrs:
        p32 = struct.pack('>I', a); i = tgt.find(p32)
        while i >= 0:
            if i % 4 == 0: hits.append((a, i, '32-bit literal'))
            i = tgt.find(p32, i + 1)
        p16 = struct.pack('>H', a & 0xFFFF); i = tgt.find(p16)
        while i >= 0:
            if i % 2 == 0:
                for pc in range(max(0, i - 512), i, 2):
                    w = u16(tgt, pc)
                    if w >> 12 == 0x9 and pc + 4 + (w & 0xFF) * 2 == i:
                        hits.append((a, pc, 'mov.w')); break
            i = tgt.find(p16, i + 1)
    return hits


def port_overrun(ref, tgt, A, V, cs, log, W):
    """find what the overrun patch needs; fills A, returns None or the reason it can't be built"""
    if A.get('ect') is None:
        v = V['ect']
        return f'coolant temperature: no confident answer ({v["agree"]}/{v["mapped"]} references agree)'
    a, b = OVERRUN_AREA
    if not all(x == 0xFF for x in tgt[a:b]): return f'flash 0x{a:05X}-0x{b - 1:05X} is not empty'
    if cs and any(s <= b - 1 and e >= a for s, e in cs): return 'its flash area is covered by the ROM checksum table'
    # a second term of the same spark-advance sum the ignition cut hooks: mov.l lit,r3 ; fadd fr0,fr2 ; mov.l ..,r2 ;
    # fmov @r3,fr3, then fr3 is added into the running sum (fadd fr3,fr2) a few instructions later. Which term it is
    # does not matter (they are all added together); its literal must not be shared with other code.
    s2 = None
    for c in range(A['spark_site'] + 8, A['spark_site'] + 0x40, 2):
        w = [u16(tgt, c + 2 * i) for i in range(4)]
        if w[0] >> 8 == 0xD3 and w[1] == 0xF200 and w[2] >> 8 == 0xD2 and w[3] == 0xF338 and \
                0xF230 in [u16(tgt, c + 8 + 2 * i) for i in range(6)]:
            s2 = c; break
    if s2 is None: return 'no second spark-advance term with the expected shape after the ignition-cut spark site'
    la, val = lit_of(tgt, s2)
    if val >> 16 != 0xFFFF: return f'spark term at 0x{s2:05X} is not a RAM value'
    if len([u for u in users(tgt, val) if lit_of(tgt, u)[0] == la]) != 1:
        return 'the spark term literal is shared with other code'
    A['spark2_term'] = val; V['spark2_term']['source'] = 'site (a term of the spark-advance sum)'
    A['spark2_site'] = s2; A['spark2_orig'] = tgt[s2:s2 + 8].hex().upper()
    d = map_addr(ref, tgt, REF['dfco_routine'])
    if d is None: return 'decel fuel-cut (DFCO) routine not found'
    if u16(tgt, d - 4) != 0x000B and u16(tgt, d - 2) != 0x000B:
        return f'DFCO routine at 0x{d:05X} does not start after a return'
    ml = d + (DFCO_MULT_LOAD - REF['dfco_routine'])
    if not (u16(tgt, ml) >> 8 == 0xDE and lit_of(tgt, ml)[1] >> 16 == 0xFFFF):
        return f'DFCO routine at 0x{d:05X}: the multiplier load is not where expected'
    mult = lit_of(tgt, ml)[1]; v = V['dfco_mult']
    if v['value'] is not None and v['value'] != mult and v['agree'] > 1:
        return f'DFCO routine uses multiplier 0x{mult:08X} but {v["agree"]}/{v["mapped"]} references say 0x{v["value"]:08X}'
    A['dfco_mult'] = mult; v['source'] = 'site'
    lits = [x for x in range(0, len(tgt), 4) if u32(tgt, x) == d]
    if len(lits) != 1: return f'the DFCO routine is called from {len(lits)} task literals (LFJ1EE has 1)'
    A['dfco_routine'], A['dfco_lit'] = d, lits[0]
    hits = ram_refs(tgt, OVERRUN_RAM)
    if any(k == '32-bit literal' for _, _, k in hits):
        return 'its RAM 0xFFFFACD0-E3 is used by the factory code (32-bit literal)'
    if hits:
        W.append('overrun RAM 0xFFFFACD0-E3 looks referenced at: ' + ', '.join(f'0x{x:08X} by {k} at 0x{p:05X}' for x, p, k in hits) +
                 ' - check with tools/dis.py whether that is real code (data tables can look like mov.w).')
    log(f'overrun: DFCO routine 0x{d:05X} (task literal 0x{lits[0]:05X}), multiplier 0x{A["dfco_mult"]:08X}, '
        f'spark term 2 at 0x{s2:05X}, coolant 0x{A["ect"]:08X}')
    return None


def checksum_cover(tgt, at=0xFF650):
    ents = []
    for k in range(64):
        s, e, _ = struct.unpack_from('>III', tgt, at + 12 * k)
        if not (s < e < 0x100000): break
        ents.append((s, e))
    return ents


def port(ref, tgt, cal, args, log):
    W = []                                                   # warnings for the report
    A = {'cal': cal}
    state = getattr(args, 'state', None)                     # lets run_port see how far a failed port got
    if state is not None: state.update(A=A, W=W)
    # ---- step 2: ID, free flash, checksum coverage
    A['id_offset'] = find_id(tgt, cal)
    log(f'calibration ID {cal} at 0x{A["id_offset"]:X}')
    gb = AD.gearbox(tgt)
    if gb is None:
        raise Fail('could not identify the gearbox (no MX-5 NC gear-ratio table found) - the patches are only for NC '
                   'manual gearboxes, and this may not be an MX-5 NC calibration')
    if not gb['manual']:
        raise Fail(f'this is an AUTOMATIC calibration ({gb["name"]}, 1st gear {gb["ratios"][0]:.3f}) - '
                   'the patches are only for manual gearboxes')
    A['gearbox'] = gb['type']
    log(f'gearbox: {gb["name"]} (ratios {", ".join(f"{r:.3f}" for r in gb["ratios"])}, final drive {gb["final"]:.2f})')
    for a, b in PATCH_AREAS:
        if not all(x == 0xFF for x in tgt[a:b]):
            raise Fail(f'flash 0x{a:05X}-0x{b - 1:05X} is not empty in this ROM - the patches cannot be placed there')
    cs = checksum_cover(tgt)
    if not cs:
        W.append('no checksum table recognised at 0xFF650 - could not confirm the patch areas are unchecksummed')
    elif any(s <= b - 1 and e >= a for s, e in cs for a, b in PATCH_AREAS):
        raise Fail('the patch areas are covered by the ROM checksum table - the patches cannot be placed there')
    log('patch flash areas free and not checksummed')
    # ---- step 4 (first): votes, needed to recognise some sites
    V = {}
    for k in VOTE_KEYS:
        v, agree, mapped = vote(ref, tgt, REF[k])
        V[k] = {'value': v, 'agree': agree, 'mapped': mapped}
    if state is not None: state['V'] = V
    # ---- step 3: code sites
    S = {k: map_addr(ref, tgt, a) for k, a in SITE_KEYS.items()}
    # dwell site: located from the load of the factory short dwell (it sits 0x12 bytes after the site start)
    dwell_cands = []
    sd = V['factory_short_dwell']['value']
    if sd is not None:
        for pc in users(tgt, sd):
            site = pc - 0x12
            cand = {'dwell_site': site, 'dwell_orig': tgt[site:site + 26].hex().upper()}
            try:
                info = AD.dwell_info(cand)
            except AssertionError:
                continue
            dwell_cands.append((site, info))
    m = map_addr(ref, tgt, REF['dwell_site'])
    if m is not None and m not in [c[0] for c in dwell_cands]:
        try:
            dwell_cands.append((m, AD.dwell_info({'dwell_site': m, 'dwell_orig': tgt[m:m + 26].hex().upper()})))
        except AssertionError:
            pass
    if len(dwell_cands) != 1:
        raise Fail(f'factory short-dwell test: {len(dwell_cands)} candidates (need exactly 1)')
    A['dwell_site'], dinfo = dwell_cands[0]
    A['dwell_orig'] = tgt[A['dwell_site']:A['dwell_site'] + 26].hex().upper()
    A['dwell_flag'] = u32(tgt, dinfo['flag_lit'])
    A['factory_short_dwell'] = u32(tgt, dinfo['dwell_lit'])
    log(f'dwell test at 0x{A["dwell_site"]:05X}')
    if S['spark_site'] is None: raise Fail('spark-advance sum load not found')
    A['spark_site'] = S['spark_site']; A['spark_orig'] = tgt[A['spark_site']:A['spark_site'] + 8].hex().upper()
    try:
        sinfo = AD.spark_info(A)
    except AssertionError:
        raise Fail(f'spark site at 0x{A["spark_site"]:05X} does not have the expected shape')
    A['spark_term'] = u32(tgt, sinfo['term_lit'])
    log(f'spark-advance load at 0x{A["spark_site"]:05X}')
    if S['crosscheck_load'] is None: raise Fail('throttle cross-check selector not found')
    A['crosscheck_lit'], A['cruise_flag'] = lit_of(tgt, S['crosscheck_load'])
    if A['crosscheck_lit'] is None: raise Fail('cross-check site is not a mov.l')
    if S['fuelcut_load'] is None: raise Fail('factory fuel-cut routine not found')
    _, A['fuel_cut_rpm'] = lit_of(tgt, S['fuelcut_load'])
    log(f'cross-check literal 0x{A["crosscheck_lit"]:05X}, fuel-cut load 0x{S["fuelcut_load"]:05X}')
    # site values must agree with the votes where the vote has an answer
    for k in ('dwell_flag', 'factory_short_dwell', 'spark_term', 'cruise_flag', 'fuel_cut_rpm'):
        v = V[k]
        if v['value'] is not None and v['value'] != A[k] and v['agree'] > 1:
            raise Fail(f'{k}: the hook site says 0x{A[k]:X} but {v["agree"]}/{v["mapped"]} references say 0x{v["value"]:X}')
        V[k]['source'] = 'site'
    # voted-only values
    for k in ('rpm', 'speed', 'pedal_in', 'pedal_out', 'clutch', 'brake'):
        v = V[k]
        if v['value'] is None or v['agree'] < MIN_AGREE or v['agree'] < MIN_SHARE * v['mapped']:
            raise Fail(f'{k}: no confident answer ({v["agree"]}/{v["mapped"]} references agree)')
        A[k] = v['value']; v['source'] = 'vote'
    for k, opt in (('clutch', args.clutch), ('brake', args.brake)):
        if opt:
            A[k] = int(opt, 16); V[k]['source'] = 'given on the command line'
    # pedal copy by behaviour + task literals
    # pedal copy (only rev-match needs it): the tiny routine the task lists call to write the engine-side pedal
    A['rev_problem'] = None
    pcs = [(pc, src, None, 10) for pc, src in find_pedal_copy(tgt, A['pedal_out'])]
    pcs += [(pc, src, ovr, 2 * len(OVERRIDE_SHAPE)) for pc, src, ovr in find_pedal_override(tgt, A['pedal_out'])]
    called = lambda pc: [x for x in range(0, len(tgt), 4) if u32(tgt, x) == pc]
    pcs = [c for c in pcs if called(c[0])]
    if len(pcs) != 1:
        A['rev_problem'] = (f'{len(pcs)} task-list routines write the engine-side pedal (LFJ1EE has 1): this software drives '
                            f'the throttle differently, so rev-match needs a manual port')
        A['pedal_copy'] = None; A['pedal_copy_orig'] = None; A['task_literals'] = []
        log('pedal copy: ' + A['rev_problem'])
    else:
        A['pedal_copy'], src, ovr, n = pcs[0]
        A['pedal_copy_orig'] = tgt[A['pedal_copy']:A['pedal_copy'] + n].hex().upper()
        A['task_literals'] = called(A['pedal_copy'])
        if ovr is not None:
            A['pedal_override'] = ovr
            W.append(f'the pedal copy has a factory pedal override, switched on by calibration byte 0x{ovr:05X} '
                     f'(currently {tgt[ovr]}). Rev-match only runs while that byte is 0; when it is not 0 the factory routine '
                     f'runs unchanged.' + (' It is NOT 0 in this ROM, so rev-match will do nothing until it is.' if tgt[ovr] else ''))
            log(f'pedal copy has a factory override (byte 0x{ovr:05X} = {tgt[ovr]})')
        if src != A['pedal_in']:
            # extra stage between sensor and engine-side pedal: rev-match takes over the copy, so it reads what the copy
            # reads; the ignition cut keeps reading the sensor value for its flat-shift pedal check
            W.append(f'the pedal copy reads 0x{src:08X}, not the pedal sensor 0x{A["pedal_in"]:08X}: this software has an extra '
                     f'stage in between. Rev-match uses 0x{src:08X}; the flat-shift check uses the sensor value.')
            A['igncut_pedal'] = A['pedal_in']; A['pedal_in'] = src
        log(f'pedal copy at 0x{A["pedal_copy"]:05X}, task-list literals {[hex(x) for x in A["task_literals"]]}')
    # rev-match RAM free?
    ram_hits = []
    for a in list(range(0xFFFFAC10, 0xFFFFAC18)) + list(range(0xFFFFAC50, 0xFFFFAC5A)):   # main state, switch + delay
        p32 = struct.pack('>I', a); i = tgt.find(p32)
        while i >= 0:
            if i % 4 == 0: ram_hits.append((a, i, '32-bit literal'))
            i = tgt.find(p32, i + 1)
        p16 = struct.pack('>H', a & 0xFFFF); i = tgt.find(p16)
        while i >= 0:
            if i % 2 == 0:
                for pc in range(max(0, i - 512), i, 2):
                    w = u16(tgt, pc)
                    if w >> 12 == 0x9 and pc + 4 + (w & 0xFF) * 2 == i:
                        ram_hits.append((a, pc, 'mov.w')); break
            i = tgt.find(p16, i + 1)
    A['gears'] = AD.gears_from_rom(gb)
    # coolant temperature (overheat protection in the ignition cut, and overrun): optional
    v = V['ect']
    if v['value'] is not None and v['agree'] >= MIN_AGREE and v['agree'] >= MIN_SHARE * v['mapped']:
        A['ect'] = v['value']; v['source'] = 'vote'
    else:
        A['ect'] = None
        W.append(f'coolant temperature not found confidently ({v["agree"]}/{v["mapped"]} references agree): the '
                 'ignition cut is built without overheat protection.')
    # overrun crackle (optional: the other patches are built even if this is not possible)
    A['overrun_problem'] = port_overrun(ref, tgt, A, V, cs, log, W)
    if A['overrun_problem']:
        for k in ('dfco_routine', 'dfco_lit', 'dfco_mult', 'spark2_site', 'spark2_orig', 'spark2_term'):
            A[k] = None
        log('overrun: not built - ' + A['overrun_problem'])
    A['verified_on_car'] = False
    return A, V, W, ram_hits


def changed_ranges(a, b):
    out, st = [], None
    for i in range(len(a)):
        if a[i] != b[i]:
            if st is None or i > pv + 8:
                if st is not None: out.append((st, pv))
                st = i
            pv = i
    if st is not None: out.append((st, pv))
    return out


def run_test(test, rom_path, addresses_json):
    """run one emulator (tests/<test>) in this process -> (last line, [FAIL lines])"""
    import runpy, io, contextlib
    buf = io.StringIO(); old_argv, old_env = sys.argv, os.environ.get('NC_ADDRESSES')
    sys.argv = [test, rom_path]; os.environ['NC_ADDRESSES'] = addresses_json
    try:
        with contextlib.redirect_stdout(buf):
            runpy.run_path(os.path.join(REPO, 'tests', test), run_name='__main__')
    except SystemExit:
        pass
    except Exception as e:                                   # an emulator crash counts as a failure
        buf.write(f'\nERROR: {type(e).__name__}: {e}')
    finally:
        sys.argv = old_argv
        if old_env is None: os.environ.pop('NC_ADDRESSES', None)
        else: os.environ['NC_ADDRESSES'] = old_env
    lines = buf.getvalue().strip().splitlines() or ['no output']
    return lines[-1], [l for l in lines if l.startswith('FAIL') or l.startswith('ERROR')]


def run_port(ref_path, rom_path, cal, out=None, clutch=None, brake=None, allow_call_rate=False, defs_path=None, log=print):
    """Port the patches to `cal`. Returns a dict: ok, error, out, report, patches, defs, warnings, log (+ what was found,
    for issue_report())."""
    cal = cal.upper()
    lines, _out = [], log
    def L(msg):
        lines.append(str(msg)); _out(msg)
    state = {}
    fail = lambda e: {'ok': False, 'error': e, 'report': None, 'cal': cal, 'log': lines, 'A': state.get('A'),
                      'V': state.get('V'), 'warnings': state.get('W') or []}
    ref = open(ref_path, 'rb').read(); tgt = open(rom_path, 'rb').read()
    if len(ref) != 0x100000 or len(tgt) != 0x100000: return fail('both ROMs must be 1 MB')
    if not AD.is_cal(ref, REF): return fail('the reference is not an LFJ1EE ROM')
    if ref[REF['dwell_site']:REF['dwell_site'] + 26].hex().upper() != REF['dwell_orig']:
        return fail('the reference must be a STOCK LFJ1EE ROM (it has been patched)')
    out = out or os.path.join(REPO, 'patches', cal.lower())
    args = argparse.Namespace(clutch=clutch, brake=brake, allow_call_rate=allow_call_rate, out=out, state=state)
    log = L
    try:
        A, V, W, ram_hits = port(ref, tgt, cal, args, log)
    except Fail as e:
        return fail(str(e))
    build_rev = True
    if A.get('rev_problem'):
        W.append('Rev-match NOT built: ' + A['rev_problem'] + '.'); build_rev = False
    elif len(A['task_literals']) != 2:
        msg = (f'the pedal copy is called from {len(A["task_literals"])} task list(s), not 2 as on LFJ1EE: it runs at a '
               f'different rate, so rev-match timings (hold time, damping - counted in calls) would be wrong.')
        if allow_call_rate:
            W.append(msg + ' Built anyway (allow call rate): measure the call rate before using rev-match.')
        else:
            W.append(msg + ' Rev-match NOT built (allow a different call rate only if you will measure and retune).'); build_rev = False
    if ram_hits and build_rev:
        hard = [h for h in ram_hits if h[2] == '32-bit literal']
        W.append('rev-match RAM 0xFFFFAC10-17 / AC50-59 appears to be referenced at: ' +
                 ', '.join(f'0x{a:08X} by {k} at 0x{p:05X}' for a, p, k in ram_hits) +
                 ' - check with tools/dis.py whether that is real code (data tables can look like mov.w).')
        if hard:
            W.append('Rev-match NOT built: a 32-bit literal reference to its RAM was found.'); build_rev = False
    W.append(('The clutch and brake addresses come' if build_rev else 'The clutch address (used by launch control and flat shift) comes')
             + ' from code similarity: CONFIRM on the car with RAM snapshots before relying on ' + ('them.' if build_rev else 'it.'))
    if build_rev:
        gbname = {c: n for c, n, _ in AD.GEARBOXES.values()}.get(A.get('gearbox'), 'gearbox')
        W.append(f'rev-match gearing (RPM per km/h) was calculated from this ROM\'s {gbname} ratios and final drive '
                 f'({", ".join(f"{k:g}" for k in A["gears"])}) assuming stock tyre size - check it against a datalog '
                 '(docs/rev-match.md) if you run different tyres.')
    build_ov = not A.get('overrun_problem')
    if not build_ov:
        W.append('Overrun crackle NOT built: ' + A['overrun_problem'] + '.')
    else:
        W.append('overrun crackle: its duration is counted in calls of the decel fuel-cut task, assumed 90 per second '
                 '(table "Overrun - Task calls per second"). Time a burst on the car and correct that table if it is off.')
    # ---- write addresses + build
    os.makedirs(out, exist_ok=True)
    A.pop('rev_problem', None); A.pop('overrun_problem', None)
    addr_json = os.path.join(out, 'addresses.json')
    open(addr_json, 'w', encoding='utf-8').write(AD.to_json(A))
    IG = _load('build_igncut'); RV = _load('build_revmatch'); OV = _load('build_overrun')
    tmp = os.path.join(out, '_stock.bin'); open(tmp, 'wb').write(tgt)
    try:
        pi = IG.build(tmp, out, A=A)
        pr = RV.build(tmp, out, A=A) if build_rev else None
        po = OV.build(tmp, out, A=A) if build_ov else None
    finally:
        os.remove(tmp)
    defs_src = os.path.join(REPO, 'ncflash', 'lfj1ee_custom_tables.xml')
    defs = defs_path or os.path.join(out, f'{cal.lower()}_custom_tables.xml')
    txt = open(defs_src, encoding='utf-8').read().replace('(NC Flash / EcuFlash metadata format, LFJ1EE)', f'(NC Flash / EcuFlash metadata format, {cal})')
    if not build_rev:
        txt = '\n'.join(l for l in txt.splitlines() if 'DBW - ' not in l)
    if not build_ov:
        txt = '\n'.join(l for l in txt.splitlines() if 'Overrun - ' not in l)
    open(defs, 'w', encoding='utf-8').write(txt)
    # ---- apply to a copy and emulate (in this process)
    patched = bytearray(tgt)
    for pth in [pi] + ([pr] if pr else []) + ([po] if po else []):
        d = open(pth, 'rb').read()
        for i in range(6, len(patched)): patched[i] ^= d[i]
    test_rom = os.path.join(out, '_patched_for_tests.bin'); open(test_rom, 'wb').write(patched)
    results = {}
    try:
        for t in ['igncut_emu.py'] + (['revemu.py'] if pr else []) + (['overrun_emu.py'] if po else []):
            results[t] = run_test(t, test_rom, addr_json)
            log(f'{t}: {results[t][0]}')
    finally:
        os.remove(test_rom)
    rng = changed_ranges(tgt, patched)
    ok = all(v[0] == 'ALL PASS' for v in results.values())
    # ---- report
    R = [f'# Port report: {cal}', '', f'Generated {datetime.date.today()} from a stock {cal} ROM and the stock LFJ1EE reference.',
         '', f'**Emulators: {"ALL PASS" if ok else "FAILED - do not flash"}.** **Not tested on a car.**', '',
         '## Built', f'- `{os.path.basename(pi)}` - ignition-cut limiter, launch control, flat-foot shift']
    R.append(f'- `{os.path.basename(pr)}` - rev-match, upshift hold, anti-stall' if pr else '- rev-match: **not built** (see warnings)')
    R.append(f'- `{os.path.basename(po)}` - timed overrun crackle' if po else '- overrun crackle: **not built** (see warnings)')
    R += [f'- `addresses.json` - the addresses below; `{os.path.basename(defs)}` - NC Flash / EcuFlash table definitions', '',
          '## Warnings and what you still have to do'] + [f'- {w}' for w in W]
    R += ['', '## Addresses', '| Name | LFJ1EE | ' + cal + ' | How found |', '|---|---|---|---|']
    for k in ('rpm', 'speed', 'pedal_in', 'pedal_out', 'clutch', 'brake', 'dwell_flag', 'spark_term', 'cruise_flag',
              'fuel_cut_rpm', 'factory_short_dwell'):
        v = V[k]; how = v.get('source', 'vote')
        how = f'{how}; {v["agree"]}/{v["mapped"]} references agree' if v['mapped'] else how
        R.append(f'| {k} | `0x{REF[k]:X}` | `0x{A[k]:X}` | {how} |')
    for k in ('ect', 'dfco_mult', 'spark2_term'):
        if A.get(k) is not None:
            v = V[k]; src = v.get('source', 'vote')
            how = f'{src}; {v["agree"]}/{v["mapped"]} references agree' if src in ('vote', 'site') else src
            R.append(f'| {k} | `0x{REF[k]:X}` | `0x{A[k]:X}` | {how} |')
    for k in ('dwell_site', 'spark_site', 'pedal_copy', 'crosscheck_lit', 'spark2_site', 'dfco_routine', 'dfco_lit'):
        R.append(f'| {k} | `0x{REF[k]:X}` | ' + (f'`0x{A[k]:X}`' if A.get(k) is not None else 'not found') + ' | code site |')
    if A.get('pedal_override') is not None:
        R.append(f'| pedal_override | - | `0x{A["pedal_override"]:X}` | calibration byte of the factory pedal override in the pedal copy |')
    if A.get('igncut_pedal'):
        R.append(f'| pedal for the flat-shift check | `0x{REF["pedal_in"]:X}` | `0x{A["igncut_pedal"]:X}` | vote (pedal sensor) |')
    R.append(f'| task_literals | {", ".join(f"`0x{x:X}`" for x in REF["task_literals"])} | {", ".join(f"`0x{x:X}`" for x in A["task_literals"])} | literals pointing to the pedal copy |')
    R.append(f'| id_offset | `0x{REF["id_offset"]:X}` | `0x{A["id_offset"]:X}` | calibration ID string |')
    R += ['', '## Bytes the patches change', ', '.join(f'`{a:05X}-{b:05X}`' for a, b in rng),
          '', '## Emulator output'] + [f'- `{t}`: {v[0]}' + (f' - failures: {v[1]}' if v[1] else '') for t, v in results.items()]
    steps = ['Confirm the ' + ('clutch and brake addresses' if pr else 'clutch address') + ' on the car (RAM snapshots).']
    if pr: steps.append('Set your gearing in the rev-match RPM-per-km/h table.')
    if po: steps.append('Overrun crackle is off by default: enable it and set Strength in NC Flash (docs/overrun.md).')
    steps += ['Add the table definitions to NC Flash / EcuFlash.', 'Apply the patches to your ROM.',
              'Full Flash, then test one feature at a time with a datalog (docs/ignition-cut.md' + (', docs/rev-match.md' if pr else '') + ').']
    R += ['', '## Next steps'] + [f'{i}. {t}' for i, t in enumerate(steps, 1)]
    report = os.path.join(out, 'PORT_REPORT.md')
    open(report, 'w', encoding='utf-8').write('\n'.join(R) + '\n')
    return {'ok': ok, 'error': None if ok else 'emulator failures - do not flash', 'out': out, 'report': report,
            'patches': [pi] + ([pr] if pr else []) + ([po] if po else []), 'defs': defs, 'warnings': W, 'addresses': addr_json,
            'A': A, 'V': V, 'cal': cal, 'log': lines, 'emulators': {t: v[0] for t, v in results.items()}}


# ---------------------------------------------------------------- problem report for a GitHub issue
ISSUES_URL = 'https://github.com/Eddy0803/nc-mx5-patches/issues/new'
PATCH_NAMES = {'igncut': 'ignition cut', 'downshift_revmatch': 'rev-match', 'overrun': 'overrun'}


def needs_report(r):
    """True when a port stopped, failed its emulator tests, or left a patch out"""
    if not r.get('report') or not r.get('ok'): return True
    built = ' '.join(os.path.basename(p) for p in r.get('patches') or [])
    return any(k not in built for k in PATCH_NAMES)


def _private(text):
    """hide the user's name and home folder in paths"""
    home = os.path.expanduser('~'); user = os.path.basename(home)
    for h in {home, home.replace('\\', '/')}:
        text = re.sub(re.escape(h), '~', text, flags=re.I)
    text = re.sub(r'(?i)([a-z]:[\\/]+users[\\/]+)[^\\/\s]+', r'\1<user>', text)
    if len(user) > 2: text = re.sub(r'(?i)\b' + re.escape(user) + r'\b', '<user>', text)
    return text


def issue_report(r, tool='tools/port.py'):
    """(title, markdown) describing a port that didn't fully work. Contains no ROM bytes, file contents or paths."""
    cal = r.get('cal') or '?'; A = r.get('A') or {}; V = r.get('V') or {}
    gb = {c: n for c, n, _ in AD.GEARBOXES.values()}.get(A.get('gearbox'), 'not identified')
    built = [os.path.basename(p) for p in r.get('patches') or []]
    if not r.get('report'):
        outcome = f'**Stopped:** {r.get("error")}'; title = f'Port to {cal} stopped: {r.get("error")}'
    elif not r.get('ok'):
        outcome = '**Built, but the emulator tests FAILED.**'; title = f'Port to {cal}: emulator tests failed'
    else:
        missing = [n for k, n in PATCH_NAMES.items() if not any(k in b for b in built)]
        outcome = f'**Built, but not every patch:** {", ".join(missing)} not built.'; title = f'Port to {cal}: {", ".join(missing)} not built'
    if len(title) > 120: title = title[:117] + '...'
    out = [f'## Port problem: {cal}', '',
           f'- **Tool:** {tool}', f'- **Calibration:** {cal}', f'- **Gearbox:** {gb}', f'- **Outcome:** {outcome}']
    if built: out.append(f'- **Patches built:** {", ".join(built)}')
    if r.get('emulators'): out.append('- **Emulators:** ' + ', '.join(f'{t}: {v}' for t, v in r['emulators'].items()))
    warn = [w for w in r.get('warnings') or []]
    if warn: out += ['', '### Warnings'] + [f'- {w}' for w in warn]
    rows = []
    for k in ('id_offset', 'rpm', 'speed', 'pedal_in', 'pedal_out', 'clutch', 'brake', 'ect', 'dwell_flag', 'spark_term',
              'cruise_flag', 'fuel_cut_rpm', 'factory_short_dwell', 'dwell_site', 'spark_site', 'pedal_copy', 'crosscheck_lit',
              'pedal_override', 'dfco_routine', 'dfco_mult', 'spark2_site'):
        v = A.get(k); vote = V.get(k)
        how = f'{vote["agree"]}/{vote["mapped"]} references agree' if vote and vote.get('mapped') else ''
        if v is None and not vote: continue
        rows.append(f'| {k} | ' + (f'`0x{v:X}`' if isinstance(v, int) else 'not found') + f' | {how} |')
    if rows: out += ['', '### What was found', '| Item | Address | Votes |', '|---|---|---|'] + rows
    if A.get('task_literals') is not None:
        out.append(f'\nPedal-copy task literals: {len(A["task_literals"])}')
    log = '\n'.join(r.get('log') or [])
    if log: out += ['', '### Port log', '```', log, '```']
    out += ['', '_Generated by NC Patcher / tools/port.py. It contains no ROM data, file contents or paths. Please don\'t attach '
            'your ECU read: it contains data specific to your car._']
    return _private(title), _private('\n'.join(out))


def issue_url(title, body, limit=6500):
    """new-issue link with the title and body filled in (cut short if the browser link would get too long)"""
    from urllib.parse import quote
    note = '\n\n_(Report cut short to fit the link: please drag the saved report file into this issue.)_'
    b = body
    while len(quote(b)) > limit:
        b = b[:int(len(b) * 0.85)]
    if b != body: b += note
    return f'{ISSUES_URL}?title={quote(title)}&body={quote(b)}&labels=port'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--ref', required=True, help='stock LFJ1EE ROM (the reference)')
    ap.add_argument('--rom', required=True, help='your stock ROM')
    ap.add_argument('--cal', required=True, help='your calibration ID, e.g. LFZZE0')
    ap.add_argument('--clutch'); ap.add_argument('--brake')
    ap.add_argument('--allow-call-rate', action='store_true',
                    help='build rev-match even though the pedal copy is not called from exactly 2 task lists')
    ap.add_argument('--out', help='output folder (default patches/<cal>)')
    a = ap.parse_args()
    cal = a.cal.upper()
    defs = None if a.out else os.path.join(REPO, 'ncflash', f'{cal.lower()}_custom_tables.xml')
    r = run_port(a.ref, a.rom, cal, a.out, a.clutch, a.brake, a.allow_call_rate, defs)
    if needs_report(r):
        title, body = issue_report(r)
        rp = os.path.abspath(f'port_problem_{cal.lower()}.md')
        open(rp, 'w', encoding='utf-8').write(f'# {title}\n\n{body}\n')
        print(f'\nA problem report you can post as a GitHub issue (no ROM data in it - read it first): {rp}')
        print(f'Post it at {ISSUES_URL} (paste the report, or drag the file in).')
    if r.get('report') is None:
        print(f'\nSTOPPED: {r["error"]}\nNothing was written. See docs/porting-with-claude.md for doing this step by hand.')
        sys.exit(1)
    print(f'\n{"OK" if r["ok"] else "EMULATOR FAILURES"} - wrote {r["out"]} (PORT_REPORT.md, addresses.json, patches) and {r["defs"]}')
    for w in r['warnings']: print(' !', w)
    sys.exit(0 if r['ok'] else 2)


if __name__ == '__main__':
    main()

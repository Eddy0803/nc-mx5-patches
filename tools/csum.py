"""Verify the LFJ1EE ROM checksum table (0xFF650..): entries (start, end, sum32).
Tries the common algorithms on the stock ROM to identify the right one, then checks each ROM given.
usage: csum.py stock.bin rom2.bin ..."""
import sys, struct

TBL, TEND = 0xFF650, 0xFF7F4

def entries(rom):
    out = []
    for o in range(TBL, TEND, 12):
        s, e, c = struct.unpack_from('>III', rom, o)
        out.append((o, s, e, c))
    return out

def alg_sum32_words(rom, s, e):
    return sum(struct.unpack_from(f'>{(e - s + 1) // 4}I', rom, s)) & 0xFFFFFFFF
def alg_sum_bytes(rom, s, e):
    return sum(rom[s:e + 1]) & 0xFFFFFFFF
def alg_neg_words(rom, s, e):
    return (-alg_sum32_words(rom, s, e)) & 0xFFFFFFFF
def alg_mazda(rom, s, e):
    return (0x5AA5A55A - alg_sum32_words(rom, s, e)) & 0xFFFFFFFF
ALGS = {'0x5AA5A55A - sum32': alg_mazda, 'sum32 of BE words': alg_sum32_words}

stock = open(sys.argv[1], 'rb').read()
ents = entries(stock)
print(f'{len(ents)} entries; first {[(hex(s), hex(e)) for _, s, e, _ in ents[:2]]} ... last {hex(ents[-1][1])}-{hex(ents[-1][2])}')
best = None
for name, fn in ALGS.items():
    ok = sum(fn(stock, s, e) == c for _, s, e, c in ents)
    print(f'  algorithm "{name}": {ok}/{len(ents)} entries match on stock')
    if best is None or ok > best[1]:
        best = (name, ok)
alg = ALGS[best[0]]
print('using:', best[0])

covered = sorted((s, e) for _, s, e, _ in ents)
gaps, pos = [], 0
for s, e in covered:
    if s > pos: gaps.append((pos, s - 1))
    pos = max(pos, e + 1)
if pos < len(stock): gaps.append((pos, len(stock) - 1))
print('NOT covered by checksum:', [f'0x{a:05X}-0x{b:05X}' for a, b in gaps])

for p in sys.argv[2:]:
    rom = open(p, 'rb').read()
    bad = [(o, s, e, c, alg(rom, s, e)) for o, s, e, c in entries(rom) if alg(rom, s, e) != c]
    print(f'== {p.split(chr(92))[-1]}: {len(bad)} bad entries')
    for o, s, e, c, calc in bad:
        print(f'   entry @0x{o:05X} range 0x{s:05X}-0x{e:05X}: stored {c:08X}, actual {calc:08X}')

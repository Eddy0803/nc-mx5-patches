"""gearcal.py rom.bin log.csv [log2.csv...] : ROM gear ratios vs measured RPM-per-km/h from logs (steady cruising, clutch engaged)."""
import sys, struct, csv, statistics
rom = open(sys.argv[1], 'rb').read()
fd = struct.unpack_from('>f', rom, 0xC1358)[0]
g = [struct.unpack_from('>f', rom, 0xC135C + 4 * i)[0] for i in range(6)]
print(f'final drive {fd:.4f}; gears {[round(x, 4) for x in g]}')
print('overall ratio per gear:', [round(x * fd, 3) for x in g])
# measured: histogram of rpm/vss where speed > 15, rpm > 1500, pedal > 5 (driving, clutch engaged)
vals = []
for p in sys.argv[2:]:
    for r in csv.DictReader(open(p, encoding='utf-8-sig')):
        try:
            v, rpm, app = float(r['VSS']), float(r['RPM']), float(r['APP'])
        except (ValueError, KeyError):
            continue
        if v > 15 and rpm > 1500 and app > 5:
            vals.append(rpm / v)
vals.sort()
clusters = []
for x in vals:
    if clusters and abs(x - clusters[-1][-1]) / x < 0.015:
        clusters[-1].append(x)
    else:
        clusters.append([x])
big = [c for c in clusters if len(c) > 40]
print('measured rpm/(km/h) clusters (n>40):', [(round(statistics.median(c), 2), len(c)) for c in big])
# implied factor rpm/kmh / overall ratio  (= 1000/60 / tyre circumference in km ... )
for c in big:
    m = statistics.median(c)
    best = min(range(6), key=lambda i: abs(m / (g[i] * fd) - big[0][0] / (g[0] * fd)) if False else abs(m / (g[i] * fd) - 7.0))
    print(f'  {m:7.2f} rpm/kmh -> factor per gear: ' + ', '.join(f'{i+1}:{m / (g[i] * fd):.3f}' for i in range(6)))

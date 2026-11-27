# Supported calibrations

NC Patcher includes ready-made ports for **85 manual-gearbox calibrations**: drop your stock ECU file into tab 2 and it recognises it, with no porting needed. They were built and emulator-tested from the stock ROMs of every calibration available (113 in total), using the same `tools/port.py` you can run yourself.

**Proven on a car: LFJ1EE only.** Every other calibration is a port: it passes all its emulator tests, but **check the clutch and brake addresses on your car** (NC Patcher tab 1) and test each feature carefully before relying on it. Each folder in `patches/<cal>/` has a `PORT_REPORT.md` with every address, how it was found, and the warnings for that calibration.

| Patches | Calibrations |
|---|---|
| Ignition cut + rev-match + overrun + traction control | 52 |
| Ignition cut + overrun (no rev-match or traction control, see below) | 33 |
| None: automatic gearbox | 28 |

## Manual calibrations

| Calibration | Gearbox | Ignition cut | Rev-match | Overrun | Traction control |
|---|---|---|---|---|---|
| L831ED | 5-speed manual | yes | yes | yes | yes |
| L831EE | 5-speed manual | yes | yes | yes | yes |
| L831EF | 5-speed manual | yes | yes | yes | yes |
| L831EG | 5-speed manual | yes | yes | yes | yes |
| L843EB | 5-speed manual | yes | no | yes | no |
| L843EC | 5-speed manual | yes | no | yes | no |
| L862ED | 5-speed manual | yes | no | yes | no |
| LF4XED | 6-speed manual | yes | yes | yes | yes |
| LF4XEE | 6-speed manual | yes | yes | yes | yes |
| LF4XEG | 6-speed manual | yes | yes | yes | yes |
| LF5AEE | 5-speed manual | yes | yes | yes | yes |
| LF5AEG | 5-speed manual | yes | yes | yes | yes |
| LF5CEG | 6-speed manual | yes | yes | yes | yes |
| LF5DEG | 5-speed manual | yes | yes | yes | yes |
| LF6JE0 | 6-speed manual | yes | yes | yes | yes |
| LF8HED | 6-speed manual | yes | yes | yes | yes |
| LF9HED | 6-speed manual | yes | no | yes | no |
| LF9HEE | 6-speed manual | yes | no | yes | no |
| LF9JED | 5-speed manual | yes | no | yes | no |
| LF9RED | 6-speed manual | yes | no | yes | no |
| LF9SED | 5-speed manual | yes | no | yes | no |
| LF9VEB | 6-speed manual | yes | yes | yes | yes |
| LF9WEB | 5-speed manual | yes | yes | yes | yes |
| LFAAEB | 6-speed manual | yes | yes | yes | yes |
| LFABEB | 5-speed manual | yes | yes | yes | yes |
| LFDJEA | 6-speed manual | yes | yes | yes | yes |
| LFDKEB | 5-speed manual | yes | yes | yes | yes |
| LFDMEA | 6-speed manual | yes | yes | yes | yes |
| LFDNEB | 5-speed manual | yes | yes | yes | yes |
| LFFCED | 6-speed manual | yes | no | yes | no |
| LFFDED | 5-speed manual | yes | no | yes | no |
| LFG2EE | 6-speed manual | yes | yes | yes | yes |
| LFG2EF | 6-speed manual | yes | yes | yes | yes |
| LFG2EG | 6-speed manual | yes | yes | yes | yes |
| LFG2EJ | 6-speed manual | yes | yes | yes | yes |
| LFG2EL | 6-speed manual | yes | yes | yes | yes |
| LFG2EM | 6-speed manual | yes | yes | yes | yes |
| LFG2EP | 6-speed manual | yes | yes | yes | yes |
| LFG3EE | 5-speed manual | yes | yes | yes | yes |
| LFG3EF | 5-speed manual | yes | yes | yes | yes |
| LFG3EG | 5-speed manual | yes | yes | yes | yes |
| LFG3EK | 5-speed manual | yes | yes | yes | yes |
| LFG3EN | 5-speed manual | yes | yes | yes | yes |
| LFG7ED | 6-speed manual | yes | yes | yes | yes |
| LFG7EG | 6-speed manual | yes | yes | yes | yes |
| LFG8EF | 5-speed manual | yes | yes | yes | yes |
| LFG8EG | 5-speed manual | yes | yes | yes | yes |
| LFGJED | 6-speed manual | yes | no | yes | no |
| LFGKEC | 5-speed manual | yes | no | yes | no |
| LFGKED | 5-speed manual | yes | no | yes | no |
| LFGMEC | 6-speed manual | yes | no | yes | no |
| LFGMED | 6-speed manual | yes | no | yes | no |
| LFGMEE | 6-speed manual | yes | no | yes | no |
| LFGNEC | 5-speed manual | yes | no | yes | no |
| LFGNEE | 5-speed manual | yes | no | yes | no |
| LFH9EC | 6-speed manual | yes | yes | yes | yes |
| LFH9ED | 6-speed manual | yes | yes | yes | yes |
| LFH9EE | 6-speed manual | yes | yes | yes | yes |
| LFH9EF | 6-speed manual | yes | yes | yes | yes |
| LFJ1EC | 5-speed manual | yes | yes | yes | yes |
| LFJ1ED | 5-speed manual | yes | yes | yes | yes |
| LFJ1EE (proven on a car) | 5-speed manual | yes | yes | yes | yes (not yet on a car) |
| LFJ1EF | 5-speed manual | yes | yes | yes | yes |
| LFLEEC | 6-speed manual | yes | no | yes | no |
| LFLGEC | 6-speed manual | yes | no | yes | no |
| LFLME0 | 6-speed manual | yes | no | yes | no |
| LFLMEA | 6-speed manual | yes | no | yes | no |
| LFLMEC | 6-speed manual | yes | no | yes | no |
| LFLMED | 6-speed manual | yes | no | yes | no |
| LFLNEC | 5-speed manual | yes | no | yes | no |
| LFLPE0 | 6-speed manual | yes | no | yes | no |
| LFLPEA | 6-speed manual | yes | no | yes | no |
| LFLPEB | 6-speed manual | yes | no | yes | no |
| LFLPEC | 6-speed manual | yes | no | yes | no |
| LFLPED | 6-speed manual | yes | no | yes | no |
| LFLREA | 5-speed manual | yes | no | yes | no |
| LFLVEB | 6-speed manual | yes | no | yes | no |
| LFLWEB | 5-speed manual | yes | no | yes | no |
| LFN4EE | 6-speed manual | yes | yes | yes | yes |
| LFN4EK | 6-speed manual | yes | yes | yes | yes |
| LFN4EP | 6-speed manual | yes | yes | yes | yes |
| LFN5EN | 5-speed manual | yes | yes | yes | yes |
| LFZZE0 | 6-speed manual | yes | yes | yes | yes |
| LFZZEA | 6-speed manual | yes | yes | yes | yes |
| LSYAEA | 6-speed manual | yes | yes | yes | yes |

## Why rev-match isn't included on some

Rev-match works by taking over the one routine that copies the accelerator pedal to the throttle. In 33 calibrations the engine-side pedal is written by two routines (or none of the routines found on LFJ1EE), so taking over one of them would not reliably control the throttle. `port.py` refuses to build rev-match there rather than guess. Ignition cut, launch control, flat shift and overrun crackle are unaffected.

**Traction control** runs from the same task slot as rev-match, so it's available on exactly the same 52 calibrations. On all 52, its RAM (`AC40`–`AC4C`) is free and `tc_emu.py` passes.

## Automatic gearboxes (not supported)

The patches are for manual gearboxes only. NC Patcher refuses these: LF4WEG, LF5BEG, LF9KEC, LF9KEE, LF9TEC, LF9TEE, LF9XEB, LFACEB, LFAKEB, LFDLEC, LFDPEC, LFFEEC, LFFEEE, LFG1EH, LFG1EK, LFG1ER, LFG9EH, LFGLEF, LFGPEF, LFJ5EG, LFLXE0, LFLXEC, LFMAE0, LFMAEB, LFMAEC, LFMSEA, LFN3EG, LFN3ER.

## Notes

- **Gearing:** rev-match's RPM-per-km/h table is calculated from each ROM's own gear ratios and final drive, for stock tyres. LF9HED/EE, LFFCED, LFH9EC-EF, LFLEEC and LFLGEC have a 6-speed with a lower first gear (3.709) and a 3.727 final drive; that is recognised too.
- **Factory pedal override:** some calibrations have a factory override in the pedal-copy routine (switched by a calibration byte that is 0 on all of them). Rev-match is built with a guard: if that byte is ever set, the factory routine runs untouched.
- **RAM warnings in some reports** (a `mov.w` that seems to load one of the patches' RAM addresses) were all checked by hand: they are inside tables of ROM addresses, not code. Each affected report says so.
- **Your own port wins:** if you port a calibration yourself (`tools/port.py`), NC Patcher uses yours instead of the bundled one.

# Supported calibrations

NC Patcher includes ready-made ports for **85 manual-gearbox calibrations**: drop your stock ECU file into tab 2 and it recognises it, with no porting needed. They were built and emulator-tested from the stock ROMs of every calibration available (113 in total), using the same `tools/port.py` you can run yourself.

**Proven on a car: LFJ1EE only.** Every other calibration is a port: it passes all its emulator tests, but **check the clutch and brake addresses on your car** (NC Patcher tab 1) and test each feature carefully before relying on it. Each folder in `patches/<cal>/` has a `PORT_REPORT.md` with every address, how it was found, and the warnings for that calibration.

| Patches | Calibrations |
|---|---|
| Ignition cut + rev-match + overrun + traction control | 81 (29 of them two-path, see below) |
| Ignition cut + overrun (no rev-match or traction control, see below) | 4 |
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
| L862ED | 5-speed manual | yes | yes (two-path) | yes | yes |
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
| LF9HEE | 6-speed manual | yes | yes (two-path) | yes | yes |
| LF9JED | 5-speed manual | yes | no | yes | no |
| LF9RED | 6-speed manual | yes | yes (two-path) | yes | yes |
| LF9SED | 5-speed manual | yes | yes (two-path) | yes | yes |
| LF9VEB | 6-speed manual | yes | yes | yes | yes |
| LF9WEB | 5-speed manual | yes | yes | yes | yes |
| LFAAEB | 6-speed manual | yes | yes | yes | yes |
| LFABEB | 5-speed manual | yes | yes | yes | yes |
| LFDJEA | 6-speed manual | yes | yes | yes | yes |
| LFDKEB | 5-speed manual | yes | yes | yes | yes |
| LFDMEA | 6-speed manual | yes | yes | yes | yes |
| LFDNEB | 5-speed manual | yes | yes | yes | yes |
| LFFCED | 6-speed manual | yes | yes (two-path) | yes | yes |
| LFFDED | 5-speed manual | yes | yes (two-path) | yes | yes |
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
| LFGJED | 6-speed manual | yes | yes (two-path) | yes | yes |
| LFGKEC | 5-speed manual | yes | yes (two-path) | yes | yes |
| LFGKED | 5-speed manual | yes | yes (two-path) | yes | yes |
| LFGMEC | 6-speed manual | yes | yes (two-path) | yes | yes |
| LFGMED | 6-speed manual | yes | yes (two-path) | yes | yes |
| LFGMEE | 6-speed manual | yes | yes (two-path) | yes | yes |
| LFGNEC | 5-speed manual | yes | yes (two-path) | yes | yes |
| LFGNEE | 5-speed manual | yes | yes (two-path) | yes | yes |
| LFH9EC | 6-speed manual | yes | yes | yes | yes |
| LFH9ED | 6-speed manual | yes | yes | yes | yes |
| LFH9EE | 6-speed manual | yes | yes | yes | yes |
| LFH9EF | 6-speed manual | yes | yes | yes | yes |
| LFJ1EC | 5-speed manual | yes | yes | yes | yes |
| LFJ1ED | 5-speed manual | yes | yes | yes | yes |
| LFJ1EE (proven on a car) | 5-speed manual | yes | yes | yes | yes (not yet on a car) |
| LFJ1EF | 5-speed manual | yes | yes | yes | yes |
| LFLEEC | 6-speed manual | yes | yes (two-path) | yes | yes |
| LFLGEC | 6-speed manual | yes | yes (two-path) | yes | yes |
| LFLME0 | 6-speed manual | yes | yes (two-path) | yes | yes |
| LFLMEA | 6-speed manual | yes | yes (two-path) | yes | yes |
| LFLMEC | 6-speed manual | yes | yes (two-path) | yes | yes |
| LFLMED | 6-speed manual | yes | yes (two-path) | yes | yes |
| LFLNEC | 5-speed manual | yes | yes (two-path) | yes | yes |
| LFLPE0 | 6-speed manual | yes | yes (two-path) | yes | yes |
| LFLPEA | 6-speed manual | yes | yes (two-path) | yes | yes |
| LFLPEB | 6-speed manual | yes | yes (two-path) | yes | yes |
| LFLPEC | 6-speed manual | yes | yes (two-path) | yes | yes |
| LFLPED | 6-speed manual | yes | yes (two-path) | yes | yes |
| LFLREA | 5-speed manual | yes | yes (two-path) | yes | yes |
| LFLVEB | 6-speed manual | yes | yes (two-path) | yes | yes |
| LFLWEB | 5-speed manual | yes | yes (two-path) | yes | yes |
| LFN4EE | 6-speed manual | yes | yes | yes | yes |
| LFN4EK | 6-speed manual | yes | yes | yes | yes |
| LFN4EP | 6-speed manual | yes | yes | yes | yes |
| LFN5EN | 5-speed manual | yes | yes | yes | yes |
| LFZZE0 | 6-speed manual | yes | yes | yes | yes |
| LFZZEA | 6-speed manual | yes | yes | yes | yes |
| LSYAEA | 6-speed manual | yes | yes | yes | yes |

## Why rev-match isn't included on some

Rev-match works by taking over the routine that copies the accelerator pedal to the throttle.

**Two-path software (29 calibrations, marked "two-path"; from 0.9.32):** the engine-side pedal is written by two copy routines, one per task list. One copies the pedal stage; the other copies a processed version of it made by extra routines in this newer software. Rev-match and traction control take over both, with a second entry point each (see [rev-match.md](rev-match.md#how-its-built)). Every emulator test passes through both entries on all 29. **This layout isn't proven on a car yet.**

**Not supported (4: L843EB, L843EC, LF9HED, LF9JED):** no routine of the LFJ1EE shape writes the engine-side pedal, so `port.py` refuses to build rev-match there rather than guess. Ignition cut, launch control, flat shift and overrun crackle are unaffected.

**Traction control** runs from the same task slots as rev-match, so it's available on exactly the same 81 calibrations. On all 81, its RAM (`AC40`–`AC4C`) is free and `tc_emu.py` passes.

## Automatic gearboxes (not supported)

The patches are for manual gearboxes only. NC Patcher refuses these: LF4WEG, LF5BEG, LF9KEC, LF9KEE, LF9TEC, LF9TEE, LF9XEB, LFACEB, LFAKEB, LFDLEC, LFDPEC, LFFEEC, LFFEEE, LFG1EH, LFG1EK, LFG1ER, LFG9EH, LFGLEF, LFGPEF, LFJ5EG, LFLXE0, LFLXEC, LFMAE0, LFMAEB, LFMAEC, LFMSEA, LFN3EG, LFN3ER.

## Notes

- **Gearing:** rev-match's RPM-per-km/h table is calculated from each ROM's own gear ratios and final drive, for stock tyres. LF9HED/EE, LFFCED, LFH9EC-EF, LFLEEC and LFLGEC have a 6-speed with a lower first gear (3.709) and a 3.727 final drive; that is recognised too.
- **Factory pedal override:** some calibrations have a factory override in the pedal-copy routine (switched by a calibration byte that is 0 on all of them). Rev-match is built with a guard: if that byte is ever set, the factory routine runs untouched.
- **RAM warnings in some reports** (a `mov.w` that seems to load one of the patches' RAM addresses) were all checked by hand: they are inside tables of ROM addresses, not code. Each affected report says so.
- **Your own port wins:** if you port a calibration yourself (`tools/port.py`), NC Patcher uses yours instead of the bundled one.

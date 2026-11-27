# Spark-cut traction control

**Status: 🧪 emulator-tested, not yet tested on a car.** It passes the emulator tests (`tests/tc_emu.py`), including a closed-loop wheelspin simulation, and it was replayed against 18 LFJ1EE datalogs (below). Test it yourself, carefully, before relying on it.

## What it does
When the rear wheels break loose, engine RPM climbs faster than the car can possibly accelerate in that gear. Traction control (TC) watches for that and, while it's happening, **cuts spark** with the same short-dwell ignition cut and timing retard that the rev limiter and flat shift use. It holds the cut for a short time (~100 ms), then lets go. If the wheels are still spinning, it cuts again.

**It needs the [ignition cut](ignition-cut.md).** The ignition cut's shared cut check also cuts while TC raises its flag. Without the ignition cut, TC can't do anything, so NC Patcher and the installer refuse to install it on its own.

It works alongside every other patch, in any install order, and alongside romdrop (it doesn't use any of romdrop's RAM).

## How it decides
Every task call (~5.5 ms) it does the following:

1. **RPM rise rate.** It keeps a filtered RPM rise per call: `rate += Alpha × (ΔRPM − rate)`. With Alpha 0.1 this is a ~55 ms average, which smooths out RPM noise.
2. **Gear.** While RPM is steady (rising slower than Min Rate), it learns the gear from RPM ÷ speed, ±8%, the same way rev-match does. It doesn't learn while the revs are sweeping (a neutral rev, clutch slip or wheelspin), because a sweep passes through other gears' ratios.
3. **Threshold** = max(RPM per km/h of that gear × Max Accel, Min Rate) × Call Time. With the defaults on a 5-speed:

   | Gear | 1st | 2nd | 3rd | 4th | 5th |
   |---|---|---|---|---|---|
   | Cut above (rpm/s) | 3,414 | 2,500 | 2,500 | 2,500 | 2,500 |
   | Hardest grip pulls in the logs (rpm/s) | ~2,400 | ~1,400 | ~1,000 | ~700 | ~500 |

4. **Cut** when the rate exceeds the threshold and all of these hold:
   - Enable is on;
   - the clutch is up and the lockout has expired;
   - speed ≥ Min Speed;
   - pedal ≥ Min Pedal;
   - RPM ≥ Min RPM;
   - a gear was learned recently (within Max Gear Age calls).

   The cut then holds for Hold calls.

### Always off
- **Clutch down,** and for **Lockout** calls (~0.5 s) after the clutch comes up. This covers launch control, flat-foot shifts, rev-match and the RPM shunt as the clutch bites.
- **Below 10 km/h or 2,000 rpm, or under 40% pedal** (the defaults).
- **In neutral while rolling,** because no gear has been learned recently.
- **Overrun crackle** never overlaps it: the crackle needs a closed pedal, TC needs at least Min Pedal.

## Settings
In NC Patcher (tab 2): **Install / keep**, **Traction control on**, **Max grip accel**, **Only above pedal** and **Only above speed**. Everything is also in NC Flash, under **Traction Control - Spark Cut**:

| Address | Table | Default | Range |
|---|---|---|---|
| `FE380` | TC - Enable | 0 (off) | 0 / 1 |
| `FE384` | Max Accel with grip, km/h per s | 30 (LFJ1EE logs peak at 15–21) | 5–80 |
| `FE3B8` | Min RPM Rise Rate (floor), rpm/s | 2500 | 0–20000 |
| `FE388` | Call Time, s (measured; leave it) | 0.0055 | 0.002–0.02 |
| `FE38C` | Filter Alpha (lower = smoother, slower) | 0.1 | 0.01–1 |
| `FE390` | Min Speed, km/h | 10 | 0–100 |
| `FE394` | Min Pedal % | 40 | 0–100 |
| `FE398` | Min RPM | 2000 | 1000–7500 |
| `FE39C` | Cut Hold Time, calls (limit 60 in code) | 18 (≈100 ms) | 0–60 |
| `FE39D` | Lockout after Clutch Release, calls | 90 (≈0.5 s) | 0–255 |
| `FE39E` | Max Gear Age, calls (limit 127) | 40 (≈220 ms) | 0–127 |
| `FE3A0` | RPM per km/h, 1st–6th (0 = TC off in that gear) | from the ROM's gearbox, like rev-match | 0–200 |

**Hard limit in the code:** the cut hold is capped at 60 calls (~330 ms) whatever the table says, so a bad value can't hold the cut on.

## Tuning
- **It cuts when the car isn't spinning:** raise Max Accel or Min Rate, or lower Alpha. Or set that gear's RPM-per-km/h entry to 0 to switch TC off in that gear.
- **It lets too much spin through:** lower Max Accel or Min Rate, or raise Hold.
- **It stutters right after you release the clutch:** raise Lockout.
- **Different tyres or final drive:** set the RPM-per-km/h table to your gearing (the same numbers as rev-match's table; see [rev-match.md](rev-match.md)).
- **The cut itself** uses the ignition cut's Dwell and Retard tables.

## Testing it on the car
1. Install it with **Traction control on** and the defaults, and take a datalog with RPM, speed and pedal.
2. **Normal driving first:** full-throttle pulls in each gear on a dry road. It must never cut. If it does, raise Max Accel (or Min Rate) before anything else.
3. **Then a controlled spin** in a safe, closed place: wet surface, 2nd gear. It should cut (you'll feel and hear it) and the revs should come back down.
4. If anything feels wrong, set Enable to 0 in NC Flash.

## Replay against LFJ1EE logs
All 18 logs were replayed through the detector at 31 ms log resolution. The logs have no clutch channel, so gear changes were treated as shifts.
- **Without the Min Rate floor:** about 20 false triggers. Most were tip-in driveline shunts in 3rd–5th at 2,000–2,600 rpm/s, plus clutch re-engagement after flat-foot shifts.
- **With the 2,500 rpm/s floor,** the only remaining hits are:
  - revs with the clutch in at constant speed (blocked by the real clutch switch);
  - one borderline sample (2,632 against 2,500 rpm/s).
- **Emulator wheelspin in 2nd (8,000 rpm/s):** cut after 3 calls (16 ms).
- **Simulated 1 s low-grip patch at full throttle:** peak slip 5% with TC, against 107% without.

## How it hooks in
- **Task slot:** the task-list literals that call the factory pedal copy (on LFJ1EE `0x11B00` and `0x134D4`) point to TC at `0xFE800`. TC first calls whatever they used to call, through the ROM pointer `0xFE3BC`: the factory pedal copy, or rev-match at `0xFE400`. Rev-match, upshift hold and anti-stall run exactly as before.
- **Install order doesn't matter.** Installing (or updating) rev-match on a file with TC changes that pointer instead of the task literals, so TC stays in front. Installing TC on a file with rev-match puts it in front of rev-match.
- **No `.patch` file.** TC changes the same task literals as rev-match, so a fixed XOR file would be wrong in one of the two orders. Install it with NC Patcher, or with the script, which works out the chain itself:
  ```
  python scripts/build_tc.py your.bin EN=1            # install / update, keeps your other settings; writes "your - tc.bin"
  python scripts/build_tc.py your.bin AMAX=35 PMIN=50 # change settings
  python scripts/build_tc.py your.bin remove          # take it out again; writes "your - no tc.bin"
  ```
- **RAM:** `FFFFAC40`–`AC4C`. These bytes are zero and unused by stock and romdrop code (checked in RAM dumps, and in every calibration's code by `tools/port.py`).
  - `AC40` f32 previous RPM
  - `AC44` f32 rate
  - `AC48` gear
  - `AC49` hold
  - `AC4A` lockout
  - `AC4B` **TC flag (1 = cutting)**, read by the ignition cut
  - `AC4C` gear age
- **Flash:** code `0xFE800`–`0xFE9AF`, tables `0xFE380`–`0xFE3BF`. Outside the ROM checksums.
- **Calibrations:** TC runs from the same task slot as rev-match, so it's available on the same 52 calibrations ([calibrations.md](calibrations.md)).

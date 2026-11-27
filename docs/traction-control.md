# Spark-cut traction control (wheel slip)

**Status: 🧪 emulator-tested, not yet tested on a car.** It passes the emulator tests (`tests/tc_emu.py`), including a closed-loop wheelspin simulation. Test it yourself, carefully, before relying on it.

## What it does
It compares each **rear** wheel with the **front** wheel on the same side. The fronts aren't driven, so they turn at road speed; a rear wheel turning faster than that is spinning. When a rear spins more than allowed, TC **cuts spark** with the same short-dwell ignition cut and timing retard that the rev limiter and flat shift use, until the wheels grip again.

**Where the wheel speeds come from:** the ABS unit sends all four wheel speeds to the ECU over CAN (message `0x4B0`: front left, front right, rear left, rear right, each km/h × 100 + 10000). The factory software copies all four into RAM but only uses the rears; TC reads all four there. This was checked in the code of all 113 NC stock ROMs. NC Patcher shows the four speeds live (tab 1), so you can check them on your car first.

**It needs the [ignition cut](ignition-cut.md).** The ignition cut's shared cut check also cuts while TC raises its flag. Without it TC can't do anything, so NC Patcher and the installer refuse to install TC on its own.

It works alongside every other patch, in any install order, and alongside romdrop (it uses none of romdrop's RAM).

## How it decides
Every task call (~5.5 ms):

1. **Slip, per side:** rear left − front left, and rear right − front right; the larger counts. Comparing per side means a corner (the outer wheels turn faster than the inner ones) doesn't look like wheelspin.
2. **Slip allowed** = **Slip Allowed km/h** + **Slip Allowed %** × road speed (the front-wheel average). With the defaults (3 km/h + 10%):

   | Road speed | 20 km/h | 50 km/h | 100 km/h | 150 km/h |
   |---|---|---|---|---|
   | Cuts when a rear is faster by more than | 5 km/h | 8 km/h | 13 km/h | 18 km/h |

   Some slip is normal and gives the best acceleration, which is why it isn't zero.
3. **Cut** while slip is above that, and for **Cut Hold** calls (~50 ms) after, so it doesn't chatter.

### Always off
- **Brake pressed.**
- **Clutch down,** and for **Lockout** calls (~0.1 s) after it comes up. This keeps it out of launch control, flat-foot shifts and rev-match. Real slip isn't fooled by the clutch biting, so the lockout is short.
- **Fronts below Min Speed** (5 km/h). Wheel sensors read about 0 at walking pace, so a launch is controlled from just above that.
- **Below Min Pedal** (20%) or **Min RPM** (2,000 rpm).
- **Wheel speeds invalid,** or **not updated for ~0.55 s** (CAN lost). It never cuts on stale data.
- **Overrun crackle** never overlaps it: the crackle needs a closed pedal.

## Settings
In NC Patcher (tab 2): **Install / keep**, **Traction control on**, **Slip allowed** (km/h), **plus** (% of speed) and **Only above pedal**. Everything is also in NC Flash, under **Traction Control - Spark Cut**:

| Address | Table | Default | Range |
|---|---|---|---|
| `FE380` | TC - Enable | 0 (off) | 0 / 1 |
| `FE384` | Slip Allowed, km/h (rear faster than front, per side) | 3 | 0–30 |
| `FE388` | Slip Allowed, plus % of road speed | 10 | 0–50 |
| `FE390` | Min Speed, front wheels km/h | 5 | 2–100 |
| `FE394` | Min Pedal % | 20 | 0–100 |
| `FE398` | Min RPM | 2000 | 1000–7500 |
| `FE39C` | Cut Hold after slip ends, calls ~5.5 ms (limit 60 in code) | 9 (≈50 ms) | 0–60 |
| `FE39D` | Lockout after Clutch Release, calls | 20 (≈110 ms) | 0–255 |

**Hard limits in the code:** the hold is capped at 60 calls (~330 ms) whatever the table says, and the stale-data cut-off (100 calls) is fixed, so a bad value can't keep the cut on.

## Tuning
- **It cuts when you don't feel wheelspin:** raise Slip Allowed (km/h or %). Check the four wheel speeds in NC Patcher's live view first: they should match each other driving straight.
- **It lets too much spin through:** lower Slip Allowed, or raise Cut Hold.
- **Different-size front and rear tyres** (staggered wheels) change the "no slip" reading: a smaller rear tyre turns faster all the time. Check the live slip driving straight and raise Slip Allowed km/h past it.
- **The cut itself** uses the ignition cut's Dwell and Retard tables.

## Testing it on the car
1. **Check the wheel speeds first:** NC Patcher tab 1, Live values. Driving straight, all four should match the speedo, and rear slip should sit near 0%.
2. Install TC with **Traction control on** and the defaults, and datalog RPM, speed and pedal.
3. **Normal driving:** full-throttle pulls on a dry road, and hard corners. It must not cut. If it does, raise Slip Allowed before anything else.
4. **Then a controlled spin** in a safe, closed place, for example a wet surface in 2nd. It should cut, and the rears should come back towards the fronts.
5. If anything feels wrong, set Enable to 0 in NC Flash.

## Emulator results
- Grip (straight, and a corner with the outer wheels 8 km/h faster): no cut.
- Rears 10 km/h faster at 50 km/h, or 20 km/h faster at 120: cut on the first call. One rear spinning: cut.
- Brake, clutch (and the lockout after it), low pedal, low rpm, fronts below 5 km/h, an invalid wheel speed, Enable 0: no cut.
- Wheel data frozen: the cut stops after 100 calls.
- **Simulated 1 s wet patch at full throttle:** peak wheelspin 57 km/h without TC, 7.9 km/h with it (about the slip allowed at that speed).

## How it hooks in
- **Task slot:** the task-list literals that call the factory pedal copy (on LFJ1EE `0x11B00` and `0x134D4`) point to TC at `0xFE800`. TC first calls whatever they used to call, through the ROM pointer `0xFE3BC`: the factory pedal copy, or rev-match at `0xFE400`. Rev-match, upshift hold and anti-stall run exactly as before.
- **Install order doesn't matter.** Installing (or updating) rev-match on a file with TC changes that pointer instead of the task literals, so TC stays in front.
- **No `.patch` file.** TC changes the same task literals as rev-match, so a fixed XOR file would be wrong in one of the two orders. Install it with NC Patcher, or with the script, which works out the chain itself:
  ```
  python scripts/build_tc.py your.bin EN=1                   # install / update, keeps your other settings; writes "your - tc.bin"
  python scripts/build_tc.py your.bin SLIPKMH=4 SLIPPCT=12    # change settings
  python scripts/build_tc.py your.bin remove                 # take it out again; writes "your - no tc.bin"
  ```
- **RAM:** `FFFFAC40`–`AC4C`, zero and unused by stock and romdrop code (checked in RAM dumps, and in every calibration's code by `tools/port.py`): `AC40` wheel-data signature, `AC44` unchanged-calls counter, `AC49` hold, `AC4A` lockout, `AC4B` **TC flag (1 = cutting)**, read by the ignition cut.
- **Flash:** code `0xFE800`–`0xFE9FF`, tables `0xFE380`–`0xFE3BF` (`FE39E` holds the table layout version, 2). Outside the ROM checksums.
- **Calibrations:** available on the 52 calibrations with rev-match (same task slot; [calibrations.md](calibrations.md)).

## Upgrading from 0.9.29–0.9.30
Those versions guessed at wheelspin from how fast the revs rose. Saving with 0.9.31 or later replaces that with wheel-slip detection: **Enable is kept**, a changed Min Pedal or Min RPM is kept, and the rest go to the new defaults (the old tables meant different things). Click **Show the new tables in NC Flash** again: it removes the old TC tables and adds the new ones.

## Not used
The factory TCS's own torque-reduction request to the ECU hasn't been identified, so TC doesn't use it.

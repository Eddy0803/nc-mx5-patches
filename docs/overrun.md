# Timed overrun crackle

Patch file: `patches/lfj1ee/lfj1ee_overrun.patch`. **Enable is 0 in the patch.** Turn it on in NC Flash, or tick "Crackle on" in the app, when you're ready to test.

**Status: not yet tested on a car.** The logic passes the emulator tests, and it uses the same spark-advance sum the ignition cut's retard uses (which has been tested on a car). How it sounds, and how hot the exhaust gets, can only be found out on the car.

## What it does
When you lift off the throttle, the factory software starts a decel fuel cut: it ramps a fuel multiplier down from 1.0 and cuts fuel completely below 0.6. For a set time after you lift off, this patch:
- **keeps fuelling** at a lambda taken from a **lambda-vs-RPM table**, so some fuel is still burnt. By default this is what a stock Ford sport-mode burble uses: **0.92 up to 3000 rpm, rising to 1.0 at 4000 rpm and above**;
- **retards the spark** a lot, so combustion is still going when the exhaust valve opens and finishes in the manifold.

That gives a crackle on the overrun, the way some modern cars do it from the factory, with only slightly rich-to-stoichiometric fuelling rather than the very rich "pops and bangs" approach that dumps fuel into the exhaust. When the time is up, the factory fuel cut carries on as normal.

## When it runs
- **Arming:** press the pedal past **Arm** (20%). Nothing happens while you're on the pedal.
- **A burst:** lift to **Closed** (2% or less). It crackles for **Duration** seconds (2 s by default, 5 s limit in code) while all of these hold:
  - clutch **up**, or pressed while slower than **Clutch pressed: allow below this speed** (0 by default = the clutch always stops it; set e.g. 3 km/h to crackle on a standing rev with the clutch in);
  - RPM between **Min RPM** and **Max RPM** (2500–6500);
  - speed at least **Min speed** (0 by default = any speed, including a free rev standing still with the clutch up in neutral);
  - coolant at least **Min coolant temp** (50 °C).
- **Ends** when the time runs out, the clutch goes down, or any condition above fails. It then stays off until you press the pedal past Arm again, so **each lift-off gives at most one burst.**
- Part throttle (between Closed and Arm) does nothing and keeps the state.

## Fuel: the lambda table
Four RPM points and the lambda at each. Between the points the lambda is interpolated in a straight line; below the first point and above the last it stays flat.

| RPM | 2000 | 3000 | 4000 | 5000 |
|---|---|---|---|---|
| Lambda (default, stock Ford) | 0.92 | 0.92 | 1.0 | 1.0 |

The code limits lambda to **0.85–1.5**. The lean limit keeps the fuel multiplier above the factory's 0.6 full-cut point.

## Strength (spark only)
**Strength** (0–100%) sets only how aggressive the **spark** is. The fuel follows the lambda table whatever the Strength.

| | Strength 0 (mild) | Strength 100 (aggressive) | Limit in code |
|---|---|---|---|
| Spark retard | 25° | 40° | 0–45° |

The default is Strength 0.

**Based on a factory Ford sport-mode burble (Fiesta ST):** Ford sets how aggressive the burble is with a spark **torque ratio clip** ("tr_clip"):
- **0.1 = mild, 0 = very aggressive.** The value is the share of full torque the spark is allowed to make, so it takes very late spark: around top dead centre or after.
- Strength 0 here corresponds to the mild end (about 0.1) and Strength 100 to the aggressive end (0).
- **Why the retard values are estimates:** the NC works in degrees rather than torque ratio. Set them from a datalog of ignition advance during a burst. The rough aim for "mild" is advance near 0° (top dead centre); for "aggressive", a little after it.
- **One difference:** the Ford's clip also gets more aggressive with RPM (on a mild file: 0.085 up to 3000 rpm, 0 at 6000 rpm). Here the retard is the same at every RPM.

## Tables
| Address | Table | Default |
|---|---|---|
| `FF000` | Enable (0 = off, 1 = on) | 0 |
| `FF004` | Strength, % (0 = mild, 100 = aggressive) | 0 |
| `FF008` | Duration after lift-off, s (limit 5) | 2.0 |
| `FF00C` | Min RPM | 2500 |
| `FF010` | Max RPM | 6500 |
| `FF014` | Min speed, km/h (0 = any speed) | 0 |
| `FF018` | Min coolant temp, °C | 50 |
| `FF01C` | Arm: pedal % to pass before a lift-off counts | 20 |
| `FF020` | Closed: pedal % at or below this counts as lifted | 2 |
| `FF02C` | Clutch pressed: allow below this speed, km/h (0 = never) | 0 |
| `FF024` | Retard at Strength 0, degrees | 25 |
| `FF028` | Retard at Strength 100, degrees | 40 |
| `FF034` | Task calls per second (timing calibration) | 90 |
| `FF040` | Lambda table: 4 RPM points (increasing) | 2000, 3000, 4000, 5000 |
| `FF050` | Lambda table: lambda at those points (0.85–1.5) | 0.92, 0.92, 1.0, 1.0 |

Change them in NC Flash after adding the tables ([ncflash-ecuflash.md](ncflash-ecuflash.md)), with the app (Enable, Strength and Duration), or with `scripts/upgrade_overrun.py your.bin EN=1 STR=40 DUR=1.5`.

## Timing calibration
The patch runs in the same scheduler task as the factory decel fuel cut, which is clock-driven (not tied to engine speed). Its rate is **assumed to be 90 calls per second**, based on the rev-match timing measured on LFJ1EE. It hasn't been measured for this task directly. To check it:
1. Set Duration to **4 s**.
2. Film a lift-off with sound.
3. Time how long the crackle lasts.
4. If it lasted T seconds, set *Task calls per second* to 90 × T / 4. For example, if it lasted 3.2 s, set 72.

## Before you test: risks
- **Catalyst and exhaust heat.** The NC's catalyst sits right after the manifold, and burning fuel in the exhaust heats it. Slightly rich (0.92) is gentler than the very rich pops-and-bangs approach, but it still adds heat. Keep bursts short, don't sit in long overruns with it on, and if you can, log or watch exhaust temperature.
- **Exhaust valves** run hotter during a burst. That's fine in short bursts.
- **Less engine braking and more fuel used** during a burst, because fuel isn't cut.
- **Roadworthiness and emissions rules:** some places treat deliberate exhaust crackle as an illegal modification.

## Testing
1. **Engine at least 50 °C**, safe place. Start with **Strength 0** and **Duration 1 s**.
2. **Log:** RPM, ignition advance, AFR / lambda (a wideband if you have one), coolant temperature and, ideally, exhaust temperature.
3. Get to 3500–4500 RPM in 3rd, then lift off completely. (A free rev in neutral with the clutch up works too, and with the clutch pressed if *Clutch pressed: allow below this speed* is set.)
4. **What the log should show during the burst:**
   - ignition advance drops by the retard;
   - lambda close to the table (about 0.92 below 3000 rpm, 1.0 above 4000), rather than off-scale lean (full fuel cut);
   - after Duration, the factory fuel cut takes over.

   If the advance doesn't drop as far as set, the factory software has a lower limit on ignition advance; note what it stops at.
5. Raise Strength in steps of 20 and listen. Check the timing calibration above.

## How it's done
- **Fuel:** the task-list entry (`0x1384C`) that called the factory decel fuel-cut routine (`0x45940`) now calls the patch. The patch runs the factory routine first, unchanged. During a burst it then overwrites the fuel multiplier that routine produced (`FFFF7560`) with 1 / lambda, where lambda comes from the table at the current RPM, limited to 0.85–1.5 (a multiplier of 0.67–1.18).
- **Spark:** in the spark-advance sum, the load of the factory term `FFFF9F74` (`0x4DAF4`) becomes a call that returns that term minus the retard. The ignition cut uses a different term in the same sum, so the two patches don't touch each other.
- **RAM** (unused by the factory software): `ACD0` time left, `ACD4` armed, `ACD5` active, `ACD8` retard. The spark hook ignores a stored retard outside 0–45°, so random RAM contents at power-up can't affect the timing.
- **No division by zero:**
  - lambda is limited to at least 0.85 before dividing;
  - RPM points that are equal or out of order are never divided by;
  - a calls-per-second value of 1 or less ends the burst.

  All of this holds even if a table is edited to 0.
- `scripts/build_overrun.py` contains the exact code. `tests/overrun_emu.py` runs it from your ROM.
- **Porting:** `tools/port.py` finds the decel fuel-cut routine, its fuel multiplier, the coolant temperature and a spark-sum term in other calibrations, and builds the patch when it can. It worked on LF9WEB, LFZZE0, LFLPED and LFDKEB. The other patches are built even if overrun can't be.
- **Where it lives:** flash `0xFF000`–`0xFF3FF` (tables at `FF000`, code from `FF080`), outside the ROM checksums. Up to 0.9.10 it sat at `0xFE800`, which clashed with romdrop-era add-ons in some tuned ROMs.
- **Older versions:** saving over a file with an earlier overrun (0.9.7–0.9.10, at `0xFE800`) moves it here and keeps the settings, except the fuel, which gets the default lambda table.

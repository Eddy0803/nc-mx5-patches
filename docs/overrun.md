# Timed overrun crackle

Patch file: `patches/lfj1ee/lfj1ee_overrun.patch`. **Enable is 0 in the patch.** Turn it on in NC Flash, or tick "Crackle on" in the app, when you're ready to test.

**Status: not yet tested on a car.** The logic passes the emulator tests, and it uses the same spark-advance sum the ignition cut's retard uses (which has been tested on a car). How it sounds, and how hot the exhaust gets, can only be found out on the car.

## What it does
When you lift off the throttle, the factory software starts a decel fuel cut: it ramps a fuel multiplier down from 1.0 and cuts fuel completely below 0.6. For a set time after you lift off, this patch:
- **holds that fuel multiplier at a lean value** (between 0.65 and 1.0, never rich), so a little fuel is still burnt;
- **retards the spark** a lot, so combustion is still going when the exhaust valve opens and finishes in the manifold.

That gives a crackle on the overrun, the lean way some modern cars do it from the factory, rather than the rich "pops and bangs" approach that dumps fuel into the exhaust. When the time is up, the factory fuel cut carries on as normal.

## When it runs
- **Arming:** press the pedal past **Arm** (20%). Nothing happens while you're on the pedal.
- **A burst:** lift to **Closed** (2% or less). It crackles for **Duration** seconds (2 s by default, 5 s limit in code) while all of these hold:
  - clutch **up** (in gear);
  - RPM between **Min RPM** and **Max RPM** (2500–6500);
  - speed at least **Min speed** (30 km/h);
  - coolant at least **Min coolant temp** (75 °C).
- **Ends** when the time runs out, the clutch goes down, or any condition above fails. It then stays off until you press the pedal past Arm again, so **each lift-off gives at most one burst.**
- Part throttle (between Closed and Arm) does nothing and keeps the state.

## Strength
One setting, **Strength** (0–100%), sets how mild or strong it sounds. It blends between two pairs of values:

| | Strength 0 (mild) | Strength 100 (strong) | Limit in code |
|---|---|---|---|
| Spark retard | 6° | 20° | 0–30° |
| Fuel multiplier | 0.82 (leaner) | 0.95 (closer to stoichiometric) | 0.65–1.0 |

More retard and more fuel give a louder crackle; less of both is milder. Strength 50 (the default) gives 13° and 0.885. All four end values can be changed in NC Flash.

## Tables
| Address | Table | Default |
|---|---|---|
| `FE800` | Enable (0 = off, 1 = on) | 0 |
| `FE804` | Strength, % (0 = mild, 100 = strong) | 50 |
| `FE808` | Duration after lift-off, s (limit 5) | 2.0 |
| `FE80C` | Min RPM | 2500 |
| `FE810` | Max RPM | 6500 |
| `FE814` | Min speed, km/h | 30 |
| `FE818` | Min coolant temp, °C | 75 |
| `FE81C` | Arm: pedal % to pass before a lift-off counts | 20 |
| `FE820` | Closed: pedal % at or below this counts as lifted | 2 |
| `FE824` | Retard at Strength 0, degrees | 6 |
| `FE828` | Retard at Strength 100, degrees | 20 |
| `FE82C` | Fuel multiplier at Strength 0 | 0.82 |
| `FE830` | Fuel multiplier at Strength 100 | 0.95 |
| `FE834` | Task calls per second (timing calibration) | 90 |

Change them in NC Flash after adding the tables ([ncflash-ecuflash.md](ncflash-ecuflash.md)), with the app (Enable, Strength and Duration), or with `scripts/upgrade_overrun.py your.bin EN=1 STR=40 DUR=1.5`.

## Timing calibration
The patch runs in the same scheduler task as the factory decel fuel cut, which is clock-driven (not tied to engine speed). Its rate is **assumed to be 90 calls per second**, based on the rev-match timing measured on LFJ1EE. It hasn't been measured for this task directly. To check it:
1. Set Duration to **4 s**.
2. Film a lift-off with sound.
3. Time how long the crackle lasts.
4. If it lasted T seconds, set *Task calls per second* to 90 × T / 4. For example, if it lasted 3.2 s, set 72.

## Before you test: risks
- **Catalyst and exhaust heat.** The NC's catalyst sits right after the manifold. Late, lean combustion is gentler on it than rich pops, but it still heats the exhaust and catalyst. Keep bursts short, don't sit in long overruns with it on, and if you can, log or watch exhaust temperature.
- **Exhaust valves** run hotter during a burst. That's fine in short bursts.
- **Less engine braking and more fuel used** during a burst, because fuel isn't fully cut.
- **Roadworthiness and emissions rules:** some places treat deliberate exhaust crackle as an illegal modification.

## Testing
1. **Warm engine**, safe road. Start with **Strength 0** and **Duration 1 s**.
2. **Log:** RPM, ignition advance, AFR / lambda (a wideband if you have one), coolant temperature and, ideally, exhaust temperature.
3. Get to 3500–4500 RPM in 3rd above 30 km/h, then lift off completely.
4. **What the log should show during the burst:**
   - ignition advance drops by the retard;
   - lambda goes lean of 1.0 rather than to full fuel cut (very lean or off-scale);
   - after Duration, the factory fuel cut takes over.

   If the advance doesn't drop as far as set, the factory software has a lower limit on ignition advance; note what it stops at.
5. Raise Strength in steps of 20 and listen. Check the timing calibration above.

## How it's done
- **Fuel:** the task-list entry (`0x1384C`) that called the factory decel fuel-cut routine (`0x45940`) now calls the patch. The patch runs the factory routine first, unchanged, then, during a burst, overwrites the fuel multiplier it produced (`FFFF7560`) with the lean value.
- **Spark:** in the spark-advance sum, the load of the factory term `FFFF9F74` (`0x4DAF4`) becomes a call that returns that term minus the retard. The ignition cut uses a different term in the same sum, so the two patches don't touch each other.
- **RAM** (unused by the factory software): `AC38` time left, `AC3C` armed, `AC3D` active, `AC40` retard. The spark hook checks that the stored retard is between 0 and 30°, so random RAM contents at power-up can't affect the timing.
- `scripts/build_overrun.py` contains the exact code. `tests/overrun_emu.py` runs it from your ROM.
- **Porting:** `tools/port.py` finds the decel fuel-cut routine, its fuel multiplier, the coolant temperature and a spark-sum term in other calibrations, and builds the patch when it can. It worked on LF9WEB, LFZZE0, LFLPED and LFDKEB. The other patches are built even if overrun can't be.

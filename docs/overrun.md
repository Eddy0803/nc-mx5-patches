# Timed overrun crackle

Patch file: `patches/lfj1ee/lfj1ee_overrun.patch`. **Enable is 0 in the patch.** Turn it on in NC Flash, or tick "Crackle on" in the app, when you're ready to test.

**Status: not yet tested on a car.** The logic passes the emulator tests, and it uses the same spark-advance sum the ignition cut's retard uses (which has been tested on a car). How it sounds, and how hot the exhaust gets, can only be found out on the car.

## What it does
When you lift off the throttle, the factory software starts a decel fuel cut: it ramps a fuel multiplier down from 1.0 and cuts fuel completely below 0.6. For a set time after you lift off, this patch:
- **keeps fuelling lean at a fixed lambda** (**1.1** by default), so a little fuel is still burnt;
- **retards the spark** a lot, so combustion is still going when the exhaust valve opens and finishes in the manifold.

That gives a crackle on the overrun, the lean way some modern cars do it from the factory, rather than the rich "pops and bangs" approach that dumps fuel into the exhaust. When the time is up, the factory fuel cut carries on as normal.

## When it runs
- **Arming:** press the pedal past **Arm** (20%). Nothing happens while you're on the pedal.
- **A burst:** lift to **Closed** (2% or less). It crackles for **Duration** seconds (2 s by default, 5 s limit in code) while all of these hold:
  - clutch **up** (in gear);
  - RPM between **Min RPM** and **Max RPM** (2500–6500);
  - speed at least **Min speed** (0 by default = any speed, including a free rev standing still with the clutch up in neutral);
  - coolant at least **Min coolant temp** (50 °C).
- **Ends** when the time runs out, the clutch goes down, or any condition above fails. It then stays off until you press the pedal past Arm again, so **each lift-off gives at most one burst.**
- Part throttle (between Closed and Arm) does nothing and keeps the state.

## Strength
**Strength** (0–100%) sets only how aggressive the **spark** is. The fuel stays at the Lambda value whatever the Strength.

| | Strength 0 (mild) | Strength 100 (aggressive) | Limit in code |
|---|---|---|---|
| Spark retard | 25° | 40° | 0–45° |
| Fuel | lambda 1.1 | lambda 1.1 | lambda 1.0 to about 1.54 (never rich) |

The default is Strength 0. The two retard values and the lambda can be changed in NC Flash.

**Based on a factory Ford sport-mode burble (Fiesta ST):**
- **Fuel:** its lambda target during burble is a fixed **1.1**, the default here.
- **Aggressiveness:** it sets how aggressive the burble is with a spark **torque ratio clip** ("tr_clip"):
  - **0.1 = mild, 0 = very aggressive.** The value is the share of full torque the spark is allowed to make, so it takes very late spark: around top dead centre or after.
  - Strength 0 here corresponds to the mild end (about 0.1) and Strength 100 to the aggressive end (0).
- **Why the retard values are estimates:** the NC works in degrees rather than torque ratio. Set them from a datalog of ignition advance during a burst. The rough aim for "mild" is advance near 0° (top dead centre); for "aggressive", a little after it.
- **One difference:** the Ford's clip also gets more aggressive with RPM (on the mild file: 0.085 up to 3000 rpm, 0 at 6000 rpm). Here the retard is the same at every RPM.

## Tables
| Address | Table | Default |
|---|---|---|
| `FE800` | Enable (0 = off, 1 = on) | 0 |
| `FE804` | Strength, % (0 = mild, 100 = aggressive) | 0 |
| `FE808` | Duration after lift-off, s (limit 5) | 2.0 |
| `FE80C` | Min RPM | 2500 |
| `FE810` | Max RPM | 6500 |
| `FE814` | Min speed, km/h (0 = any speed) | 0 |
| `FE818` | Min coolant temp, °C | 50 |
| `FE81C` | Arm: pedal % to pass before a lift-off counts | 20 |
| `FE820` | Closed: pedal % at or below this counts as lifted | 2 |
| `FE824` | Retard at Strength 0, degrees | 25 |
| `FE828` | Retard at Strength 100, degrees | 40 |
| `FE82C` | Lambda during a burst (1.0–1.5) | 1.1 |
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
1. **Engine at least 50 °C**, safe place. Start with **Strength 0** and **Duration 1 s**.
2. **Log:** RPM, ignition advance, AFR / lambda (a wideband if you have one), coolant temperature and, ideally, exhaust temperature.
3. Get to 3500–4500 RPM in 3rd, then lift off completely. (A free rev in neutral with the clutch up works too.)
4. **What the log should show during the burst:**
   - ignition advance drops by the retard;
   - lambda around 1.1, rather than off-scale lean (full fuel cut);
   - after Duration, the factory fuel cut takes over.

   If the advance doesn't drop as far as set, the factory software has a lower limit on ignition advance; note what it stops at.
5. Raise Strength in steps of 20 and listen. Check the timing calibration above.

## How it's done
- **Fuel:** the task-list entry (`0x1384C`) that called the factory decel fuel-cut routine (`0x45940`) now calls the patch. The patch runs the factory routine first, unchanged, then, during a burst, overwrites the fuel multiplier it produced (`FFFF7560`) with 1 / lambda (limited to 0.65–1.0).
- **Spark:** in the spark-advance sum, the load of the factory term `FFFF9F74` (`0x4DAF4`) becomes a call that returns that term minus the retard. The ignition cut uses a different term in the same sum, so the two patches don't touch each other.
- **RAM** (unused by the factory software): `AC38` time left, `AC3C` armed, `AC3D` active, `AC40` retard. The spark hook ignores a stored retard outside 0–45°, so random RAM contents at power-up can't affect the timing.
- **No division by zero:** a lambda or calls-per-second value of 1 or less is never divided by, even if a table is edited to 0.
- `scripts/build_overrun.py` contains the exact code. `tests/overrun_emu.py` runs it from your ROM.
- **Porting:** `tools/port.py` finds the decel fuel-cut routine, its fuel multiplier, the coolant temperature and a spark-sum term in other calibrations, and builds the patch when it can. It worked on LF9WEB, LFZZE0, LFLPED and LFDKEB. The other patches are built even if overrun can't be.
- **Older versions:** saving over a file with the 0.9.7 or 0.9.8 overrun updates the code and keeps the settings, except the fuel, which is reset to lambda 1.1.

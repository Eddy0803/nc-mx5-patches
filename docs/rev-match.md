# Downshift rev-match, upshift hold and anti-stall (LFJ1EE)

Patch file: `patches/lfj1ee/lfj1ee_downshift_revmatch.patch`. **Enable is 0 in the patch.** Turn it on in NC Flash when you're ready to test.

## Downshift rev-match
- **When:** clutch **and** brake pressed, pedal released, above Min Speed.
- **What it does:** the ECU opens the throttle to hold the engine at the RPM the **next gear down** needs at your current speed (plus an offset). The target follows your speed as you brake.
- **Ends:** as soon as you release the clutch or the brake, press the accelerator, drop below Min Speed, or the hold time runs out.

### How it decides
- **Gear:** while the clutch is up, it learns the gear from RPM ÷ speed, matching the RPM-per-km/h table within ±8%.
- **Target:** speed × RPM-per-km/h of one gear lower + Offset, capped at Max Target RPM.
- **Throttle:** virtual pedal = Gain × (target − RPM) − Damping × (RPM change since the last call). It's clamped between 0 and Max Output Pedal (**40% hard limit in code**), and the ECU uses max(your pedal, virtual pedal), so your foot always wins.
- **Throttle-plausibility check:** relaxed **only while it's active**, the same way the factory does for cruise control.

## On/off switch for downshift rev-match
**Emulator-tested, not yet on a car. Off by default** (On/Off Switch Enable = 0).

Turn downshift rev-match on or off from the driver's seat, without remapping:
1. **Stop the car** (below 3 km/h) and **hold the clutch down**.
2. **Tap the brake 3 times within 2 s** (Tap Window).
3. **The engine confirms it:**
   - switched **on**: it holds about **2000 rpm for 3 s**;
   - switched **off**: it holds about **1500 rpm for 3 s**.

How it behaves:
- **Clutch down the whole time.** The confirmation stops at once if you let the clutch up or the car moves. Pressing the accelerator still works as normal: your foot always wins.
- **It's held with the rev-match controller,** so the real RPM may sit about 50–150 rpm under the set value. If you want it exact, raise the Confirm RPM tables by that much. The code limits them to 4000 rpm and the time to 1100 calls (about 6 s).
- **It only switches downshift rev-match.** Upshift hold and anti-stall keep following their own Enable tables. The main Enable (`FE300`) stays the master switch: at 0, downshift rev-match is off whatever the switch says.
- **Every time the ECU powers up, the switch starts at On/Off Switch State at Start-up** (1 = on).
- Holding the brake down counts as one tap. Taps while the car is moving, or with the clutch up, don't count.

## Upshift hold
- **When:** clutch pressed **without** the brake, pedal released, Upshift Hold Enable on.
- **What it does:** if the revs fall below the RPM the **next gear up** needs, it adds just enough throttle to hold them there, so the revs settle where the next gear wants them.
- **Limit:** it can only *add* throttle. If the revs hang above the target, it can't pull them down.
- **Flat-foot shifts:** with your foot on the pedal it stays off, so it doesn't interfere with a flat-foot shift.

## Hold time
Up to **Max Hold Time** per clutch press: default 270 calls ≈ 1.5 s, limit 600 calls ≈ 3.3 s. It reloads when the clutch comes up, so every shift gets the full time.

## Anti-stall
**Working on a car. Off by default.**
- **When:** rev-match isn't active, speed ≤ Max Speed, the engine is running (> 300 rpm), and RPM is below the Anti-Stall RPM.
- **What it does:** adds Gain × (Anti-Stall RPM − RPM) of pedal, up to Max Pedal (**20% hard limit in code**).
- **Keep the Anti-Stall RPM below your idle target,** or it will raise your idle permanently.

## Tables
### `DBW - Downshift Rev Match`
| Address | Table | Default |
|---|---|---|
| `FE300` | Enable | 0 |
| `FE320` | Target offset, rpm | +100 |
| `FE364` | On/off switch enable (stopped + clutch down + 3 brake taps) | 0 |
| `FE368` | On/off switch state at start-up (1 = on) | 1 |
| `FE374` | On/off switch tap window, calls of ~5.5 ms | 364 (2 s) |
| `FE36C` | Confirm RPM when switched on (limit 4000) | 2000 |
| `FE370` | Confirm RPM when switched off (limit 4000) | 1500 |
| `FE376` | Confirm time, calls of ~5.5 ms (limit 1100, 0 = no confirmation) | 545 (3 s) |

### `DBW - Upshift Hold`
| Address | Table | Default |
|---|---|---|
| `FE340` | Upshift hold enable | 0 |
| `FE344` | Upshift target offset, rpm | +150 |

### `DBW - Rev Match / Upshift Hold - Shared`
| Address | Table | Default |
|---|---|---|
| `FE304` | Max output pedal % (limit 40) | 30 |
| `FE308` | Max real pedal % allowed | 3 |
| `FE30C` | Min speed, km/h | 15 |
| `FE310` | Brake switch RAM address | `FFFF70EE` (LFJ1EE) |
| `FE316` | Max hold time, calls of ~5.5 ms (limit 600) | 270 |
| `FE318` | Gain, % pedal per rpm below target | 0.03 |
| `FE31C` | Damping, % per rpm rise per call | 0.3 |
| `FE324` | Max target RPM | 6000 |
| `FE328` | RPM per km/h, 1st–6th (0 = no such gear) | 113.8, 68.5, 48.3, 36.3, 29.5, 0 |

### `DBW - Anti-Stall`
| Address | Table | Default |
|---|---|---|
| `FE350` | Enable | 0 |
| `FE354` | Anti-stall RPM | 850 |
| `FE358` | Gain, % pedal per rpm below | 0.03 |
| `FE35C` | Max pedal % (limit 20) | 10 |
| `FE360` | Max speed, km/h | 20 |

## Set the RPM-per-km/h table for your car
The defaults are for the **5-speed** (gears 3.136 / 1.888 / 1.330 / 1.000 / 0.814, final drive 4.10, stock tyre size), and the 6th entry is 0. A **6-speed**, a different final drive or different tyres need different values. The easiest way to get them is from a datalog:
1. Drive steadily in each gear with the clutch fully up.
2. Run `python tools/gearcal.py your.bin your_log.csv` to get the measured RPM per km/h for each gear.

## Tuning
| Symptom | Change |
|---|---|
| Revs fall short of the lower gear | Raise Offset or Gain |
| Revs overshoot or hunt | Raise Damping, or lower Gain |
| Hold ends too soon | Raise Max Hold Time |

Values that worked well on the test car for quicker downshifts: Max Output 35, Gain 0.04, Damping 0.15, Offset +200.

## Testing
Somewhere safe, with a datalog running (RPM, speed, pedal, throttle):
1. **Downshift:** brake, clutch in, select the lower gear. The revs should rise to the lower gear's RPM and hold while the clutch is in.
2. **Upshift** (if enabled): lift off, clutch in without braking. The revs should settle at the next gear's RPM instead of dropping to idle.
3. **Release:** let the clutch up, or release the brake during a downshift. It should stop at once.
4. **Anti-stall** (if enabled): pull away gently. If the revs dip below the anti-stall RPM, the throttle should open slightly.
5. **On/off switch** (if enabled), stopped in neutral: hold the clutch down and tap the brake 3 times. The revs should go to about 1500 for 3 s (now off). Do a downshift: no blip. Stop and tap 3 times again: about 2000 for 3 s (back on). Let the clutch up during a confirmation: it should stop at once.

## Behaviour to know
- **Braking to a stop:** it holds the revs whenever the clutch and brake are down above Min Speed, including when you're just braking to a stop without changing gear. Keep Min Speed around 15 km/h for road use.
- **Skipped gears:** it targets **one** gear lower. A skipped-gear downshift (4th → 2nd) won't be fully matched.

## How it's built
- **Task hook:** the two task-list pointers at `0x11B00` and `0x134D4` normally call the stock pedal-copy routine `0x387F8`. They now call the rev-match routine at `0xFE400`, which does the same copy plus rev-match.
- **Plausibility check:** literal `0xB61F0` points to a flag that's 1 only while rev-match is active.
- **RAM:** `FFFFAC10`–`AC1F`. `AC18` holds the on/off switch: `5AA5` = on, `A55A` = off. Any other value means not set yet, so the start-up state is used.

`scripts/build_revmatch.py` contains the exact code. `tests/revemu.py` runs it against your ROM, including closed-loop simulations of a downshift, an upshift and a stall.

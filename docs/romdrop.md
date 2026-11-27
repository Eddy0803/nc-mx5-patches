# Using the patches with romdrop

**Short answer:** on **LFJ1EE**, NC Patcher's patches and romdrop's patch can be used together, as long as you use **NC Patcher 0.9.24 or later** and **don't run romdrop's launch control or flat shift at the same time as the ignition-cut patch's.**

romdrop is a separate project with its own licence. Nothing from it is included in this repository or in NC Patcher.

## What was checked
romdrop's own LFJ1EE patch was applied to a stock LFJ1EE ROM (as romdrop does), and the result was compared with what every patch here uses:

| Check | Result |
|---|---|
| Code romdrop changes vs. the code sites the patches hook | **No overlap.** romdrop changes 59 byte ranges; none touch the ignition-cut, rev-match or overrun hook sites, their literals, or the factory routines they rely on. |
| Free flash | **No overlap.** romdrop's added code is at `0xFB9D0`–`0xFC843`. The patches use `0xFE000`–`0xFE19F`, `0xFE300`–`0xFE7FF` and `0xFF000`–`0xFF3FF`. |
| RAM | **No overlap** (from 0.9.24). romdrop uses `FFFFAB00`, `FFFFAC00`–`AC0D` (including the flex-fuel CAN buffer at `AC00`–`AC07`) and `FFFFAC18`–`AC3B`. The patches use `AC10`–`AC17`, `AC50`–`AC59` and `ACD0`–`ACE3`. Every way romdrop addresses its RAM was traced, including 16-bit addresses and moving pointers. |
| Installing | NC Patcher's installers accept a romdrop ROM for all three patches. |
| Emulator tests | The ignition-cut, rev-match and overrun emulators all pass on the combined ROM. |

**Use 0.9.24 or later.** Up to 0.9.23, the rev-match on/off switch and clutch hold delay used RAM `AC18`–`AC21`, which romdrop also writes. On a romdrop ROM the two would have overwritten each other. If you saved a file with an older version, save it again with the current one. The rev-match emulator test now checks that the patch never writes to romdrop's RAM.

## Features that do the same job
| romdrop | Here | What to do |
|---|---|---|
| Launch control (Engine Limiter - Launch) | Ignition-cut launch control | Use **one**. romdrop's ships switched off (activation 8000 rpm). If you turn both on, two systems cut at once. |
| Flat shift (Engine Limiter - Flat Shift) | Ignition-cut flat-foot shift | Use **one**. romdrop's ships switched off (pedal threshold 200%). |
| Launch control spark retard | Ignition-cut timing retard | Only matters if romdrop's launch control is on. Ships at 0. |
| Speed limiter, RPM throttle cut | (none) | No interaction. |
| Flex fuel, speed density, fuel/spark blends | Overrun crackle (fuel and spark during a burst) | They work together: the overrun only changes the fuel multiplier and spark during a burst, on top of whatever romdrop has calculated. |

## How to combine them
1. **Start from a stock read** and apply romdrop's patch first, the way romdrop does it.
2. **Then add the patches here** with NC Patcher (tab 2) or the scripts. They check every hook site holds the factory code before changing anything, and refuse otherwise.
3. **Flash with NC Flash** (Full Flash the first time), which recalculates the checksums. Flashing a combined file with romdrop's own flasher hasn't been tested.
4. **Add the tables** to your definition (NC Patcher's **Show the new tables in NC Flash**) so both sets of tables show up.
5. **Test each feature on its own** first, as described in each patch's doc.

## Limits of this check
- It covers **LFJ1EE** with the romdrop patch that was available at the time. Another calibration, or another romdrop version, needs checking again.
- It's a code, flash and RAM comparison plus emulator tests. The combination hasn't been driven yet.

# Ignition-cut rev limiter, launch control and flat-foot shift (LFJ1EE)

Patch file: `patches/lfj1ee/lfj1ee_igncut.patch`. Settings: **Engine Limiter - RPM Ignition Cut** in NC Flash, or `scripts/upgrade_igncut.py`.

## How the cut works
Above the cut point, the ignition coil's charge time (dwell) is replaced with a very short one. The coil can't charge enough to fire, that cylinder misfires, and RPM drops.
- **Fuel keeps flowing.** The factory fuel cut stays in place above it as a backstop.
- **Timing retard:** while cutting, spark advance on the cylinders that still fire is reduced by the retard table, which cuts torque further.
- **Factory behaviour kept:** the factory's own short-dwell mode is left exactly as it was.

## Which cut point applies
| Situation | Cut point |
|---|---|
| **Clutch pressed, speed below the split speed** (stopped) and Launch RPM > 0 | **Launch RPM**: launch control |
| **Clutch pressed, speed at or above the split speed, pedal at or above the flat-shift minimum,** and Flat Shift RPM > 0 | **Flat Shift RPM**: flat-foot shift |
| Anything else | **RPM Fuel Cut** table (the factory rev limit, `0xC487C`) **+ Offset** |

- **Launch:** hold the clutch, floor it, and the revs hold at the launch RPM. Release the clutch and the normal limiter takes over.
- **Flat-foot shift:** keep your foot flat, clutch in, change gear, clutch out. While the clutch is in, the revs hold at the flat-shift RPM on the ignition cut alone. There's no fuel cut, even if you clutch in well above that RPM.
- **Normal shifts** (pedal below the flat-shift minimum) and **revving in neutral with the clutch up** use only the normal limiter.

## Tables (`Engine Limiter - RPM Ignition Cut`)
| Address | Table | Default |
|---|---|---|
| `0xFE180` | Enable (0/1) | 1 |
| `0xFE184` | Offset from RPM Fuel Cut, rpm | −300 |
| `0xFE188` | Coil dwell while cutting, ms (0.2 ms minimum in code) | 0.3 |
| `0xFE18C` | Timing retard while cutting, degrees (0 = off) | 5 |
| `0xFE194` | Launch control RPM (0 = off) | 0 |
| `0xFE190` | Flat shift RPM (0 = off) | 0 |
| `0xFE198` | Launch / flat-shift split speed, km/h | 10 |
| `0xFE19C` | Flat shift minimum pedal, % | 80 |

**Why these defaults:**
- **Dwell:** Mazda's own limiter dwell (0.768 ms) didn't stop the spark at full throttle. 0.3 ms does.
- **Offset:** an ignition cut just below the fuel cut (−50 rpm) kept falling into the fuel cut's on/off band. −300 keeps them apart.

**Rev limit:** to change it, change the factory **RPM Fuel Cut** table. The ignition cut follows it at the offset.

**Example:** launch 4,500, flat shift 5,300: `python scripts/upgrade_igncut.py your.bin LAUNCH=4500 FS=5300`.

## Testing
Somewhere safe, with a datalog running (RPM, speed, pedal, fuel pulse width, spark advance):
1. **Limiter:** in a low gear, rev to the limit. RPM should hold about 300 rpm below the RPM Fuel Cut value, with **fuel pulse width staying above 0** and spark advance dropping by the retard amount. Fuel pulse width at 0 means the fuel cut, not the ignition cut.
2. **Launch** (stopped, clutch in, pedal floored): RPM holds at the launch RPM. Release the clutch and it's gone.
3. **Flat shift** (above the split speed, full throttle, clutch in): RPM falls to and holds at the flat-shift RPM, with no fuel-cut rows during the shift.

## Risks
- **Hot catalytic converter.** Fuel is still injected while cutting, so unburnt fuel reaches the exhaust: expect pops and bangs, and keep time on the limiter short. More retard makes it worse.
- **Overshoot.** The cut reacts slightly late, so RPM can overshoot once when the limit is first reached.
- **Dwell floor.** Don't remove the 0.2 ms minimum.

## How it's built
- **Dwell hook:** the factory short-dwell flag test at `0x50D00` becomes a call (via literal `0x50DDC`) to the dwell routine at `0xFE000`.
- **Spark hook:** the load of a factory spark-advance term (`FFFF7D68`) at `0x4DAE8` becomes a call (via literal `0x4DCC0`) to the retard routine, which returns that term minus the retard while cutting.
- **Cut check:** one shared routine, used by both hooks. It reads RPM, speed, pedal and the clutch switch. **Nothing is written to RAM.**
- **Checksums:** code `0xFE000`–`0xFE17F`, tables `0xFE180`–`0xFE19F`, in flash the factory software doesn't use or checksum. The two hooks are in checksummed blocks, so the flashing tool must recalculate the checksums.
- **Traction control:** the cut check also has an input for an optional traction-control add-on (not in this repo). Without it, that input is ignored.

`scripts/build_igncut.py` contains the exact code. To check the logic against your own patched ROM, run `tests/igncut_emu.py`.

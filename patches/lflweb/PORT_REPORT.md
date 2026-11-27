# Port report: LFLWEB

Pre-ported and bundled with NC Patcher. Generated 2026-11-27 from a stock LFLWEB ROM and the stock LFJ1EE reference.

**Emulators: ALL PASS.** **Not tested on a car.**

## Built
- `lflweb_igncut.patch` - ignition-cut limiter, launch control, flat-foot shift
- rev-match: **not built** (see warnings)
- `lflweb_overrun.patch` - timed overrun crackle
- `addresses.json` - the addresses below; `lflweb_custom_tables.xml` - NC Flash / EcuFlash table definitions

## Warnings and what you still have to do
- Rev-match NOT built: 2 task-list routines write the engine-side pedal (LFJ1EE has 1): this software drives the throttle differently, so rev-match needs a manual port.
- The clutch address (used by launch control and flat shift) comes from code similarity: CONFIRM on the car with RAM snapshots before relying on it.
- overrun crackle: its duration is counted in calls of the decel fuel-cut task, assumed 90 per second (table "Overrun - Task calls per second"). Time a burst on the car and correct that table if it is off.

## Addresses
| Name | LFJ1EE | LFLWEB | How found |
|---|---|---|---|
| rpm | `0xFFFF6D5C` | `0xFFFF6DB8` | vote; 36/36 references agree |
| speed | `0xFFFF6D04` | `0xFFFF6D60` | vote; 32/33 references agree |
| pedal_in | `0xFFFF56C8` | `0xFFFF56C4` | vote; 6/7 references agree |
| pedal_out | `0xFFFF6CA4` | `0xFFFF6CFC` | vote; 6/6 references agree |
| clutch | `0xFFFF7100` | `0xFFFF7192` | vote; 12/12 references agree |
| brake | `0xFFFF70EE` | `0xFFFF7182` | vote; 30/30 references agree |
| dwell_flag | `0xFFFF7346` | `0xFFFF742C` | site; 35/36 references agree |
| spark_term | `0xFFFF7D68` | `0xFFFF7CBC` | site; 1/2 references agree |
| cruise_flag | `0xFFFF585E` | `0xFFFF5882` | site; 27/27 references agree |
| fuel_cut_rpm | `0xC487C` | `0xC5018` | site; 1/1 references agree |
| factory_short_dwell | `0xBB9FC` | `0xBB990` | site; 1/1 references agree |
| ect | `0xFFFF6D44` | `0xFFFF6DA0` | vote; 3/3 references agree |
| dfco_mult | `0xFFFF7560` | `0xFFFF7634` | site; 9/9 references agree |
| spark2_term | `0xFFFF9F74` | `0xFFFF7CE0` | site (a term of the spark-advance sum) |
| dwell_site | `0x50D00` | `0x53432` | code site |
| spark_site | `0x4DAE8` | `0x5011C` | code site |
| pedal_copy | `0x387F8` | not found | code site |
| crosscheck_lit | `0xB61F0` | `0xB63D8` | code site |
| spark2_site | `0x4DAF4` | `0x50128` | code site |
| dfco_routine | `0x45940` | `0x47880` | code site |
| dfco_lit | `0x1384C` | `0x141D8` | code site |
| task_literals | `0x11B00`, `0x134D4` |  | literals pointing to the pedal copy |
| id_offset | `0xB8046` | `0xB8046` | calibration ID string |

## Bytes the patches change
`141D9-141DA`, `5011E-5012F`, `502F8-50303`, `53432-5344B`, `53529-5352B`, `FE000-FE117`, `FE180-FE1AF`, `FE201-FE26F`, `FE2FC-FE2FF`, `FF000-FF037`, `FF040-FF06D`, `FF080-FF33B`, `FF3F0-FF3FB`

## Emulator output
- `igncut_emu.py`: ALL PASS
- `overrun_emu.py`: ALL PASS

## Next steps
1. Confirm the clutch address on the car (RAM snapshots).
2. Overrun crackle is off by default: enable it and set Strength in NC Flash (docs/overrun.md).
3. Add the table definitions to NC Flash / EcuFlash.
4. Apply the patches to your ROM.
5. Full Flash, then test one feature at a time with a datalog (docs/ignition-cut.md).

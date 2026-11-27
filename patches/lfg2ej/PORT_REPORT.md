# Port report: LFG2EJ

Pre-ported and bundled with NC Patcher. Generated 2026-11-27 from a stock LFG2EJ ROM and the stock LFJ1EE reference.

**Emulators: ALL PASS.** **Not tested on a car.**

## Built
- `lfg2ej_igncut.patch` - ignition-cut limiter, launch control, flat-foot shift
- `lfg2ej_downshift_revmatch.patch` - rev-match, upshift hold, anti-stall
- `lfg2ej_overrun.patch` - timed overrun crackle
- `addresses.json` - the addresses below; `lfg2ej_custom_tables.xml` - NC Flash / EcuFlash table definitions

## Warnings and what you still have to do
- The clutch and brake addresses come from code similarity: CONFIRM on the car with RAM snapshots before relying on them.
- rev-match gearing (RPM per km/h) was calculated from this ROM's 6-speed manual ratios and final drive (138.4, 82, 59.5, 42.7, 36.3, 30.2) assuming stock tyre size - check it against a datalog (docs/rev-match.md) if you run different tyres.
- overrun crackle: its duration is counted in calls of the decel fuel-cut task, assumed 90 per second (table "Overrun - Task calls per second"). Time a burst on the car and correct that table if it is off.

## Addresses
| Name | LFJ1EE | LFG2EJ | How found |
|---|---|---|---|
| rpm | `0xFFFF6D5C` | `0xFFFF6D58` | vote; 38/38 references agree |
| speed | `0xFFFF6D04` | `0xFFFF6D00` | vote; 38/38 references agree |
| pedal_in | `0xFFFF56C8` | `0xFFFF56C4` | vote; 9/9 references agree |
| pedal_out | `0xFFFF6CA4` | `0xFFFF6CA0` | vote; 9/9 references agree |
| clutch | `0xFFFF7100` | `0xFFFF70F6` | vote; 13/13 references agree |
| brake | `0xFFFF70EE` | `0xFFFF70E6` | vote; 33/34 references agree |
| dwell_flag | `0xFFFF7346` | `0xFFFF733E` | site; 38/38 references agree |
| spark_term | `0xFFFF7D68` | `0xFFFF7D74` | site; 2/2 references agree |
| cruise_flag | `0xFFFF585E` | `0xFFFF585A` | site; 28/28 references agree |
| fuel_cut_rpm | `0xC487C` | `0xC487C` | site; 1/1 references agree |
| factory_short_dwell | `0xBB9FC` | `0xBB9FC` | site; 1/1 references agree |
| ect | `0xFFFF6D44` | `0xFFFF6D40` | vote; 3/3 references agree |
| dfco_mult | `0xFFFF7560` | `0xFFFF754C` | site; 13/13 references agree |
| spark2_term | `0xFFFF9F74` | `0xFFFFA09C` | site (a term of the spark-advance sum) |
| dwell_site | `0x50D00` | `0x51280` | code site |
| spark_site | `0x4DAE8` | `0x4DF8C` | code site |
| pedal_copy | `0x387F8` | `0x3894E` | code site |
| crosscheck_lit | `0xB61F0` | `0xB61F4` | code site |
| spark2_site | `0x4DAF4` | `0x4DF98` | code site |
| dfco_routine | `0x45940` | `0x45A38` | code site |
| dfco_lit | `0x1384C` | `0x13818` | code site |
| task_literals | `0x11B00`, `0x134D4` | `0x11AD0`, `0x134A4` | literals pointing to the pedal copy |
| id_offset | `0xB8046` | `0xB8046` | calibration ID string |

## Bytes the patches change
`11AD1-11AD3`, `134A5-134A7`, `13819-1381B`, `4DF8E-4DF9F`, `4E164-4E16F`, `51280-51299`, `5135D-5135F`, `B61F6-B61F7`, `FE000-FE117`, `FE180-FE1AF`, `FE201-FE26F`, `FE2FC-FE347`, `FE350-FE379`, `FE400-FE773`, `FF000-FF037`, `FF040-FF06D`, `FF080-FF33B`, `FF3F0-FF3FB`

## Emulator output
- `igncut_emu.py`: ALL PASS
- `revemu.py`: ALL PASS
- `overrun_emu.py`: ALL PASS

## Next steps
1. Confirm the clutch and brake addresses on the car (RAM snapshots).
2. Set your gearing in the rev-match RPM-per-km/h table.
3. Overrun crackle is off by default: enable it and set Strength in NC Flash (docs/overrun.md).
4. Add the table definitions to NC Flash / EcuFlash.
5. Apply the patches to your ROM.
6. Full Flash, then test one feature at a time with a datalog (docs/ignition-cut.md, docs/rev-match.md).

# Port report: LFLGEC

Pre-ported and bundled with NC Patcher. Generated 2026-11-27 from a stock LFLGEC ROM and the stock LFJ1EE reference.

**Emulators: ALL PASS.** **Not tested on a car.**

## Built
- `lflgec_igncut.patch` - ignition-cut limiter, launch control, flat-foot shift
- `lflgec_downshift_revmatch.patch` - rev-match, upshift hold, anti-stall
- `lflgec_overrun.patch` - timed overrun crackle
- traction control: available (installed with NC Patcher or `scripts/build_tc.py`; no .patch file)
- `addresses.json` - the addresses below; `lflgec_custom_tables.xml` - NC Flash / EcuFlash table definitions

## Warnings and what you still have to do
- two-path throttle software: the engine-side pedal 0xFFFF6CF0 is written by two copy routines, one per task list: 0x3926C copies the pedal stage 0xFFFF6CF4 (task literal 0x121ec), 0x39276 copies the processed value 0xFFFFA49C (task literal 0x13c08). Rev-match and traction control take over both (a second entry point each), so the throttle request is always max(that path, the rev-match blip). This layout is NOT yet proven on a car: test rev-match carefully.
- The clutch and brake addresses come from code similarity: CONFIRM on the car with RAM snapshots before relying on them.
- rev-match gearing (RPM per km/h) was calculated from this ROM's 6-speed manual ratios and final drive (122.3, 72.2, 50.7, 38.8, 33, 27.4) assuming stock tyre size - check it against a datalog (docs/rev-match.md) if you run different tyres.
- overrun crackle: its duration is counted in calls of the decel fuel-cut task, assumed 90 per second (table "Overrun - Task calls per second"). Time a burst on the car and correct that table if it is off.

## Addresses
| Name | LFJ1EE | LFLGEC | How found |
|---|---|---|---|
| rpm | `0xFFFF6D5C` | `0xFFFF6DAC` | vote; 37/37 references agree |
| speed | `0xFFFF6D04` | `0xFFFF6D54` | vote; 36/36 references agree |
| pedal_in | `0xFFFF56C8` | `0xFFFF6CF4` | vote; 7/7 references agree |
| pedal_out | `0xFFFF6CA4` | `0xFFFF6CF0` | vote; 6/6 references agree |
| clutch | `0xFFFF7100` | `0xFFFF718C` | vote; 12/12 references agree |
| brake | `0xFFFF70EE` | `0xFFFF717A` | vote; 32/32 references agree |
| dwell_flag | `0xFFFF7346` | `0xFFFF73EC` | site; 37/38 references agree |
| spark_term | `0xFFFF7D68` | `0xFFFF7E14` | site; 2/2 references agree |
| cruise_flag | `0xFFFF585E` | `0xFFFF5882` | site; 27/27 references agree |
| fuel_cut_rpm | `0xC487C` | `0xC4CBC` | site; 1/1 references agree |
| factory_short_dwell | `0xBB9FC` | `0xBB650` | site; 1/1 references agree |
| ect | `0xFFFF6D44` | `0xFFFF6D94` | vote; 3/3 references agree |
| dfco_mult | `0xFFFF7560` | `0xFFFF7600` | site; 13/13 references agree |
| spark2_term | `0xFFFF9F74` | `0xFFFF9FC8` | site (a term of the spark-advance sum) |
| dwell_site | `0x50D00` | `0x52246` | code site |
| spark_site | `0x4DAE8` | `0x4F010` | code site |
| pedal_copy | `0x387F8` | `0x3926C` | code site |
| crosscheck_lit | `0xB61F0` | `0xB6324` | code site |
| spark2_site | `0x4DAF4` | `0x4F01C` | code site |
| dfco_routine | `0x45940` | `0x46D18` | code site |
| dfco_lit | `0x1384C` | `0x13FF8` | code site |
| pedal for the flat-shift check | `0xFFFF56C8` | `0xFFFF56C4` | vote (pedal sensor) |
| task_literals | `0x11B00`, `0x134D4` | `0x121EC` | literals pointing to the pedal copy |
| pedal stage (path 1 source) | - | `0xFFFF6CF4` | two-path software: what the first copy copies |
| pedal_copy2 | - | `0x39276` | two-path software: second copy routine |
| pedal_in2 | - | `0xFFFFA49C` | two-path software: processed value the second copy copies |
| task_literals2 | - | `0x13C08` | literal pointing to the second copy |
| id_offset | `0xB8046` | `0xB8046` | calibration ID string |

## Bytes the patches change
`121ED-121EF`, `13C09-13C0B`, `13FF9-13FFB`, `4F012-4F023`, `4F1E8-4F1F3`, `52246-5225F`, `5233D-5233F`, `B6326-B6327`, `FE000-FE117`, `FE180-FE1AF`, `FE201-FE26F`, `FE2FC-FE347`, `FE350-FE39E`, `FE3B8-FE3BF`, `FE400-FE773`, `FE7C0-FE7D3`, `FE800-FE977`, `FE9C0-FE9CB`, `FF000-FF037`, `FF040-FF06D`, `FF080-FF33B`, `FF3F0-FF3FB`

## Emulator output
- `igncut_emu.py`: ALL PASS
- `revemu.py`: ALL PASS
- `overrun_emu.py`: ALL PASS
- `tc_emu.py`: ALL PASS

## Next steps
1. Confirm the clutch and brake addresses on the car (RAM snapshots).
2. Set your gearing in the rev-match RPM-per-km/h table.
3. Overrun crackle is off by default: enable it and set Strength in NC Flash (docs/overrun.md).
4. Add the table definitions to NC Flash / EcuFlash.
5. Apply the patches to your ROM.
6. Full Flash, then test one feature at a time with a datalog (docs/ignition-cut.md, docs/rev-match.md).

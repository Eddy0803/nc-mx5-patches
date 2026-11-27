# Port report: L831ED

Pre-ported and bundled with NC Patcher. Generated 2026-11-27 from a stock L831ED ROM and the stock LFJ1EE reference.

**Emulators: ALL PASS.** **Not tested on a car.**

## Built
- `l831ed_igncut.patch` - ignition-cut limiter, launch control, flat-foot shift
- `l831ed_downshift_revmatch.patch` - rev-match, upshift hold, anti-stall
- `l831ed_overrun.patch` - timed overrun crackle
- traction control: available (installed with NC Patcher or `scripts/build_tc.py`; no .patch file)
- `addresses.json` - the addresses below; `l831ed_custom_tables.xml` - NC Flash / EcuFlash table definitions

## Warnings and what you still have to do
- rev-match RAM 0xFFFFAC10-17 / AC50-59 appears to be referenced at: 0xFFFFAC10 by mov.w at 0x944E2 - check with tools/dis.py whether that is real code (data tables can look like mov.w).
- The clutch and brake addresses come from code similarity: CONFIRM on the car with RAM snapshots before relying on them.
- rev-match gearing (RPM per km/h) was calculated from this ROM's 5-speed manual ratios and final drive (113.8, 68.5, 48.3, 36.3, 29.5, 0) assuming stock tyre size - check it against a datalog (docs/rev-match.md) if you run different tyres.
- overrun crackle: its duration is counted in calls of the decel fuel-cut task, assumed 90 per second (table "Overrun - Task calls per second"). Time a burst on the car and correct that table if it is off.

## Addresses
| Name | LFJ1EE | L831ED | How found |
|---|---|---|---|
| rpm | `0xFFFF6D5C` | `0xFFFF6D58` | vote; 38/38 references agree |
| speed | `0xFFFF6D04` | `0xFFFF6D00` | vote; 39/39 references agree |
| pedal_in | `0xFFFF56C8` | `0xFFFF56C4` | vote; 9/9 references agree |
| pedal_out | `0xFFFF6CA4` | `0xFFFF6CA0` | vote; 10/10 references agree |
| clutch | `0xFFFF7100` | `0xFFFF70FC` | vote; 13/13 references agree |
| brake | `0xFFFF70EE` | `0xFFFF70EA` | vote; 34/34 references agree |
| dwell_flag | `0xFFFF7346` | `0xFFFF7325` | site; 39/39 references agree |
| spark_term | `0xFFFF7D68` | `0xFFFF7D40` | site; 2/2 references agree |
| cruise_flag | `0xFFFF585E` | `0xFFFF585A` | site; 27/27 references agree |
| fuel_cut_rpm | `0xC487C` | `0xC486C` | site; 1/1 references agree |
| factory_short_dwell | `0xBB9FC` | `0xBB9FC` | site; 1/1 references agree |
| ect | `0xFFFF6D44` | `0xFFFF6D40` | vote; 3/3 references agree |
| dfco_mult | `0xFFFF7560` | `0xFFFF7538` | site; 14/14 references agree |
| spark2_term | `0xFFFF9F74` | `0xFFFF9F44` | site (a term of the spark-advance sum) |
| dwell_site | `0x50D00` | `0x50674` | code site |
| spark_site | `0x4DAE8` | `0x4D45C` | code site |
| pedal_copy | `0x387F8` | `0x38738` | code site |
| crosscheck_lit | `0xB61F0` | `0xB61B4` | code site |
| spark2_site | `0x4DAF4` | `0x4D468` | code site |
| dfco_routine | `0x45940` | `0x45338` | code site |
| dfco_lit | `0x1384C` | `0x13840` | code site |
| task_literals | `0x11B00`, `0x134D4` | `0x11B00`, `0x134CC` | literals pointing to the pedal copy |
| id_offset | `0xB8046` | `0xB8046` | calibration ID string |

## Bytes the patches change
`11B01-11B03`, `134CD-134CF`, `13841-13843`, `4D45E-4D46F`, `4D634-4D63F`, `50674-5068D`, `50751-50753`, `B61B6-B61B7`, `FE000-FE117`, `FE180-FE1AF`, `FE201-FE26F`, `FE2FC-FE347`, `FE350-FE39E`, `FE3BC-FE3BF`, `FE400-FE773`, `FE800-FE977`, `FF000-FF037`, `FF040-FF06D`, `FF080-FF33B`, `FF3F0-FF3FB`

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

## Review of the RAM warnings
- rev-match RAM 0xFFFFAC10 "referenced by mov.w at 0x944E2": checked by hand - that location is inside a table of 32-bit ROM addresses (data), so the "mov.w" is the low half of a stored address, not an instruction, and the value is never used as a RAM address. False alarm.

# Port report: LFLPEB

Pre-ported and bundled with NC Patcher. Generated 2026-11-27 from a stock LFLPEB ROM and the stock LFJ1EE reference.

**Emulators: ALL PASS.** **Not tested on a car.**

## Built
- `lflpeb_igncut.patch` - ignition-cut limiter, launch control, flat-foot shift
- `lflpeb_downshift_revmatch.patch` - rev-match, upshift hold, anti-stall
- `lflpeb_overrun.patch` - timed overrun crackle
- traction control: available (installed with NC Patcher or `scripts/build_tc.py`; no .patch file)
- `addresses.json` - the addresses below; `lflpeb_custom_tables.xml` - NC Flash / EcuFlash table definitions

## Warnings and what you still have to do
- two-path throttle software: the engine-side pedal 0xFFFF6D1C is written by two copy routines, one per task list: 0x3A04E copies the pedal stage 0xFFFF6D20 (task literal 0x16b38), 0x3A058 copies the processed value 0xFFFFA970 (task literal 0x18728). Rev-match and traction control take over both (a second entry point each), so the throttle request is always max(that path, the rev-match blip). This layout is NOT yet proven on a car: test rev-match carefully. The pedal stage has a factory pedal override (calibration byte 0xC2CA6, currently 0); while it is not 0, both copies run unchanged.
- rev-match RAM 0xFFFFAC10-17 / AC50-59 appears to be referenced at: 0xFFFFAC50 by mov.w at 0xA475A - check with tools/dis.py whether that is real code (data tables can look like mov.w).
- The clutch and brake addresses come from code similarity: CONFIRM on the car with RAM snapshots before relying on them.
- rev-match gearing (RPM per km/h) was calculated from this ROM's 6-speed manual ratios and final drive (138.4, 82, 59.5, 42.7, 36.3, 28.6) assuming stock tyre size - check it against a datalog (docs/rev-match.md) if you run different tyres.
- overrun crackle: its duration is counted in calls of the decel fuel-cut task, assumed 90 per second (table "Overrun - Task calls per second"). Time a burst on the car and correct that table if it is off.

## Addresses
| Name | LFJ1EE | LFLPEB | How found |
|---|---|---|---|
| rpm | `0xFFFF6D5C` | `0xFFFF6DD8` | vote; 36/36 references agree |
| speed | `0xFFFF6D04` | `0xFFFF6D80` | vote; 32/33 references agree |
| pedal_in | `0xFFFF56C8` | `0xFFFF6D20` | vote; 6/7 references agree |
| pedal_out | `0xFFFF6CA4` | `0xFFFF6D1C` | vote; 6/6 references agree |
| clutch | `0xFFFF7100` | `0xFFFF7262` | vote; 11/11 references agree |
| brake | `0xFFFF70EE` | `0xFFFF7252` | vote; 30/30 references agree |
| dwell_flag | `0xFFFF7346` | `0xFFFF73F2` | site; 35/36 references agree |
| spark_term | `0xFFFF7D68` | `0xFFFF7C40` | site; 1/2 references agree |
| cruise_flag | `0xFFFF585E` | `0xFFFF522A` | site; 27/27 references agree |
| fuel_cut_rpm | `0xC487C` | `0xCCC68` | site; 1/1 references agree |
| factory_short_dwell | `0xBB9FC` | `0xC35D4` | site; 1/1 references agree |
| ect | `0xFFFF6D44` | `0xFFFF6DC0` | vote; 3/3 references agree |
| dfco_mult | `0xFFFF7560` | `0xFFFF75F8` | site; 9/9 references agree |
| spark2_term | `0xFFFF9F74` | `0xFFFF7C6C` | site (a term of the spark-advance sum) |
| dwell_site | `0x50D00` | `0x4F9FE` | code site |
| spark_site | `0x4DAE8` | `0x502C0` | code site |
| pedal_copy | `0x387F8` | `0x3A04E` | code site |
| crosscheck_lit | `0xB61F0` | `0xBE3EC` | code site |
| spark2_site | `0x4DAF4` | `0x502CC` | code site |
| dfco_routine | `0x45940` | `0x47A94` | code site |
| dfco_lit | `0x1384C` | `0x18B18` | code site |
| pedal_override | - | `0xC2CA6` | calibration byte of the factory pedal override in the pedal copy |
| pedal for the flat-shift check | `0xFFFF56C8` | `0xFFFF5318` | vote (pedal sensor) |
| task_literals | `0x11B00`, `0x134D4` | `0x16B38` | literals pointing to the pedal copy |
| pedal stage (path 1 source) | - | `0xFFFF6D20` | two-path software: what the first copy copies |
| pedal_copy2 | - | `0x3A058` | two-path software: second copy routine |
| pedal_in2 | - | `0xFFFFA970` | two-path software: processed value the second copy copies |
| task_literals2 | - | `0x18728` | literal pointing to the second copy |
| id_offset | `0xB8046` | `0xC0046` | calibration ID string |

## Bytes the patches change
`16B39-16B3B`, `18729-1872B`, `18B19-18B1B`, `4F9FE-4FA17`, `4FAF5-4FAF7`, `502C2-502D3`, `5049C-504A7`, `BE3EE-BE3EF`, `FE000-FE117`, `FE180-FE1AF`, `FE201-FE26F`, `FE2FC-FE347`, `FE350-FE39E`, `FE3B8-FE3BF`, `FE400-FE787`, `FE7C0-FE7E7`, `FE800-FE977`, `FE9C0-FE9CB`, `FF000-FF037`, `FF040-FF06D`, `FF080-FF33B`, `FF3F0-FF3FB`

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
- rev-match RAM 0xFFFFAC50 "referenced by mov.w at 0xA475A": checked by hand - that location is inside a table of 32-bit ROM addresses (data), so the "mov.w" is the low half of a stored address, not an instruction; the word it "loads" is the low half of the ROM address 0x000DAC50, not the RAM byte. Not a real reference.

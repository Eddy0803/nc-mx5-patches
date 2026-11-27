# Port report: LF9HEE

Pre-ported and bundled with NC Patcher. Generated 2026-11-27 from a stock LF9HEE ROM and the stock LFJ1EE reference.

**Emulators: ALL PASS.** **Not tested on a car.**

## Built
- `lf9hee_igncut.patch` - ignition-cut limiter, launch control, flat-foot shift
- rev-match: **not built** (see warnings)
- `lf9hee_overrun.patch` - timed overrun crackle
- traction control: **not available** (see warnings)
- `addresses.json` - the addresses below; `lf9hee_custom_tables.xml` - NC Flash / EcuFlash table definitions

## Warnings and what you still have to do
- overrun RAM 0xFFFFACD0-E3 looks referenced at: 0xFFFFACD0 by mov.w at 0x943D2 - check with tools/dis.py whether that is real code (data tables can look like mov.w).
- Rev-match NOT built: 2 task-list routines write the engine-side pedal (LFJ1EE has 1): this software drives the throttle differently, so rev-match needs a manual port.
- The clutch address (used by launch control and flat shift) comes from code similarity: CONFIRM on the car with RAM snapshots before relying on it.
- Traction control NOT available: it runs from the same task slot as rev-match.
- overrun crackle: its duration is counted in calls of the decel fuel-cut task, assumed 90 per second (table "Overrun - Task calls per second"). Time a burst on the car and correct that table if it is off.

## Addresses
| Name | LFJ1EE | LF9HEE | How found |
|---|---|---|---|
| rpm | `0xFFFF6D5C` | `0xFFFF6D88` | vote; 37/37 references agree |
| speed | `0xFFFF6D04` | `0xFFFF6D30` | vote; 36/36 references agree |
| pedal_in | `0xFFFF56C8` | `0xFFFF56C4` | vote; 7/7 references agree |
| pedal_out | `0xFFFF6CA4` | `0xFFFF6CCC` | vote; 7/7 references agree |
| clutch | `0xFFFF7100` | `0xFFFF7130` | vote; 12/12 references agree |
| brake | `0xFFFF70EE` | `0xFFFF711E` | vote; 33/33 references agree |
| dwell_flag | `0xFFFF7346` | `0xFFFF7374` | site; 37/38 references agree |
| spark_term | `0xFFFF7D68` | `0xFFFF7D94` | site; 2/2 references agree |
| cruise_flag | `0xFFFF585E` | `0xFFFF5866` | site; 27/27 references agree |
| fuel_cut_rpm | `0xC487C` | `0xC49C4` | site; 1/1 references agree |
| factory_short_dwell | `0xBB9FC` | `0xBB5D4` | site; 1/1 references agree |
| ect | `0xFFFF6D44` | `0xFFFF6D70` | vote; 3/3 references agree |
| dfco_mult | `0xFFFF7560` | `0xFFFF7588` | site; 13/13 references agree |
| spark2_term | `0xFFFF9F74` | `0xFFFF9F38` | site (a term of the spark-advance sum) |
| dwell_site | `0x50D00` | `0x51858` | code site |
| spark_site | `0x4DAE8` | `0x4E640` | code site |
| pedal_copy | `0x387F8` | not found | code site |
| crosscheck_lit | `0xB61F0` | `0xB6314` | code site |
| spark2_site | `0x4DAF4` | `0x4E64C` | code site |
| dfco_routine | `0x45940` | `0x46380` | code site |
| dfco_lit | `0x1384C` | `0x13F60` | code site |
| task_literals | `0x11B00`, `0x134D4` |  | literals pointing to the pedal copy |
| id_offset | `0xB8046` | `0xB8046` | calibration ID string |

## Bytes the patches change
`13F61-13F62`, `4E642-4E653`, `4E818-4E823`, `51858-51871`, `51935-51937`, `FE000-FE117`, `FE180-FE1AF`, `FE201-FE26F`, `FE2FC-FE2FF`, `FF000-FF037`, `FF040-FF06D`, `FF080-FF33B`, `FF3F0-FF3FB`

## Emulator output
- `igncut_emu.py`: ALL PASS
- `overrun_emu.py`: ALL PASS

## Next steps
1. Confirm the clutch address on the car (RAM snapshots).
2. Overrun crackle is off by default: enable it and set Strength in NC Flash (docs/overrun.md).
3. Add the table definitions to NC Flash / EcuFlash.
4. Apply the patches to your ROM.
5. Full Flash, then test one feature at a time with a datalog (docs/ignition-cut.md).

## Review of the RAM warnings
- overrun RAM 0xFFFFACD0 "referenced by mov.w at 0x943D2": checked by hand - that location is inside a table of 32-bit ROM addresses (data), so the "mov.w" is the low half of a stored address, not an instruction, and the value is never used as a RAM address. False alarm.

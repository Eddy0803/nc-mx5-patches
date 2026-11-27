# Port report: LFGNEE

Pre-ported and bundled with NC Patcher. Generated 2026-11-27 from a stock LFGNEE ROM and the stock LFJ1EE reference.

**Emulators: ALL PASS.** **Not tested on a car.**

## Built
- `lfgnee_igncut.patch` - ignition-cut limiter, launch control, flat-foot shift
- `lfgnee_downshift_revmatch.patch` - rev-match, upshift hold, anti-stall
- `lfgnee_overrun.patch` - timed overrun crackle
- traction control: available (installed with NC Patcher or `scripts/build_tc.py`; no .patch file)
- `addresses.json` - the addresses below; `lfgnee_custom_tables.xml` - NC Flash / EcuFlash table definitions

## Warnings and what you still have to do
- two-path throttle software: the engine-side pedal 0xFFFF6CFC is written by two copy routines, one per task list: 0x39E6A copies the pedal stage 0xFFFF6D00 (task literal 0x16b0c), 0x39E74 copies the processed value 0xFFFFA834 (task literal 0x186d4). Rev-match and traction control take over both (a second entry point each), so the throttle request is always max(that path, the rev-match blip). This layout is NOT yet proven on a car: test rev-match carefully. The pedal stage has a factory pedal override (calibration byte 0xC2CA6, currently 0); while it is not 0, both copies run unchanged.
- The clutch and brake addresses come from code similarity: CONFIRM on the car with RAM snapshots before relying on them.
- rev-match gearing (RPM per km/h) was calculated from this ROM's 5-speed manual ratios and final drive (113.8, 68.5, 48.3, 36.3, 29.5, 0) assuming stock tyre size - check it against a datalog (docs/rev-match.md) if you run different tyres.
- overrun crackle: its duration is counted in calls of the decel fuel-cut task, assumed 90 per second (table "Overrun - Task calls per second"). Time a burst on the car and correct that table if it is off.

## Addresses
| Name | LFJ1EE | LFGNEE | How found |
|---|---|---|---|
| rpm | `0xFFFF6D5C` | `0xFFFF6DB8` | vote; 36/36 references agree |
| speed | `0xFFFF6D04` | `0xFFFF6D60` | vote; 32/33 references agree |
| pedal_in | `0xFFFF56C8` | `0xFFFF6D00` | vote; 6/7 references agree |
| pedal_out | `0xFFFF6CA4` | `0xFFFF6CFC` | vote; 7/7 references agree |
| clutch | `0xFFFF7100` | `0xFFFF7242` | vote; 12/12 references agree |
| brake | `0xFFFF70EE` | `0xFFFF7232` | vote; 30/30 references agree |
| dwell_flag | `0xFFFF7346` | `0xFFFF73C8` | site; 35/36 references agree |
| spark_term | `0xFFFF7D68` | `0xFFFF7C18` | site; 1/2 references agree |
| cruise_flag | `0xFFFF585E` | `0xFFFF522A` | site; 27/27 references agree |
| fuel_cut_rpm | `0xC487C` | `0xCCC5C` | site; 1/1 references agree |
| factory_short_dwell | `0xBB9FC` | `0xC35D4` | site; 1/1 references agree |
| ect | `0xFFFF6D44` | `0xFFFF6DA0` | vote; 3/3 references agree |
| dfco_mult | `0xFFFF7560` | `0xFFFF75D0` | site; 9/9 references agree |
| spark2_term | `0xFFFF9F74` | `0xFFFF7C44` | site (a term of the spark-advance sum) |
| dwell_site | `0x50D00` | `0x4F6A6` | code site |
| spark_site | `0x4DAE8` | `0x4FF68` | code site |
| pedal_copy | `0x387F8` | `0x39E6A` | code site |
| crosscheck_lit | `0xB61F0` | `0xBE3CC` | code site |
| spark2_site | `0x4DAF4` | `0x4FF74` | code site |
| dfco_routine | `0x45940` | `0x477DC` | code site |
| dfco_lit | `0x1384C` | `0x18AC4` | code site |
| pedal_override | - | `0xC2CA6` | calibration byte of the factory pedal override in the pedal copy |
| pedal for the flat-shift check | `0xFFFF56C8` | `0xFFFF5318` | vote (pedal sensor) |
| task_literals | `0x11B00`, `0x134D4` | `0x16B0C` | literals pointing to the pedal copy |
| pedal stage (path 1 source) | - | `0xFFFF6D00` | two-path software: what the first copy copies |
| pedal_copy2 | - | `0x39E74` | two-path software: second copy routine |
| pedal_in2 | - | `0xFFFFA834` | two-path software: processed value the second copy copies |
| task_literals2 | - | `0x186D4` | literal pointing to the second copy |
| id_offset | `0xB8046` | `0xC0046` | calibration ID string |

## Bytes the patches change
`16B0D-16B0F`, `186D5-186D7`, `18AC5-18AC7`, `4F6A6-4F6BF`, `4F79D-4F79F`, `4FF6A-4FF7B`, `50144-5014F`, `BE3CE-BE3CF`, `FE000-FE117`, `FE180-FE1AF`, `FE201-FE26F`, `FE2FC-FE347`, `FE350-FE39E`, `FE3B8-FE3BF`, `FE400-FE787`, `FE7C0-FE7E7`, `FE800-FE977`, `FE9C0-FE9CB`, `FF000-FF037`, `FF040-FF06D`, `FF080-FF33B`, `FF3F0-FF3FB`

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

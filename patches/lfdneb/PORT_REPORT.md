# Port report: LFDNEB

Pre-ported and bundled with NC Patcher. Generated 2026-11-27 from a stock LFDNEB ROM and the stock LFJ1EE reference.

**Emulators: ALL PASS.** **Not tested on a car.**

## Built
- `lfdneb_igncut.patch` - ignition-cut limiter, launch control, flat-foot shift
- `lfdneb_downshift_revmatch.patch` - rev-match, upshift hold, anti-stall
- `lfdneb_overrun.patch` - timed overrun crackle
- `addresses.json` - the addresses below; `lfdneb_custom_tables.xml` - NC Flash / EcuFlash table definitions

## Warnings and what you still have to do
- the pedal copy has a factory pedal override, switched on by calibration byte 0xBACA6 (currently 0). Rev-match only runs while that byte is 0; when it is not 0 the factory routine runs unchanged.
- The clutch and brake addresses come from code similarity: CONFIRM on the car with RAM snapshots before relying on them.
- rev-match gearing (RPM per km/h) was calculated from this ROM's 5-speed manual ratios and final drive (113.8, 68.5, 48.3, 36.3, 29.5, 0) assuming stock tyre size - check it against a datalog (docs/rev-match.md) if you run different tyres.
- overrun crackle: its duration is counted in calls of the decel fuel-cut task, assumed 90 per second (table "Overrun - Task calls per second"). Time a burst on the car and correct that table if it is off.

## Addresses
| Name | LFJ1EE | LFDNEB | How found |
|---|---|---|---|
| rpm | `0xFFFF6D5C` | `0xFFFF6DA8` | vote; 36/36 references agree |
| speed | `0xFFFF6D04` | `0xFFFF6D50` | vote; 32/33 references agree |
| pedal_in | `0xFFFF56C8` | `0xFFFF5318` | vote; 8/8 references agree |
| pedal_out | `0xFFFF6CA4` | `0xFFFF6CF0` | vote; 8/8 references agree |
| clutch | `0xFFFF7100` | `0xFFFF7232` | vote; 13/13 references agree |
| brake | `0xFFFF70EE` | `0xFFFF7222` | vote; 30/32 references agree |
| dwell_flag | `0xFFFF7346` | `0xFFFF73B8` | site; 36/37 references agree |
| spark_term | `0xFFFF7D68` | `0xFFFF7C04` | site; 1/2 references agree |
| cruise_flag | `0xFFFF585E` | `0xFFFF522A` | site; 27/27 references agree |
| fuel_cut_rpm | `0xC487C` | `0xC49E0` | site; 1/1 references agree |
| factory_short_dwell | `0xBB9FC` | `0xBB5D4` | site; 1/1 references agree |
| ect | `0xFFFF6D44` | `0xFFFF6D90` | vote; 3/3 references agree |
| dfco_mult | `0xFFFF7560` | `0xFFFF75C0` | site; 9/9 references agree |
| spark2_term | `0xFFFF9F74` | `0xFFFF7C30` | site (a term of the spark-advance sum) |
| dwell_site | `0x50D00` | `0x4F3CA` | code site |
| spark_site | `0x4DAE8` | `0x4FC70` | code site |
| pedal_copy | `0x387F8` | `0x39C0A` | code site |
| crosscheck_lit | `0xB61F0` | `0xB62F4` | code site |
| spark2_site | `0x4DAF4` | `0x4FC7C` | code site |
| dfco_routine | `0x45940` | `0x474F8` | code site |
| dfco_lit | `0x1384C` | `0x18A70` | code site |
| pedal_override | - | `0xBACA6` | calibration byte of the factory pedal override in the pedal copy |
| task_literals | `0x11B00`, `0x134D4` | `0x168D0`, `0x18700` | literals pointing to the pedal copy |
| id_offset | `0xB8046` | `0xB8046` | calibration ID string |

## Bytes the patches change
`168D1-168D3`, `18701-18703`, `18A71-18A73`, `4F3CA-4F3E3`, `4F4AD-4F4AF`, `4FC72-4FC83`, `4FE4C-4FE57`, `B62F6-B62F7`, `FE000-FE117`, `FE180-FE1AF`, `FE201-FE26F`, `FE2FC-FE347`, `FE350-FE379`, `FE400-FE787`, `FF000-FF037`, `FF040-FF06D`, `FF080-FF33B`, `FF3F0-FF3FB`

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

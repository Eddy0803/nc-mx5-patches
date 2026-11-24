# Using these patches on a different ECU code

**The patches in this repo only work on `LFJ1EE`.** They write code and pointers at exact addresses, and read RAM variables at exact addresses, all specific to that software. Applying them to another calibration would at best be refused by the scripts, and at worst stop the car running.

The scripts check the bytes they change and refuse to run if they don't match. Still, never force a patch onto a different calibration.

## What differs between calibrations
1. **Code locations** of what gets hooked: the coil-dwell and spark-advance routines (ignition cut), and the task lists that call the pedal-copy routine and the throttle-plausibility check (rev-match).
2. **RAM and calibration addresses:** RPM, vehicle speed, pedal position, the clutch and brake switches, and the RPM Fuel Cut table. The brake switch on LFJ1EE was found by comparing RAM snapshots with the brake pressed and released.
3. **Free space:** the ROM areas and RAM bytes the patches use must be unused in your software.
4. **Gearing:** the RPM-per-km/h table for rev-match, for a 6-speed or a different final drive.

## How a port is done
**Step-by-step, with ready-made prompts:** [porting-with-claude.md](porting-with-claude.md) walks through all of this using Claude Code, with a full reference sheet of the LFJ1EE addresses and factory code. The outline:

1. **Start from a calibration closely related to LFJ1EE**, on a manual car.
2. **Find each hooked routine in your ROM by its instruction pattern,** ignoring the bytes that encode addresses. Related calibrations, such as other `LFJ1` builds, usually contain the same routines at shifted addresses. The RAM addresses those routines use give you the variables in item 2 above.
3. **Check that the free ROM and RAM areas really are unused** in your ROM and in RAM snapshots from your car.
4. **Confirm the clutch and brake RAM addresses on the car:** take RAM snapshots with each pedal pressed and released.
5. **Rebuild the patches with your addresses** (`scripts/build_igncut.py` and `scripts/build_revmatch.py` show exactly what's written where).
6. **Run `tests/igncut_emu.py` and `tests/revemu.py`** against your ROM, then test on the car one feature at a time, with logs.

`tools/dis.py` (a SH-2E disassembler, needs `pip install capstone`) and `tools/csum.py` (checksum checker) help with this.

## Want your calibration supported?
Open an issue with your **calibration ID**, model year and gearbox. Please **don't post your ECU read publicly:** it contains data specific to your car.

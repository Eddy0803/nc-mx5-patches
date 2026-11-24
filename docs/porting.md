# Using these patches on a different ECU code

The patches are built for **`LFJ1EE`**. Other NC calibrations run closely related Mazda software, but every routine, RAM variable and table sits at a different address. So a patch has to be **ported** before it can be used on another calibration. Never force an LFJ1EE patch onto another ROM; the scripts refuse to anyway.

There are two ways to port:
1. **Automatically, with `tools/port.py`** (below). Try this first.
2. **Step by step with Claude Code**, using [porting-with-claude.md](porting-with-claude.md). Use this when `port.py` stops, or to understand and double-check what it did.

## Automatic: `tools/port.py`
**You need:**
- **A stock read of your ECU** (before any tuning), and its **calibration ID**.
- **A stock LFJ1EE ROM** as the reference. Stock ROMs are shared in the NC tuning community.
- **Python 3.8+.**

**Run** from the repo folder:
```
python tools/port.py --ref lfj1ee_stock.bin --rom my_stock.bin --cal LFZZE0
```

**What it does:**
1. **Checks your ROM:**
   - finds the calibration ID, even where it sits somewhere other than on LFJ1EE;
   - **identifies the gearbox** from the ROM's gear-ratio table (1st gear 3.136 = 5-speed manual, 3.815 = 6-speed manual, 3.538 = 6-speed automatic). **Automatics are refused** (the patches are for manual gearboxes only), and so is a ROM with no recognisable NC gear table;
   - checks that the flash areas the patches use are empty and not covered by the ROM checksums.
2. **Finds every code site the patches hook** by instruction pattern. The bits that legitimately change between software builds are ignored, and each site's shape is checked.
3. **Finds every RAM and table address by voting:** each place the LFJ1EE code uses an address is located in your ROM and votes for the address used there. Values that can be read straight from a hook site are taken from the site, and must agree with the vote.
4. **Stops rather than guesses** if anything is missing, ambiguous, or below the confidence threshold (at least 75% of references agreeing, and at least 2). It writes nothing in that case.
5. **Builds:**
   - `patches/<cal>/addresses.json`;
   - `patches/<cal>/<cal>_igncut.patch`;
   - `patches/<cal>/<cal>_downshift_revmatch.patch`;
   - `ncflash/<cal>_custom_tables.xml`.
6. **Tests:** applies both patches to a copy of your ROM and runs both emulators.
7. **Reports:** writes `patches/<cal>/PORT_REPORT.md` with every address, how it was found and how confident it is, the bytes changed, the emulator results, the warnings and what's left for you to do.

**Rev-match is built only when it's safe to.** `port.py` leaves it out, with the reason in the report, if:
- the engine-side pedal is written by more than one task-list routine;
- the pedal copy runs from a different number of task lists than on LFJ1EE (different call rate: `--allow-call-rate` builds it anyway, for you to measure and retune);
- its RAM is already used.

The ignition cut doesn't depend on any of that.

**What it can't do:**
- **Confirm the clutch and brake addresses on your car.** They come from code similarity, which is strong evidence, but they differ between builds. Check them with RAM snapshots ([porting-with-claude.md](porting-with-claude.md#step-5-confirm-the-clutch-and-brake-on-the-car)) before relying on them. If they turn out different, rerun with `--clutch 0x…` / `--brake 0x…`.
- **Know your tyre size.** The rev-match RPM-per-km/h table is calculated from the ROM's own gear ratios and final drive, assuming stock tyres. With other tyres, or a gearbox or diff swap, set it from a datalog (see [rev-match.md](rev-match.md#set-the-rpm-per-kmh-table-for-your-car)).
- **Test on a car.** A port that passes the emulators has only been checked against the addresses it found. Test one feature at a time, with a datalog.

**After porting:** the normal tools work with your calibration:
- `scripts/apply_patch.py` and the `upgrade_*.py` settings scripts read `patches/<cal>/addresses.json`;
- `tools/add_definitions.py --cal <cal> --source ncflash/<cal>_custom_tables.xml` adds the tables to NC Flash / EcuFlash.

### How it was tested
- **LFJ1EE ported to itself:** reproduces the published patches byte for byte.
- **Four other calibrations, picked at random from the stock ROMs:**

  | Calibration | Result |
  |---|---|
  | **LFJ1EF** | Both patches built, both emulators pass. It warns about a look-alike reference to rev-match's RAM, which turned out to be a data table. |
  | **LFZZE0** | Both built, both emulators pass. Apply → change settings → remove gives the exact stock ROM back. |
  | **LFN4EP** | Both built, both emulators pass. |
  | **LFLPED** | Different layout. Ignition cut built and passes. Rev-match **refused**: two task-list routines drive the engine-side pedal in this software, so it needs a manual port. |

None of these ports has been flashed to a car.

## What differs between calibrations
1. **Code locations** of what gets hooked: the coil-dwell and spark-advance routines (ignition cut), and the task lists that call the pedal-copy routine and the throttle-plausibility check (rev-match).
2. **RAM and calibration addresses:** RPM, vehicle speed, pedal position, the clutch and brake switches, and the RPM Fuel Cut table. The brake switch on LFJ1EE was found by comparing RAM snapshots with the brake pressed and released.
3. **Free space:** the ROM areas and RAM bytes the patches use must be unused in your software.
4. **Gearing:** the RPM-per-km/h table for rev-match, for a 6-speed or a different final drive.
5. **Sometimes structure:** for example, an extra pedal stage, or the throttle driven from more than one routine (LFLPED).

`tools/dis.py` (a SH-2E disassembler, needs `pip install capstone`) and `tools/csum.py` (checksum checker) help when looking at any of this by hand.

## Want your calibration supported?
If `port.py` works for you and the patches work on your car, consider opening a pull request with your `patches/<cal>/` folder and table definitions. **Don't include ROMs.** Say which features you tested on the car.

If it stops, open an issue with your **calibration ID**, model year, gearbox, and the message it gave. Please **don't post your ECU read publicly:** it contains data specific to your car.

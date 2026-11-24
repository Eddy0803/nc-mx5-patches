# Installing (LFJ1EE)

## 1. Read your ECU and check the calibration
Read your ECU with NC Flash. The calibration ID must be **`LFJ1EE`**. If it's anything else, stop and read [porting.md](porting.md). The scripts refuse a ROM they don't recognise, but don't rely on that alone.

**Keep this original read safe.** It's your way back to stock.

**Already tuned?** You can patch your tuned ROM instead of a stock read, as long as nothing else uses the same places. The scripts check this and refuse if something does. In that case, if your tune already has its own launch control or flat-shift feature, **turn it off** so the two don't fight.

## 2. Add the patches
Install Python 3.8+ and run these from the repo folder. Each command writes a new file; your input is never changed.

```
python scripts/apply_patch.py stock.bin patches/lfj1ee/lfj1ee_igncut.patch
python scripts/apply_patch.py "stock - igncut.bin" patches/lfj1ee/lfj1ee_downshift_revmatch.patch
```

Use either patch on its own, or both in either order.

**To remove a patch,** run the same command on the patched file. It refuses if the ROM holds a different version of the patch, because removing it with the wrong file would corrupt the ROM.

## 3. Choose your settings
Either edit the tables in NC Flash (step 4), or set them with the scripts. These write another new file and keep every value you don't give:

```
python scripts/upgrade_igncut.py "stock - igncut - revmatch.bin" LAUNCH=4500 FS=5300
python scripts/upgrade_revmatch.py "stock - igncut - revmatch - igncut.bin" EN=1 UPEN=1
```

**Patch defaults:**
- **Ignition-cut limiter:** on, cutting 300 rpm below your **RPM Fuel Cut** table.
- **Launch control and flat-foot shift:** off (RPM 0).
- **Rev-match, upshift hold and anti-stall:** all off.

Run either script with no arguments to see every option. They're described in [ignition-cut.md](ignition-cut.md) and [rev-match.md](rev-match.md).

**Gearing:** rev-match needs your car's RPM per km/h for each gear. The defaults are for the 5-speed with standard final drive and tyres. See [rev-match.md](rev-match.md#set-the-rpm-per-kmh-table-for-your-car) for anything else.

## 4. Add the tables to NC Flash
1. Close NC Flash and **back up** your `lfj1ee.xml` definition file. In NC Flash it's in `%APPDATA%\NCFlash\metadata\`.
2. Open `ncflash/lfj1ee_custom_tables.xml`. Paste its `<scaling>` lines next to the other `<scaling>` entries, and the `<table>` lines for the patches you installed next to the other `<table>` entries.
3. Restart NC Flash and open your patched ROM. The tables appear under:
   - **Engine Limiter - RPM Ignition Cut**
   - **DBW - Downshift Rev Match**
   - **DBW - Anti-Stall**

## 5. Flash
- **Do a Full Flash the first time,** and again whenever anything else (another tuning tool, a dealer) has flashed the ECU since your last NC Flash flash. NC Flash's quick ("Dynamic") flash only writes blocks that differ from *its own record* of the last flash. After another tool has flashed the ECU, it can leave a mix of old and new blocks. The symptoms are code P0601, no ignition cut, or a flashing immobiliser light. A Full Flash fixes it.
- Keep a battery charger connected while flashing.
- The patches change ROM blocks the ECU checksums. NC Flash recalculates the checksums when it flashes. If your flashing tool doesn't, you'll get P0601.

## 6. Test
Test one feature at a time, in a safe place, with a datalog running. What to look for is in each patch's doc:
- [ignition-cut.md](ignition-cut.md#testing)
- [rev-match.md](rev-match.md#testing)

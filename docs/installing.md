# Installing (LFJ1EE)

## 1. Read your ECU and check the calibration
Read your ECU with NC Flash. The calibration ID must be **`LFJ1EE`**. If it's anything else, stop and read [porting.md](porting.md). The scripts refuse a ROM they don't recognise, but don't rely on that alone.

**Keep this original read safe.** It's your way back to stock.

**Already tuned?** You can patch your tuned ROM instead of a stock read, as long as nothing else uses the same places. The scripts check this and refuse if something does. In that case, if your tune already has its own launch control or flat-shift feature, **turn it off** so the two don't fight. **romdrop** on LFJ1EE has been checked and works alongside these patches: see [romdrop.md](romdrop.md).

## 2. Add the patches
Install Python 3.8+ and run these from the repo folder. Each command writes a new file; your input is never changed.

```
python scripts/apply_patch.py stock.bin patches/lfj1ee/lfj1ee_igncut.patch
python scripts/apply_patch.py "stock - igncut.bin" patches/lfj1ee/lfj1ee_downshift_revmatch.patch
python scripts/apply_patch.py "stock - igncut - revmatch.bin" patches/lfj1ee/lfj1ee_overrun.patch
```

Use any patch on its own, or several in any order.

**To remove a patch,** run the same command on the patched file. It refuses if the ROM holds a different version of the patch, because removing it with the wrong file would corrupt the ROM.

## 3. Choose your settings
Either edit the tables in NC Flash (step 4), or set them with the scripts. These write another new file and keep every value you don't give:

```
python scripts/upgrade_igncut.py "stock - igncut - revmatch - overrun.bin" LAUNCH=4500 FS=5300 OHEN=1
python scripts/upgrade_revmatch.py "stock - igncut - revmatch - overrun - igncut.bin" EN=1 UPEN=1
python scripts/upgrade_overrun.py "stock - igncut - revmatch - overrun - igncut - revmatch.bin" EN=1 STR=0
```

**Patch defaults:**
- **Ignition-cut limiter:** on, cutting 300 rpm below your **RPM Fuel Cut** table.
- **Launch control and flat-foot shift:** off (RPM 0).
- **Overheat protection** (part of the ignition cut): off. When on: the rev limit drops above 110 °C coolant, to 5000 rpm at 120 °C.
- **Rev-match, upshift hold and anti-stall:** all off. When on: 30% max throttle (code limit 40%), 1.5 s max hold, 150 ms clutch hold delay (recommended 50–400 ms, code limit 0–500 ms), from 15 km/h. See [rev-match.md](rev-match.md#safety-limits-and-why-theyre-set-where-they-are) for why.
- **Overrun crackle:** off.

Run any script with no arguments to see every option. They're described in [ignition-cut.md](ignition-cut.md), [rev-match.md](rev-match.md) and [overrun.md](overrun.md).

**Gearing:** rev-match needs your car's RPM per km/h for each gear. The defaults are for the 5-speed with standard final drive and tyres. See [rev-match.md](rev-match.md#set-the-rpm-per-kmh-table-for-your-car) for anything else.

## 4. Make the tables show up in NC Flash / EcuFlash
The new settings are in the ROM, but NC Flash and EcuFlash only show tables listed in their definition file. Add them once. Close NC Flash first, then:
```
python tools/add_definitions.py "%APPDATA%\NCFlash\metadata\lfj1ee.xml"
```
That's for Command Prompt; in PowerShell use `"$env:APPDATA\NCFlash\metadata\lfj1ee.xml"`. The script backs the file up first and skips anything already there.

Reopen NC Flash and open your patched ROM. The tables appear under:
- **Engine Limiter - RPM Ignition Cut** and **Engine Limiter - Overheat Protection**
- **DBW - Downshift Rev Match**, **DBW - Upshift Hold** and **DBW - Rev Match / Upshift Hold - Shared**
- **DBW - Anti-Stall**
- **Spark - Overrun Crackle**

For EcuFlash, adding by hand, and how to change and save the settings, see **[ncflash-ecuflash.md](ncflash-ecuflash.md)**.

## 5. Flash
- **Do a Full Flash the first time,** and again whenever anything else (another tuning tool, a dealer) has flashed the ECU since your last NC Flash flash. NC Flash's quick ("Dynamic") flash only writes blocks that differ from *its own record* of the last flash. After another tool has flashed the ECU, it can leave a mix of old and new blocks. The symptoms are code P0601, no ignition cut, or a flashing immobiliser light. A Full Flash fixes it.
- Keep a battery charger connected while flashing.
- The patches change ROM blocks the ECU checksums. NC Flash recalculates the checksums when it flashes. If your flashing tool doesn't, you'll get P0601.

## 6. Test
Test one feature at a time, in a safe place, with a datalog running. What to look for is in each patch's doc:
- [ignition-cut.md](ignition-cut.md#testing)
- [rev-match.md](rev-match.md#testing)
- [overrun.md](overrun.md#testing)

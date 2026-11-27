# Seeing and changing the patch settings in NC Flash / EcuFlash

## Why the new tables don't show up on their own
NC Flash and EcuFlash only show the tables listed in their **definition file** for your calibration, an XML file that says "table X is at address Y, stored as a float, shown in rpm". The patches put their settings into your ROM, but your definition file doesn't know about them yet. Until you add them, the settings are **in the ROM but invisible.**

This repo includes those definitions (`ncflash/lfj1ee_custom_tables.xml`) and a script that adds them to your definition file for you.

## 1. Add the definitions (once)
**Close NC Flash / EcuFlash first.**

### NC Flash
The definition file is `%APPDATA%\NCFlash\metadata\lfj1ee.xml`. Run from the repo folder, in Command Prompt:
```
python tools/add_definitions.py "%APPDATA%\NCFlash\metadata\lfj1ee.xml"
```
or in PowerShell:
```
python tools/add_definitions.py "$env:APPDATA\NCFlash\metadata\lfj1ee.xml"
```

### EcuFlash
EcuFlash keeps its definitions in the `rommetadata` folder inside its install folder, often under `C:\Program Files (x86)\OpenECU\EcuFlash\`. It may also be wherever you pointed EcuFlash's settings. To find the file that describes LFJ1EE:
```
python tools/add_definitions.py --find "C:\Program Files (x86)\OpenECU\EcuFlash\rommetadata"
```
Then run the script on the file it lists:
```
python tools/add_definitions.py "<the file it found>"
```
If the definitions sit in a protected folder like Program Files, Windows may refuse to let the script save. Run the command prompt as administrator, or copy the file somewhere else, run the script on the copy, and copy it back.

### What the script does
- **Adds** the scalings (units and limits) and the tables for all the patches to the `<rom>` block whose calibration ID is `LFJ1EE`. Scalings go after `<romid>`, tables before `</rom>`.
  - To add only one patch's tables: `--only igncut`, `--only revmatch` or `--only overrun`.
  - **Already added the tables with an older version?** Run it again: tables already there are moved to the current categories (for example the rev-match split into Downshift Rev Match / Upshift Hold / Shared), and anything new is added.
- **Backs up** the original next to it first, as `lfj1ee.xml.<date-time>.bak`. It isn't named `.xml`, so neither program loads it as a second definition.
- **Skips** anything that's already there, so running it twice is harmless.
- **Stops** if a table of the same name is already in the file at a *different* address. That usually means an older version of a patch, and adding the new one would make the program show the wrong bytes. Remove the old `<table …>` lines it names (or restore your original definition), then run it again.
- **Checks** that the file is still valid XML before saving.

**Undo:** delete the edited file and rename the `.bak` back to `lfj1ee.xml`.

**By hand instead:** open `ncflash/lfj1ee_custom_tables.xml`. Copy its `<scaling …/>` lines to just after `</romid>` in your definition, and its `<table …/>` lines to just before `</rom>`. Make a backup first.

### Check it worked
Reopen the program and open your **patched** ROM. You should see these categories:

| Category | Patch |
|---|---|
| **Engine Limiter - RPM Ignition Cut** | ignition cut, launch control, flat-foot shift |
| **Engine Limiter - Overheat Protection** | lower rev limit when the coolant is too hot (part of the ignition cut) |
| **DBW - Downshift Rev Match** | downshift rev-match: Enable, target offset, on/off switch |
| **DBW - Upshift Hold** | upshift hold: Enable, target offset |
| **DBW - Rev Match / Upshift Hold - Shared** | settings both use: gain, damping, limits, hold time, clutch hold delay, gearing, brake switch |

**Limits:** NC Flash lets you type any value into the rev-match tables, but the patch code enforces hard limits (for example 40% throttle, 3.3 s hold, 0–500 ms clutch hold delay). A value beyond a limit is used as the limit. The clutch hold delay table takes anything from 0 to 500 ms (0 = no delay); 50–400 ms is the recommended range, which is what NC Patcher's slider covers.

**Already added the tables with 0.9.19?** Click **Show the new tables in NC Flash** again (or rerun `add_definitions.py`): it updates the clutch hold delay's range from 50–400 to 0–500 ms. The full list, and why each limit is where it is, is in [rev-match.md](rev-match.md#safety-limits-and-why-theyre-set-where-they-are).
| **DBW - Anti-Stall** | anti-stall |
| **Spark - Overrun Crackle** | timed overrun crackle |

Every table from these patches ends in "(custom patch)". If the values look like nonsense (for example NaN, or huge numbers), you've opened a ROM **without** the patch, or one with an older version of it at different addresses.

**Calibration:** these definitions are for **LFJ1EE**. For another calibration, use the definitions you made when porting ([porting-with-claude.md](porting-with-claude.md), step 8): `python tools/add_definitions.py <your definition file> --cal <your ID> --source <your tables .xml>`.

## 2. Change the settings
### NC Flash
1. **Open** your patched ROM.
2. **Find the table** in the category list, for example *Engine Limiter - RPM Ignition Cut → Launch Control RPM*.
3. **Open it,** type the new value, and confirm.
4. **Save the ROM with File → Save ROM As.** Plain Save (Ctrl+S) only saves an NC Flash *project*, not the `.bin` file.
5. **Flash it.** The first flash after patching, or after any other tool has flashed the ECU, must be a **Full Flash** (see [installing.md](installing.md#5-flash)).

### EcuFlash
1. **Open** your patched ROM and **edit** the tables the same way.
2. **Save** the ROM file.
3. **Check checksums before flashing.** The patches change ROM blocks the ECU checksums. Flash with a tool that recalculates the NC's checksums; NC Flash does. If your EcuFlash setup doesn't, the car will set **P0601** and may not run properly. This hasn't been checked with EcuFlash, so check it for your version, for example by reading the ECU back and comparing.

### Or from the command line
Every patch's settings can also be set without either program. Each command writes a new file:
```
python scripts/upgrade_igncut.py your.bin LAUNCH=4500 FS=5300 OHEN=1
python scripts/upgrade_revmatch.py "your - igncut.bin" EN=1 UPEN=1
python scripts/upgrade_overrun.py "your - igncut - revmatch.bin" EN=1 STR=0
```

## Example: a typical setup
Goal: launch control at 4,500 rpm, flat-foot shift at 5,300 rpm, rev-match and upshift hold on.

| Category → table | Set to |
|---|---|
| Engine Limiter - RPM Ignition Cut → **Launch Control RPM** | 4500 |
| Engine Limiter - RPM Ignition Cut → **Flat Shift RPM** | 5300 |
| DBW - Downshift Rev Match → **Rev Match - Enable** | 1 |
| DBW - Upshift Hold → **Upshift Hold Enable** | 1 |
| DBW - Rev Match / Upshift Hold - Shared → **RPM per km/h, 1st to 6th** | your car's values (see [rev-match.md](rev-match.md#set-the-rpm-per-kmh-table-for-your-car)) |

Then **Save ROM As**, Full Flash, and test each feature as described in [ignition-cut.md](ignition-cut.md#testing) and [rev-match.md](rev-match.md#testing).

## Changing the rev limit
The ignition cut follows the factory **RPM Fuel Cut** table (in the *Engine Limiter - RPM Fuel Cut* category of a standard LFJ1EE definition). It cuts at that value plus **Offset from RPM Fuel Cut** (−300 by default). To raise or lower your rev limit, change **RPM Fuel Cut**.

## After updating the patches
If a newer version of this repo adds tables or changes their categories, run `tools/add_definitions.py` again (or click *Show the new tables in NC Flash* in the app). It adds new tables, moves existing ones to their current category, skips ones that are unchanged, and stops if one has moved to a different address, telling you which old lines to remove.

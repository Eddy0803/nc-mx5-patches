# NC Patcher (Windows app)

A point-and-click way to use everything in this repo: drag in your ECU file, choose the features, and save a patched file to flash with NC Flash. It can also port the patches to other calibrations, and connect to the car through a J2534 interface to find the pedal switch addresses, with a guide for the first run.

**Version 0.9.19 is a beta:**
- **Proven:** patching and porting give exactly the same results as the scripts, and that's tested.
- **Proven on a car:** reading from the ECU through the car connection (tab 1), on an LFJ1EE.

## Download and run
1. Go to the repo's **Releases** page and download `NCPatcher.exe` from the latest release.
2. Put it anywhere and double-click it. Nothing is installed.
   - **Windows SmartScreen** may warn that the app is unrecognised, because it isn't code-signed. Click **More info → Run anyway** if you trust the download. You can check it against the SHA-256 checksum listed on the release.
   - **Don't run it as administrator.** Windows blocks drag-and-drop from Explorer into programs running as admin.

**Requirements:** Windows 10 or 11. For tab 1, a J2534 interface with its **32-bit** J2534 driver installed (OBDX Pro, Tactrix OpenPort 2.0 and most others install one).

## Tab 1: Check my car (J2534)
**Start here.** The patches need to know which RAM bytes your ECU uses for the **clutch and brake switches**. This tab finds them on your car, step by step. **The app only ever reads from the ECU. It never writes to it or flashes it.**

The first time you open the app, a **guide** at the top of this tab walks you through it. It shows one instruction at a time and highlights the button to press:
1. **Plug in your interface,** ignition ON, engine OFF. Choose the interface and click **Connect**. The app identifies the ECU by reading its calibration ID.
2. Feet off the pedals: **1. No pedals pressed**.
3. **Hold the brake** down: **2. HOLD the brake**.
4. Let go: **3. No pedals again**.
5. **Hold the clutch** down: **4. HOLD the clutch**.
6. Let go and click **Analyse**.
7. Check the result and click **Use these addresses**.

**What happens next:**
- **They're remembered** for that calibration (in `%APPDATA%\NCPatcher\settings.json`).
- **Tab 2** uses them when it patches your file. Its rev-match box shows which addresses it's using and whether they were checked on your car.
- **Tab 3** (porting) gets them filled in.
- **The guide then takes you on:** to tab 2 for a supported calibration, or to tab 3 if yours needs porting first.
- **Next start:** the app opens on tab 2, and this tab shows what was checked. Run the steps again whenever you like.

**No interface?** **Skip - no interface** goes straight to tab 2. The patches then use the usual addresses for your calibration, and tab 2 shows that they weren't checked on your car.

**How it picks:**
- It lists the bytes that changed only with each pedal, ignoring any that change on their own between the two no-pedal captures.
- **Supported calibrations:** if the calibration's usual address is among the best candidates, that one is used, and it's reported as confirmed. If it isn't, the best candidate is used and you're told it's **not the usual address**, so you can capture again if in doubt.
- **Ranking:** loading this car's ECU file in tab 2 first (optional) ranks first the bytes the ECU's code actually reads. On a real LFJ1EE capture this put the true brake and clutch bytes at the top of about 650 changing bytes.

**Live values** show RPM, speed, pedal, clutch and brake, so you can check the addresses respond.
## Tab 2: Patch my ECU file
1. **Drag your ECU file** (the 1 MB `.bin` you read with NC Flash) onto the box, or click it to browse. The app identifies the calibration and shows whether the patches are already installed, with their current settings.
2. **Tick the patches you want** and set the main options:

   | Patch | Options |
   |---|---|
   | Ignition cut | launch RPM, flat-shift RPM, retard, offset, flat-shift pedal threshold, split speed, coil dwell |
   | Rev-match | rev-match, upshift hold, anti-stall and the downshift on/off switch, each on or off; a slider for the clutch hold delay (50–400 ms: how long the clutch must be down before the throttle opens) |
   | Overrun crackle | on or off, Strength (spark: mild to aggressive slider), duration after lift-off |

   Fine tuning (gains, offsets, gearing, overrun limits) is done in NC Flash. See [overrun.md](overrun.md) before turning the crackle on.
3. **Click "Save patched file...".** The app patches a copy in memory, runs both emulator tests on it, and only lets you save if they pass. Your original file is never changed.
4. **Click "Show the new tables in NC Flash" (once).** This adds the patch tables to NC Flash's definition file for your calibration, after making a backup. Close NC Flash first. See [ncflash-ecuflash.md](ncflash-ecuflash.md).
5. **Flash** the saved file with NC Flash. Do a **Full Flash** the first time, then test one feature at a time with a datalog.

**Clutch and brake:** the addresses checked on your car in tab 1 are used automatically (the rev-match box says which addresses are in use). The emulator tests run with exactly those addresses.

**Unsupported calibration:** the app tells you to port it first in tab 3.

**Automatic gearboxes:** the app reads the gear ratios from the file and refuses automatics. The patches are for manual gearboxes only.

## Tab 3: Port to another calibration
**You need:**
- a **stock LFJ1EE** file (the reference);
- a **stock read of your calibration** (before any tuning).

Drag them onto the two boxes. The calibration ID and **gearbox** (5-speed manual, 6-speed manual or automatic) are shown, and automatics are refused. Then click **Port**.

This runs the same engine as `tools/port.py` (see [porting.md](porting.md)):
- it finds every address, checks it, builds the patches (ignition cut, rev-match, overrun), runs the emulators and writes a report;
- it stops rather than guesses;
- rev-match is only built when it's safe for that software.

Ported calibrations are kept in `%APPDATA%\NCPatcher\ports\<calibration>\`, and tab 2 then recognises that calibration's files.

**If the port doesn't fully work** (it stops, the emulator tests fail, or a patch can't be built for your software), the app shows a **problem report** you can send to the project, so support for your calibration can be added:
- **What's in it:** the calibration ID, gearbox, what stopped or wasn't built, the addresses that were found, and the port log. It contains **no ROM data, file contents, names or folder paths**.
- **You see it first:** the window shows exactly what would be sent. **Submit report** sends it from inside the app (to the project's Google Form). **Save to file...** keeps a copy. **Cancel** sends nothing.
- **Later:** **Report a problem...** on this tab reopens it for the last port.

The clutch and brake addresses from the car check (tab 1) are filled in automatically.

When the port finishes, the app offers to take you to **tab 2**. Say yes, then drop your ECU file again: the new patches are **applied to it automatically**, the emulator tests run, and you're asked where to save the patched copy (next to the original by default). The patches go in with their default settings (launch and flat shift off, rev-match off), which you then set in NC Flash or in tab 2.

## How it reads memory (and why it's beta)
The NC's "read memory by address" request format isn't publicly documented. On connecting, the app **tries a few standard encodings** and keeps the one that returns the calibration ID out of ROM, so it checks itself. If every read is refused, it tries a standard (non-programming) diagnostic session once. This has been **confirmed working on a car** (LFJ1EE). If it can't connect on yours, the log shows each format's reply; please open an issue with it.

## Building it yourself
Use a **32-bit** Python 3.12 with tkinter (the python.org 32-bit installer), so the app can load 32-bit J2534 drivers:
```
<32-bit python> -m pip install pyinstaller
powershell -ExecutionPolicy Bypass -File app\build_exe.ps1 -Python <32-bit python>
```
The result is `dist\NCPatcher.exe`. Source:

| File | Contents |
|---|---|
| `app/ncpatcher.py` | the GUI |
| `app/core.py` | glue to the patch code |
| `app/ecu.py` | memory reading and the pedal analysis |
| `app/j2534.py` | the J2534 binding |
| `app/dragdrop.py` | file drops |
| `app/theme.py` | the dark theme |

You can also run it from source with any Python 3.12 (`python app\ncpatcher.py`). Use 32-bit Python for J2534 with 32-bit drivers.

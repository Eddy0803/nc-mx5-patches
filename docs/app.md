# NC Patcher (Windows app)

A point-and-click way to use everything in this repo: drag in your ECU file, choose the features, and save a patched file to flash with NC Flash. It can also port the patches to other calibrations, and connect to the car through a J2534 interface to confirm the pedal switch addresses.

**Version 0.9.11 is a beta:**
- **Proven:** patching and porting give exactly the same results as the scripts, and that's tested.
- **Not yet proven on a car:** the car connection (tab 3).

## Download and run
1. Go to the repo's **Releases** page and download `NCPatcher.exe` from the latest release.
2. Put it anywhere and double-click it. Nothing is installed.
   - **Windows SmartScreen** may warn that the app is unrecognised, because it isn't code-signed. Click **More info → Run anyway** if you trust the download. You can check it against the SHA-256 checksum listed on the release.
   - **Don't run it as administrator.** Windows blocks drag-and-drop from Explorer into programs running as admin.

**Requirements:** Windows 10 or 11. For tab 3, a J2534 interface with its **32-bit** J2534 driver installed (OBDX Pro, Tactrix OpenPort 2.0 and most others install one).

## Tab 1: Port to another calibration
**You need:**
- a **stock LFJ1EE** file (the reference);
- a **stock read of your calibration** (before any tuning).

Drag them onto the two boxes. The calibration ID and **gearbox** (5-speed manual, 6-speed manual or automatic) are shown, and automatics are refused. Then click **Port**.

This runs the same engine as `tools/port.py` (see [porting.md](porting.md)):
- it finds every address, checks it, builds the patches (ignition cut, rev-match, overrun), runs the emulators and writes a report;
- it stops rather than guesses;
- rev-match is only built when it's safe for that software.

Ported calibrations are kept in `%APPDATA%\NCPatcher\ports\<calibration>\`, and tab 2 then recognises that calibration's files.

When the port finishes, the app offers to take you to **tab 2**. Say yes, then drop your ECU file again: the new patches are **applied to it automatically**, the emulator tests run, and you're asked where to save the patched copy (next to the original by default). The patches go in with their default settings (launch and flat shift off, rev-match off), which you then set in NC Flash or in tab 2.

## Tab 2: Patch my ECU file
1. **Drag your ECU file** (the 1 MB `.bin` you read with NC Flash) onto the box, or click it to browse. The app identifies the calibration and shows whether the patches are already installed, with their current settings.
2. **Tick the patches you want** and set the main options:

   | Patch | Options |
   |---|---|
   | Ignition cut | launch RPM, flat-shift RPM, retard, offset, flat-shift pedal threshold, split speed, coil dwell |
   | Rev-match | rev-match, upshift hold and anti-stall on or off |
   | Overrun crackle | on or off, Strength (spark: mild to aggressive slider), duration after lift-off |

   Fine tuning (gains, offsets, gearing, overrun limits) is done in NC Flash. See [overrun.md](overrun.md) before turning the crackle on.
3. **Click "Save patched file...".** The app patches a copy in memory, runs both emulator tests on it, and only lets you save if they pass. Your original file is never changed.
4. **Click "Show the new tables in NC Flash" (once).** This adds the patch tables to NC Flash's definition file for your calibration, after making a backup. Close NC Flash first. See [ncflash-ecuflash.md](ncflash-ecuflash.md).
5. **Flash** the saved file with NC Flash. Do a **Full Flash** the first time, then test one feature at a time with a datalog.

**Unsupported calibration:** the app tells you to port it first in tab 1.

**Automatic gearboxes:** the app reads the gear ratios from the file and refuses automatics. The patches are for manual gearboxes only.

## Tab 3: Car connection (J2534)
**The app only ever reads from the ECU. It never writes to it or flashes it.**

1. **Plug in your interface,** ignition on (engine off for the pedal check). Choose the interface and click **Connect**. The app identifies the ECU by reading its calibration ID.
2. **Pedal check:** it confirms which RAM bytes are the brake and clutch switches, which the patches rely on. Press the four capture buttons in order, doing what each says:
   1. no pedals pressed;
   2. **hold the brake**;
   3. no pedals again;
   4. **hold the clutch**.

   Then click **Analyse**.
   - **How it picks:** it lists the bytes that changed only with each pedal, ignoring any that change on their own between the two no-pedal captures. If you've loaded this car's ECU file in tab 2, it ranks first the bytes the ECU's code actually reads. On a real LFJ1EE capture this put the true brake and clutch bytes at the top of about 650 changing bytes.
   - **What you get:** for supported calibrations, it says whether the found addresses **match** the ones the patches use.
   - **Ported calibrations:** **Save these for my calibration** stores them. Re-save your patched file in tab 2 afterwards.
3. **Live values** show RPM, speed, pedal, clutch and brake, so you can check the addresses respond.

### How it reads memory (and why it's beta)
The NC's "read memory by address" request format isn't publicly documented. On connecting, the app **tries a few standard encodings** and keeps the one that returns the calibration ID out of ROM, so it checks itself. If every read is refused, it tries a standard (non-programming) diagnostic session once. This has been tested with the J2534 drivers installed, but **not yet on a car**. If it can't connect, the log shows each format's reply; please open an issue with it.

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

# NC Patcher (Windows app)

A point-and-click way to use everything in this repo: drag in your ECU file, choose the features, and save a patched file to flash with NC Flash. It knows 85 manual calibrations out of the box (see [calibrations.md](calibrations.md)), and connects to the car through a J2534 interface to find the pedal switch addresses, with a guide for the first run. It has two tabs, **1. Check my car** and **2. Patch my ECU file**, plus **Report a problem** and **Request a feature** buttons at the top.

**Version 0.9.29 is a beta:**
- **Proven:** patching gives exactly the same results as the scripts, and that's tested.
- **Proven on a car:** reading from the ECU through the car connection (tab 1), on an LFJ1EE.

## Download and run
1. Go to the repo's **Releases** page and download `NCPatcher.exe` from the latest release.
2. Put it anywhere and double-click it. Nothing is installed.
   - **Windows SmartScreen** may warn that the app is unrecognised, because it isn't code-signed. Click **More info → Run anyway** if you trust the download. You can check it against the SHA-256 checksum listed on the release.
   - **Opening your ECU file:** drag it from Explorer and drop it **anywhere on the window** (it opens in tab 2), drop it onto **NCPatcher.exe's icon**, or click the drop box in tab 2 to browse. Windows normally blocks drops into programs run as administrator; NC Patcher tells Windows to let them through, but it's simplest not to run it as administrator.

**Requirements:** Windows 10 or 11. For tab 1, a J2534 interface with its **32-bit** J2534 driver installed (OBDX Pro, Tactrix OpenPort 2.0 and most others install one).

## Report a problem / Request a feature
Two buttons at the top right of the window, on every tab. They open a short form that goes to the project, so problems can be fixed and ideas considered:
- **Choose** *Report a problem* or *Request a feature*, then give it a **title** and a **description**.
- **Contact (optional):** only if you'd like a reply, e.g. a GitHub or forum username. It's sent exactly as you type it.
- **Include basic details** (on by default): the app and Windows version, the calibration of the file in tab 2 and its gearbox, which patches are ticked, and whether a car is connected.
- **Include the app's log** (on by default for problems): what the app has logged this session.

**What's sent, and what isn't:**
- The window shows **exactly** what will be sent, and **nothing is sent until you press Submit** (and confirm).
- **It never contains ROM data or file contents.**
- **Paths and file names are removed:** ECU file names often include names, plates or car details. The names of every file opened or saved in the session are replaced with `<file>`, any path with `<path>`, and your Windows user name is hidden. That applies to the log, the details and your own description.
- It goes to the project's Google Form. **Save to file...** keeps a copy instead (or as well), for example to post as a GitHub issue.

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
- **Tab 2** fills them into its **ECU addresses** box and builds the patches with them.
- **The guide then takes you on** to tab 2. For a calibration NC Patcher doesn't know, it points you to `tools/port.py` instead.
- **Next start:** the app opens on tab 2, and this tab shows what was checked. Run the steps again whenever you like.

**No interface?** **Skip - no interface** goes straight to tab 2. The patches then use the usual addresses for your calibration, and tab 2 shows that they weren't checked on your car.

**How it picks:**
- It lists the bytes that changed only with each pedal, ignoring any that change on their own between the two no-pedal captures.
- **Supported calibrations:** if the calibration's usual address is among the best candidates, that one is used, and it's reported as confirmed. If it isn't, the best candidate is used and you're told it's **not the usual address**, so you can capture again if in doubt.
- **Ranking:** loading this car's ECU file in tab 2 first (optional) ranks first the bytes the ECU's code actually reads. On a real LFJ1EE capture this put the true brake and clutch bytes at the top of about 650 changing bytes.

**Optional - TCS button** (for the overrun's sport mode): finds the RAM byte that follows the DSC button.
1. Engine **running**, parked in neutral with the handbrake on.
2. Press **Capture: TCS ON (normal)**, then press the DSC button once (TCS OFF light on) and press **Capture: TCS OFF (pressed once)**.
3. Keep alternating: at least **3 captures of each**. Two captures of the same state in a row aren't used, because alternating is what rules out bytes that just drift or flicker.
4. Press **Find the TCS byte**, then **Use it**. It's remembered for your calibration, like the clutch and brake.
5. **Check it:** turn on Live values and press the DSC button a few times. TCS must show OFF exactly when the light is on.

If no byte follows the button, your car's ECU isn't told the TCS state, and sport mode can't be used. If several bytes follow it equally well, any of them works: the ECU can keep the same signal in more than one place.

**Live values** show RPM, speed, pedal, clutch, brake and (once found) TCS, so you can check the addresses respond.
## Tab 2: Patch my ECU file
1. **Drag your ECU file** (the 1 MB `.bin` you read with NC Flash) onto the window (anywhere, on either tab), or onto NCPatcher.exe's icon, or click the box to browse. The app identifies the calibration and shows whether the patches are already installed, with their current settings.
2. **Check the ECU addresses box** (clutch switch, brake switch, and optionally the TCS byte). See below.
3. **Tick the patches you want** and set the main options:

   | Patch | Options |
   |---|---|
   | Ignition cut | launch RPM, flat-shift RPM, retard, offset, flat-shift pedal threshold, split speed, coil dwell |
   | Rev-match | rev-match, upshift hold, anti-stall and the downshift on/off switch, each on or off; a slider for the clutch hold delay (recommended 50–400 ms: how long the clutch must be down before the throttle opens) |
   | Overrun crackle | on or off, Strength (spark: mild to aggressive slider), duration after lift-off, fuel during the burst (lambda 0.80–1.20 at each of the 4 RPM points, with a **Ford defaults** button), **Sport mode only** (needs the TCS byte from tab 1; see [overrun.md](overrun.md#sport-mode-tcs-button)) |
   | Traction control | on or off, **Max grip accel** (km/h per s: raise it if it cuts without wheelspin), only above a pedal % and a speed. Needs the ignition cut (it cuts spark through it). See [traction-control.md](traction-control.md) |

   Fine tuning (gains, offsets, gearing, overrun limits) is done in NC Flash. See [overrun.md](overrun.md) before turning the crackle on.

   **Clutch hold delay slider:** how long the clutch must stay down before rev-match or upshift hold opens the throttle. If you let the clutch up sooner, nothing happens. Start at the default 150 ms. Raise it if the car jolts as you press the clutch (the throttle is opening while the clutch still bites); lower it if the revs are late on quick downshifts. The slider covers the recommended 50–400 ms: shorter is effectively no delay, and longer risks the blip starting as the clutch comes back up. NC Flash's table accepts the full 0–500 ms the ECU code allows (0 = no delay). If your file has a value outside the slider's range, the app shows it with a `*` and keeps it unless you move the slider.

   **"Why these limits?"** in the rev-match box explains every rev-match limit: what it is, whether the code enforces it, and why it's set there. The same information, in more detail, is in [rev-match.md](rev-match.md#safety-limits-and-why-theyre-set-where-they-are).
4. **Click "Save patched file...".** The app patches a copy in memory with the addresses from the box, runs the emulator tests on it with the same addresses, and only lets you save if they pass. Your original file is never changed.
5. **Click "Show the new tables in NC Flash"** the first time, and again after each NC Patcher update. Close NC Flash first. It backs up NC Flash's definition file for your calibration, then:
   - adds the patch tables, and updates ones an older version added;
   - removes old entries earlier versions added that are no longer used (only this project's own, matched by exact name and address; other patches' tables are left alone).
   
   It lists what it changed. See [ncflash-ecuflash.md](ncflash-ecuflash.md#what-the-script-does).
6. **Flash** the saved file with NC Flash. Do a **Full Flash** the first time, then test one feature at a time with a datalog.

**ECU addresses box:** the RAM bytes the patches read, filled in when you drop a file. Each one says where its value came from:
- **Clutch and brake switches:** the addresses from the car check (tab 1) if you've done it; otherwise the calibration's usual addresses, marked *proven on a car* (LFJ1EE) or *NOT checked on a car* (every other calibration: do the car check first).
- **TCS byte** (optional, only for the overrun sport mode): its address, the bit **mask**, and the value when TCS is **off**, all hex. Filled in from the TCS capture in tab 1, or from the file if it already has one. The overrun's **Sport mode only** option is available only while a valid TCS byte is in the box.
- **You can edit them** if you know your car's addresses (hex, in RAM `FFFF0000`–`FFFFBFFF`). A wrong entry is refused when you save, with the reason. The patches are built, and the emulator tests run, with exactly what's in the box, and the log lists them. Addresses you type in are remembered for that calibration and shown as *entered by hand*.

**Supported calibrations:** 85 manual calibrations are built in (see [calibrations.md](calibrations.md)), so most stock files are recognised straight away. Calibrations without rev-match (33 of them) have rev-match and traction control greyed out.

**Unticked patches are left as they are:** "Install / keep this patch" off means the app doesn't touch that patch, it doesn't remove it. To stop one working, untick its "on" box (e.g. **Traction control on**) and save.

**Unsupported calibration:** the app says so. A manual calibration that isn't built in can be ported with `tools/port.py` ([porting.md](porting.md)); NC Patcher then recognises it, and a port of your own is used instead of a built-in one for the same calibration.

**Automatic gearboxes:** the app reads the gear ratios from the file and refuses automatics. The patches are for manual gearboxes only.

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
| `app/make_icon.py` | draws `app/ncpatcher.ico`, the app icon (needs Pillow; only to regenerate it) |

You can also run it from source with any Python 3.12 (`python app\ncpatcher.py`). Use 32-bit Python for J2534 with 32-bit drivers.

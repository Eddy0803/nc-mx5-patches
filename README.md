# NC MX-5 ECU Patches

> [!WARNING]
> **Disclaimer:** Any changes made to your ECU or vehicle using these patches are the sole responsibility of the user.

**Ignition-cut limiter · launch control · flat shift · rev-match · overrun crackle** for the 2006–2015 Mazda MX-5 (NC).

Extra ECU features for the 2006–2015 Mazda MX-5 (NC) manual, of the kind newer cars and aftermarket ECUs have. They patch the factory ECU software directly, so they work on a **stock** ROM. Everything is set with tables in NC Flash or EcuFlash.

| Patch | Feature | What it does | Status |
|---|---|---|---|
| `lfj1ee_igncut.patch` | **Ignition-cut rev limiter** | Holds the rev limit by cutting **spark** instead of fuel, with optional timing retard while cutting | ✅ Cut method proven on a car* |
| | **Launch control** | Clutch in while stopped: holds a set launch RPM on the ignition cut | ✅ Cut method proven on a car* |
| | **Flat-foot shift** | Clutch in while moving at full throttle: holds a fixed RPM on the ignition cut, with no fuel cut | ✅ Cut method proven on a car* |
| | **Overheat protection** | Optional: lowers the rev limit (and launch / flat-shift points) when the coolant gets too hot | 🧪 Emulator-tested, not yet on a car |
| `lfj1ee_downshift_revmatch.patch` | **Downshift rev-match** | Clutch + brake: the ECU blips the throttle and holds the RPM the next gear down needs | ✅ Working on a car |
| | **Upshift hold** ("dashpot") | Clutch without brake: holds the next gear up's RPM so the revs don't drop too far | ✅ Working on a car |
| | **On/off switch** | Stopped, clutch down, 3 brake taps: turns downshift rev-match on or off without remapping (the revs confirm it) | 🧪 Emulator-tested, not yet on a car |
| | **Clutch hold delay** | Downshift rev-match and upshift hold wait until the clutch has been down for a set time (NC Patcher slider 50–400 ms; NC Flash 0–500 ms), so the throttle doesn't open while the clutch is still biting | 🧪 Emulator-tested, not yet on a car |
| | **Anti-stall** | Adds a little throttle if the revs dip below a set RPM at low speed | ✅ Working on a car |
| `lfj1ee_overrun.patch` | **Timed overrun crackle** | After a lift-off, a set time of heavily retarded combustion that crackles in the exhaust. Fuel follows a lambda-vs-RPM table (stock Ford burble values by default, adjustable 0.8–1.2 in NC Patcher or NC Flash); Strength sets the spark from mild to aggressive | 🧪 Emulator-tested, not yet on a car |
| | **Sport mode** | Optional: crackle only with TCS off, or after pressing the DSC button twice quickly (needs the TCS byte, found on the car with NC Patcher) | 🧪 Emulator-tested, not yet on a car |

\* The ignition cut, its dwell and retard, and all three uses were tested on a car with an earlier version. In that version, the launch and flat-shift decisions came from a separate limiter patch. In this standalone version, the patch makes those decisions itself from the clutch switch, speed and pedal. That logic passes the emulator tests, but this exact version hasn't been driven yet, so test it yourself first (see [docs/ignition-cut.md](docs/ignition-cut.md#testing)).

## Download the app
**NC Patcher** for Windows: a guided check finds your clutch and brake switches on the car through a J2534 interface (read-only); then drag in your ECU file, tick the features and save a patched file. It recognises 85 manual calibrations out of the box, and shows and lets you edit the clutch, brake and TCS addresses the patches are built with. Download `NCPatcher.exe` from **Releases**, and see [docs/app.md](docs/app.md). *Version 0.9.28 is a beta. Reading from the car (tab 1) has been confirmed working on an LFJ1EE car.*

**Supported calibrations: 85 manual-gearbox calibrations, ready to use.** NC Patcher recognises your stock file and patches it with no porting needed: see [docs/calibrations.md](docs/calibrations.md) for the list and which patches each one gets (52 get all three; 33 get ignition cut and overrun but not rev-match). **Only LFJ1EE has been proven on a car**; on the others, check the clutch and brake addresses on your car (NC Patcher tab 1) and test carefully. Automatics aren't supported.

A calibration that isn't in the list can still be ported:
- **`tools/port.py`** does it automatically from your stock ROM: it finds every address, builds and tests the patches, and writes a report. See [docs/porting.md](docs/porting.md).
- [docs/porting-with-claude.md](docs/porting-with-claude.md) walks you through doing it step by step with Claude Code, for when `port.py` stops or you want to check its work.

## Read this first

### **You use these patches entirely at your own risk, with no warranty of any kind.**

- **This modifies your engine computer.** A mistake can stop the car running, damage the engine or catalytic converter, or make it behave unexpectedly. Rev-match opens the throttle without your foot on the pedal (that's the point). It's fenced in by hard limits in the code (at most 40% throttle, 3.3 s per clutch press, your foot always wins), explained in [rev-match.md](docs/rev-match.md#safety-limits-and-why-theyre-set-where-they-are).
- **Keep a copy of your original ECU read** somewhere safe.
- **Tested on one car** (LFJ1EE, 5-speed). Test every feature yourself, in a safe place, with a datalog, before relying on it.
- **Exhaust heat:** ignition cut sends unburnt fuel into a hot exhaust, and overrun crackle burns fuel in the manifold. Keep time on the limiter, launches, flat shifts and overrun bursts short.
- Check your local laws on ECU modifications and emissions.

## What you need
- An NC MX-5 manual with one of the [supported calibrations](docs/calibrations.md) (LFJ1EE is the one proven on a car), and a read of its ECU.
- **NC Flash**, or another flashing tool that recalculates the ROM checksums.
- **Python 3.8 or newer.** `tools/dis.py` also needs `capstone`.

## Quick start
Full instructions: [docs/installing.md](docs/installing.md).

```
python scripts/apply_patch.py stock.bin patches/lfj1ee/lfj1ee_igncut.patch
python scripts/apply_patch.py "stock - igncut.bin" patches/lfj1ee/lfj1ee_downshift_revmatch.patch
python scripts/apply_patch.py "stock - igncut - revmatch.bin" patches/lfj1ee/lfj1ee_overrun.patch
python scripts/upgrade_igncut.py "stock - igncut - revmatch - overrun.bin" LAUNCH=4500 FS=5300 OHEN=1
python tools/add_definitions.py "%APPDATA%\NCFlash\metadata\lfj1ee.xml"   # makes the new tables show up in NC Flash
# then reopen NC Flash, check the tables, Save ROM As, and do a Full Flash
```

**Using romdrop too?** On LFJ1EE the patches work alongside romdrop's patch (NC Patcher 0.9.24 or later). Apply romdrop first, and use only one launch control and one flat shift. See [docs/romdrop.md](docs/romdrop.md).

The patches are independent: use any of them, in any order. `apply_patch.py` never changes its input file. Run it on a ROM that already has the patch and it removes it. It refuses to touch a ROM whose patch sites don't hold exactly the factory code or exactly this patch.

## Docs
- [NC Patcher app](docs/app.md)
- [Supported calibrations](docs/calibrations.md)
- [Installing, step by step](docs/installing.md)
- [Seeing and changing the settings in NC Flash / EcuFlash](docs/ncflash-ecuflash.md)
- [Ignition-cut limiter, launch control and flat-foot shift](docs/ignition-cut.md)
- [Downshift rev-match, upshift hold and anti-stall](docs/rev-match.md)
- [Timed overrun crackle](docs/overrun.md)
- [Using the patches with romdrop](docs/romdrop.md)
- [Porting to your ECU automatically (tools/port.py)](docs/porting.md)
- [Porting to your ECU with Claude, step by step](docs/porting-with-claude.md)

## Repo layout
| Folder | Contents |
|---|---|
| `patches/<cal>/` | Patch files: 1 MB each, a 6-byte calibration ID, then an XOR delta against the stock ROM. Ported calibrations also have `addresses.json` and `PORT_REPORT.md`. |
| `scripts/` | `apply_patch.py` applies or removes a patch. `upgrade_igncut.py` / `upgrade_revmatch.py` / `upgrade_overrun.py` install a patch or change its settings and keep your values. `build_*.py` show exactly how each patch is assembled (`sh_asm.py` is the tiny assembler they use). |
| `app/` | The NC Patcher Windows app (GUI, J2534, build script) |
| `ncflash/` | Table definitions for NC Flash / EcuFlash |
| `tests/` | SH-2E emulators that run the patch code from your ROM: `igncut_emu.py`, `revemu.py` (includes closed-loop downshift, upshift and stall simulations) and `overrun_emu.py` |
| `tools/` | `port.py` (ports the patches to another calibration), `add_definitions.py` (makes the new tables show up in NC Flash / EcuFlash), disassembler, checksum checker, and a gear-ratio calculator from datalogs |

## Licence
GPL-3.0, see [LICENSE](LICENSE). This covers the code and docs in this repository only. Mazda's ECU software, NC Flash and EcuFlash belong to their respective owners.

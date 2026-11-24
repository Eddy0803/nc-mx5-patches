# Porting the patches to your ECU with Claude

The patches here are built for **LFJ1EE**. Other NC calibrations run closely related Mazda software, but every routine, RAM variable and table sits at a different address. This guide shows how to use **Claude Code** (Anthropic's coding assistant) to find those addresses in *your* ROM, build the patch files for *your* calibration, and check them before you go near the car.

You don't need to read assembly yourself, but you do need to **check what Claude tells you**. Claude can be wrong, and a wrong address in an ECU patch can stop the car running. The guide builds in checks at every step for that reason.

## What you need
| | |
|---|---|
| **Claude Code** | The Code tab of the Claude desktop app, or the `claude` command-line tool. It works on files on your own computer. |
| **Python 3.8+** | For the scripts Claude writes and runs. |
| **This repository** | Cloned or downloaded. |
| **Your stock ROM** | A read of *your* ECU before any tuning, and its calibration ID. |
| **A stock LFJ1EE ROM** | The reference. Claude compares your ROM against it. Stock ROMs are shared in the NC tuning community. |
| **Your calibration's table definition** | Your NC Flash / EcuFlash definition XML. It tells Claude where tables such as **RPM Fuel Cut** are in your ROM. |
| **A way to read ECU RAM and log** | To confirm the clutch and brake switch addresses on the car (step 5), and to test. |

**Keep your ECU reads private.** They contain data specific to your car. Claude works with them on your computer; don't commit them or post them online. The repo's `.gitignore` already blocks `.bin` files.

## Set up
1. Clone or download this repository and open its folder in Claude Code.
2. Make a folder called `work` inside it, and put three files there:
   - `work/mine.bin`: your stock read;
   - `work/lfj1ee.bin`: the stock LFJ1EE reference;
   - `work/mine.xml`: your calibration's definition.

   The whole `work/` folder is in `.gitignore`, so none of it can be committed by accident.
3. Start Claude Code in the repo folder. Work through the steps below **in order**, pasting each prompt and reading the answer before moving on. If Claude's answer doesn't match what the step says to expect, stop and ask it why.

> **Tip:** use Claude Code's **plan mode** for steps 2–4. Claude only reads and reports, and doesn't change anything until you approve.

## Step 1: Orientation
> Read README.md, docs/ignition-cut.md, docs/rev-match.md and docs/porting-with-claude.md, then scripts/build_igncut.py and scripts/build_revmatch.py. Summarise in plain words what each patch changes in the ROM, and list every LFJ1EE address they depend on. Don't change any files.

**Expect:** a list that matches the [LFJ1EE reference sheet](#lfj1ee-reference-sheet) at the bottom of this page.

## Step 2: Identify your ROM
> work/mine.bin is my stock ECU read and work/lfj1ee.bin is a stock LFJ1EE. Find the calibration ID string in each (on LFJ1EE it is at 0xB8046) and tell me mine. Check both are 1 MB SH-2E (big-endian) images. Then check that every flash area the patches use in LFJ1EE (0xFE000–0xFE19F and 0xFE300–0xFE7FF) is erased (all 0xFF) in my ROM, and not covered by my ROM's checksum table (LFJ1EE's table is at 0xFF650: entries of start, end, value). Report, don't change anything.

**Expect:**
- **Your calibration ID**, which may sit at a different offset from LFJ1EE's.
- **Free space:** "all 0xFF" for both areas, and not checksummed.

If an area isn't free or is checksummed, ask Claude to find another free, unchecksummed area. Then every address in the patch code and tables moves, including the NC Flash definitions.

## Step 3: Find the hook sites
> For each code site in the LFJ1EE reference sheet in docs/porting-with-claude.md, find the same code in work/mine.bin. Method: take the reference instructions around the site, mask out the bits that legitimately change between software builds (the displacement of mov.l/mov.w @(disp,PC), mova, bt/bf/bt.s/bf.s, bra/bsr), and search my ROM for that pattern. Try a long window first, then shorter ones, and accept a match only if it is unique. For each site, show me the reference disassembly next to the disassembly of the match in my ROM (tools/dis.py can disassemble), and say how confident you are. Don't change any files.

**Expect** one unique match for each site:
- the factory short-dwell test;
- the spark-advance sum load;
- the pedal-copy routine and the task-list literals that point to it (two of them on LFJ1EE);
- the throttle cross-check selector.

The disassembly side by side should look the same apart from addresses.

**If a site has no match, or several:** your software differs there. Ask Claude to show the surrounding code in both ROMs and explain the difference. Only carry on if the routine clearly does the same job.

## Step 4: Map the RAM and table addresses
> For each RAM and calibration address in the reference sheet, find every instruction in work/lfj1ee.bin that loads it (as a mov.l literal). Find the same instruction in work/mine.bin with the masked-pattern method from step 3, read which address my ROM loads there, and tally the votes per address. Show me a table: name, LFJ1EE address, my address, votes agreeing / references mapped. Also check the RPM Fuel Cut table address against work/mine.xml. Finally confirm that RAM 0xFFFFAC10–0xFFFFAC17 is not referenced anywhere in my ROM (as a 32-bit literal, or as a sign-extended 16-bit mov.w literal). Don't change any files.

**Expect:** each address has a clear winner, ideally with all mapped references agreeing.
- **Split vote:** treat that address as unknown until step 5 or further digging settles it.
- **RAM in use:** if `0xFFFFAC10`–`AC17` *is* referenced in your ROM, the rev-match RAM must move.

## Step 5: Confirm the clutch and brake on the car
Code similarity is strong evidence, but these two switch addresses are worth confirming directly, the way they were found on LFJ1EE.

1. Ignition on, engine off. Save a RAM snapshot (`0xFFFF0000` upward) with **no pedals** pressed, one with **the brake held**, and one with **the clutch held**. Save them as `work/ram_none.bin`, `work/ram_brake.bin` and `work/ram_clutch.bin`.
2. Then ask:
> Compare work/ram_none.bin, work/ram_brake.bin and work/ram_clutch.bin (RAM starting at 0xFFFF0000). List the bytes that change only with the brake and only with the clutch, especially ones that go 0 → 1. Does that agree with the clutch and brake addresses from step 4?

**Expect:** one byte that's 0 normally and 1 with the brake, and the same for the clutch. These should match step 4.

## Step 6: Build your patches
> Make a copy of scripts/build_igncut.py and scripts/build_revmatch.py for my calibration (name them after it), using the addresses we found: replace every LFJ1EE code site, literal, RAM and calibration address, and set the calibration ID and its offset. Keep the patch code itself unchanged. Rebuild the dwell and spark hooks from MY ROM's factory code: the branch targets, literal positions and delay-slot instruction must come from my code, not be copied from LFJ1EE. Build both patch files from work/mine.bin into patches/<my calibration>/. Then show me a list of every byte range each patch changes, and disassemble each changed hook site before and after.

**Check:**
- **The changed byte ranges** should be only:
  - **Ignition cut:** the dwell hook (13 instructions) and its literal; the spark hook (4 instructions) and its literal; the code and tables in free flash.
  - **Rev-match:** the two task-list literals; the cross-check literal; the code and tables in free flash.
- **The hooks:** after patching, each one should call the new code and otherwise keep the factory flow. The dwell hook's branches should land where the factory branches did.

## Step 7: Test in the emulators
> Adapt tests/igncut_emu.py and tests/revemu.py to my calibration's addresses (RAM addresses, the RPM Fuel Cut table, and how they find the code), apply my patches to a copy of work/mine.bin with scripts/apply_patch.py (extended for my calibration), and run both emulators. Show me the full output.

**Expect:** `ALL PASS` from both. **Don't flash anything that fails.**

## Step 8: Table definitions
> Write NC Flash / EcuFlash table definitions for my patched ROM, based on ncflash/lfj1ee_custom_tables.xml, with addresses changed only where my build moved them.

## Step 9: Flash and test on the car
Follow [installing.md](installing.md) from step 4 onwards.
- **Do a Full Flash.**
- **Keep your stock read** to hand.
- **Test one feature at a time,** in a safe place, with a datalog, as described in [ignition-cut.md](ignition-cut.md#testing) and [rev-match.md](rev-match.md#testing).
- **Ignition cut first:** start with only the rev limiter, then launch and flat shift. Turn on rev-match last.

## Share it (optional)
If it works on your car, consider opening a pull request with your calibration's build scripts, patch files, test changes and table definitions. **No ROMs or RAM snapshots.** Say which features you tested on the car.

## Good habits when working with Claude
- **Ask it to show evidence,** such as disassembly, byte dumps or vote counts, rather than accepting a bare answer.
- **Ask "how could this be wrong?"** at each step. It's good at finding holes in its own work when asked.
- **Keep the reference sheet below in the conversation;** it's what makes the search concrete.
- **If you get stuck,** open an issue with your calibration ID, model year, gearbox, and what step 3 or 4 reported. Leave out the ROM itself.

---

## LFJ1EE reference sheet
Everything both patches depend on, with the factory code at each site.

### Code sites
| Name | Address | Factory code (hex) | What it is / how the patch uses it |
|---|---|---|---|
| Dwell short-dwell test | `0x50D00` | `D035 6000 C820 0029 70FF 600B 8801 8F04 0009 D332 F338 A00B FE3A` | Inside the coil-dwell routine. Loads flag `0xFFFF7346`, tests bit 5. If set, loads the factory short dwell (`mov.l` → literal `0x50DDC` = table `0xBB9FC`) and branches to where the dwell is stored (`bra` to `0x50D30`, store in the delay slot). Otherwise `bf/s` to the normal dwell map (`0x50D1A`). **Patch:** replaced by `mov.l` (literal `0x50DDC` now = `0xFE000`), `jsr`, `nop`, `bf 0x50D1A`, `bra 0x50D30`, `FE3A`, then nops. The new routine returns T=1 + dwell in fr3 for "use this short dwell". |
| Spark-advance sum load | `0x4DAE8` | `D175 F230 D275 F118` | In the spark-advance sum (routine starts `0x4DA9C`): `mov.l` → literal `0x4DCC0` (= RAM `0xFFFF7D68`, an additive spark term), `fadd fr3,fr2`, `mov.l`, `fmov.s @r1,fr1`. **Patch:** `mov.l` (literal now = retard routine), `jsr @r1`, `fadd` in the delay slot, `mov.l`. The routine returns fr1 = term − retard while cutting. r0 is free here; the caller reloads fr0/fr3/fr5. |
| Pedal-copy routine | `0x387F8` | `D32A F338 D12A 000B F13A` | Copies real pedal `0xFFFF56C8` → engine-side pedal `0xFFFF6CA4`. Called from two task lists (about every 5.5 ms) through the literals below. |
| Task-list literals | `0x11B00`, `0x134D4` | value `0x000387F8` | **Patch:** both point to the rev-match routine (`0xFE400`), which does the pedal copy itself plus rev-match. |
| Throttle cross-check selector | `0xB5FF0` (the `mov.l` at `0xB5FDC`+0x14) | routine starts `2FE6 2FD6 FFFB 4F22 D4.. D3.. 430B 0009 DD.. DE.. D4.. D2.. 420B FF0C 600C 8801` | Chooses the throttle plausibility thresholds. The first `mov.l` loads RPM. The `mov.l` at `0xB5FF0` loads literal `0xB61F0` = cruise flag `0xFFFF585E`, used only here. **Patch:** that literal points to `0xFFFFAC12`, which rev-match sets to 1 only while it's opening the throttle. |

### RAM
| Name | LFJ1EE | Type / meaning |
|---|---|---|
| RPM | `0xFFFF6D5C` | float |
| Vehicle speed | `0xFFFF6D04` | float, km/h |
| Real pedal | `0xFFFF56C8` | float, % |
| Engine-side pedal | `0xFFFF6CA4` | float, % (written by the pedal copy) |
| Clutch switch | `0xFFFF7100` | byte, 1 = pressed (confirmed by RAM snapshots) |
| Brake switch | `0xFFFF70EE` | byte, 1 = pressed (confirmed by RAM snapshots) |
| Short-dwell flag | `0xFFFF7346` | byte, bit 5 |
| Spark term | `0xFFFF7D68` | float, degrees |
| Cruise flag | `0xFFFF585E` | byte |
| Rev-match state (patch's own) | `0xFFFFAC10`–`0xFFFFAC17` | must be unused by the factory software |

### Calibration tables
| Name | LFJ1EE | |
|---|---|---|
| RPM Fuel Cut | `0xC487C` | float. The ignition cut's normal cut point = this + offset. Loaded by the factory fuel-cut routine at `0x41432`. |
| Factory short dwell | `0xBB9FC` | float. Found from the dwell site. |

### Patch layout (in free, unchecksummed flash)
| Area | Contents |
|---|---|
| `0xFE000`–`0xFE17F` | Ignition-cut code: dwell routine at `0xFE000`, cut check, retard routine |
| `0xFE180`–`0xFE19F` | Ignition-cut tables |
| `0xFE300`–`0xFE37F` | Rev-match tables |
| `0xFE400`–`0xFE7FF` | Rev-match code |
| `0xFF650` | Checksum table (35 entries of start, end, value; block sum + value = `0x5AA5A55A`). `0xFB000`–`0xFF7FF` isn't covered. |

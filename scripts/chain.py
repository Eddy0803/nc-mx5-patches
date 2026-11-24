"""Shared task-chain helpers for the patches hooked into the pedal-copy task (~5.5 ms per call).

The task-list literals 0x11B00 / 0x134D4 call one routine. Wrapper patches (each calls the routine below it first,
through a pointer in ROM, then does its own work) can be stacked on top of the bottom routine:

    literals -> [map switch 0xFEA00] -> [traction control 0xFE800] -> bottom (pedal copy 0x387F8 or rev-match 0xFE400)
"""
import struct

HOOKS = (0x11B00, 0x134D4)
WRAPPERS = {0xFE800: 0xFE3BC,     # traction control: next pointer
            0xFEA00: 0xFEC7C}     # map switch:       next pointer
PEDAL_COPY, REVMATCH, OLD_BLIP = 0x000387F8, 0xFE400, 0xFE200

u32 = lambda rom, a: struct.unpack_from('>I', rom, a)[0]


def walk(rom):
    """-> (wrappers top-down, slots that point at the bottom routine, bottom routine address)"""
    vals = [u32(rom, h) for h in HOOKS]
    assert vals[0] == vals[1], 'task literals differ'
    chain, slots, v = [], list(HOOKS), vals[0]
    while v in WRAPPERS:
        assert v not in chain, 'task chain loops'
        chain.append(v); slots = [WRAPPERS[v]]; v = u32(rom, slots[0])
    return chain, slots, v


def set_slots(rom, slots, value):
    for s in slots:
        rom[s:s + 4] = struct.pack('>I', value)


def insert_bottom(rom, code):
    """put wrapper `code` directly above the bottom routine (if not already in the chain). Returns the routine it calls."""
    chain, slots, bottom = walk(rom)
    if code in chain:
        return u32(rom, WRAPPERS[code])
    rom[WRAPPERS[code]:WRAPPERS[code] + 4] = struct.pack('>I', bottom)
    set_slots(rom, slots, code)
    return bottom


def insert_top(rom, code):
    """put wrapper `code` at the top (called directly by the task lists), if not already in the chain."""
    chain, _, _ = walk(rom)
    if code in chain:
        return u32(rom, WRAPPERS[code])
    top = u32(rom, HOOKS[0])
    rom[WRAPPERS[code]:WRAPPERS[code] + 4] = struct.pack('>I', top)
    set_slots(rom, list(HOOKS), code)
    return top

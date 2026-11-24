"""Disassemble an SH-2E (big-endian) ROM region and resolve PC-relative literals.
usage: dis.py rom.bin start_hex end_hex"""
import struct, sys, os
# this file is called dis.py, which would shadow Python's own 'dis' module (capstone imports it): drop our folder first
sys.path[:] = [p for p in sys.path if os.path.abspath(p or '.') != os.path.dirname(os.path.abspath(__file__))]
import capstone as cs

rom = open(sys.argv[1], 'rb').read()
start, end = int(sys.argv[2], 16), int(sys.argv[3], 16)

md = cs.Cs(cs.CS_ARCH_SH, cs.CS_MODE_BIG_ENDIAN | cs.CS_MODE_SH2A | cs.CS_MODE_SHFPU)
md.skipdata = True

for ins in md.disasm(rom[start:end], start):
    note = ''
    op = struct.unpack_from('>H', rom, ins.address)[0]
    hi = op >> 12
    if hi == 0xD:  # mov.l @(disp,pc),Rn
        ea = (ins.address & ~3) + 4 + (op & 0xFF) * 4
        note = f'   ; [0x{ea:05X}] = 0x{struct.unpack_from(">I", rom, ea)[0]:08X}'
    elif hi == 0x9:  # mov.w @(disp,pc),Rn
        ea = ins.address + 4 + (op & 0xFF) * 2
        note = f'   ; [0x{ea:05X}] = 0x{struct.unpack_from(">H", rom, ea)[0]:04X}'
    print(f'{ins.address:05X}: {op:04X}  {ins.mnemonic:10s} {ins.op_str}{note}')

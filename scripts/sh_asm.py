"""Tiny two-pass assembler for the SH-2E instructions used by the patches in this repo.

Instructions are given as raw 16-bit words (w), plus a few PC-relative forms that need label resolution:
    lit('movl', n, label)   mov.l @(disp,PC),Rn     -> loads the 32-bit pool entry `label`
    lit('mova', 0, label)   mova  @(disp,PC),R0     -> address of the pool entry `label`
    br('bt'|'bf'|'bra'|'bsr', label)
    pool([(label, bytes), ...])  aligned literal pool
"""
import struct


class Asm:
    def __init__(self, base):
        self.base, self.items, self.labels = base, [], {}

    def L(self, name): self.items.append(('label', name))
    def w(self, word): self.items.append(('w', word))
    def lit(self, kind, n, sym): self.items.append((kind, n, sym))
    def br(self, kind, sym): self.items.append((kind, sym))
    def pool(self, entries): self.items.append(('pool', entries))

    def assemble(self):
        for pass_ in (1, 2):
            pc, out = self.base, bytearray()
            for it in self.items:
                k = it[0]
                if k == 'label':
                    self.labels[it[1]] = pc; continue
                if k == 'pool':
                    while pc % 4: out += b'\x00\x09'; pc += 2
                    for name, data in it[1]:
                        self.labels[name] = pc; out += data; pc += len(data)
                    continue
                word = 0x0009
                if pass_ == 2:
                    if k == 'w':
                        word = it[1]
                    elif k in ('movl', 'mova'):
                        tgt = self.labels[it[2]]; b = (pc & ~3) + 4; d = (tgt - b) // 4
                        assert (tgt - b) % 4 == 0 and 0 <= d <= 255, (k, it, hex(pc))
                        word = (0xD000 | it[1] << 8 | d) if k == 'movl' else (0xC700 | d)
                    elif k in ('bt', 'bf'):
                        d = (self.labels[it[1]] - pc - 4) // 2
                        assert -128 <= d <= 127, f'{k} to {it[1]} at 0x{pc:05X} out of range ({d} words)'
                        word = (0x8900 if k == 'bt' else 0x8B00) | (d & 0xFF)
                    elif k in ('bra', 'bsr'):
                        d = (self.labels[it[1]] - pc - 4) // 2; assert -2048 <= d <= 2047
                        word = (0xA000 if k == 'bra' else 0xB000) | (d & 0xFFF)
                out += struct.pack('>H', word); pc += 2
        return bytes(out)

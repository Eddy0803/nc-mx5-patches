"""Reading NC ECU memory over J2534 (read-only).

The request format for "read memory by address" (service 0x23) isn't publicly documented for this ECU, so the
reader PROBES a few common encodings by reading the calibration ID out of ROM (known bytes) and keeps the one that
returns it. Only read requests (0x23) are ever sent, plus - only if every read is refused - a standard
"diagnostic session" request. Nothing is written to the ECU.
"""
import re, struct, time

RAM_START, RAM_END = 0xFFFF0000, 0xFFFFC000
ID_OFFSETS = (0xB8046, 0xC0046, 0xB8000, 0xC0000)     # where NC calibration IDs have been seen
ID_RE = re.compile(rb'L[A-Z0-9]{5}')


def _fmt(kind, addr, n):
    a4 = struct.pack('>I', addr & 0xFFFFFFFF); a3 = a4[1:]
    return {'A4S2': b'\x23' + a4 + struct.pack('>H', n),
            'A4S1': b'\x23' + a4 + bytes([n]),
            'U14': b'\x23\x14' + a4 + bytes([n]),
            'U24': b'\x23\x24' + a4 + struct.pack('>H', n),
            'A3S1': b'\x23' + a3 + bytes([n]),
            'A3S2': b'\x23' + a3 + struct.pack('>H', n)}[kind]


FORMATS = ('A4S2', 'U14', 'U24', 'A4S1', 'A3S1', 'A3S2')
SESSIONS = (b'\x10\x81', b'\x10\x03')                # default (KWP) / extended (UDS) - never a programming session


class EcuError(Exception):
    pass


def nrc_text(code):
    return {0x10: 'general reject', 0x11: 'service not supported', 0x12: 'sub-function / format not supported',
            0x13: 'wrong message length or format', 0x22: 'conditions not correct', 0x31: 'request out of range',
            0x33: 'security access denied', 0x7F: 'service not supported in this session'}.get(code, f'code 0x{code:02X}')


class Ecu:
    def __init__(self, passthru, log=print):
        self.pt, self.log = passthru, log
        self.fmt = None; self.skip = 0; self.chunk = 0x40; self.cal = None

    def _read_raw(self, kind, addr, n):
        r = self.pt.request(_fmt(kind, addr, n))
        if r is None: return None, 'no reply'
        if r[0] == 0x7F: return None, f'refused ({nrc_text(r[2]) if len(r) > 2 else "?"})'
        if r[0] != 0x63: return None, f'unexpected reply {r[:8].hex()}'
        return r[1:], None

    def probe(self):
        """find the read format by reading the calibration ID from ROM; returns the calibration ID"""
        last = {}
        for attempt in range(2):
            for kind in FORMATS:
                for off in ID_OFFSETS:
                    data, err = self._read_raw(kind, off, 6)
                    if err:
                        last[kind] = err; continue
                    m = ID_RE.search(data)
                    if m and m.start() + 6 <= len(data):
                        self.fmt, self.skip = kind, m.start()          # some replies echo the address first
                        self.cal = m.group(0).decode()
                        self.log(f'read format {kind} works: calibration {self.cal} at 0x{off:X}')
                        self._find_chunk()
                        return self.cal
                    last[kind] = f'reply did not contain a calibration ID ({data[:12].hex()})'
            if attempt == 0:                                      # everything refused: try a standard diagnostic session
                for s in SESSIONS:
                    r = self.pt.request(s)
                    if r and r[0] == 0x50:
                        self.log(f'diagnostic session {s.hex()} accepted'); break
        raise EcuError('the ECU did not answer any memory-read format. Last replies: ' +
                       '; '.join(f'{k}: {v}' for k, v in last.items()))

    def _find_chunk(self):
        for n in (0x80, 0x40, 0x20, 0x10):
            data, err = self._read_raw(self.fmt, RAM_START + 0x7000, n)
            if not err and len(data) - self.skip >= n:
                self.chunk = n; self.log(f'reading {n} bytes per request'); return
        self.chunk = 0x08

    def read(self, addr, n):
        if not self.fmt: raise EcuError('not probed yet')
        out = bytearray()
        while len(out) < n:
            k = min(self.chunk, n - len(out))
            for tries in range(3):
                data, err = self._read_raw(self.fmt, addr + len(out), k)
                if not err: break
            if err: raise EcuError(f'read 0x{addr + len(out):08X}: {err}')
            out += data[self.skip:self.skip + k]
        return bytes(out)

    def snapshot(self, start=RAM_START, end=RAM_END, progress=None):
        out = bytearray(); a = start
        while a < end:
            n = min(0x400, end - a)
            out += self.read(a, n); a += n
            if progress: progress((a - start) / (end - start))
        return bytes(out)

    def f32(self, addr):
        return struct.unpack('>f', self.read(addr, 4))[0]

    def u8(self, addr):
        return self.read(addr, 1)[0]


def code_refs(rom):
    """how many 32-bit literals in the ROM point at each RAM address (a real switch flag is read in many places)"""
    import collections
    refs = collections.Counter()
    for i in range(0, len(rom) - 3, 4):
        v = struct.unpack_from('>I', rom, i)[0]
        if RAM_START <= v < RAM_END: refs[v] += 1
    return refs


def analyse(nones, brake, clutch, rom=None, base=RAM_START):
    """bytes that change only with the brake held / only with the clutch held.
    nones: one or more no-pedal snapshots - bytes that differ between them are noise and ignored.
    rom: the calibration's ROM - candidates the code reads in 3+ places are ranked first (on LFJ1EE this puts the
    real brake and clutch flags at the top out of ~650 noisy bytes).
    -> {'brake': [(score, addr, before, after, refs)], 'clutch': [...]} best first"""
    if isinstance(nones, (bytes, bytearray)): nones = [nones]
    none = nones[0]
    n = min(len(x) for x in list(nones) + [brake, clutch])
    stable = [all(x[i] == none[i] for x in nones[1:]) for i in range(n)]
    refs = code_refs(rom) if rom else None
    out = {'brake': [], 'clutch': []}
    for which, snap, other in (('brake', brake, clutch), ('clutch', clutch, brake)):
        for i in range(n):
            if stable[i] and snap[i] != none[i] and other[i] == none[i]:
                a = base + i; r = refs[a] if refs else 0
                score = (2 if r >= 3 else 0) + (2 if (none[i], snap[i]) == (0, 1) else 1 if snap[i] - none[i] == 1 else 0)
                out[which].append((score, a, none[i], snap[i], r))
        out[which].sort(key=lambda t: (-t[0], -t[4], t[1]))
    return out

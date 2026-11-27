"""Read NC Flash / EcuFlash table definitions (the metadata XML already on the user's PC) and read / write table values
in a ROM image. Nothing from those definition files is bundled with the app; it reads the user's own file.

Format: <rom> with <romid><xmlid>CAL</xmlid>..., <scaling name units toexpr frexpr format min max storagetype endian/>,
<table name category type="1D|2D|3D" address elements scaling swapxy> with child <table type="X Axis|Y Axis" .../>.
3D data: swapxy="true" stores the Y axis fastest (index = x * ny + y), otherwise X fastest (index = y * nx + x).
"""
import math, re, struct
import xml.etree.ElementTree as ET

FMT = {'uint8': 'B', 'int8': 'b', 'uint16': 'H', 'int16': 'h', 'uint32': 'I', 'int32': 'i', 'float': 'f'}
_SAFE = {'__builtins__': {}, 'exp': math.exp, 'log': math.log, 'sqrt': math.sqrt, 'abs': abs, 'pow': pow}


def _expr(e):
    e = (e or 'x').strip().replace('^', '**')
    if not re.fullmatch(r'[0-9x+\-*/(). eE]*|.*\b(exp|log|sqrt|abs|pow)\b.*', e):
        raise ValueError(f'unsupported scaling expression {e!r}')
    return compile(e, '<scaling>', 'eval')


class Scaling:
    def __init__(self, el):
        g = el.get
        self.name, self.units = g('name'), g('units') or ''
        self.storage = g('storagetype') or 'float'
        if self.storage not in FMT: raise ValueError(f'scaling {self.name}: storage type {self.storage} not supported')
        self.fmt = ('<' if (g('endian') or 'big') == 'little' else '>') + FMT[self.storage]
        self.size = struct.calcsize(self.fmt)
        self.to_s, self.fr_s = g('toexpr') or 'x', g('frexpr') or 'x'
        self._to, self._fr = _expr(self.to_s), _expr(self.fr_s)
        self.format = g('format') or '%0.3f'
        self.min = float(g('min')) if g('min') not in (None, '') else None
        self.max = float(g('max')) if g('max') not in (None, '') else None

    def to_real(self, raw):
        return eval(self._to, _SAFE, {'x': raw})

    def from_real(self, v):
        raw = eval(self._fr, _SAFE, {'x': float(v)})
        if self.storage == 'float': return float(raw)
        lo, hi = {'B': (0, 255), 'b': (-128, 127), 'H': (0, 65535), 'h': (-32768, 32767),
                  'I': (0, 0xFFFFFFFF), 'i': (-2 ** 31, 2 ** 31 - 1)}[self.fmt[-1]]
        return max(lo, min(hi, int(round(raw))))

    def show(self, v):
        try:
            return (self.format % v) if '%' in self.format else f'{v:g}'
        except (TypeError, ValueError):
            return f'{v:g}'


class Table:
    def __init__(self, el, scalings, parent=None):
        g = el.get
        self.name, self.category, self.type = g('name'), g('category') or (parent.category if parent else ''), g('type') or '1D'
        self.address, self.elements = int(g('address'), 16), int(g('elements') or 1)
        self.scaling = scalings.get(g('scaling'))
        self.swapxy = (g('swapxy') or 'false').lower() == 'true'
        self.x = self.y = None
        for c in el.findall('table'):
            if c.get('address') is None: continue                      # static axes are not used by these definitions
            t = Table(c, scalings, self)
            if (c.get('type') or '').startswith('X'): self.x = t
            else: self.y = t

    @property
    def ok(self):
        return self.scaling is not None and all(a.scaling is not None for a in (self.x, self.y) if a)

    def span(self):
        """flash bytes the table's values occupy (not its axes)"""
        return self.address, self.address + self.elements * self.scaling.size

    def read_list(self, rom):
        s = self.scaling
        return [s.to_real(struct.unpack_from(s.fmt, rom, self.address + i * s.size)[0]) for i in range(self.elements)]

    def write_index(self, rom, i, value):
        s = self.scaling
        struct.pack_into(s.fmt, rom, self.address + i * s.size, s.from_real(value))

    def grid(self, rom):
        """-> (x axis values or None, y axis values or None, rows) with rows[y][x] (1D / 2D: one column)"""
        vals = self.read_list(rom)
        xs = self.x.read_list(rom) if self.x else None
        ys = self.y.read_list(rom) if self.y else None
        if self.type == '3D' and xs and ys:
            nx, ny = len(xs), len(ys)
            if nx * ny != len(vals): raise ValueError(f'{self.name}: {nx} x {ny} axis points but {len(vals)} values')
            rows = [[vals[(x * ny + y) if self.swapxy else (y * nx + x)] for x in range(nx)] for y in range(ny)]
            return xs, ys, rows
        axis = ys or xs
        if axis and len(axis) != len(vals): raise ValueError(f'{self.name}: {len(axis)} axis points but {len(vals)} values')
        return None, axis, [[v] for v in vals]

    def cell_index(self, row, col, nx=None, ny=None):
        if self.type == '3D' and self.x and self.y:
            return (col * ny + row) if self.swapxy else (row * nx + col)
        return row


class Definition:
    def __init__(self, path, cal):
        root = ET.parse(path).getroot()
        roms = [r for r in root.iter('rom')]
        rom = next((r for r in roms if (r.findtext('romid/xmlid') or '').strip().upper() == cal.upper()
                    or (r.findtext('romid/internalidstring') or '').strip().upper() == cal.upper()), None)
        if rom is None and len(roms) == 1: rom = roms[0]
        if rom is None: raise ValueError(f'no definition for {cal} in {path}')
        self.scalings, self.bad = {}, []
        for s in rom.iter('scaling'):
            try: self.scalings[s.get('name')] = Scaling(s)
            except ValueError as e: self.bad.append(str(e))
        self.tables = []
        for t in rom.findall('table'):
            if t.get('address') is None: continue
            try:
                tb = Table(t, self.scalings)
                if tb.ok: self.tables.append(tb)
                else: self.bad.append(f'{tb.name}: unknown scaling')
            except (ValueError, TypeError) as e:
                self.bad.append(f'{t.get("name")}: {e}')
        self.categories = {}
        for t in self.tables: self.categories.setdefault(t.category or 'Other', []).append(t)

"""Tab 4: datalog through the J2534 connection made in tab 1 (any J2534 interface: Tactrix OpenPort 2.0, OBDX, ...).
Read-only: it reads RAM by address, the same way as tab 1's live values. Live values, a scrolling graph, and a CSV log."""
import csv, os, struct, threading, time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import core


def channels(A):
    """(name, address, kind) for this calibration; kinds: f32, u8 (1 = on), wheel (4 x u16 km/h*100+10000), magic5A"""
    ch = [('RPM', A['rpm'], 'f32'), ('Speed km/h', A['speed'], 'f32'), ('Pedal %', A.get('igncut_pedal') or A['pedal_in'], 'f32'),
          ('Throttle request %', A['pedal_out'], 'f32')]
    if A.get('ect'): ch.append(('Coolant C', A['ect'], 'f32'))
    ch += [('Clutch', A['clutch'], 'u8'), ('Brake', A['brake'], 'u8')]
    if A.get('wheel_speeds'): ch.append(('Wheels', A['wheel_speeds'], 'wheel'))
    ch += [('Rev-match / anti-stall acting', 0xFFFFAC12, 'u8'), ('TC cutting', 0xFFFFAC4B, 'u8'), ('Overrun burst', 0xFFFFACD5, 'magic5A')]
    return ch


WHEELS = ('Front left km/h', 'Front right km/h', 'Rear left km/h', 'Rear right km/h')
GRAPH = (('RPM', 8000, '#D97757'), ('Speed km/h', 250, '#6EA8FE'), ('Pedal %', 100, '#8FD18F'), ('Throttle request %', 100, '#E5C07B'),
         ('Throttle %', 100, '#E5C07B'))


def obd_channels(obd):
    """standard OBD-II mode $01 channels this ECU supports (any NC ECU)"""
    import ecu as ECU
    return [(ECU.OBD_PIDS[p][0], p, 'obd') for p in obd.supported()]


def read_row(ecu, ch, obd=None):
    row = {}
    for name, addr, kind in ch:
        if kind == 'obd': row[name] = round(obd.read(addr), 3); continue
        if kind == 'f32': row[name] = round(ecu.f32(addr), 3)
        elif kind == 'u8': row[name] = 1 if ecu.u8(addr) == 1 else 0
        elif kind == 'magic5A': row[name] = 1 if ecu.u8(addr) == 0x5A else 0
        elif kind == 'wheel':
            raw = ecu.read(addr, 8)
            for i, w in enumerate(WHEELS):
                v = core.AD.wheel_kmh(struct.unpack_from('>H', raw, 2 * i)[0]); row[w] = '' if v is None else round(v, 2)
    return row


class LoggerTab:
    WINDOW_S = 20.0

    def __init__(self, app, frame, px, PAD, T):
        self.app, self.px, self.T = app, px, T
        self.running = False; self.hist = []; self.f = None; self.w = None; self.n = 0; self.t0 = 0; self.path = None
        bar = ttk.Frame(frame); bar.pack(fill='x', padx=px(8), pady=px(6))
        self.btn = ttk.Button(bar, text='Start logging...', command=self.toggle, style='Accent.TButton'); self.btn.pack(side='left')
        self.view_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text='Watch only (no file)', variable=self.view_only).pack(side='left', padx=px(10))
        self.obd_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text='Standard OBD-II only (any NC ECU)', variable=self.obd_only).pack(side='left')
        ttk.Button(bar, text='OpenPort SD-card file (logcfg.txt)...', command=self.make_logcfg).pack(side='right')
        self.stat = ttk.Label(bar, text='Connect in tab 1 first (any J2534 interface, e.g. Tactrix OpenPort 2.0).', style='Hint.TLabel')
        self.stat.pack(side='left', padx=px(10))
        self.vals = ttk.Frame(frame); self.vals.pack(fill='x', padx=px(8))
        self.lbls = {}
        self.canvas = tk.Canvas(frame, height=px(260), bg=T.SURFACE, highlightthickness=0); self.canvas.pack(fill='both', expand=True, padx=px(8), pady=px(6))
        leg = ttk.Frame(frame); leg.pack(fill='x', padx=px(8), pady=(0, px(6)))
        for name, mx, col in GRAPH:
            tk.Label(leg, text=f'■ {name} (0-{mx})', fg=col, bg=T.BG).pack(side='left', padx=(0, px(14)))
        ttk.Label(frame, text='Reads the ECU\'s RAM by address over the car connection; it never writes to the ECU. '
                              'The CSV has one row per sample (time in seconds, then every channel) and opens in Excel or '
                              'any log viewer. The sample rate depends on the interface (about 5-15 per second).',
                  style='Hint.TLabel', wraplength=px(880)).pack(anchor='w', padx=px(8), pady=(0, px(6)))

    def make_logcfg(self):
        """pick the channels, then write a logcfg.txt for the OpenPort 2.0's own microSD logging (no laptop)"""
        LogcfgDialog(self.app, self.px)


    def build_labels(self, names):
        for w in self.vals.winfo_children(): w.destroy()
        self.lbls = {}
        for i, n in enumerate(names):
            r, c = divmod(i, 6)
            ttk.Label(self.vals, text=n, style='Hint.TLabel').grid(row=2 * r, column=c, sticky='w', padx=self.px(6))
            self.lbls[n] = ttk.Label(self.vals, text='-', style='Big.TLabel'); self.lbls[n].grid(row=2 * r + 1, column=c, sticky='w', padx=self.px(6))

    def toggle(self):
        if self.running: self.running = False; return
        app = self.app
        if not app.pt:
            messagebox.showinfo('NC Patcher', 'Connect to the car in tab 1 first (any J2534 interface, e.g. Tactrix OpenPort 2.0).'); return
        import ecu as ECU
        self.obd = ECU.Obd(app.pt)
        ram = app.ecu is not None and getattr(app, 'A3', None) and not self.obd_only.get()
        if ram:                                  # this calibration's RAM: more channels (wheel speeds, patch states)
            A = core.with_switches(app.A3)[0]; self.ch = channels(A); cal = A['cal']
        else:                                    # any NC ECU: standard OBD-II
            with app.lock: self.ch = obd_channels(self.obd)
            if not self.ch: messagebox.showerror('NC Patcher', 'The ECU didn\'t list any standard OBD-II values.'); return
            cal = app.ecu_cal or 'NC'
            if not self.obd_only.get():
                self.app.log_to(self.app.log3, 'Datalog: calibration not known to NC Patcher or memory reads not available - '
                                               'logging standard OBD-II values.')
        A = {'cal': cal}
        names = [n for n, _, k in self.ch if k != 'wheel'] + ([*WHEELS] if any(k == 'wheel' for _, _, k in self.ch) else [])
        self.names = names; self.build_labels(names)
        self.path = None
        if not self.view_only.get():
            p = filedialog.asksaveasfilename(title='Save datalog as', defaultextension='.csv', filetypes=[('CSV', '*.csv')],
                                             initialfile=time.strftime(f'{A["cal"]} log %Y-%m-%d %H%M%S.csv'))
            if not p: return
            self.path = p; self.f = open(p, 'w', newline='', encoding='utf-8'); self.w = csv.writer(self.f)
            self.w.writerow(['time_s'] + names)
        self.hist = []; self.n = 0; self.t0 = time.monotonic(); self.running = True
        self.btn.config(text='Stop'); self.stat.config(text='Logging...' if self.path else 'Watching...')
        threading.Thread(target=self.loop, daemon=True).start(); self.app.after(250, self.redraw)

    def loop(self):
        err = None
        try:
            while self.running and self.app.pt:
                with self.app.lock:
                    row = read_row(self.app.ecu, self.ch, self.obd)
                t = time.monotonic() - self.t0; self.n += 1
                if self.w: self.w.writerow([f'{t:.3f}'] + [row.get(n, '') for n in self.names])
                if self.w and self.n % 20 == 0: self.f.flush()
                self.hist.append((t, row)); self.hist = [h for h in self.hist if h[0] > t - self.WINDOW_S] if self.n % 10 == 0 else self.hist
                self.last = row
        except Exception as e:
            err = e
        self.running = False
        if self.f: self.f.close(); self.f = None; self.w = None
        self.app.ui(self.stopped, err)

    def stopped(self, err):
        self.btn.config(text='Start logging...')
        rate = self.n / max(0.1, (time.monotonic() - self.t0))
        msg = (f'Read failed: {err}. ' if err else '') + (f'Saved {self.n} samples ({rate:.1f} per second) to {os.path.basename(self.path)}.'
                                                          if self.path else f'Stopped ({rate:.1f} samples per second).')
        self.stat.config(text=msg); self.app.log_to(self.app.log3, 'Datalog: ' + msg)

    def redraw(self):
        if not self.running: return
        row = getattr(self, 'last', None)
        if row:
            for n, l in self.lbls.items():
                v = row.get(n, '')
                l.config(text=('on' if v == 1 else 'off') if n in ('Clutch', 'Brake', 'Rev-match / anti-stall acting', 'TC cutting', 'Overrun burst')
                         else (f'{v:.0f}' if isinstance(v, float) and abs(v) >= 100 else f'{v}'))
            rate = self.n / max(0.1, time.monotonic() - self.t0)
            self.stat.config(text=f'{"Logging" if self.path else "Watching"}: {self.n} samples, {rate:.1f} per second')
        c = self.canvas; c.delete('all'); W, H = c.winfo_width(), c.winfo_height()
        for k in range(1, 4): c.create_line(0, H * k / 4, W, H * k / 4, fill=self.T.BORDER)
        h = list(self.hist)
        if len(h) > 1:
            tn = h[-1][0]
            for name, mx, col in GRAPH:
                pts = []
                for t, r in h:
                    v = r.get(name)
                    if isinstance(v, (int, float)):
                        pts += [W * (1 - (tn - t) / self.WINDOW_S), H - H * max(0, min(1, v / mx))]
                if len(pts) >= 4: c.create_line(*pts, fill=col, width=2)
        self.app.after(200, self.redraw)


class LogcfgDialog(tk.Toplevel):
    """tick what to log: engine values (RAM), wheel speeds, the patches' states, standard OBD-II -> logcfg.txt.
    The calibration and the ECU's memory-read format can be chosen here, so it works without the car connected."""
    FMT_TEXT = {'A4S2': 'A4S2 - 4-byte address, 2-byte length', 'A4S1': 'A4S1 - 4-byte address, 1-byte length',
                'A3S1': 'A3S1 - 3-byte address, 1-byte length', 'A3S2': 'A3S2 - 3-byte address, 2-byte length',
                'U14': 'U14 - UDS, 4-byte address, 1-byte length', 'U24': 'U24 - UDS, 4-byte address, 2-byte length'}

    def __init__(self, app, px):
        super().__init__(app); self.app, self.px = app, px
        self.title('OpenPort SD-card logging - choose what to log'); self.transient(app); self.configure(bg=app.cget('bg'))
        A = (getattr(app, 'A3', None) if app.pt else None) or app.A
        cal0 = A['cal'] if A else (app.ecu_cal or '')
        self.sup = None
        if app.pt:                                             # connected: only offer the OBD-II PIDs this ECU supports
            try:
                import ecu as ECU
                with app.lock: self.sup = set(ECU.Obd(app.pt).supported())
            except Exception:
                self.sup = None
        top = ttk.Frame(self); top.pack(fill='x', padx=px(10), pady=(px(10), 0))
        cals = sorted({a['cal'] for a in core.AD.known()})
        ttk.Label(top, text='Calibration').pack(side='left')
        self.cal_var = tk.StringVar(value=cal0 if cal0 in cals else '(OBD-II only)')
        cb = ttk.Combobox(top, textvariable=self.cal_var, state='readonly', width=14, values=['(OBD-II only)'] + cals)
        cb.pack(side='left', padx=(px(6), px(16))); cb.bind('<<ComboboxSelected>>', lambda e: self.rebuild())
        ttk.Label(top, text='Memory read format').pack(side='left')
        self.fmt_var = tk.StringVar()
        self.fmt_box = ttk.Combobox(top, textvariable=self.fmt_var, state='readonly', width=44)
        self.fmt_box.pack(side='left', padx=px(6)); self.fmt_box.bind('<<ComboboxSelected>>', lambda e: self.rebuild(keep_fmt=True))
        self.note = ttk.Label(self, text='', wraplength=px(740), style='Hint.TLabel'); self.note.pack(anchor='w', padx=px(10), pady=px(6))
        self.body = ttk.Frame(self); self.body.pack(fill='both', expand=True, padx=px(10))
        bar = ttk.Frame(self); bar.pack(fill='x', padx=px(10), pady=px(10))
        ttk.Button(bar, text='Defaults', command=lambda: self.set_all('default')).pack(side='left')
        ttk.Button(bar, text='All', command=lambda: self.set_all(True)).pack(side='left', padx=px(6))
        ttk.Button(bar, text='None', command=lambda: self.set_all(False)).pack(side='left')
        self.n_lbl = ttk.Label(bar, text='', style='Hint.TLabel'); self.n_lbl.pack(side='left', padx=px(12))
        ttk.Button(bar, text='Generate logcfg.txt...', style='Accent.TButton', command=self.generate).pack(side='right')
        self.rebuild()

    def rebuild(self, keep_fmt=False):
        px = self.px; cal = self.cal_var.get()
        known = {a['cal']: a for a in core.AD.known()}
        self.A = core.with_switches(known[cal])[0] if cal in known else None
        self.cal = cal if self.A else (self.app.ecu_cal or '')
        learned = core.remembered_read_format(cal) if self.A else None
        if self.A:
            opts = [self.FMT_TEXT[f] + ('  (learned from your car)' if learned and learned['fmt'] == f else '') for f in core.LOGCFG_MODE23]
            self.fmt_box.config(values=opts, state='readonly')
            if not keep_fmt or not self.fmt_var.get():
                f = learned['fmt'] if learned and learned['fmt'] in core.LOGCFG_MODE23 else 'A4S2'
                self.fmt_var.set(opts[list(core.LOGCFG_MODE23).index(f)])
            fmt = self.fmt_var.get().split(' ')[0]
            self.rf = {'fmt': fmt, 'skip': learned['skip'] if learned and learned['fmt'] == fmt else 0}
        else:
            self.fmt_box.config(values=(), state='disabled'); self.fmt_var.set(''); self.rf = None
        confirmed = bool(learned and self.rf and learned['fmt'] == self.rf['fmt'])
        self.note.config(text=(f'{cal}: engine values, wheel speeds and the patches\' states are read from the ECU\'s memory. '
                               + ('The read format was learned from your car. ' if confirmed else
                                  'The read format hasn\'t been confirmed on your car: A4S2 is the usual one; connecting once in '
                                  'tab 1 confirms it (if the OpenPort logs nothing, connect once and make the file again). ')
                               if self.A else 'No calibration chosen: standard OBD-II values only (they work on any NC ECU). ')
                          + ('Only the OBD-II values your ECU says it supports are offered. ' if self.sup is not None else
                             'Not connected: an OBD-II value your ECU doesn\'t support can stop the logging, so only the common '
                             'ones are ticked. ') + 'Fewer channels give more samples per second.')
        self.cat = core.log_catalog(self.A, core.remembered_tcs(cal) if self.A else None)
        for w in self.body.winfo_children(): w.destroy()
        self.vars = []; cols = [ttk.Frame(self.body), ttk.Frame(self.body)]
        for c in cols: c.pack(side='left', fill='both', expand=True, anchor='n', padx=(0, px(10)))
        groups = []
        for c in self.cat:
            if c['group'] not in groups: groups.append(c['group'])
        for g in groups:
            f = ttk.LabelFrame(cols[0 if g != 'Standard OBD-II (any NC ECU)' else 1], text=g); f.pack(fill='x', pady=px(4), anchor='n')
            for c in [c for c in self.cat if c['group'] == g]:
                usable = (c['mode'] == 0x23 and self.A is not None) or (c['mode'] == 0x01 and (self.sup is None or c['id'] in self.sup))
                v = tk.BooleanVar(value=bool(c['default'] and usable))
                ttk.Checkbutton(f, text=c['name'], variable=v, state='normal' if usable else 'disabled',
                                command=self.count).pack(anchor='w', padx=px(6))
                self.vars.append((c, v, usable))
        self.count()

    def set_all(self, how):
        for c, v, ok in self.vars: v.set(bool(ok and (c['default'] if how == 'default' else how)))
        self.count()

    def picked(self):
        return [c for c, v, ok in self.vars if ok and v.get()]

    def count(self):
        self.n_lbl.config(text=f'{len(self.picked())} channels selected')

    def generate(self):
        picked = self.picked()
        if not picked: messagebox.showinfo('NC Patcher', 'Tick at least one channel.', parent=self); return
        learned = core.remembered_read_format(self.cal) if self.A else None
        if any(c['mode'] == 0x23 for c in picked) and not (learned and self.rf and learned['fmt'] == self.rf['fmt']):
            if not messagebox.askokcancel(
                    'NC Patcher - read format not confirmed',
                    'The engine values, wheel speeds and patch channels are read straight from the ECU\'s memory, and the '
                    'file has to say exactly how your ECU answers those reads (its "memory read format").\n\n'
                    f'NC Patcher hasn\'t learned that from your car yet, so this file uses {self.rf["fmt"]}, the usual one '
                    'for NC ECUs.\n\nIf the OpenPort doesn\'t record anything with this file: connect to the car once in '
                    'tab 1 (Check my car) so NC Patcher learns your ECU\'s format, then make the file again. The standard '
                    'OBD-II values work either way.\n\nMake the file now?', parent=self):
                return
        p = filedialog.asksaveasfilename(parent=self, title='Save logcfg.txt (then copy it to the root of the OpenPort\'s microSD card)',
                                         initialfile='logcfg.txt', defaultextension='.txt', filetypes=[('Text', '*.txt')])
        if not p: return
        txt = core.logcfg_custom_text(self.cal, picked, *((self.rf['fmt'], self.rf['skip']) if self.rf else (None, 0)))
        open(p, 'w', encoding='ascii', newline='\r\n').write(txt)
        messagebox.showinfo('NC Patcher', f'Saved {p} ({len(picked)} channels).\n\nCopy it to the ROOT of the OpenPort 2.0\'s microSD '
                                          'card, named exactly logcfg.txt. With the cable plugged in and the ignition on, it logs to '
                                          'the card by itself. Not yet tried on a car: check a log appears and the values look right.',
                            parent=self)
        self.destroy()

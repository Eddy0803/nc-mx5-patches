"""NC Patcher - GUI for the NC MX-5 ECU patches.

Tab 1: port the patches to another calibration (stock LFJ1EE + your stock ROM).
Tab 2: drop your ECU file, choose features and settings, save a patched file (flash it with NC Flash).
Tab 3: connect to the car through a J2534 interface (read-only) to identify the ECU, run the pedal check
       (confirms the clutch / brake RAM addresses) and watch live values.
"""
import os, queue, struct, sys, threading, traceback

if sys.stdout is None: sys.stdout = open(os.devnull, 'w')      # windowed .exe has no console
if sys.stderr is None: sys.stderr = open(os.devnull, 'w')
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core                       # noqa: E402
import ecu as ECU                 # noqa: E402
import j2534                      # noqa: E402
try:
    import dragdrop               # noqa: E402
except Exception:                 # non-Windows or no comctl32: browsing still works
    dragdrop = None

APP = 'NC Patcher'
VERSION = '0.9.4 beta'
PAD = {'padx': 8, 'pady': 4}


class DropZone(tk.Frame):
    """a box you can drop a file on, or click to browse"""
    def __init__(self, master, text, on_file, height=70):
        super().__init__(master, bd=2, relief='groove', bg='#f4f6f8', height=height, cursor='hand2')
        self.pack_propagate(False)
        self.text = text; self.on_file = on_file
        self.label = tk.Label(self, text=text, bg='#f4f6f8', fg='#333', wraplength=560, justify='center')
        self.label.pack(expand=True, fill='both', padx=10)
        for w in (self, self.label):
            w.bind('<Button-1>', lambda e: self.browse())
        if dragdrop:
            self.after(50, lambda: (dragdrop.enable(self, self._dropped), dragdrop.enable(self.label, self._dropped)))

    def browse(self):
        p = filedialog.askopenfilename(title=self.text, filetypes=[('ECU files', '*.bin'), ('All files', '*.*')])
        if p: self.on_file(p)

    def _dropped(self, files):
        if files: self.on_file(files[0])

    def show(self, text, ok=True):
        self.label.config(text=text, fg='#1b5e20' if ok else '#b71c1c')


def labelled(parent, row, text, var, width=10, tip=''):
    ttk.Label(parent, text=text).grid(row=row, column=0, sticky='w', **PAD)
    e = ttk.Entry(parent, textvariable=var, width=width); e.grid(row=row, column=1, sticky='w', **PAD)
    if tip: ttk.Label(parent, text=tip, foreground='#666').grid(row=row, column=2, sticky='w', **PAD)
    return e


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'{APP} {VERSION}')
        self.geometry('920x720'); self.minsize(820, 620)
        self.q = queue.Queue()
        self.lock = threading.Lock()
        self.pt = None; self.ecu = None; self.ecu_cal = None; self.live_on = False
        self.snaps = {}
        nb = ttk.Notebook(self); nb.pack(fill='both', expand=True, padx=6, pady=6)
        self.nb = nb; self.auto_patch_cal = None
        self.t1, self.t2, self.t3 = (ttk.Frame(nb) for _ in range(3))
        nb.add(self.t2, text='  1. Port to another calibration  ')
        nb.add(self.t1, text='  2. Patch my ECU file  ')
        nb.add(self.t3, text='  3. Car connection (J2534)  ')
        self.build_tab1(); self.build_tab2(); self.build_tab3()
        self.after(100, self.pump)
        self.protocol('WM_DELETE_WINDOW', self.quit_app)

    # ------------------------------------------------------------------ helpers
    def pump(self):
        try:
            while True:
                fn, args = self.q.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.after(100, self.pump)

    def ui(self, fn, *args):
        self.q.put((fn, args))

    def work(self, fn, *args, done=None):
        def run():
            try:
                r = fn(*args)
                if done: self.ui(done, r, None)
            except Exception as e:
                traceback.print_exc()
                if done: self.ui(done, None, e)
        threading.Thread(target=run, daemon=True).start()

    @staticmethod
    def log_to(widget, text):
        widget.configure(state='normal'); widget.insert('end', text + '\n'); widget.see('end'); widget.configure(state='disabled')

    def quit_app(self):
        self.live_on = False
        try:
            if self.pt: self.pt.close()
        except Exception:
            pass
        self.destroy()

    # ------------------------------------------------------------------ tab 2
    def build_tab1(self):
        t = self.t1
        ttk.Label(t, text='Drop your ECU file (a 1 MB .bin read with NC Flash) to add the patches to it. '
                          'The file you drop is never changed; you save a new one.', wraplength=860).pack(anchor='w', **PAD)
        self.drop1 = DropZone(t, 'Drop your ECU file here  -  or click to browse', self.load_rom)
        self.drop1.pack(fill='x', padx=8, pady=4)
        self.info1 = ttk.Label(t, text='', wraplength=860); self.info1.pack(anchor='w', **PAD)
        body = ttk.Frame(t); body.pack(fill='x', padx=4)
        # ignition cut
        self.ig_on = tk.BooleanVar(value=True)
        f = ttk.LabelFrame(body, text='Ignition-cut rev limiter, launch control, flat-foot shift'); f.pack(side='left', fill='both', expand=True, padx=4)
        ttk.Checkbutton(f, text='Install / keep this patch', variable=self.ig_on).grid(row=0, column=0, columnspan=3, sticky='w', **PAD)
        self.ig_vars = {k: tk.StringVar() for k in ('LAUNCH', 'FS', 'RET', 'OFS', 'FSAPP', 'VSPLIT', 'DW')}
        labelled(f, 1, 'Launch control RPM', self.ig_vars['LAUNCH'], tip='0 = off')
        labelled(f, 2, 'Flat-shift RPM', self.ig_vars['FS'], tip='0 = off')
        labelled(f, 3, 'Timing retard while cutting', self.ig_vars['RET'], tip='degrees')
        labelled(f, 4, 'Cut below RPM Fuel Cut by', self.ig_vars['OFS'], tip='rpm (negative)')
        labelled(f, 5, 'Flat shift needs pedal above', self.ig_vars['FSAPP'], tip='%')
        labelled(f, 6, 'Launch / flat-shift split speed', self.ig_vars['VSPLIT'], tip='km/h')
        labelled(f, 7, 'Coil dwell while cutting', self.ig_vars['DW'], tip='ms (min 0.2)')
        ttk.Label(f, text='Rev limit = your RPM Fuel Cut table (change it in NC Flash).', foreground='#666').grid(row=8, column=0, columnspan=3, sticky='w', **PAD)
        # rev-match
        self.rv_on = tk.BooleanVar(value=True)
        g = ttk.LabelFrame(body, text='Downshift rev-match, upshift hold, anti-stall'); g.pack(side='left', fill='both', expand=True, padx=4)
        self.rv_chk = ttk.Checkbutton(g, text='Install / keep this patch', variable=self.rv_on); self.rv_chk.grid(row=0, column=0, columnspan=2, sticky='w', **PAD)
        self.rv_en, self.rv_up, self.rv_as = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()
        ttk.Checkbutton(g, text='Rev-match on downshifts (clutch + brake)', variable=self.rv_en).grid(row=1, column=0, columnspan=2, sticky='w', **PAD)
        ttk.Checkbutton(g, text='Upshift hold (clutch, no brake)', variable=self.rv_up).grid(row=2, column=0, columnspan=2, sticky='w', **PAD)
        ttk.Checkbutton(g, text='Anti-stall', variable=self.rv_as).grid(row=3, column=0, columnspan=2, sticky='w', **PAD)
        self.rv_note = ttk.Label(g, text='', foreground='#666', wraplength=360); self.rv_note.grid(row=4, column=0, columnspan=2, sticky='w', **PAD)
        ttk.Label(g, text='Fine tuning (gains, offsets, gearing) is done in NC Flash after adding the tables.',
                  foreground='#666', wraplength=360).grid(row=5, column=0, columnspan=2, sticky='w', **PAD)
        bar = ttk.Frame(t); bar.pack(fill='x', padx=8, pady=6)
        self.btn_save = ttk.Button(bar, text='Save patched file...', command=self.save_patched, state='disabled'); self.btn_save.pack(side='left')
        self.btn_defs = ttk.Button(bar, text='Show the new tables in NC Flash', command=self.add_defs, state='disabled'); self.btn_defs.pack(side='left', padx=8)
        self.log1 = tk.Text(t, height=10, state='disabled', bg='#fbfbfb'); self.log1.pack(fill='both', expand=True, padx=8, pady=4)
        self.rom = None; self.rom_path = None; self.A = None
        self.set_defaults()

    def set_defaults(self, st=None):
        ig = (st or {}).get('ig') or {}
        d = dict(core.IG.DEFAULTS); d.update({k: v for k, v in ig.items() if v == v})
        for k, v in self.ig_vars.items(): v.set(f'{d[k]:g}')
        rv = (st or {}).get('rv') or {}
        self.rv_en.set(bool(rv.get('EN', 0) > 0)); self.rv_up.set(bool(rv.get('UPEN', 0) > 0)); self.rv_as.set(bool(rv.get('ASEN', 0) > 0))

    def load_rom(self, path):
        try:
            rom = core.read_rom(path)
        except (OSError, ValueError) as e:
            self.drop1.show(str(e), ok=False); return
        cal, A = core.guess_cal(rom)
        self.rom, self.rom_path, self.A = rom, path, A
        name = os.path.basename(path)
        gb = core.AD.gearbox(rom)
        if gb and not gb['manual']:
            self.A = None
            self.drop1.show(f'{name}\nCalibration {cal}: this is an AUTOMATIC ({gb["name"]}). The patches are for manual gearboxes only.', ok=False)
            self.btn_save.config(state='disabled'); self.btn_defs.config(state='disabled'); self.info1.config(text='')
            self.auto_patch_cal = None
            return
        if not A:
            self.drop1.show(f'{name}\nCalibration {cal or "unknown"} is not supported yet - port it in tab 1 first.', ok=False)
            self.btn_save.config(state='disabled'); self.btn_defs.config(state='disabled'); self.info1.config(text='')
            if cal: self.cal_var.set(cal)
            return
        st = core.state(rom, A)
        self.drop1.show(f'{name}\nCalibration {cal}' + (f' - {gb["name"]}' if gb else '') +
                        ('' if A.get('verified_on_car') else '  (ported - not yet proven on a car)'))
        inst = [n for n, k in (('ignition cut', 'igncut'), ('rev-match', 'revmatch')) if st[k]]
        self.info1.config(text=('Already installed: ' + ', '.join(inst) + ' - current settings loaded below.') if inst
                          else 'No patches installed yet (a stock or tuned ROM).')
        self.set_defaults(st)
        rv_ok = core.rev_available(A)
        self.rv_chk.config(state='normal' if rv_ok else 'disabled')
        if not rv_ok: self.rv_on.set(False)
        brake = A.get('brake')
        self.rv_note.config(text=(f'Brake switch RAM 0x{brake:08X}, clutch 0x{A["clutch"]:08X}' +
                                  ('' if A.get('verified_on_car') or A.get('switches_confirmed_on_car') else
                                   ' - not yet confirmed on the car (tab 3 pedal check)')) if rv_ok else
                             'Rev-match is not available for this calibration (see its port report).')
        self.btn_save.config(state='normal'); self.btn_defs.config(state='normal')
        self.log_to(self.log1, f'Loaded {name}: {cal}.')
        if self.auto_patch_cal:
            if cal == self.auto_patch_cal:
                self.auto_patch_cal = None
                self.log_to(self.log1, f'Applying the {cal} patches automatically...')
                self.after(150, self.save_patched)
            else:
                messagebox.showwarning(APP, f'This file is {cal}, but the port was for {self.auto_patch_cal}. '
                                            f'Drop your {self.auto_patch_cal} ECU file to apply the new patches.')

    def _ig_values(self):
        try:
            return {k: float(v.get()) for k, v in self.ig_vars.items()}
        except ValueError:
            raise ValueError('the ignition-cut settings must be numbers')

    def save_patched(self):
        if not self.rom: return
        try:
            ig = self._ig_values() if self.ig_on.get() else None
            rv = None
            if self.rv_on.get():
                rv = {'EN': 1.0 if self.rv_en.get() else 0.0, 'UPEN': 1.0 if self.rv_up.get() else 0.0, 'ASEN': 1.0 if self.rv_as.get() else 0.0}
            if ig is None and rv is None:
                messagebox.showinfo(APP, 'Tick at least one patch.'); return
            rom = bytearray(self.rom)
            notes = core.patch(rom, self.A, ig, rv)
        except Exception as e:
            messagebox.showerror(APP, f'Could not patch this file:\n\n{e}'); return
        tests = (['igncut_emu.py'] if ig is not None or core.state(rom, self.A)['igncut'] else []) + \
                (['revemu.py'] if core.state(rom, self.A)['revmatch'] else [])
        self.log_to(self.log1, 'Patched in memory: ' + '; '.join(notes) + '. Running the emulator tests...')
        self.update_idletasks()
        res = core.emulate(rom, self.A, tests)
        for t, (last, fails) in res.items(): self.log_to(self.log1, f'  {t}: {last}' + (f'  {fails[:3]}' if fails else ''))
        if not all(v[0] == 'ALL PASS' for v in res.values()):
            messagebox.showerror(APP, 'The emulator tests failed - the file was NOT saved.'); return
        stem, ext = os.path.splitext(self.rom_path)
        p = filedialog.asksaveasfilename(title='Save patched ECU file', initialfile=os.path.basename(stem) + ' - patched' + (ext or '.bin'),
                                         initialdir=os.path.dirname(self.rom_path), defaultextension='.bin', filetypes=[('ECU files', '*.bin')])
        if not p: return
        if os.path.abspath(p) == os.path.abspath(self.rom_path):
            messagebox.showerror(APP, 'Choose a new file name - the original is never overwritten.'); return
        open(p, 'wb').write(rom)
        self.log_to(self.log1, f'Saved {p}')
        messagebox.showinfo(APP, f'Saved:\n{p}\n\nNext:\n1. Click "Show the new tables in NC Flash" (once).\n'
                                 '2. Open the file in NC Flash, check the settings, and do a FULL flash the first time.\n'
                                 '3. Test one feature at a time, with a datalog.')

    def add_defs(self):
        if not self.A: return
        if not core.defs_source(self.A):
            messagebox.showerror(APP, 'No table definitions for this calibration.'); return
        p = core.ncflash_definition(self.A['cal'])
        if not p:
            p = filedialog.askopenfilename(title=f'Find the {self.A["cal"]} definition file (NC Flash or EcuFlash)', filetypes=[('Definition', '*.xml')])
            if not p: return
        if not messagebox.askokcancel(APP, f'Add the patch tables to:\n{p}\n\nClose NC Flash / EcuFlash first. A backup (.bak) is made next to the file.'):
            return
        ok, msg = core.add_definitions(p, self.A)
        self.log_to(self.log1, msg)
        (messagebox.showinfo if ok else messagebox.showerror)(APP, msg[-1200:])

    # ------------------------------------------------------------------ tab 1
    def build_tab2(self):
        t = self.t2
        ttk.Label(t, text='Port the patches to another calibration: drop a STOCK LFJ1EE file (the reference) and a STOCK read of '
                          'your calibration. Every address is found automatically and checked; the port stops rather than guessing.',
                  wraplength=860).pack(anchor='w', **PAD)
        self.ref_path = self.stock_path = None
        self.drop_ref = DropZone(t, 'Drop a stock LFJ1EE file here (the reference)', self.load_ref, height=56); self.drop_ref.pack(fill='x', padx=8, pady=3)
        self.drop_stock = DropZone(t, 'Drop a stock read of YOUR calibration here', self.load_stock, height=56); self.drop_stock.pack(fill='x', padx=8, pady=3)
        f = ttk.Frame(t); f.pack(fill='x', padx=8)
        self.cal_var = tk.StringVar(); self.clutch_var = tk.StringVar(); self.brake_var = tk.StringVar(); self.allow_rate = tk.BooleanVar()
        labelled(f, 0, 'Calibration ID', self.cal_var, tip='filled in from the file')
        labelled(f, 1, 'Clutch RAM address (optional)', self.clutch_var, width=14, tip='only if the pedal check (tab 3) found a different one')
        labelled(f, 2, 'Brake RAM address (optional)', self.brake_var, width=14)
        ttk.Checkbutton(f, text='Build rev-match even if its call rate differs from LFJ1EE (you will measure and retune)',
                        variable=self.allow_rate).grid(row=3, column=0, columnspan=3, sticky='w', **PAD)
        bar = ttk.Frame(t); bar.pack(fill='x', padx=8, pady=4)
        self.btn_port = ttk.Button(bar, text='Port', command=self.do_port); self.btn_port.pack(side='left')
        self.btn_report = ttk.Button(bar, text='Open report', command=lambda: self.open(self.last_report), state='disabled'); self.btn_report.pack(side='left', padx=8)
        ttk.Button(bar, text='Open ports folder', command=lambda: self.open(core.PORTS)).pack(side='left')
        self.prog2 = ttk.Progressbar(bar, mode='indeterminate', length=200); self.prog2.pack(side='right')
        self.log2 = tk.Text(t, height=14, state='disabled', bg='#fbfbfb'); self.log2.pack(fill='both', expand=True, padx=8, pady=4)
        self.last_report = None

    def load_ref(self, p):
        try:
            rom = core.read_rom(p)
        except (OSError, ValueError) as e:
            self.drop_ref.show(str(e), ok=False); return
        if not core.AD.is_cal(rom, core.AD.LFJ1EE):
            self.drop_ref.show(f'{os.path.basename(p)} is not an LFJ1EE file', ok=False); return
        self.ref_path = p; self.drop_ref.show(f'Reference: {os.path.basename(p)} (LFJ1EE)')

    def load_stock(self, p):
        try:
            rom = core.read_rom(p)
        except (OSError, ValueError) as e:
            self.drop_stock.show(str(e), ok=False); return
        cal, A = core.guess_cal(rom)
        gb = core.AD.gearbox(rom)
        self.stock_path = p; self.cal_var.set(cal or '')
        if gb and not gb['manual']:
            self.drop_stock.show(f'{os.path.basename(p)} - calibration {cal}: AUTOMATIC ({gb["name"]}). '
                                 'The patches are for manual gearboxes only.', ok=False)
            return
        self.drop_stock.show(f'Your ROM: {os.path.basename(p)} - calibration {cal or "? (type it in)"}'
                             + (f', {gb["name"]}' if gb else ', gearbox not recognised') + ('  (already supported)' if A else ''),
                             ok=bool(gb))

    @staticmethod
    def open(path):
        if path and os.path.exists(path): os.startfile(path)

    def do_port(self):
        if not (self.ref_path and self.stock_path and self.cal_var.get().strip()):
            messagebox.showinfo(APP, 'Drop both files first (and check the calibration ID).'); return
        cal = self.cal_var.get().strip().upper()
        parse = lambda s: s.strip() or None
        self.btn_port.config(state='disabled'); self.prog2.start(12)
        self.log_to(self.log2, f'Porting to {cal}...')
        log = lambda s: self.ui(self.log_to, self.log2, s)
        self.work(core.port, self.ref_path, self.stock_path, cal, parse(self.clutch_var.get()), parse(self.brake_var.get()),
                  self.allow_rate.get(), log, done=self.port_done)

    def port_done(self, r, err):
        self.prog2.stop(); self.btn_port.config(state='normal')
        if err:
            self.log_to(self.log2, f'ERROR: {err}'); messagebox.showerror(APP, str(err)); return
        if not r.get('report'):
            self.log_to(self.log2, f'STOPPED: {r["error"]}\nNothing was written.')
            messagebox.showwarning(APP, f'The port stopped:\n\n{r["error"]}\n\nNothing was written.'); return
        self.last_report = r['report']; self.btn_report.config(state='normal')
        for w in r['warnings']: self.log_to(self.log2, ' ! ' + w)
        self.log_to(self.log2, ('DONE - emulators ALL PASS. ' if r['ok'] else 'EMULATOR FAILURES - do not use. ') + f'Saved in {r["out"]}')
        if r['ok']:
            cal = r['A']['cal']
            go = messagebox.askyesno(APP, f'Ported to {cal} - the patches for {cal} are ready.\n\n'
                                          f'Next: go to tab 2 "Patch my ECU file" and drop your {cal} ECU file again. The patches '
                                          f'will be applied to it automatically, tested, and you\'ll be asked where to save the patched copy.\n\n'
                                          'Read the report, and confirm the clutch / brake addresses on the car (tab 3) before relying on them.\n\n'
                                          'Go to tab 2 now?')
            if go:
                self.auto_patch_cal = cal
                self.nb.select(self.t1)
                self.drop1.show(f'Drop your {cal} ECU file here (or click to browse) - the patches will be applied automatically')

    # ------------------------------------------------------------------ tab 3
    def build_tab3(self):
        t = self.t3
        ttk.Label(t, text='Connect to the car with a J2534 interface (OBDX, Tactrix OpenPort, ...). This app only READS from the ECU - '
                          'it never writes or flashes. Ignition on; engine off for the pedal check.', wraplength=860).pack(anchor='w', **PAD)
        f = ttk.Frame(t); f.pack(fill='x', padx=8)
        self.devs = []
        self.dev_var = tk.StringVar()
        self.dev_box = ttk.Combobox(f, textvariable=self.dev_var, state='readonly', width=62); self.dev_box.grid(row=0, column=0, **PAD)
        ttk.Button(f, text='Refresh', command=self.refresh_devices).grid(row=0, column=1, **PAD)
        self.btn_conn = ttk.Button(f, text='Connect', command=self.connect); self.btn_conn.grid(row=0, column=2, **PAD)
        self.conn_lbl = ttk.Label(f, text='Not connected'); self.conn_lbl.grid(row=1, column=0, columnspan=3, sticky='w', **PAD)
        # pedal check
        g = ttk.LabelFrame(t, text='Pedal check: confirms which RAM bytes are the brake and clutch switches'); g.pack(fill='x', padx=8, pady=6)
        ttk.Label(g, text='Ignition on, engine off. Press each button and do what it says; each capture takes a few seconds.',
                  wraplength=840).grid(row=0, column=0, columnspan=5, sticky='w', **PAD)
        self.snap_btns = {}
        for i, (k, txt) in enumerate((('none1', '1. No pedals pressed'), ('brake', '2. HOLD the brake'),
                                      ('none2', '3. No pedals again'), ('clutch', '4. HOLD the clutch'))):
            b = ttk.Button(g, text=txt, command=lambda k=k: self.capture(k), state='disabled'); b.grid(row=1, column=i, **PAD)
            self.snap_btns[k] = b
        self.btn_analyse = ttk.Button(g, text='Analyse', command=self.analyse, state='disabled'); self.btn_analyse.grid(row=1, column=4, **PAD)
        self.prog3 = ttk.Progressbar(g, mode='determinate', length=300); self.prog3.grid(row=2, column=0, columnspan=3, sticky='w', **PAD)
        self.btn_confirm = ttk.Button(g, text='Save these for my calibration', command=self.save_switches, state='disabled')
        self.btn_confirm.grid(row=2, column=3, columnspan=2, sticky='e', **PAD)
        # live
        h = ttk.LabelFrame(t, text='Live values'); h.pack(fill='x', padx=8, pady=6)
        self.live_var = tk.BooleanVar()
        self.live_chk = ttk.Checkbutton(h, text='Show live values', variable=self.live_var, command=self.toggle_live, state='disabled')
        self.live_chk.grid(row=0, column=0, sticky='w', **PAD)
        self.live_lbls = {}
        for i, k in enumerate(('RPM', 'Speed km/h', 'Pedal %', 'Clutch', 'Brake')):
            ttk.Label(h, text=k).grid(row=1, column=i, **PAD)
            self.live_lbls[k] = ttk.Label(h, text='-', font=('Segoe UI', 13, 'bold')); self.live_lbls[k].grid(row=2, column=i, **PAD)
        self.log3 = tk.Text(t, height=9, state='disabled', bg='#fbfbfb'); self.log3.pack(fill='both', expand=True, padx=8, pady=4)
        self.found = {}
        self.refresh_devices()

    def refresh_devices(self):
        try:
            self.devs = j2534.list_devices()
        except Exception as e:
            self.devs = []; self.log_to(self.log3, f'Could not list J2534 interfaces: {e}')
        names = [f'{d["name"]}' + ('' if d['usable'] else ('   (driver file missing)' if d['bits'] is None else f'   ({d["bits"]}-bit driver - not usable by this 32-bit app)')) for d in self.devs]
        self.dev_box['values'] = names
        usable = [i for i, d in enumerate(self.devs) if d['usable']]
        if usable: self.dev_box.current(usable[0])
        elif names: self.dev_box.current(0)
        if not self.devs: self.log_to(self.log3, 'No J2534 interfaces are installed. Install your interface\'s J2534 driver first.')

    def connect(self):
        if self.pt:
            self.live_on = False; self.live_var.set(False)
            with self.lock:
                try: self.pt.close()
                except Exception: pass
            self.pt = self.ecu = None
            self.conn_lbl.config(text='Not connected'); self.btn_conn.config(text='Connect'); self._enable3(False); return
        i = self.dev_box.current()
        if i < 0 or not self.devs: return
        d = self.devs[i]
        if not d['usable']:
            messagebox.showerror(APP, f'{d["name"]} has a {d["bits"]}-bit driver; this app is {j2534.APP_BITS}-bit.'); return
        self.conn_lbl.config(text=f'Connecting to {d["name"]}...'); self.btn_conn.config(state='disabled')
        log = lambda s: self.ui(self.log_to, self.log3, s)

        def go():
            pt = j2534.PassThru(d['dll']); pt.open()
            try:
                v = pt.version(); pt.connect_iso15765()
                e = ECU.Ecu(pt, log); cal = e.probe()
                return pt, e, cal, v
            except Exception:
                pt.close(); raise
        self.work(go, done=self.connected)

    def connected(self, r, err):
        self.btn_conn.config(state='normal')
        if err:
            self.conn_lbl.config(text=f'Could not connect: {err}'); self.log_to(self.log3, f'Connect failed: {err}'); return
        self.pt, self.ecu, cal, v = r
        try:
            self.A3 = core.AD.for_cal(cal)
        except AssertionError:
            self.A3 = None
        self.ecu_cal = cal
        self.conn_lbl.config(text=f'Connected ({v}). ECU calibration: {cal}' + ('' if self.A3 else ' - not supported yet (port it in tab 1)'))
        self.btn_conn.config(text='Disconnect'); self._enable3(True)

    def _enable3(self, on):
        s = 'normal' if on else 'disabled'
        for b in self.snap_btns.values(): b.config(state=s)
        self.live_chk.config(state=s if (on and getattr(self, 'A3', None)) else 'disabled')
        if not on: self.btn_analyse.config(state='disabled'); self.btn_confirm.config(state='disabled')

    def capture(self, which):
        if not self.ecu: return
        self.live_on = False; self.live_var.set(False)
        for b in self.snap_btns.values(): b.config(state='disabled')
        self.prog3['value'] = 0
        self.log_to(self.log3, f'Capturing "{self.snap_btns[which]["text"]}"... keep still.')

        def go():
            with self.lock:
                return self.ecu.snapshot(progress=lambda f: self.ui(self.prog3.configure, {'value': f * 100}))
        self.work(go, done=lambda r, err: self.captured(which, r, err))

    def captured(self, which, r, err):
        for b in self.snap_btns.values(): b.config(state='normal')
        if err:
            self.log_to(self.log3, f'Capture failed: {err}'); return
        self.snaps[which] = r
        self.snap_btns[which].config(text=self.snap_btns[which]['text'].split('  ')[0] + '  ✓')
        self.log_to(self.log3, f'Captured {len(r)} bytes of RAM.')
        if all(k in self.snaps for k in ('none1', 'brake', 'clutch')): self.btn_analyse.config(state='normal')

    def analyse(self):
        nones = [self.snaps['none1']] + ([self.snaps['none2']] if 'none2' in self.snaps else [])
        rom = bytes(self.rom) if (self.rom and self.A and self.A['cal'] == self.ecu_cal) else None
        if rom is None:
            self.log_to(self.log3, 'Tip: drop this car\'s ECU file in tab 2 first - the analysis then ranks the candidates far better.')
        r = ECU.analyse(nones, self.snaps['brake'], self.snaps['clutch'], rom)
        self.found = {}
        for k in ('brake', 'clutch'):
            top = r[k][:5]
            exp = self.A3.get(k) if self.A3 else None
            self.log_to(self.log3, f'{k.upper()}: {len(r[k])} candidate bytes. Best:')
            for score, a, x, y, refs in top:
                self.log_to(self.log3, f'   0x{a:08X}  {x} -> {y}   read by the code in {refs} places' + ('   <== expected' if a == exp else ''))
            if top: self.found[k] = top[0][1]
            if exp is not None:
                verdict = ('MATCHES' if top and top[0][1] == exp else 'is in the list' if any(t[1] == exp for t in top) else 'was NOT found')
                self.log_to(self.log3, f'   expected 0x{exp:08X} for {self.ecu_cal}: {verdict}')
        can_save = bool(self.A3) and core.addresses_json(self.A3) and self.found
        self.btn_confirm.config(state='normal' if can_save else 'disabled')

    def save_switches(self):
        c, b = self.found.get('clutch'), self.found.get('brake')
        if not messagebox.askokcancel(APP, f'Save for {self.ecu_cal}:\nclutch 0x{c:08X}\nbrake 0x{b:08X}\n\n'
                                           'Then re-save your patched file in tab 2 so the patches use them.'):
            return
        if core.confirm_switches(self.A3, c, b):
            self.log_to(self.log3, 'Saved. Re-open your ECU file in tab 2 and save the patched file again.')

    def toggle_live(self):
        self.live_on = self.live_var.get()
        if self.live_on: self.work(self.live_loop)

    def live_loop(self):
        A = self.A3
        while self.live_on and self.ecu:
            try:
                with self.lock:
                    vals = {'RPM': f'{self.ecu.f32(A["rpm"]):.0f}', 'Speed km/h': f'{self.ecu.f32(A["speed"]):.0f}',
                            'Pedal %': f'{self.ecu.f32(A["pedal_in"]):.0f}',
                            'Clutch': 'pressed' if self.ecu.u8(A['clutch']) == 1 else 'up',
                            'Brake': 'pressed' if self.ecu.u8(A['brake']) == 1 else 'off'}
                for k, v in vals.items(): self.ui(self.live_lbls[k].config, {'text': v})
            except Exception as e:
                self.ui(self.log_to, self.log3, f'Live read failed: {e}'); self.live_on = False
                self.ui(self.live_var.set, False); break
            threading.Event().wait(0.25)


if __name__ == '__main__':
    App().mainloop()

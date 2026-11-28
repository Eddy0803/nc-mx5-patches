"""NC Patcher - GUI for the NC MX-5 ECU patches.

Tab 1: check my car - connect through a J2534 interface (read-only), identify the ECU and run the guided pedal check,
       which finds the clutch / brake switch (and optionally the TCS byte) RAM addresses, remembered per calibration.
Tab 2: drop your ECU file, check the addresses, choose features and settings, save a patched file (flash it with NC Flash).
Top bar: report a problem or request a feature (to the project's Google Form, only when the user presses Submit).
"""
import os, platform, queue, struct, sys, threading, traceback

if sys.stdout is None: sys.stdout = open(os.devnull, 'w')      # windowed .exe has no console
if sys.stderr is None: sys.stderr = open(os.devnull, 'w')
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


def _dpi_aware():
    """draw at the display's real resolution instead of letting Windows stretch a 96-dpi picture (which looks soft)"""
    if sys.platform != 'win32': return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)          # system DPI aware (Windows 8.1+)
    except Exception:
        try: ctypes.windll.user32.SetProcessDPIAware()          # Vista / 7
        except Exception: pass
_dpi_aware()
SCALE = 1.0                                                     # display DPI / 96, set when the window is created
def px(v):
    return int(round(v * SCALE))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core                       # noqa: E402
import theme as T                 # noqa: E402
import ecu as ECU                 # noqa: E402
import j2534                      # noqa: E402
import editor                     # noqa: E402  tab 3: table editor
import logger                     # noqa: E402  tab 4: datalog
try:
    import dragdrop               # noqa: E402
except Exception:                 # non-Windows or no comctl32: browsing still works
    dragdrop = None

APP = 'NC Patcher'
VERSION = '0.9.37 beta'
PAD = {'padx': 8, 'pady': 4}


class DropZone(tk.Frame):
    """a box you can drop a file on, or click to browse"""
    def __init__(self, master, text, on_file, height=70):
        super().__init__(master, bd=0, bg=T.SURFACE, height=px(height), cursor='hand2', highlightthickness=1,
                         highlightbackground=T.BORDER, highlightcolor=T.BORDER)
        self.pack_propagate(False)
        self.text = text; self.on_file = on_file
        self.label = tk.Label(self, text=text, bg=T.SURFACE, fg=T.TEXT2, wraplength=px(560), justify='center')
        self.label.pack(expand=True, fill='both', padx=px(10))
        for w in (self, self.label):
            w.bind('<Button-1>', lambda e: self.browse())
        if dragdrop:
            self.after(50, lambda: (dragdrop.enable(self, self._dropped), dragdrop.enable(self.label, self._dropped)))

    def browse(self):
        p = filedialog.askopenfilename(title=self.text, filetypes=[('ECU files', '*.bin'), ('All files', '*.*')])
        if p: self.on_file(p)

    def _dropped(self, files):
        files = [f for f in files if os.path.isfile(f)]
        if files: self.on_file(files[0])

    def show(self, text, ok=True):
        self.label.config(text=text, fg=T.OK if ok else T.ERR)


def limits_text():
    """plain-words explanation of the rev-match limits; numbers come from the patch builder so they always match the code"""
    RV = core.RV; ms = RV.CALL_MS / 1000
    d = RV.DEFAULTS
    return f"""Rev-match opens the throttle without your foot on the pedal, so every way it can act is fenced in.

TWO KINDS OF LIMIT
- Hard limits in the ECU code. Editing a table can't get past them: a value beyond a limit is used as the limit. They stop a typo, a corrupted table or a value from another car from doing anything dangerous.
- Settings with safe defaults. You can change these here or in NC Flash, within the hard limits.

HARD LIMITS (IN THE CODE)
- Throttle it can add: {RV.CAP_PCT:.0f}% pedal.
  A downshift blip needs much less (on the test car 15% pedal was plenty). {RV.CAP_PCT:.0f}% leaves room for quick blips on any NC while capping what a fault, like a wrong gear table or a stuck switch, could do.
- Throttle anti-stall can add: {RV.CAP_AS:.0f}% pedal.
  Enough to catch a dip at idle, never enough to pull the car along by itself.
- Hold per clutch press: {RV.CAP_T} calls, about {RV.CAP_T * ms:.1f} s.
  A downshift takes well under a second. If the clutch switch sticks or you sit with the clutch down, the revs drop back to idle instead of being held.
- Clutch hold delay: {round(RV.CD_MIN * RV.CALL_MS, -1):.0f}-{round(RV.CD_MAX * RV.CALL_MS, -1):.0f} ms (0 = no delay). The slider here covers the recommended {round(RV.CD_REC_MIN * RV.CALL_MS, -1):.0f}-{round(RV.CD_REC_MAX * RV.CALL_MS, -1):.0f} ms; NC Flash accepts the full range.
  The clutch switch closes near the top of the pedal travel. Under {round(RV.CD_REC_MIN * RV.CALL_MS, -1):.0f} ms is effectively no delay, so the throttle can open while the clutch still bites and the car jolts. Over {round(RV.CD_REC_MAX * RV.CALL_MS, -1):.0f} ms, on a quick shift the blip could start just as the clutch comes back up (a jolt at the other end), and the revs would be late. The code stops at {round(RV.CD_MAX * RV.CALL_MS, -1):.0f} ms, so a wrong or corrupted value can't delay it far beyond a normal shift.
- On/off switch confirmation: at most {RV.CAP_FB_RPM:.0f} rpm for {RV.CAP_FB_T} calls (about {RV.CAP_FB_T * ms:.0f} s).
  It revs a stationary engine with no load, so it's kept mild and short.
- Gears: it only targets gears that exist in the RPM-per-km/h table (1st-6th, 0 = no gear), recognised within +-{RV.GEAR_TOL * 100:.0f}% above 10 km/h. Otherwise it stays off rather than guess.
- Anti-stall only works with the engine running (above {RV.AS_RUNNING:.0f} rpm), never while cranking or after a stall.
- The ECU's throttle plausibility check is relaxed only while rev-match is actually adding throttle, the same way the factory does it for cruise control.

ALWAYS
- Your foot always wins: the ECU uses whichever is higher, your pedal or rev-match's. Above the Max Real Pedal setting rev-match stops altogether.
- It stops at once when you let the clutch up, release the brake on a downshift, drop below Min Speed or the hold time runs out.
- It can only add throttle, never cut it.

SETTINGS AND THEIR DEFAULTS
- Max Output Pedal {d['MAXPCT']:.0f}% (limit {RV.CAP_PCT:.0f}): a crisp blip on the test car, with margin under the limit.
- Max Real Pedal {d['PMAX']:.0f}%: just above foot-off, so any real throttle hands control back to you. Also keeps it out of flat-foot shifts.
- Min Speed {d['VMIN']:.0f} km/h: so it doesn't rev the engine while you brake to a stop with the clutch in.
- Max Hold Time {d['MAXT']} calls, about {d['MAXT'] * ms:.1f} s (limit {RV.CAP_T * ms:.1f} s): a normal downshift with time to spare.
- Clutch Hold Delay {round(d['CDLY'] * RV.CALL_MS, -1):.0f} ms (slider {round(RV.CD_REC_MIN * RV.CALL_MS, -1):.0f}-{round(RV.CD_REC_MAX * RV.CALL_MS, -1):.0f}, NC Flash {round(RV.CD_MIN * RV.CALL_MS, -1):.0f}-{round(RV.CD_MAX * RV.CALL_MS, -1):.0f}): past the biting point on a normal press, with the revs still up before you release. Raise it if the car jolts as you press the clutch; lower it if the revs are late on quick downshifts.
- Max Target RPM {d['MAXRPM']:.0f}: stops it chasing very high revs, e.g. 2nd to 1st at speed. Keep it below your rev limit.
- Anti-stall: up to {d['ASMAX']:.0f}% pedal (limit {RV.CAP_AS:.0f}), below {d['ASRPM']:.0f} rpm (keep it under your idle), up to {d['ASVMAX']:.0f} km/h.

More detail: docs/rev-match.md, "Safety limits, and why they're set where they are"."""


class FeedbackDialog(tk.Toplevel):
    """report a problem or request a feature: sent to the project's Google Form only when the user presses Submit,
    and the window shows exactly what would be sent"""
    def __init__(self, app, kind='problem'):
        super().__init__(app)
        self.app = app
        self.title(f'{APP} - report a problem or request a feature'); self.configure(bg=T.BG); self.transient(app)
        self.geometry(f'{px(780)}x{px(720)}'); self.minsize(px(600), px(560))
        P = dict(padx=px(12))
        top = ttk.Frame(self); top.pack(fill='x', pady=(px(12), px(4)), **P)
        self.kind = tk.StringVar(value=kind)
        ttk.Radiobutton(top, text='Report a problem', value='problem', variable=self.kind, command=self.refresh).pack(side='left')
        ttk.Radiobutton(top, text='Request a feature', value='feature', variable=self.kind, command=self.refresh).pack(side='left', padx=px(16))
        f = ttk.Frame(self); f.pack(fill='x', **P)
        ttk.Label(f, text='Title').grid(row=0, column=0, sticky='w', pady=px(3))
        self.ttl = tk.StringVar(); ttk.Entry(f, textvariable=self.ttl, width=70).grid(row=0, column=1, sticky='we', padx=(px(8), 0))
        ttk.Label(f, text='Contact (optional)').grid(row=1, column=0, sticky='w', pady=px(3))
        self.contact = tk.StringVar(); ttk.Entry(f, textvariable=self.contact, width=40).grid(row=1, column=1, sticky='w', padx=(px(8), 0))
        f.columnconfigure(1, weight=1)
        ttk.Label(self, text='Only if you want a reply (e.g. a GitHub or forum username). It is sent as you type it.',
                  style='Hint.TLabel').pack(anchor='w', **P)
        self.prompt = ttk.Label(self, text='', wraplength=px(740)); self.prompt.pack(anchor='w', pady=(px(8), px(2)), **P)
        self.desc = T.text(self, height=7, wrap='word'); self.desc.pack(fill='x', **P)
        opts = ttk.Frame(self); opts.pack(fill='x', pady=px(4), **P)
        self.inc_details, self.inc_log = tk.BooleanVar(value=True), tk.BooleanVar(value=kind == 'problem')
        ttk.Checkbutton(opts, text='Include basic details (app and Windows version, calibration, which patches are ticked)',
                        variable=self.inc_details, command=self.refresh).pack(anchor='w')
        ttk.Checkbutton(opts, text="Include the app's log (file paths and names are removed)", variable=self.inc_log,
                        command=self.refresh).pack(anchor='w')
        ttk.Label(self, text='This is exactly what will be sent. It never contains ROM data or file contents. Nothing is sent '
                             'unless you press Submit.', style='Hint.TLabel', wraplength=px(740)).pack(anchor='w', pady=(px(6), px(2)), **P)
        self.preview = T.text(self, height=10, wrap='word', state='disabled'); self.preview.pack(fill='both', expand=True, **P)
        self.status = ttk.Label(self, text='', style='Hint.TLabel'); self.status.pack(anchor='w', pady=(px(6), 0), **P)
        bar = ttk.Frame(self); bar.pack(fill='x', pady=px(12), **P)
        self.btn_submit = ttk.Button(bar, text='Submit', style='Accent.TButton', command=self.submit); self.btn_submit.pack(side='left')
        ttk.Button(bar, text='Save to file...', command=self.save).pack(side='left', padx=px(8))
        ttk.Button(bar, text='Cancel', command=self.destroy).pack(side='right')
        for v in (self.ttl, self.contact): v.trace_add('write', lambda *_: self.refresh())
        self.desc.bind('<KeyRelease>', lambda e: self.refresh())
        if not core.REPORT_FORM:
            self.status.config(text='Sending is not set up in this version - you can save it to a file.')
        self.refresh()
        T.dark_title_bar(self); self.focus_set()

    def details(self):
        a = self.app
        d = {'Windows': platform.platform()}
        if a.A and a.rom:
            gb = core.AD.gearbox(a.rom)
            d['ECU file in tab 2'] = f'calibration {a.A["cal"]}' + (f', {gb["name"]}' if gb else '') + \
                                     ('' if a.A.get('verified_on_car') else ' (built-in port)')
            d['Patches ticked'] = ', '.join(n for n, v in (('ignition cut', a.ig_on), ('rev-match', a.rv_on), ('overrun', a.ov_on),
                                                           ('traction control', a.tc_on))
                                            if v.get()) or 'none'
        elif a.rom:
            d['ECU file in tab 2'] = 'loaded, but not a calibration NC Patcher knows'
        else:
            d['ECU file in tab 2'] = 'none loaded'
        d['Car check'] = f'connected, ECU calibration {a.ecu_cal}' if a.ecu else 'not connected'
        return d

    def compose(self):
        a = self.app
        log = (a.log1.get('1.0', 'end') + a.log3.get('1.0', 'end')) if self.inc_log.get() else None
        names = [os.path.basename(p) for p in (a.rom_path,) + tuple(a.saved_paths) if p]
        names += [os.path.splitext(n)[0] for n in names if len(os.path.splitext(n)[0]) > 3]   # also without the extension
        return core.make_feedback(self.kind.get(), self.ttl.get() or '(no title yet)', self.desc.get('1.0', 'end'),
                                  self.details() if self.inc_details.get() else None, log, self.contact.get(), VERSION, names)

    def refresh(self):
        problem = self.kind.get() == 'problem'
        self.prompt.config(text=('What went wrong? What did you do, what did you expect, and what happened instead?'
                                 if problem else 'What would you like NC Patcher or the patches to do, and how would you use it?'))
        title, body = self.compose()
        self.preview.configure(state='normal'); self.preview.delete('1.0', 'end')
        self.preview.insert('1.0', f'{title}\n\n{body}'); self.preview.configure(state='disabled')
        ready = self.ttl.get().strip() and self.desc.get('1.0', 'end').strip()
        self.btn_submit.config(state='normal' if ready and core.REPORT_FORM else 'disabled')

    def save(self):
        title, body = self.compose()
        p = filedialog.asksaveasfilename(parent=self, title='Save', defaultextension='.md', initialfile=f'nc-patcher-{self.kind.get()}.md',
                                         filetypes=[('Markdown', '*.md'), ('Text', '*.txt')])
        if p:
            open(p, 'w', encoding='utf-8').write(f'# {title}\n\n{body}\n')
            self.status.config(text=f'Saved: {os.path.basename(p)}')

    def submit(self):
        title, body = self.compose()
        if not messagebox.askokcancel(APP, 'Send this to the project now?\n\nIt goes to the project\'s Google Form, exactly as shown '
                                           'in the window.', parent=self):
            return
        self.btn_submit.config(state='disabled'); self.status.config(text='Sending...')
        self.app.work(core.submit_report, title, body, done=self.sent)

    def sent(self, r, err):
        ok, msg = (False, str(err)) if err else r
        self.status.config(text=msg)
        if ok:
            messagebox.showinfo(APP, 'Sent - thank you.', parent=self); self.destroy()
        else:
            self.btn_submit.config(state='normal')


class LimitsDialog(tk.Toplevel):
    """read-only explanation of the rev-match limits"""
    def __init__(self, app):
        super().__init__(app)
        self.title(f'{APP} - rev-match limits'); self.configure(bg=T.BG); self.transient(app)
        self.geometry(f'{px(760)}x{px(640)}'); self.minsize(px(520), px(400))
        ttk.Label(self, text='Rev-match: the limits, and why they are set where they are', font=('Segoe UI Semibold', 10),
                  wraplength=px(720)).pack(anchor='w', padx=px(12), pady=(px(12), px(6)))
        box = T.text(self, height=24, wrap='word'); box.pack(fill='both', expand=True, padx=px(12))
        box.insert('1.0', limits_text()); box.configure(state='disabled')
        bar = ttk.Frame(self); bar.pack(fill='x', padx=px(12), pady=px(12))
        ttk.Button(bar, text='Close', command=self.destroy, style='Accent.TButton').pack(side='right')
        T.dark_title_bar(self); self.focus_set()


class ScrollArea(ttk.Frame):
    """a vertically scrolling area: put widgets in .inner. The scrollbar only shows when the content is taller than the window."""
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=T.BG, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.win = self.canvas.create_window(0, 0, window=self.inner, anchor='nw')
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.inner.bind('<Configure>', self._sync); self.canvas.bind('<Configure>', self._sync)
        self.bind('<Enter>', lambda e: self.bind_all('<MouseWheel>', self._wheel))
        self.bind('<Leave>', lambda e: self.unbind_all('<MouseWheel>'))

    def _sync(self, e=None):
        self.canvas.itemconfigure(self.win, width=self.canvas.winfo_width())
        h = self.inner.winfo_reqheight()
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), h))
        if h > self.canvas.winfo_height() + 1:
            if not self.vsb.winfo_ismapped(): self.vsb.pack(side='right', fill='y', before=self.canvas)
        elif self.vsb.winfo_ismapped():
            self.vsb.pack_forget(); self.canvas.yview_moveto(0)

    def _wheel(self, e):
        if self.vsb.winfo_ismapped(): self.canvas.yview_scroll(int(-e.delta / 120), 'units')


def autowrap(label, container, margin=16):
    """wrap a label's text to its container's width as the window is resized"""
    container.bind('<Configure>', lambda e: label.config(wraplength=max(px(200), e.width - px(margin))), add='+')


def labelled(parent, row, text, var, width=10, tip=''):
    ttk.Label(parent, text=text).grid(row=row, column=0, sticky='w', **PAD)
    e = ttk.Entry(parent, textvariable=var, width=width); e.grid(row=row, column=1, sticky='w', **PAD)
    if tip: ttk.Label(parent, text=tip, style='Hint.TLabel').grid(row=row, column=2, sticky='w', **PAD)
    return e


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'{APP} {VERSION}')
        ico = os.path.join(core.BASE, 'app', 'ncpatcher.ico')
        if os.path.exists(ico):
            try:
                self.iconbitmap(default=ico)                       # this window and every dialog
            except tk.TclError:
                pass
        global SCALE
        SCALE = max(1.0, self.winfo_fpixels('1i') / 96.0)
        PAD.update(padx=px(8), pady=px(4))
        w, h = min(px(940), int(self.winfo_screenwidth() * 0.95)), min(px(800), int(self.winfo_screenheight() * 0.9))
        self.geometry(f'{w}x{h}'); self.minsize(min(px(840), w), min(px(700), h))
        T.apply(self, SCALE)
        self.q = queue.Queue()
        self.lock = threading.Lock()
        self.pt = None; self.ecu = None; self.ecu_cal = None; self.live_on = False
        self.snaps = {}
        nb = ttk.Notebook(self); nb.pack(fill='both', expand=True, padx=px(6), pady=px(6))
        self.nb = nb
        # top right, in the free space beside the tabs: report a problem / request a feature
        fb = ttk.Frame(self); fb.place(relx=1.0, x=-px(10), y=px(6), anchor='ne')
        self.btn_problem = ttk.Button(fb, text='Report a problem', command=lambda: FeedbackDialog(self, 'problem'))
        self.btn_problem.pack(side='left')
        self.btn_feature = ttk.Button(fb, text='Request a feature', command=lambda: FeedbackDialog(self, 'feature'))
        self.btn_feature.pack(side='left', padx=(px(6), 0))
        self.after(50, fb.lift)
        self.t1, self.t3 = ttk.Frame(nb), ttk.Frame(nb)        # t3 = check my car (tab 1), t1 = patch (tab 2)
        nb.add(self.t3, text=' 1. Check my car (J2534) ')
        nb.add(self.t1, text=' 2. Patch my ECU file ')
        self.t_ed, self.t_log = ttk.Frame(nb), ttk.Frame(nb)
        nb.add(self.t_ed, text=' 3. Edit tables ')
        nb.add(self.t_log, text=' 4. Datalog ')
        self.build_tab1(); self.build_tab3()
        self.editor = editor.EditorTab(self, self.t_ed, px, PAD, T)
        self.logger = logger.LoggerTab(self, self.t_log, px, PAD, T)
        self.nb.select(self.t1 if core.settings().get('guide_done') else self.t3)   # first start: the guided car check
        self.after(100, self.pump)
        self.protocol('WM_DELETE_WINDOW', self.quit_app)
        if dragdrop:                                            # an ECU file dropped anywhere on the window -> tab 2
            self.after(80, lambda: dragdrop.enable_window(self, self.dropped_anywhere))

    def dropped_anywhere(self, files):
        files = [f for f in files if os.path.isfile(f)]
        if not files:
            return
        if len(files) > 1:
            self.log_to(self.log1, f'{len(files)} files were dropped - opening the first one. Drop one ECU file at a time.')
        self.open_ecu_file(files[0])

    def open_ecu_file(self, path):
        """open an ECU file in tab 2 (from a drop anywhere on the window, or the command line / the exe's icon)"""
        self.nb.select(self.t1)
        self.load_rom(path)

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

    # ------------------------------------------------------------------ tab 2: patch my ECU file
    def build_tab1(self):
        outer = self.t1
        # the Save bar and the log are pinned at the bottom; everything above scrolls if the window is too small for it
        bar = ttk.Frame(outer); bar.pack(side='bottom', fill='x', padx=px(8), pady=px(6))
        self.btn_save = ttk.Button(bar, text='Save patched file...', command=self.save_patched, state='disabled', style='Accent.TButton'); self.btn_save.pack(side='left')
        self.btn_defs = ttk.Button(bar, text='Show the new tables in NC Flash', command=self.add_defs, state='disabled'); self.btn_defs.pack(side='left', padx=px(8))
        self.log1 = T.text(outer, height=5, state='disabled'); self.log1.pack(side='bottom', fill='x', padx=px(8), pady=(px(4), 0))
        self.scroll1 = ScrollArea(outer); self.scroll1.pack(fill='both', expand=True)
        t = self.scroll1.inner
        top = ttk.Label(t, text='Drop your ECU file (a 1 MB .bin read with NC Flash) to add the patches to it. '
                                'The file you drop is never changed; you save a new one.', wraplength=px(860))
        top.pack(anchor='w', **PAD); autowrap(top, t)
        self.drop1 = DropZone(t, 'Drop your ECU file here  -  or click to browse', self.load_rom)
        self.drop1.pack(fill='x', padx=px(8), pady=px(4))
        self.info1 = ttk.Label(t, text='', wraplength=px(860)); self.info1.pack(anchor='w', **PAD); autowrap(self.info1, t)
        # the ECU's RAM addresses the patches read: shown, and editable, before the patches are built
        a = ttk.LabelFrame(t, text='ECU addresses the patches use (RAM)'); a.pack(fill='x', padx=px(8), pady=(0, px(6)))
        self.addr = {k: tk.StringVar() for k in ('clutch', 'brake', 'tcs', 'tcsm', 'tcsv')}
        self.addr_src = {}
        for r, (k, label) in enumerate((('clutch', 'Clutch switch'), ('brake', 'Brake switch'))):
            ttk.Label(a, text=label).grid(row=r, column=0, sticky='w', **PAD)
            ttk.Entry(a, textvariable=self.addr[k], width=12).grid(row=r, column=1, sticky='w', pady=px(3))
            self.addr_src[k] = ttk.Label(a, text='', style='Hint.TLabel', wraplength=px(560))
            self.addr_src[k].grid(row=r, column=2, columnspan=5, sticky='w', **PAD)
        ttk.Label(a, text='TCS byte (sport mode)').grid(row=2, column=0, sticky='w', **PAD)
        ttk.Entry(a, textvariable=self.addr['tcs'], width=12).grid(row=2, column=1, sticky='w', pady=px(3))
        tf = ttk.Frame(a); tf.grid(row=2, column=2, columnspan=5, sticky='w', **PAD)
        ttk.Label(tf, text='mask', style='Hint.TLabel').pack(side='left', padx=(0, px(4)))
        ttk.Entry(tf, textvariable=self.addr['tcsm'], width=4).pack(side='left')
        ttk.Label(tf, text='off =', style='Hint.TLabel').pack(side='left', padx=(px(10), px(4)))
        ttk.Entry(tf, textvariable=self.addr['tcsv'], width=4).pack(side='left')
        self.addr_src['tcs'] = ttk.Label(tf, text='', style='Hint.TLabel', wraplength=px(330))
        self.addr_src['tcs'].pack(side='left', padx=(px(12), 0))
        addr_hint =ttk.Label(a, text='Filled in from the car check (tab 1) when you have done it, otherwise the usual addresses for '
                                      'this calibration. The patches are built with what is here, and the emulator tests use the same '
                                      'values. Change them only for your own car\'s confirmed addresses (hex, FFFF0000-FFFFBFFF); '
                                      'they are remembered for this calibration. The TCS byte is optional: it is only needed for the '
                                      'overrun "sport mode".', style='Hint.TLabel', wraplength=px(860))
        addr_hint.grid(row=3, column=0, columnspan=7, sticky='w', **PAD); autowrap(addr_hint, a)
        for k in ('tcs', 'tcsm', 'tcsv'): self.addr[k].trace_add('write', lambda *_: self.tcs_changed())
        body = ttk.Frame(t); body.pack(fill='x', padx=px(4))
        # ignition cut
        self.ig_on = tk.BooleanVar(value=True)
        f = ttk.LabelFrame(body, text='Ignition-cut rev limiter, launch control, flat-foot shift'); f.pack(side='left', fill='both', expand=True, padx=px(4))
        ttk.Checkbutton(f, text='Install / keep this patch', variable=self.ig_on).grid(row=0, column=0, columnspan=3, sticky='w', **PAD)
        self.ig_vars = {k: tk.StringVar() for k in ('LAUNCH', 'FS', 'RET', 'OFS', 'FSAPP', 'VSPLIT', 'DW')}
        labelled(f, 1, 'Launch control RPM', self.ig_vars['LAUNCH'], tip='0 = off')
        labelled(f, 2, 'Flat-shift RPM', self.ig_vars['FS'], tip='0 = off')
        labelled(f, 3, 'Timing retard while cutting', self.ig_vars['RET'], tip='degrees')
        labelled(f, 4, 'Cut below RPM Fuel Cut by', self.ig_vars['OFS'], tip='rpm (negative)')
        labelled(f, 5, 'Flat shift needs pedal above', self.ig_vars['FSAPP'], tip='%')
        labelled(f, 6, 'Launch / flat-shift split speed', self.ig_vars['VSPLIT'], tip='km/h')
        labelled(f, 7, 'Coil dwell while cutting', self.ig_vars['DW'], tip='ms (min 0.2)')
        ttk.Label(f, text='Rev limit = your RPM Fuel Cut table (change it in NC Flash).', style='Hint.TLabel').grid(row=8, column=0, columnspan=3, sticky='w', **PAD)
        # rev-match
        self.rv_on = tk.BooleanVar(value=True)
        g = ttk.LabelFrame(body, text='Downshift rev-match, upshift hold, anti-stall'); g.pack(side='left', fill='both', expand=True, padx=px(4))
        self.rv_chk = ttk.Checkbutton(g, text='Install / keep this patch', variable=self.rv_on); self.rv_chk.grid(row=0, column=0, columnspan=2, sticky='w', **PAD)
        self.rv_en, self.rv_up, self.rv_as, self.rv_sw = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()
        ttk.Checkbutton(g, text='Rev-match on downshifts (clutch + brake)', variable=self.rv_en).grid(row=1, column=0, columnspan=2, sticky='w', **PAD)
        ttk.Checkbutton(g, text='Upshift hold (clutch, no brake)', variable=self.rv_up).grid(row=2, column=0, columnspan=2, sticky='w', **PAD)
        ttk.Checkbutton(g, text='Anti-stall', variable=self.rv_as).grid(row=3, column=0, columnspan=2, sticky='w', **PAD)
        ttk.Checkbutton(g, text='Downshift on/off switch (stopped: clutch + 3 brake taps)', variable=self.rv_sw).grid(row=4, column=0, columnspan=2, sticky='w', **PAD)
        # clutch hold delay: how long the clutch must stay down before downshift rev-match / upshift hold act
        cf = ttk.Frame(g); cf.grid(row=5, column=0, columnspan=2, sticky='we', padx=px(6), pady=(px(4), 0))
        self.rv_cd = tk.DoubleVar(value=self.CD_DEFAULT_MS)
        ttk.Label(cf, text='Clutch hold').pack(side='left', padx=(0, px(8)))
        ttk.Label(cf, text=f'{self.CD_MIN_MS}', style='Hint.TLabel').pack(side='left')
        ttk.Scale(cf, from_=self.CD_MIN_MS, to=self.CD_MAX_MS, variable=self.rv_cd, orient='horizontal', length=px(140),
                  command=self.cd_moved).pack(side='left', padx=px(4))
        ttk.Label(cf, text=f'{self.CD_MAX_MS} ms', style='Hint.TLabel').pack(side='left')
        self.rv_cd_lbl = ttk.Label(cf, text=f'{self.CD_DEFAULT_MS} ms', width=7); self.rv_cd_lbl.pack(side='left', padx=px(8))
        self.rv_cd_note = ttk.Label(g, text='', style='Hint.TLabel', wraplength=px(350))
        self.rv_cd_note.grid(row=6, column=0, columnspan=2, sticky='w', padx=px(6)); self.rv_cd_note.grid_remove()
        ttk.Label(g, text='How long the clutch must stay down before the throttle opens. Raise it if the car jolts as you press '
                          'the clutch; lower it if the revs are late. Recommended 50-400 ms (NC Flash: 0-500).',
                  style='Hint.TLabel', wraplength=px(350)).grid(row=7, column=0, columnspan=2, sticky='w', padx=px(6), pady=(0, px(2)))
        self.rv_note = ttk.Label(g, text='', style='Hint.TLabel', wraplength=px(350)); self.rv_note.grid(row=8, column=0, columnspan=2, sticky='w', padx=px(6), pady=px(2))
        lim = ttk.Frame(g); lim.grid(row=9, column=0, columnspan=2, sticky='we', padx=px(6), pady=(px(2), px(6)))
        ttk.Button(lim, text='Why these limits?', command=lambda: LimitsDialog(self)).pack(side='left')
        ttk.Label(lim, text='Fine tuning is in NC Flash. Every setting has a hard limit in the ECU code.', style='Hint.TLabel',
                  wraplength=px(210)).pack(side='left', padx=px(8))
        # overrun crackle
        self.ov_on, self.ov_en = tk.BooleanVar(value=False), tk.BooleanVar(value=False)
        self.ov_str, self.ov_dur = tk.DoubleVar(value=core.OV.DEFAULTS['STR']), tk.StringVar(value=f"{core.OV.DEFAULTS['DUR']:g}")
        o = ttk.LabelFrame(t, text='Overrun crackle (timed)'); o.pack(fill='x', padx=px(8), pady=(px(6), 0))
        self.ov_chk = ttk.Checkbutton(o, text='Install / keep this patch', variable=self.ov_on); self.ov_chk.grid(row=0, column=0, sticky='w', **PAD)
        ttk.Checkbutton(o, text='Crackle on', variable=self.ov_en).grid(row=0, column=1, sticky='w', **PAD)
        ttk.Label(o, text='Duration after lift-off').grid(row=0, column=2, sticky='e', **PAD)
        ttk.Entry(o, textvariable=self.ov_dur, width=6).grid(row=0, column=3, sticky='w', pady=px(4))
        ttk.Label(o, text='s (max 5)', style='Hint.TLabel').grid(row=0, column=4, sticky='w', **PAD)
        ttk.Label(o, text='Strength (spark)').grid(row=1, column=0, sticky='w', **PAD)
        sf = ttk.Frame(o); sf.grid(row=1, column=1, columnspan=4, sticky='we', **PAD)
        ttk.Label(sf, text='mild', style='Hint.TLabel').pack(side='left')
        ttk.Scale(sf, from_=0, to=100, variable=self.ov_str, orient='horizontal', length=px(320),
                  command=lambda v: self.ov_str_lbl.config(text=f'{float(v):.0f}%')).pack(side='left', padx=px(6))
        ttk.Label(sf, text='aggressive', style='Hint.TLabel').pack(side='left')
        self.ov_str_lbl = ttk.Label(sf, text=f"{core.OV.DEFAULTS['STR']:.0f}%", width=5); self.ov_str_lbl.pack(side='left', padx=px(8))
        # fuel during a burst: lambda at the 4 RPM points of the lambda-vs-RPM table
        ttk.Label(o, text='Fuel (lambda at rpm)').grid(row=2, column=0, sticky='w', **PAD)
        lf = ttk.Frame(o); lf.grid(row=2, column=1, columnspan=4, sticky='w', **PAD)
        self.ov_lam = [tk.StringVar() for _ in range(4)]; self.ov_lam_lbl = []
        for i in range(4):
            lb = ttk.Label(lf, text='', style='Hint.TLabel'); lb.pack(side='left', padx=(px(10) if i else 0, px(4)))
            self.ov_lam_lbl.append(lb)
            ttk.Entry(lf, textvariable=self.ov_lam[i], width=6).pack(side='left')
        ttk.Button(lf, text='Ford defaults', command=self.ov_lam_ford).pack(side='left', padx=(px(14), 0))
        lam_hint = ttk.Label(o, text=f'Lambda {core.OV.LAM_MIN:.2f}-{core.OV.LAM_MAX:.2f}, lower = richer (more to burn; {core.OV.LAM_MIN:.1f} is the rich '
                                     f'limit for a hot exhaust and cat, {core.OV.LAM_MAX:.1f} still well clear of a full fuel cut). Ford: 0.92 to '
                                     f'3000 rpm, 1.00 from 4000. It blends between the points; the RPM points are set in NC Flash.',
                             style='Hint.TLabel', wraplength=px(800))
        lam_hint.grid(row=3, column=0, columnspan=5, sticky='w', padx=px(6))
        self.ov_note = ttk.Label(o, text='Lifting off after the pedal has been above 20% gives one burst. Needs coolant 50 C+, '
                                 '2500-6500 rpm, clutch up; any speed. Strength sets the spark. Other limits are in NC Flash.', style='Hint.TLabel', wraplength=px(800))
        self.ov_note.grid(row=4, column=0, columnspan=5, sticky='w', padx=px(6), pady=(0, px(2)))
        self.ov_sport = tk.BooleanVar(value=False)
        self.ov_sport_chk = ttk.Checkbutton(o, text='Sport mode only: crackle only with TCS off (DSC pressed once), or after '
                                                    'pressing DSC twice quickly (off, then on within 2 s)', variable=self.ov_sport)
        self.ov_sport_chk.grid(row=5, column=0, columnspan=5, sticky='w', padx=px(6))
        self.ov_sport_note = ttk.Label(o, text='', style='Hint.TLabel', wraplength=px(800))
        self.ov_sport_note.grid(row=6, column=0, columnspan=5, sticky='w', padx=px(6), pady=(0, px(6)))
        autowrap(self.ov_sport_note, o)
        autowrap(lam_hint, o); autowrap(self.ov_note, o)
        # traction control (spark cut through the ignition cut)
        self.tc_on, self.tc_en = tk.BooleanVar(value=False), tk.BooleanVar(value=False)
        self.tc_vars = {k: tk.StringVar() for k in ('SLIPKMH', 'SLIPPCT', 'PMIN')}
        c = ttk.LabelFrame(t, text='Traction control (wheel slip, spark cut)'); c.pack(fill='x', padx=px(8), pady=(px(6), px(6)))
        self.tc_chk = ttk.Checkbutton(c, text='Install / keep this patch', variable=self.tc_on); self.tc_chk.grid(row=0, column=0, sticky='w', **PAD)
        ttk.Checkbutton(c, text='Traction control on', variable=self.tc_en).grid(row=0, column=1, sticky='w', **PAD)
        for col, (k, label, tip) in enumerate((('SLIPKMH', 'Slip allowed', 'km/h'), ('SLIPPCT', 'plus', '% of speed'),
                                               ('PMIN', 'Only above pedal', '%'))):
            f2 = ttk.Frame(c); f2.grid(row=1, column=col, sticky='w', **PAD)
            ttk.Label(f2, text=label).pack(side='left', padx=(0, px(4)))
            ttk.Entry(f2, textvariable=self.tc_vars[k], width=6).pack(side='left')
            ttk.Label(f2, text=tip, style='Hint.TLabel').pack(side='left', padx=(px(4), 0))
        self.tc_note = ttk.Label(c, text='', style='Hint.TLabel', wraplength=px(800))
        self.tc_note.grid(row=2, column=0, columnspan=4, sticky='w', padx=px(6), pady=(0, px(6))); autowrap(self.tc_note, c)
        self.tc_note_default = ('Compares each rear wheel with the front wheel on its side (the ABS unit\'s wheel speeds). When a '
                                'rear turns faster than allowed (default 3 km/h plus 10% of speed), it cuts spark with the ignition '
                                'cut\'s dwell and retard until the wheels grip again. Off with the brake on, the clutch down (and '
                                '~0.1 s after), below 5 km/h, 2000 rpm or the pedal setting. Raise "slip allowed" if it cuts too '
                                'early. Needs the ignition cut. Not yet tested on a car.')
        self.tc_note.config(text=self.tc_note_default)
        self.rom = None; self.rom_path = None; self.A = None; self.tcs_file = None
        self.saved_paths = []          # every file opened or saved this session (their names are removed from reports)
        self.set_defaults()

    def set_defaults(self, st=None):
        ig = (st or {}).get('ig') or {}
        d = dict(core.IG.DEFAULTS); d.update({k: v for k, v in ig.items() if v == v})
        for k, v in self.ig_vars.items(): v.set(f'{d[k]:g}')
        rv = (st or {}).get('rv') or {}
        self.rv_en.set(bool(rv.get('EN', 0) > 0)); self.rv_up.set(bool(rv.get('UPEN', 0) > 0)); self.rv_as.set(bool(rv.get('ASEN', 0) > 0))
        self.rv_sw.set(bool(rv.get('TGEN', 0) > 0))
        cd = rv.get('CDLY', 0xFFFF)                                    # calls; 0xFFFF = older version without it
        if cd == 0xFFFF:
            self.cd_moved(self.CD_DEFAULT_MS)
        else:
            cd = max(core.RV.CD_MIN, min(core.RV.CD_MAX, cd))
            if core.RV.CD_REC_MIN <= cd <= core.RV.CD_REC_MAX:
                self.cd_moved(cd * core.RV.CALL_MS)
            else:                                                      # set in NC Flash outside the slider's range: keep it
                self.cd_custom = cd
                self.cd_moved(cd * core.RV.CALL_MS, user=False)
                self.rv_cd_lbl.config(text=f'{round(cd * core.RV.CALL_MS):.0f} ms*')
        ov = dict(core.OV.DEFAULTS); ov.update({k: v for k, v in ((st or {}).get('ov') or {}).items() if v == v})
        self.ov_on.set(bool((st or {}).get('overrun'))); self.ov_en.set(ov['EN'] > 0)
        self.ov_str.set(ov['STR']); self.ov_str_lbl.config(text=f"{ov['STR']:.0f}%"); self.ov_dur.set(f"{ov['DUR']:g}")
        self.ov_sport.set(ov.get('SPEN', 0) > 0)
        tcv = dict(core.TC.DEFAULTS)
        cur = (st or {}).get('tcv') or {}
        if cur.get('VER') == core.TC.VERSION:          # an older TC's tables mean something else: shown as the new defaults
            tcv.update({k: v for k, v in cur.items() if k in tcv and v == v})
        elif cur.get('EN') == cur.get('EN') and cur.get('EN') is not None:
            tcv['EN'] = cur['EN']
        self.tc_on.set(bool((st or {}).get('tc'))); self.tc_en.set(tcv['EN'] > 0)
        for k, v in self.tc_vars.items(): v.set(f'{tcv[k]:g}')
        self.fill_addresses(st)
        ok_list = lambda v: isinstance(v, list) and len(v) == 4 and all(x == x for x in v)
        ax = ov.get('LAX') if ok_list(ov.get('LAX')) else core.OV.ARR_DEFAULTS['LAX']
        lam = ov.get('LAM') if ok_list(ov.get('LAM')) else core.OV.ARR_DEFAULTS['LAM']
        lo, hi = core.OV.LAM_MIN, core.OV.LAM_MAX
        shown = [min(hi, max(lo, v)) for v in lam]
        for i, (lb, var) in enumerate(zip(self.ov_lam_lbl, self.ov_lam)):
            lb.config(text=('to ' if i == 0 else '') + f'{ax[i]:.0f}' + ('+' if i == 3 else ''))
            var.set(f'{shown[i]:.2f}')
        if any(abs(a - b) > 1e-6 for a, b in zip(lam, shown)) and hasattr(self, 'log1'):
            self.log_to(self.log1, f'Overrun lambda in this file ({", ".join(f"{v:.2f}" for v in lam)}) is outside '
                                   f'{lo:.1f}-{hi:.1f}; shown limited to that range, which the patch code now enforces.')

    # ---- the ECU addresses box (tab 2)
    def fill_addresses(self, st=None):
        """clutch / brake / TCS boxes: from the car check if done, else the file (TCS) or the calibration's usual addresses"""
        A = self.A; self.tcs_file = None
        want_sport = self.ov_sport.get() if hasattr(self, 'ov_sport') else False
        self._filling = True                                         # don't react to each box as it is filled
        try:
            self._fill_addresses(A, st)
        finally:
            self._filling = False
        self.tcs_changed()
        if want_sport and str(self.ov_sport_chk['state']) == 'normal': self.ov_sport.set(True)

    def _fill_addresses(self, A, st):
        for v in self.addr.values(): v.set('')
        for l in self.addr_src.values(): l.config(text='')
        if not A: return
        mem = core.remembered_switches(A['cal'])
        for k in ('clutch', 'brake'):
            if mem:
                val = mem[k]
                src = ('entered by hand' if mem.get('source') == 'entered' else 'checked on your car') + \
                      (f' ({mem["checked"]})' if mem.get('checked') else '')
                if val != A[k]: src += f' - not the usual {A["cal"]} address 0x{A[k]:08X}'
            else:
                val = A[k]
                src = (f'usual {A["cal"]} address, proven on a car - the car check (tab 1) confirms it on yours'
                       if A.get('verified_on_car') else f'usual {A["cal"]} address from the port - NOT checked on a car: '
                                                        'do the car check (tab 1) first')
            self.addr[k].set(f'0x{val:08X}'); self.addr_src[k].config(text=src)
        tc = core.remembered_tcs(A['cal'])
        ov = (st or {}).get('ov') or {}
        fa = ov.get('TCSA', 0xFFFFFFFF)
        self.tcs_file = (fa, ov['TCSM'], ov['TCSV']) if core.ECU_RAM[0] <= fa < core.ECU_RAM[1] and ov.get('TCSM') else None
        if tc:
            vals, src = (tc['addr'], tc['mask'], tc['val']), ('entered by hand' if tc.get('source') == 'entered' else 'found on your car') + \
                        (f' ({tc["checked"]})' if tc.get('checked') else '')
        elif core.ECU_RAM[0] <= fa < core.ECU_RAM[1] and ov.get('TCSM'):
            vals, src = (fa, ov['TCSM'], ov['TCSV']), 'already in this file'
        else:
            vals, src = None, 'not set - find it with the TCS button step in tab 1 (optional)'
        if vals:
            self.addr['tcs'].set(f'0x{vals[0]:08X}'); self.addr['tcsm'].set(f'{vals[1]:02X}'); self.addr['tcsv'].set(f'{vals[2]:02X}')
        self.addr_src['tcs'].config(text=src)

    @staticmethod
    def _ram(s, what):
        try:
            v = int(s.strip(), 16)
        except ValueError:
            raise ValueError(f'the {what} address must be hex, e.g. 0xFFFF7100 (got "{s.strip()}")')
        if not core.ECU_RAM[0] <= v < core.ECU_RAM[1]:
            raise ValueError(f'the {what} address 0x{v:08X} is not in the ECU\'s RAM (FFFF0000-FFFFBFFF)')
        return v

    def tcs_values(self):
        """-> {'TCSA','TCSM','TCSV'} from the TCS boxes, None if empty; raises ValueError if filled in wrongly"""
        a, m, v = (self.addr[k].get().strip() for k in ('tcs', 'tcsm', 'tcsv'))
        if not (a or m or v): return None
        addr = self._ram(a, 'TCS byte')
        try:
            mask, val = int(m or 'x', 16), int(v or 'x', 16)
        except ValueError:
            raise ValueError('the TCS mask and "off" value must be hex bytes, e.g. 08 and 08')
        if not (0 < mask <= 0xFF and 0 <= val <= 0xFF) or val & ~mask:
            raise ValueError('the TCS mask must be 01-FF and the "off" value must only use bits of the mask')
        return {'TCSA': addr, 'TCSM': mask, 'TCSV': val}

    def tcs_changed(self):
        """the sport-mode option is available while the TCS boxes hold a valid TCS byte"""
        if not hasattr(self, 'ov_sport_chk') or getattr(self, '_filling', False): return
        try:
            tc = self.tcs_values()
        except ValueError:
            tc = None
        self.ov_sport_chk.config(state='normal' if tc else 'disabled')
        if not tc: self.ov_sport.set(False)
        self.ov_sport_note.config(text=(f'Uses the TCS byte 0x{tc["TCSA"]:08X} from the addresses box above. Sport mode starts OFF at '
                                         'every key-on; TCS off always allows the crackle.') if tc else
                                        'Needs the TCS byte in the addresses box above (find it with the TCS button step in tab 1).')

    def entered_addresses(self):
        """-> (A with the clutch / brake from the boxes, TCS dict or None); raises ValueError on a bad entry"""
        A = dict(self.A)
        A['clutch'] = self._ram(self.addr['clutch'].get(), 'clutch switch')
        A['brake'] = self._ram(self.addr['brake'].get(), 'brake switch')
        return A, self.tcs_values()

    def remember_entered(self, A, tcs):
        """remember addresses typed in by hand (the car check remembers its own)"""
        cal = A['cal']; mem = core.remembered_switches(cal); base = core.AD.for_cal(cal)
        cur = (mem['clutch'], mem['brake']) if mem else (base['clutch'], base['brake'])
        if (A['clutch'], A['brake']) != cur:
            core.remember_switches(cal, A['clutch'], A['brake'], source='entered')
            self.log_to(self.log1, f'Remembered for {cal}: clutch 0x{A["clutch"]:08X}, brake 0x{A["brake"]:08X} (entered by hand).')
        tc = core.remembered_tcs(cal)
        now = (tcs['TCSA'], tcs['TCSM'], tcs['TCSV']) if tcs else None
        if tcs and now != self.tcs_file and (not tc or (tc['addr'], tc['mask'], tc['val']) != now):
            core.remember_tcs(cal, tcs['TCSA'], tcs['TCSM'], tcs['TCSV'], source='entered')
            self.log_to(self.log1, f'Remembered for {cal}: TCS byte 0x{tcs["TCSA"]:08X} (entered).')

    def ov_lam_ford(self):
        for var, v in zip(self.ov_lam, core.OV.ARR_DEFAULTS['LAM']): var.set(f'{v:.2f}')

    def ov_lam_values(self):
        lo, hi = core.OV.LAM_MIN, core.OV.LAM_MAX
        try:
            vals = [float(v.get()) for v in self.ov_lam]
        except ValueError:
            raise ValueError('the overrun lambda values must be numbers, e.g. 0.92')
        bad = [v for v in vals if not lo - 1e-9 <= v <= hi + 1e-9]
        if bad:
            raise ValueError(f'overrun lambda must be between {lo:.2f} and {hi:.2f} (got {", ".join(f"{v:g}" for v in bad)})')
        return vals

    # slider = the recommended range; NC Flash's table takes 0-500 ms (the code's own limits)
    CD_MIN_MS, CD_MAX_MS, CD_DEFAULT_MS = 50, 400, 150
    cd_custom = None          # calls, when the file holds a value outside the slider's range (kept unless the slider moves)

    def cd_moved(self, v, user=True):
        """slider moved: snap to 10 ms"""
        ms = min(self.CD_MAX_MS, max(self.CD_MIN_MS, round(float(v) / 10) * 10))
        self.rv_cd.set(ms); self.rv_cd_lbl.config(text=f'{ms} ms')
        if user: self.cd_custom = None
        if hasattr(self, 'rv_cd_note'):
            if self.cd_custom is None:
                self.rv_cd_note.config(text=''); self.rv_cd_note.grid_remove()
            else:
                self.rv_cd_note.config(text=f'* {round(self.cd_custom * core.RV.CALL_MS):.0f} ms was set in NC Flash, outside the '
                                            f'recommended 50-400 ms. It is kept as it is unless you move the slider.')
                self.rv_cd_note.grid()

    def cd_calls(self):
        if self.cd_custom is not None: return self.cd_custom
        return max(core.RV.CD_REC_MIN, min(core.RV.CD_REC_MAX, round(float(self.rv_cd.get()) / core.RV.CALL_MS)))

    def load_rom(self, path):
        self.saved_paths.append(path)
        try:
            rom = core.read_rom(path)
        except (OSError, ValueError) as e:
            self.drop1.show(str(e), ok=False); return
        cal, A = core.guess_cal(rom)
        self.rom, self.rom_path, self.A = rom, path, A
        name = os.path.basename(path)
        gb = core.AD.gearbox(rom)
        if gb and not gb['manual']:
            self.A = None; self.fill_addresses()
            self.drop1.show(f'{name}\nCalibration {cal}: this is an AUTOMATIC ({gb["name"]}). The patches are for manual gearboxes only.', ok=False)
            self.btn_save.config(state='disabled'); self.btn_defs.config(state='disabled'); self.info1.config(text='')
            return
        if not A:
            self.A = None; self.fill_addresses()
            self.drop1.show(f'{name}\nCalibration {cal or "unknown"} is not one of the {len(core.AD.known())} calibrations NC Patcher '
                            'knows. It can be ported with tools/port.py (see docs/porting.md).', ok=False)
            self.btn_save.config(state='disabled'); self.btn_defs.config(state='disabled'); self.info1.config(text='')
            return
        st = core.state(rom, A)
        self.drop1.show(f'{name}\nCalibration {cal}' + (f' - {gb["name"]}' if gb else '') +
                        ('' if A.get('verified_on_car') else '  (ported - not yet proven on a car)'))
        inst = [n for n, k in (('ignition cut', 'igncut'), ('rev-match', 'revmatch'), ('overrun', 'overrun'),
                               ('traction control', 'tc')) if st[k]]
        self.info1.config(text=('Already installed: ' + ', '.join(inst) + ' - current settings loaded below.') if inst
                          else 'No patches installed yet (a stock or tuned ROM).')
        self.set_defaults(st)
        rv_ok = core.rev_available(A)
        self.rv_chk.config(state='normal' if rv_ok else 'disabled')
        if not rv_ok: self.rv_on.set(False)
        self.rv_note.config(text='' if rv_ok else 'Rev-match is not available for this calibration: its throttle software is laid '
                                                  'out differently (see docs/calibrations.md).')
        ov_ok = core.overrun_available(A)
        self.ov_chk.config(state='normal' if ov_ok else 'disabled')
        if not ov_ok:
            self.ov_on.set(False)
            self.ov_note.config(text='Overrun is not available for this calibration.')
        tc_ok = core.tc_available(A)
        self.tc_chk.config(state='normal' if tc_ok else 'disabled')
        if not tc_ok: self.tc_on.set(False)
        self.tc_note.config(text=self.tc_note_default if tc_ok else 'Traction control is not available for this calibration: it '
                            'runs from the same place in the throttle software as rev-match (see docs/calibrations.md).')
        self.btn_save.config(state='normal'); self.btn_defs.config(state='normal')
        self.log_to(self.log1, f'Loaded {name}: {cal}.')
        self.editor.rom_loaded()

    def _ig_values(self):
        try:
            return {k: float(v.get()) for k, v in self.ig_vars.items()}
        except ValueError:
            raise ValueError('the ignition-cut settings must be numbers')

    def save_patched(self):
        if not self.rom: return
        try:
            A, tcs = self.entered_addresses()                        # the addresses box: used for building AND testing
            ig = self._ig_values() if self.ig_on.get() else None
            rv = None
            if self.rv_on.get():
                rv = {'EN': 1.0 if self.rv_en.get() else 0.0, 'UPEN': 1.0 if self.rv_up.get() else 0.0, 'ASEN': 1.0 if self.rv_as.get() else 0.0,
                      'TGEN': 1.0 if self.rv_sw.get() else 0.0, 'CDLY': self.cd_calls(), 'BRK': A['brake']}
            ov = None
            if self.ov_on.get():
                try:
                    dur = float(self.ov_dur.get())
                except ValueError:
                    raise ValueError('the overrun duration must be a number of seconds')
                ov = {'EN': 1.0 if self.ov_en.get() else 0.0, 'STR': round(float(self.ov_str.get())), 'DUR': dur,
                      'LAM': self.ov_lam_values(), 'SPEN': 1.0 if self.ov_sport.get() else 0.0}
                if self.ov_sport.get() and not tcs:
                    raise ValueError('sport mode needs the TCS byte in the addresses box (find it with the TCS button step in tab 1)')
                if tcs: ov.update(tcs)
            tc = None
            if self.tc_on.get():
                try:
                    tc = {k: float(v.get()) for k, v in self.tc_vars.items()}
                except ValueError:
                    raise ValueError('the traction-control settings must be numbers')
                for k, val in tc.items():
                    lo, hi = core.TC.LIMITS[k]
                    if not lo <= val <= hi:
                        raise ValueError(f'traction control: {dict(SLIPKMH="slip allowed (km/h)", SLIPPCT="slip allowed (% of speed)", PMIN="pedal")[k]} must be '
                                         f'{lo:g}-{hi:g} (got {val:g})')
                tc['EN'] = 1.0 if self.tc_en.get() else 0.0
            if ig is None and rv is None and ov is None and tc is None:
                messagebox.showinfo(APP, 'Tick at least one patch.'); return
            rom = bytearray(self.rom)
            notes = core.patch(rom, A, ig, rv, ov, tc)
        except Exception as e:
            messagebox.showerror(APP, f'Could not patch this file:\n\n{e}'); return
        st = core.state(rom, A)
        tests = (['igncut_emu.py'] if ig is not None or st['igncut'] else []) + \
                (['revemu.py'] if st['revmatch'] else []) + (['overrun_emu.py'] if st['overrun'] else []) + \
                (['tc_emu.py'] if st['tc'] else [])
        self.log_to(self.log1, f'Addresses: clutch 0x{A["clutch"]:08X}, brake 0x{A["brake"]:08X}'
                               + (f', TCS 0x{tcs["TCSA"]:08X} (mask {tcs["TCSM"]:02X}, off {tcs["TCSV"]:02X})' if tcs else '') + '.')
        self.log_to(self.log1, 'Patched in memory: ' + '; '.join(notes) + '. Running the emulator tests...')
        self.update_idletasks()
        res = core.emulate(rom, A, tests)
        for t, (last, fails) in res.items(): self.log_to(self.log1, f'  {t}: {last}' + (f'  {fails[:3]}' if fails else ''))
        if not all(v[0] == 'ALL PASS' for v in res.values()):
            messagebox.showerror(APP, 'The emulator tests failed - the file was NOT saved.'); return
        stem, ext = os.path.splitext(self.rom_path)
        p = filedialog.asksaveasfilename(title='Save patched ECU file', initialfile=os.path.basename(stem) + ' - patched' + (ext or '.bin'),
                                         initialdir=os.path.dirname(self.rom_path), defaultextension='.bin', filetypes=[('ECU files', '*.bin')])
        if not p: return
        if os.path.abspath(p) == os.path.abspath(self.rom_path):
            messagebox.showerror(APP, 'Choose a new file name - the original is never overwritten.'); return
        open(p, 'wb').write(rom); self.saved_paths.append(p)
        self.log_to(self.log1, f'Saved {p}')
        self.remember_entered(A, tcs)
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

    # ------------------------------------------------------------------ tab 1: check my car (guided)
    def build_tab3(self):
        outer = self.t3
        self.log3 = T.text(outer, height=6, state='disabled'); self.log3.pack(side='bottom', fill='x', padx=px(8), pady=px(4))
        self.scroll3 = ScrollArea(outer); self.scroll3.pack(fill='both', expand=True)
        t = self.scroll3.inner
        intro = ttk.Label(t, text='Start here: this finds the RAM bytes your ECU uses for the clutch and brake switches, which the patches '
                                  'need. Connect with a J2534 interface (OBDX, Tactrix OpenPort, ...). This app only READS from the ECU - '
                                  'it never writes or flashes.', wraplength=px(860))
        intro.pack(anchor='w', **PAD); autowrap(intro, t)
        gd = tk.Frame(t, bg=T.SURFACE, highlightthickness=1, highlightbackground=T.ACCENT, highlightcolor=T.ACCENT)
        gd.pack(fill='x', padx=px(8), pady=px(4))
        self.guide_lbl = tk.Label(gd, text='', bg=T.SURFACE, fg=T.TEXT, justify='left', anchor='w', wraplength=px(640),
                                  font=('Segoe UI Semibold', 10))
        self.guide_lbl.pack(side='left', fill='x', expand=True, padx=px(10), pady=px(8))
        self.guide_next = ttk.Button(gd, text='Go to tab 2', style='Accent.TButton', command=self.guide_go)
        self.guide_skip = ttk.Button(gd, text='Skip - no interface', command=self.guide_skip_check)
        f = ttk.Frame(t); f.pack(fill='x', padx=px(8))
        self.devs = []
        self.dev_var = tk.StringVar()
        self.dev_box = ttk.Combobox(f, textvariable=self.dev_var, state='readonly', width=62); self.dev_box.grid(row=0, column=0, **PAD)
        ttk.Button(f, text='Refresh', command=self.refresh_devices).grid(row=0, column=1, **PAD)
        self.btn_conn = ttk.Button(f, text='Connect', command=self.connect, style='Accent.TButton'); self.btn_conn.grid(row=0, column=2, **PAD)
        self.conn_lbl = ttk.Label(f, text='Not connected'); self.conn_lbl.grid(row=1, column=0, columnspan=3, sticky='w', **PAD)
        # pedal check
        g = ttk.LabelFrame(t, text='Pedal check: confirms which RAM bytes are the brake and clutch switches'); g.pack(fill='x', padx=px(8), pady=px(6))
        ttk.Label(g, text='Ignition on, engine off. Press each button and do what it says; each capture takes a few seconds.',
                  wraplength=px(840)).grid(row=0, column=0, columnspan=5, sticky='w', **PAD)
        self.snap_btns = {}
        for i, (k, txt) in enumerate((('none1', '1. No pedals pressed'), ('brake', '2. HOLD the brake'),
                                      ('none2', '3. No pedals again'), ('clutch', '4. HOLD the clutch'))):
            b = ttk.Button(g, text=txt, command=lambda k=k: self.capture(k), state='disabled'); b.grid(row=1, column=i, **PAD)
            self.snap_btns[k] = b
        self.btn_analyse = ttk.Button(g, text='Analyse', command=self.analyse, state='disabled'); self.btn_analyse.grid(row=1, column=4, **PAD)
        self.prog3 = ttk.Progressbar(g, mode='determinate', length=px(300)); self.prog3.grid(row=2, column=0, columnspan=3, sticky='w', **PAD)
        self.btn_confirm = ttk.Button(g, text='Use these addresses', command=self.save_switches, state='disabled')
        self.btn_confirm.grid(row=2, column=3, columnspan=2, sticky='e', **PAD)
        self.found_lbl = ttk.Label(g, text='', wraplength=px(840)); self.found_lbl.grid(row=3, column=0, columnspan=5, sticky='w', **PAD)
        # TCS button (optional): for the overrun sport mode
        k = ttk.LabelFrame(t, text='Optional - TCS button, for the overrun "sport mode"'); k.pack(fill='x', padx=px(8), pady=px(6))
        tcs_help = ttk.Label(k, text='Engine RUNNING, parked in neutral with the handbrake on. Capture with TCS on (normal), then press '
                                     'the DSC button ONCE (TCS OFF light on) and capture again. Keep switching back and forth: '
                                     'at least 3 captures of each, alternating. More captures make it surer.', wraplength=px(840))
        tcs_help.grid(row=0, column=0, columnspan=4, sticky='w', **PAD); autowrap(tcs_help, k)
        self.tcs_btns = {'tcs_on': ttk.Button(k, text='Capture: TCS ON (normal)', command=lambda: self.capture('tcs_on'), state='disabled'),
                         'tcs_off': ttk.Button(k, text='Capture: TCS OFF (pressed once)', command=lambda: self.capture('tcs_off'), state='disabled')}
        self.tcs_btns['tcs_on'].grid(row=1, column=0, **PAD); self.tcs_btns['tcs_off'].grid(row=1, column=1, **PAD)
        self.btn_tcs_find = ttk.Button(k, text='Find the TCS byte', command=self.analyse_tcs, state='disabled'); self.btn_tcs_find.grid(row=1, column=2, **PAD)
        self.btn_tcs_use = ttk.Button(k, text='Use it', command=self.save_tcs, state='disabled'); self.btn_tcs_use.grid(row=1, column=3, **PAD)
        self.tcs_lbl = ttk.Label(k, text='', wraplength=px(840)); self.tcs_lbl.grid(row=2, column=0, columnspan=4, sticky='w', **PAD)
        autowrap(self.tcs_lbl, k)
        self.tcs_snaps = {'tcs_on': [], 'tcs_off': []}; self.tcs_seq = []; self.tcs_found = None
        # live
        h = ttk.LabelFrame(t, text='Live values'); h.pack(fill='x', padx=px(8), pady=px(6))
        self.live_var = tk.BooleanVar()
        self.live_chk = ttk.Checkbutton(h, text='Show live values', variable=self.live_var, command=self.toggle_live, state='disabled')
        self.live_chk.grid(row=0, column=0, sticky='w', **PAD)
        self.live_lbls = {}
        for i, k in enumerate(('RPM', 'Speed km/h', 'Pedal %', 'Clutch', 'Brake', 'TCS')):
            ttk.Label(h, text=k).grid(row=1, column=i, **PAD)
            self.live_lbls[k] = ttk.Label(h, text='-', style='Big.TLabel'); self.live_lbls[k].grid(row=2, column=i, **PAD)
        # the four wheel speeds the ABS unit sends the ECU (CAN 0x4B0); the factory software only uses the rear two
        for i, k in enumerate(self.WHEELS + ('Rear slip %',)):
            ttk.Label(h, text=k).grid(row=3, column=i, **PAD)
            self.live_lbls[k] = ttk.Label(h, text='-', style='Big.TLabel'); self.live_lbls[k].grid(row=4, column=i, **PAD)
        wh = ttk.Label(h, text='Wheel speeds (km/h) as the ABS unit sends them to the ECU. Rear slip = how much faster the rear '
                               'wheels turn than the front ones (0% = grip; it rises when the rears spin, and goes negative when '
                               'they lock under braking). Check all four match the speedo when driving straight.',
                       style='Hint.TLabel', wraplength=px(840))
        wh.grid(row=5, column=0, columnspan=6, sticky='w', **PAD); autowrap(wh, h)
        self.found = {}; self.guide_target = None; self.A3 = None
        self.refresh_devices()
        self.guide('start')

    # ---- the guide: one instruction at a time, with the button to press highlighted
    GUIDE = {
        'connect': 'Step 1 of 7 - Plug your J2534 interface into the OBD port under the dash and turn the ignition ON '
                   '(engine OFF). Choose the interface below and press Connect.',
        'none1': 'Step 2 of 7 - Feet off all the pedals. Press "1. No pedals pressed" and keep still until the bar is full.',
        'brake': 'Step 3 of 7 - HOLD the brake pedal down, press "2. HOLD the brake", and keep holding until the bar is full.',
        'none2': 'Step 4 of 7 - Let go of the brake. Press "3. No pedals again".',
        'clutch': 'Step 5 of 7 - HOLD the clutch pedal down, press "4. HOLD the clutch", and keep holding until the bar is full.',
        'analyse': 'Step 6 of 7 - Let go of the clutch and press Analyse.',
        'use': 'Step 7 of 7 - Check the result under the buttons, then press "Use these addresses". They are remembered '
               'for this calibration and used when you patch your file in tab 2.',
    }

    def guide(self, step):
        """show the instruction for a step and highlight the button to press"""
        buttons = {'connect': self.btn_conn, 'analyse': self.btn_analyse, 'use': self.btn_confirm, **self.snap_btns}
        for k, b in buttons.items():
            b.config(style='Accent.TButton' if k == step else 'TButton')
        self.guide_next.pack_forget(); self.guide_skip.pack_forget()
        if step == 'start':
            mem = core.settings().get('switches') or {}
            if mem:
                done = '; '.join(f'{c}: clutch {v["clutch"]}, brake {v["brake"]} ({v.get("checked", "")})' for c, v in mem.items())
                text = (f'Already checked on your car - {done}. Go to tab 2 to patch your ECU file, or follow the steps '
                        'again to re-check.\n\n' + self.GUIDE['connect'])
                self.guide_target = self.t1; self.guide_next.config(text='Go to tab 2')
                self.guide_next.pack(side='right', padx=px(8), pady=px(8))
            else:
                text = 'Welcome to NC Patcher. First, find your clutch and brake switches on the car (about 2 minutes).\n\n' + self.GUIDE['connect']
                self.guide_skip.pack(side='right', padx=px(8), pady=px(8))
            self.btn_conn.config(style='Accent.TButton')
        elif step == 'done':
            c, b = self.found['clutch'], self.found['brake']
            if self.A3:
                text = (f'Done - clutch 0x{c:08X} and brake 0x{b:08X} are remembered for {self.ecu_cal}.\n\n'
                        f'Next: go to tab 2 and drop your {self.ecu_cal} ECU file (read with NC Flash). The patches will use '
                        'these addresses.')
                self.guide_target = self.t1; self.guide_next.config(text='Go to tab 2')
            else:
                text = (f'Done - clutch 0x{c:08X} and brake 0x{b:08X} are remembered for {self.ecu_cal}.\n\n'
                        f'{self.ecu_cal} is not one of the calibrations NC Patcher knows (automatics aren\'t supported). '
                        'A manual calibration can be ported with tools/port.py - see docs/porting.md.')
                self.guide_target = None
            if self.guide_target is not None: self.guide_next.pack(side='right', padx=px(8), pady=px(8))
        elif step == 'notfound':
            text = ('The clutch and brake could not both be found. Make sure the ignition is on and hold each pedal fully down '
                    'for the whole capture, then start again from step 2.')
            buttons['none1'].config(style='Accent.TButton')
        else:
            text = self.GUIDE[step]
        self.guide_lbl.config(text=text)

    def guide_next_capture(self):
        for k in ('none1', 'brake', 'none2', 'clutch'):
            if k not in self.snaps: return self.guide(k)
        self.guide('analyse')

    def guide_go(self):
        if self.guide_target is not None: self.nb.select(self.guide_target)

    def guide_skip_check(self):
        if not messagebox.askokcancel(APP, 'Skip the car check?\n\nThe patches then use the usual addresses for your calibration, '
                                           'which have not been checked on your car. You can come back to tab 1 at any time.'):
            return
        s = core.settings(); s['guide_done'] = True; core.save_settings(s)
        self.guide('start'); self.nb.select(self.t1)

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
            self.conn_lbl.config(text='Not connected'); self.btn_conn.config(text='Connect'); self._enable3(False)
            self.guide('connect'); return
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
                e = ECU.Ecu(pt, log)
                try:
                    cal = e.probe()
                except ECU.EcuError as err:            # memory reads refused: standard OBD-II still works on any NC ECU
                    cal = ECU.Obd(pt).calibration_id()
                    if not cal and not ECU.Obd(pt).supported(): raise
                    log(f'memory reads not available ({err}); standard OBD-II only (tab 4 can still log)')
                    e = None
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
            self.A3 = core.AD.for_cal(cal) if cal else None
        except AssertionError:
            self.A3 = None
        if self.ecu is None:                       # memory reads refused: tab 1's checks need them, tab 4 logs standard OBD-II
            self.ecu_cal = cal
            self.conn_lbl.config(text=f'Connected ({v}). ECU calibration: {cal or "unknown"}. This ECU doesn\'t answer memory '
                                      'reads, so the pedal / TCS checks can\'t run; tab 4 can still log standard OBD-II values.')
            self.btn_conn.config(text='Disconnect'); return
        self.ecu_cal = cal
        if cal and getattr(self.ecu, 'fmt', None):
            core.remember_read_format(cal, self.ecu.fmt, self.ecu.skip)        # for the OpenPort SD-card logging file (tab 4)
        self.conn_lbl.config(text=f'Connected ({v}). ECU calibration: {cal}' + ('' if self.A3 else ' - not one NC Patcher knows (see docs/porting.md)'))
        self.btn_conn.config(text='Disconnect'); self._enable3(True)
        self.snaps = {}; self.found = {}; self.found_lbl.config(text='')
        for k, b in self.snap_btns.items(): b.config(text=b['text'].split('  ')[0])
        self.tcs_snaps = {'tcs_on': [], 'tcs_off': []}; self.tcs_seq = []; self.tcs_found = None
        for b in self.tcs_btns.values(): b.config(text=b['text'].split('  ')[0])
        self.btn_tcs_find.config(state='disabled'); self.btn_tcs_use.config(state='disabled')
        tc = core.remembered_tcs(cal)
        self.tcs_lbl.config(text=(f'Already found for {cal}: TCS byte 0x{tc["addr"]:08X}, mask 0x{tc["mask"]:02X} = 0x{tc["val"]:02X} '
                                  f'when off ({tc["checked"]}). Turn on Live values to watch it follow the button.') if tc else '',
                            foreground=T.OK)
        self.guide_next_capture()

    def _enable3(self, on):
        s = 'normal' if on else 'disabled'
        for b in list(self.snap_btns.values()) + list(self.tcs_btns.values()): b.config(state=s)
        if not on: self.btn_tcs_find.config(state='disabled'); self.btn_tcs_use.config(state='disabled')
        self.live_chk.config(state=s if (on and getattr(self, 'A3', None)) else 'disabled')
        if not on: self.btn_analyse.config(state='disabled'); self.btn_confirm.config(state='disabled')

    def capture(self, which):
        if not self.ecu: return
        self.live_on = False; self.live_var.set(False)
        for b in list(self.snap_btns.values()) + list(self.tcs_btns.values()): b.config(state='disabled')
        self.prog3['value'] = 0
        btn = self.snap_btns.get(which) or self.tcs_btns[which]
        self.log_to(self.log3, f'Capturing "{btn["text"].split("  ")[0]}"... keep still.')

        def go():
            with self.lock:
                return self.ecu.snapshot(progress=lambda f: self.ui(self.prog3.configure, {'value': f * 100}))
        self.work(go, done=lambda r, err: self.captured(which, r, err))

    def captured(self, which, r, err):
        for b in list(self.snap_btns.values()) + list(self.tcs_btns.values()): b.config(state='normal')
        if err:
            self.log_to(self.log3, f'Capture failed: {err}'); return
        if which in self.tcs_btns:                                   # TCS button captures (any number of each, alternating)
            if self.tcs_seq and self.tcs_seq[-1] == which:
                self.log_to(self.log3, 'Same TCS state twice in a row: that capture is not used. Press the DSC button and '
                                       'capture the other state - alternating is what rules out bytes that just drift.')
                return
            self.tcs_snaps[which].append(r); self.tcs_seq.append(which)
            b = self.tcs_btns[which]; b.config(text=b['text'].split('  ')[0] + f'  ({len(self.tcs_snaps[which])})')
            self.log_to(self.log3, f'Captured {len(r)} bytes of RAM.')
            n_on, n_off = len(self.tcs_snaps['tcs_on']), len(self.tcs_snaps['tcs_off'])
            self.btn_tcs_find.config(state='normal' if min(n_on, n_off) >= self.TCS_MIN else 'disabled')
            nxt = 'TCS OFF (press DSC once)' if which == 'tcs_on' else 'TCS ON (press DSC again)'
            self.tcs_lbl.config(text=f'{n_on} TCS-on and {n_off} TCS-off captures. ' +
                                (f'Next: {nxt}. At least {self.TCS_MIN} of each are needed, alternating.'
                                 if min(n_on, n_off) < self.TCS_MIN else 'You can press "Find the TCS byte" now (more captures make it surer).'),
                                foreground=T.TEXT)
            return
        self.snaps[which] = r
        self.snap_btns[which].config(text=self.snap_btns[which]['text'].split('  ')[0] + '  ✓')
        self.log_to(self.log3, f'Captured {len(r)} bytes of RAM.')
        if all(k in self.snaps for k in ('none1', 'brake', 'clutch')): self.btn_analyse.config(state='normal')
        self.guide_next_capture()

    def analyse(self):
        nones = [self.snaps['none1']] + ([self.snaps['none2']] if 'none2' in self.snaps else [])
        rom = bytes(self.rom) if (self.rom and self.A and self.A['cal'] == self.ecu_cal) else None
        if rom is None:
            self.log_to(self.log3, '(Optional: dropping this car\'s ECU file in tab 2 before Analyse helps rank the candidates.)')
        r = ECU.analyse(nones, self.snaps['brake'], self.snaps['clutch'], rom)
        self.found = {}; summary = []
        for k in ('brake', 'clutch'):
            top = r[k][:5]
            exp = self.A3.get(k) if self.A3 else None
            self.log_to(self.log3, f'{k.upper()}: {len(r[k])} candidate bytes. Best:')
            for score, a, x, y, refs in top:
                self.log_to(self.log3, f'   0x{a:08X}  {x} -> {y}   read by the code in {refs} places' + ('   <== expected' if a == exp else ''))
            if exp is not None and any(t[1] == exp for t in top):
                self.found[k] = exp                                  # the calibration's usual address switched: confirmed
                summary.append(f'{k.capitalize()}: 0x{exp:08X} - the usual {self.ecu_cal} address, confirmed on your car.')
            elif top:
                self.found[k] = top[0][1]
                summary.append(f'{k.capitalize()}: 0x{top[0][1]:08X}' + (f' - NOT the usual {self.ecu_cal} address 0x{exp:08X}. '
                               'Check the log; if in doubt, capture again.' if exp is not None else ' (best candidate).'))
            else:
                summary.append(f'{k.capitalize()}: not found.')
        ok = 'clutch' in self.found and 'brake' in self.found
        self.found_lbl.config(text='\n'.join(summary), foreground=T.OK if ok else T.ERR)
        self.btn_confirm.config(state='normal' if ok else 'disabled')
        self.guide('use' if ok else 'notfound')

    def save_switches(self):
        c, b = self.found.get('clutch'), self.found.get('brake')
        if c is None or b is None or not self.ecu_cal: return
        if not messagebox.askokcancel(APP, f'Use these for {self.ecu_cal}?\n\nclutch 0x{c:08X}\nbrake 0x{b:08X}\n\n'
                                           'NC Patcher remembers them and uses them when it patches your ECU file.'):
            return
        core.remember_switches(self.ecu_cal, c, b)
        if self.A3: core.confirm_switches(self.A3, c, b)            # ported calibrations: also recorded in addresses.json
        self.log_to(self.log3, f'Remembered for {self.ecu_cal}: clutch 0x{c:08X}, brake 0x{b:08X}.')
        if self.rom_path and self.A and self.A['cal'].upper() == self.ecu_cal.upper():
            self.load_rom(self.rom_path)                             # the file already in tab 2 picks them up
        self.guide('done')

    TCS_MIN = 3                    # captures of each TCS state needed (alternating), so chance matches are very unlikely

    def analyse_tcs(self):
        ons, offs = self.tcs_snaps['tcs_on'], self.tcs_snaps['tcs_off']
        rom = bytes(self.rom) if (self.rom and self.A and self.A['cal'] == self.ecu_cal) else None
        r = ECU.analyse_toggle(ons, offs, rom)
        self.tcs_found = None; self.btn_tcs_use.config(state='disabled')
        self.log_to(self.log3, f'TCS: {len(r)} candidate bytes from {len(ons)} on / {len(offs)} off captures. Best:')
        for score, a, x, y, refs, mask, val in r[:6]:
            self.log_to(self.log3, f'   0x{a:08X}  on 0x{x:02X} -> off 0x{y:02X}   mask 0x{mask:02X}   read by the code in {refs} places')
        if not r:
            self.tcs_lbl.config(text='No RAM byte follows the TCS button. Check the TCS OFF light really changed between the '
                                     'captures and try again. If it still finds nothing, this car\'s ECU is not told the TCS state, '
                                     'and the sport mode cannot be used.', foreground=T.ERR); return
        best = r[0]; ties = [t for t in r if t[0] == best[0]]
        self.tcs_found = best
        more = (f' {len(ties) - 1} other byte(s) followed the button exactly as well (listed in the log) - normal, the ECU '
                'can keep the same signal in more than one place; any of them works.') if len(ties) > 1 else ''
        self.tcs_lbl.config(text=f'TCS byte: 0x{best[1]:08X} - TCS off when (byte & 0x{best[5]:02X}) = 0x{best[6]:02X}.{more} '
                                 f'Press "Use it" to remember it for {self.ecu_cal}.', foreground=T.OK)
        self.btn_tcs_use.config(state='normal')

    def save_tcs(self):
        if not self.tcs_found or not self.ecu_cal: return
        _, a, _, _, _, mask, val = self.tcs_found
        if not messagebox.askokcancel(APP, f'Use this for {self.ecu_cal}?\n\nTCS byte 0x{a:08X}: TCS off when (byte & 0x{mask:02X}) '
                                           f'= 0x{val:02X}\n\nNC Patcher remembers it; the overrun "sport mode" option in tab 2 uses it.'):
            return
        core.remember_tcs(self.ecu_cal, a, mask, val)
        self.log_to(self.log3, f'Remembered for {self.ecu_cal}: TCS byte 0x{a:08X}, mask 0x{mask:02X}, off = 0x{val:02X}.')
        self.tcs_lbl.config(text=f'Remembered: TCS byte 0x{a:08X}. Now CHECK it: turn on Live values and press the DSC button a '
                                 'few times - TCS must show OFF exactly when the TCS OFF light is on. If it does not, capture '
                                 'again. Then use the overrun "sport mode" option in tab 2.', foreground=T.OK)
        if self.rom_path and self.A and self.A['cal'].upper() == self.ecu_cal.upper():
            self.load_rom(self.rom_path)                             # the file already in tab 2 picks it up

    WHEELS = ('Front left', 'Front right', 'Rear left', 'Rear right')

    @classmethod
    def wheel_values(cls, raw):
        """8 bytes of the CAN 0x4B0 buffer (or None) -> label texts for the four wheels and the rear slip"""
        if not raw or len(raw) < 8:
            return {k: '-' for k in cls.WHEELS + ('Rear slip %',)}
        kmh = [core.AD.wheel_kmh(struct.unpack_from('>H', raw, 2 * i)[0]) for i in range(4)]
        out = {k: ('-' if v is None else f'{v:.1f}') for k, v in zip(cls.WHEELS, kmh)}
        if None in kmh:
            out['Rear slip %'] = '-'
        else:
            front, rear = (kmh[0] + kmh[1]) / 2, (kmh[2] + kmh[3]) / 2
            out['Rear slip %'] = f'{(rear - front) / front * 100:+.0f}' if front >= 5 else '-'    # meaningless when (nearly) stopped
        return out

    def toggle_live(self):
        self.live_on = self.live_var.get()
        if self.live_on: self.work(self.live_loop)

    def live_loop(self):
        A = core.with_switches(self.A3)[0]          # the clutch / brake checked on the car, if any
        while self.live_on and self.ecu:
            try:
                with self.lock:
                    vals = {'RPM': f'{self.ecu.f32(A["rpm"]):.0f}', 'Speed km/h': f'{self.ecu.f32(A["speed"]):.0f}',
                            'Pedal %': f'{self.ecu.f32(A["pedal_in"]):.0f}',
                            'Clutch': 'pressed' if self.ecu.u8(A['clutch']) == 1 else 'up',
                            'Brake': 'pressed' if self.ecu.u8(A['brake']) == 1 else 'off'}
                tc = core.remembered_tcs(A['cal'])
                vals['TCS'] = ('OFF' if (self.ecu.u8(tc['addr']) & tc['mask']) == tc['val'] else 'on') if tc else '-'
                vals.update(self.wheel_values(self.ecu.read(A['wheel_speeds'], 8) if A.get('wheel_speeds') else None))
                for k, v in vals.items(): self.ui(self.live_lbls[k].config, {'text': v})
            except Exception as e:
                self.ui(self.log_to, self.log3, f'Live read failed: {e}'); self.live_on = False
                self.ui(self.live_var.set, False); break
            threading.Event().wait(0.25)


if __name__ == '__main__':
    app = App()
    # a file dropped onto NCPatcher.exe's icon (or "Open with" / a command-line argument) opens straight in tab 2
    start = next((a for a in sys.argv[1:] if os.path.isfile(a)), None)
    if start: app.after(300, app.open_ecu_file, start)
    app.mainloop()

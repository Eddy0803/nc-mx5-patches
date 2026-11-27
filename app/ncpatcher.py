"""NC Patcher - GUI for the NC MX-5 ECU patches.

Tab 1: check my car - connect through a J2534 interface (read-only), identify the ECU and run the guided pedal check,
       which finds the clutch / brake switch RAM addresses. They are remembered per calibration and used by tabs 2 and 3.
Tab 2: drop your ECU file, choose features and settings, save a patched file (flash it with NC Flash).
Tab 3: port the patches to another calibration (stock LFJ1EE + your stock ROM).
"""
import os, queue, struct, sys, threading, traceback

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
try:
    import dragdrop               # noqa: E402
except Exception:                 # non-Windows or no comctl32: browsing still works
    dragdrop = None

APP = 'NC Patcher'
VERSION = '0.9.21 beta'
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


class ReportDialog(tk.Toplevel):
    """shows a port problem report; it is only sent if the user presses Submit"""
    def __init__(self, app, r):
        super().__init__(app)
        self.app, self.r = app, r
        self.title_text, self.body = core.make_report(r, VERSION)
        self.title(f'{APP} - port problem report'); self.configure(bg=T.BG); self.transient(app)
        self.geometry(f'{px(760)}x{px(620)}'); self.minsize(px(560), px(420))
        stopped = not r.get('report')
        head = ('The port stopped.' if stopped else 'The port finished, but not everything was built.') + \
               ' You can send this report to the project so your calibration can be supported.'
        ttk.Label(self, text=head, wraplength=px(720), font=('Segoe UI Semibold', 10)).pack(anchor='w', padx=px(12), pady=(px(12), px(4)))
        ttk.Label(self, text='This is everything that would be sent. It contains no ROM data, file contents, names or folder '
                             'paths. Nothing is sent unless you press Submit.', style='Hint.TLabel', wraplength=px(720)
                  ).pack(anchor='w', padx=px(12), pady=(0, px(8)))
        box = T.text(self, height=20, wrap='word'); box.pack(fill='both', expand=True, padx=px(12))
        box.insert('1.0', self.title_text + '\n\n' + self.body); box.configure(state='disabled')
        self.status = ttk.Label(self, text='', style='Hint.TLabel'); self.status.pack(anchor='w', padx=px(12), pady=(px(6), 0))
        bar = ttk.Frame(self); bar.pack(fill='x', padx=px(12), pady=px(12))
        self.btn_submit = ttk.Button(bar, text='Submit report', style='Accent.TButton', command=self.submit)
        self.btn_submit.pack(side='left')
        ttk.Button(bar, text='Save to file...', command=self.save).pack(side='left', padx=px(8))
        ttk.Button(bar, text='Cancel', command=self.destroy).pack(side='right')
        if not core.REPORT_FORM:
            self.btn_submit.config(state='disabled'); self.status.config(text='Sending is not set up in this version - you can save the report to a file.')
        T.dark_title_bar(self); self.grab_set(); self.focus_set()

    def save(self):
        p = filedialog.asksaveasfilename(parent=self, title='Save report', defaultextension='.md',
                                         initialfile=f'port-problem-{(self.r.get("cal") or "unknown").lower()}.md',
                                         filetypes=[('Markdown', '*.md'), ('Text', '*.txt')])
        if p:
            open(p, 'w', encoding='utf-8').write(f'# {self.title_text}\n\n{self.body}\n')
            self.status.config(text=f'Saved: {os.path.basename(p)}')

    def submit(self):
        self.btn_submit.config(state='disabled'); self.status.config(text='Sending...')
        self.app.work(core.submit_report, self.title_text, self.body, done=self.sent)

    def sent(self, res, err):
        ok, msg = res if res else (False, str(err))
        if not self.winfo_exists(): return
        self.status.config(text=msg)
        if ok:
            core.save_report(self.title_text, self.body, self.r.get('cal'))
            self.btn_submit.config(text='Sent', state='disabled')
        else:
            self.btn_submit.config(state='normal')


def labelled(parent, row, text, var, width=10, tip=''):
    ttk.Label(parent, text=text).grid(row=row, column=0, sticky='w', **PAD)
    e = ttk.Entry(parent, textvariable=var, width=width); e.grid(row=row, column=1, sticky='w', **PAD)
    if tip: ttk.Label(parent, text=tip, style='Hint.TLabel').grid(row=row, column=2, sticky='w', **PAD)
    return e


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'{APP} {VERSION}')
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
        self.nb = nb; self.auto_patch_cal = None
        self.t1, self.t2, self.t3 = (ttk.Frame(nb) for _ in range(3))
        nb.add(self.t3, text='  1. Check my car (J2534)  ')
        nb.add(self.t1, text='  2. Patch my ECU file  ')
        nb.add(self.t2, text='  3. Port to another calibration  ')
        self.build_tab1(); self.build_tab2(); self.build_tab3()
        self.nb.select(self.t1 if core.settings().get('guide_done') else self.t3)   # first start: the guided car check
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

    # ------------------------------------------------------------------ tab 2: patch my ECU file
    def build_tab1(self):
        t = self.t1
        ttk.Label(t, text='Drop your ECU file (a 1 MB .bin read with NC Flash) to add the patches to it. '
                          'The file you drop is never changed; you save a new one.', wraplength=px(860)).pack(anchor='w', **PAD)
        self.drop1 = DropZone(t, 'Drop your ECU file here  -  or click to browse', self.load_rom)
        self.drop1.pack(fill='x', padx=px(8), pady=px(4))
        self.info1 = ttk.Label(t, text='', wraplength=px(860)); self.info1.pack(anchor='w', **PAD)
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
        ttk.Checkbutton(g, text='Downshift on/off switch (stopped, clutch down, 3 brake taps)', variable=self.rv_sw).grid(row=4, column=0, columnspan=2, sticky='w', **PAD)
        # clutch hold delay: how long the clutch must stay down before downshift rev-match / upshift hold act
        ttk.Label(g, text='Clutch hold before it acts').grid(row=5, column=0, columnspan=2, sticky='w', padx=px(6), pady=(px(6), 0))
        cf = ttk.Frame(g); cf.grid(row=6, column=0, columnspan=2, sticky='we', padx=px(6))
        self.rv_cd = tk.DoubleVar(value=self.CD_DEFAULT_MS)
        ttk.Label(cf, text=f'{self.CD_MIN_MS} ms', style='Hint.TLabel').pack(side='left')
        ttk.Scale(cf, from_=self.CD_MIN_MS, to=self.CD_MAX_MS, variable=self.rv_cd, orient='horizontal', length=px(200),
                  command=self.cd_moved).pack(side='left', padx=px(6))
        ttk.Label(cf, text=f'{self.CD_MAX_MS} ms', style='Hint.TLabel').pack(side='left')
        self.rv_cd_lbl = ttk.Label(cf, text=f'{self.CD_DEFAULT_MS} ms', width=7); self.rv_cd_lbl.pack(side='left', padx=px(8))
        self.rv_cd_note = ttk.Label(g, text='', style='Hint.TLabel', wraplength=px(360))
        self.rv_cd_note.grid(row=7, column=0, columnspan=2, sticky='w', padx=px(6))
        ttk.Label(g, text='The clutch must stay down this long before the throttle opens. Raise it if the car jolts as you press '
                          'the clutch; lower it if the revs are late on quick downshifts. Default 150 ms. The slider covers the '
                          'recommended 50-400 ms: shorter is no real delay, longer risks the blip starting as the clutch comes '
                          'back up. NC Flash accepts 0-500 ms (0 = no delay).',
                  style='Hint.TLabel', wraplength=px(360)).grid(row=8, column=0, columnspan=2, sticky='w', **PAD)
        self.rv_note = ttk.Label(g, text='', style='Hint.TLabel', wraplength=px(360)); self.rv_note.grid(row=9, column=0, columnspan=2, sticky='w', **PAD)
        ttk.Label(g, text='Fine tuning (gains, offsets, gearing, switch confirm RPM) is done in NC Flash after adding the tables. '
                          'Every setting has a hard limit in the ECU code (e.g. 40% throttle, 3.3 s hold), so a wrong value '
                          "can't make it do anything dangerous.",
                  style='Hint.TLabel', wraplength=px(360)).grid(row=10, column=0, columnspan=2, sticky='w', **PAD)
        ttk.Button(g, text='Why these limits?', command=lambda: LimitsDialog(self)).grid(row=11, column=0, sticky='w', padx=px(6), pady=(0, px(6)))
        # overrun crackle
        self.ov_on, self.ov_en = tk.BooleanVar(value=False), tk.BooleanVar(value=False)
        self.ov_str, self.ov_dur = tk.DoubleVar(value=core.OV.DEFAULTS['STR']), tk.StringVar(value=f"{core.OV.DEFAULTS['DUR']:g}")
        o = ttk.LabelFrame(t, text='Overrun crackle (timed, lean)'); o.pack(fill='x', padx=px(8), pady=(px(6), 0))
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
        self.ov_note = ttk.Label(o, text='Lifting off after the pedal has been above 20% gives one burst. Needs coolant 50 C+, '
                                 '2500-6500 rpm, clutch up; any speed. Fuel follows the lambda table (stock Ford: 0.92 to 3000 rpm, 1.0 from 4000); Strength sets the spark. Other limits are in NC Flash.', style='Hint.TLabel', wraplength=px(860))
        self.ov_note.grid(row=2, column=0, columnspan=5, sticky='w', **PAD)
        bar = ttk.Frame(t); bar.pack(fill='x', padx=px(8), pady=px(6))
        self.btn_save = ttk.Button(bar, text='Save patched file...', command=self.save_patched, state='disabled', style='Accent.TButton'); self.btn_save.pack(side='left')
        self.btn_defs = ttk.Button(bar, text='Show the new tables in NC Flash', command=self.add_defs, state='disabled'); self.btn_defs.pack(side='left', padx=px(8))
        self.log1 = T.text(t, height=10, state='disabled'); self.log1.pack(fill='both', expand=True, padx=px(8), pady=px(4))
        self.rom = None; self.rom_path = None; self.A = None; self.sw_mem = None
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

    # slider = the recommended range; NC Flash's table takes 0-500 ms (the code's own limits)
    CD_MIN_MS, CD_MAX_MS, CD_DEFAULT_MS = 50, 400, 150
    cd_custom = None          # calls, when the file holds a value outside the slider's range (kept unless the slider moves)

    def cd_moved(self, v, user=True):
        """slider moved: snap to 10 ms"""
        ms = min(self.CD_MAX_MS, max(self.CD_MIN_MS, round(float(v) / 10) * 10))
        self.rv_cd.set(ms); self.rv_cd_lbl.config(text=f'{ms} ms')
        if user: self.cd_custom = None
        if hasattr(self, 'rv_cd_note'):
            self.rv_cd_note.config(text='' if self.cd_custom is None else
                                   f'* {round(self.cd_custom * core.RV.CALL_MS):.0f} ms was set in NC Flash, outside the '
                                   f'recommended 50-400 ms. It is kept as it is unless you move the slider.')

    def cd_calls(self):
        if self.cd_custom is not None: return self.cd_custom
        return max(core.RV.CD_REC_MIN, min(core.RV.CD_REC_MAX, round(float(self.rv_cd.get()) / core.RV.CALL_MS)))

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
            self.drop1.show(f'{name}\nCalibration {cal or "unknown"} is not supported yet - port it in tab 3 first.', ok=False)
            self.btn_save.config(state='disabled'); self.btn_defs.config(state='disabled'); self.info1.config(text='')
            if cal: self.cal_var.set(cal)
            return
        A, self.sw_mem = core.with_switches(A); self.A = A        # clutch / brake checked on the car, if any
        st = core.state(rom, A)
        self.drop1.show(f'{name}\nCalibration {cal}' + (f' - {gb["name"]}' if gb else '') +
                        ('' if A.get('verified_on_car') else '  (ported - not yet proven on a car)'))
        inst = [n for n, k in (('ignition cut', 'igncut'), ('rev-match', 'revmatch'), ('overrun', 'overrun')) if st[k]]
        self.info1.config(text=('Already installed: ' + ', '.join(inst) + ' - current settings loaded below.') if inst
                          else 'No patches installed yet (a stock or tuned ROM).')
        self.set_defaults(st)
        rv_ok = core.rev_available(A)
        self.rv_chk.config(state='normal' if rv_ok else 'disabled')
        if not rv_ok: self.rv_on.set(False)
        self.rv_note.config(text=self.switch_note(A) if rv_ok else 'Rev-match is not available for this calibration (see its port report).')
        ov_ok = core.overrun_available(A)
        self.ov_chk.config(state='normal' if ov_ok else 'disabled')
        if not ov_ok:
            self.ov_on.set(False)
            self.ov_note.config(text='Overrun is not available for this calibration yet - port it again in tab 3 with this version.')
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
                rv = {'EN': 1.0 if self.rv_en.get() else 0.0, 'UPEN': 1.0 if self.rv_up.get() else 0.0, 'ASEN': 1.0 if self.rv_as.get() else 0.0,
                      'TGEN': 1.0 if self.rv_sw.get() else 0.0, 'CDLY': self.cd_calls()}
                if self.sw_mem: rv['BRK'] = self.A['brake']          # the brake switch checked on the car
            ov = None
            if self.ov_on.get():
                try:
                    dur = float(self.ov_dur.get())
                except ValueError:
                    raise ValueError('the overrun duration must be a number of seconds')
                ov = {'EN': 1.0 if self.ov_en.get() else 0.0, 'STR': round(float(self.ov_str.get())), 'DUR': dur}
            if ig is None and rv is None and ov is None:
                messagebox.showinfo(APP, 'Tick at least one patch.'); return
            rom = bytearray(self.rom)
            notes = core.patch(rom, self.A, ig, rv, ov)
        except Exception as e:
            messagebox.showerror(APP, f'Could not patch this file:\n\n{e}'); return
        tests = (['igncut_emu.py'] if ig is not None or core.state(rom, self.A)['igncut'] else []) + \
                (['revemu.py'] if core.state(rom, self.A)['revmatch'] else []) + \
                (['overrun_emu.py'] if core.state(rom, self.A)['overrun'] else [])
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

    def switch_note(self, A):
        base = core.AD.for_cal(A['cal'])
        txt = f'Brake switch RAM 0x{A["brake"]:08X}, clutch 0x{A["clutch"]:08X}'
        if self.sw_mem:
            same = (base['brake'], base['clutch']) == (A['brake'], A['clutch'])
            return txt + f' - checked on your car ({self.sw_mem["checked"]})' + ('' if same else f' (not the usual {A["cal"]} addresses - using yours)')
        if A.get('verified_on_car'):
            return txt + f' - the usual {A["cal"]} addresses, proven on a car. Tab 1 checks them on yours.'
        return txt + ' - NOT checked on your car yet: do the pedal check in tab 1 first.'

    # ------------------------------------------------------------------ tab 3: port to another calibration
    def build_tab2(self):
        t = self.t2
        ttk.Label(t, text='Port the patches to another calibration: drop a STOCK LFJ1EE file (the reference) and a STOCK read of '
                          'your calibration. Every address is found automatically and checked; the port stops rather than guessing.',
                  wraplength=px(860)).pack(anchor='w', **PAD)
        self.ref_path = self.stock_path = None
        self.drop_ref = DropZone(t, 'Drop a stock LFJ1EE file here (the reference)', self.load_ref, height=56); self.drop_ref.pack(fill='x', padx=px(8), pady=px(3))
        self.drop_stock = DropZone(t, 'Drop a stock read of YOUR calibration here', self.load_stock, height=56); self.drop_stock.pack(fill='x', padx=px(8), pady=px(3))
        f = ttk.Frame(t); f.pack(fill='x', padx=px(8))
        self.cal_var = tk.StringVar(); self.clutch_var = tk.StringVar(); self.brake_var = tk.StringVar(); self.allow_rate = tk.BooleanVar()
        labelled(f, 0, 'Calibration ID', self.cal_var, tip='filled in from the file')
        labelled(f, 1, 'Clutch RAM address (optional)', self.clutch_var, width=14, tip='filled in by the pedal check (tab 1)')
        labelled(f, 2, 'Brake RAM address (optional)', self.brake_var, width=14)
        ttk.Checkbutton(f, text='Build rev-match even if its call rate differs from LFJ1EE (you will measure and retune)',
                        variable=self.allow_rate).grid(row=3, column=0, columnspan=3, sticky='w', **PAD)
        bar = ttk.Frame(t); bar.pack(fill='x', padx=px(8), pady=px(4))
        self.btn_port = ttk.Button(bar, text='Port', command=self.do_port, style='Accent.TButton'); self.btn_port.pack(side='left')
        self.btn_report = ttk.Button(bar, text='Open report', command=lambda: self.open(self.last_report), state='disabled'); self.btn_report.pack(side='left', padx=px(8))
        ttk.Button(bar, text='Open ports folder', command=lambda: self.open(core.PORTS)).pack(side='left')
        self.btn_problem = ttk.Button(bar, text='Report a problem...', command=lambda: ReportDialog(self, self.last_result),
                                      state='disabled'); self.btn_problem.pack(side='left', padx=px(8))
        self.last_result = None
        self.prog2 = ttk.Progressbar(bar, mode='indeterminate', length=px(200)); self.prog2.pack(side='right')
        self.log2 = T.text(t, height=14, state='disabled'); self.log2.pack(fill='both', expand=True, padx=px(8), pady=px(4))
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
        mem = core.remembered_switches(cal)
        if mem:                                       # found by the pedal check in tab 1
            self.clutch_var.set(f'0x{mem["clutch"]:08X}'); self.brake_var.set(f'0x{mem["brake"]:08X}')
        if gb and not gb['manual']:
            self.drop_stock.show(f'{os.path.basename(p)} - calibration {cal}: AUTOMATIC ({gb["name"]}). '
                                 'The patches are for manual gearboxes only.', ok=False)
            return
        self.drop_stock.show(f'Your ROM: {os.path.basename(p)} - calibration {cal or "? (type it in)"}'
                             + (f', {gb["name"]}' if gb else ', gearbox not recognised') + ('  (already supported)' if A else ''),
                             ok=bool(gb))

    @staticmethod
    def open(path):
        """open a folder in Explorer, or a file with its usual program. Folders go straight to explorer.exe: on some PCs
        another program sets Windows' default folder action to 'none', and os.startfile then silently does nothing."""
        import subprocess
        if not path or not os.path.exists(path):
            messagebox.showinfo(APP, f'Nothing to open yet:\n{path or "(no file)"}'); return
        path = os.path.normpath(path)
        try:
            if os.path.isdir(path):
                subprocess.Popen(['explorer', path])
            else:
                try:
                    os.startfile(path)
                except OSError:                                   # no program set for this file type
                    subprocess.Popen(['notepad', path])
        except Exception as e:
            messagebox.showerror(APP, f'Could not open:\n{path}\n\n{e}')

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
        self.last_result = r
        problem = core.needs_report(r)
        self.btn_problem.config(state='normal' if problem else 'disabled')
        if not r.get('report'):
            self.log_to(self.log2, f'STOPPED: {r["error"]}\nNothing was written.')
            ReportDialog(self, r); return
        if problem:
            self.log_to(self.log2, 'Not everything was built - "Report a problem..." makes a report you can send to the project.')
        self.last_report = r['report']; self.btn_report.config(state='normal')
        for w in r['warnings']: self.log_to(self.log2, ' ! ' + w)
        self.log_to(self.log2, ('DONE - emulators ALL PASS. ' if r['ok'] else 'EMULATOR FAILURES - do not use. ') + f'Saved in {r["out"]}')
        if problem:
            self.wait_window(ReportDialog(self, r))
        if r['ok']:
            cal = r['A']['cal']
            go = messagebox.askyesno(APP, f'Ported to {cal} - the patches for {cal} are ready.\n\n'
                                          f'Next: go to tab 2 "Patch my ECU file" and drop your {cal} ECU file again. The patches '
                                          f'will be applied to it automatically, tested, and you\'ll be asked where to save the patched copy.\n\n'
                                          'Read the report, and check the clutch / brake addresses on the car (tab 1) before relying on them.\n\n'
                                          'Go to tab 2 now?')
            if go:
                self.auto_patch_cal = cal
                self.nb.select(self.t1)
                self.drop1.show(f'Drop your {cal} ECU file here (or click to browse) - the patches will be applied automatically')

    # ------------------------------------------------------------------ tab 1: check my car (guided)
    def build_tab3(self):
        t = self.t3
        ttk.Label(t, text='Start here: this finds the RAM bytes your ECU uses for the clutch and brake switches, which the patches '
                          'need. Connect with a J2534 interface (OBDX, Tactrix OpenPort, ...). This app only READS from the ECU - '
                          'it never writes or flashes.', wraplength=px(860)).pack(anchor='w', **PAD)
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
        # live
        h = ttk.LabelFrame(t, text='Live values'); h.pack(fill='x', padx=px(8), pady=px(6))
        self.live_var = tk.BooleanVar()
        self.live_chk = ttk.Checkbutton(h, text='Show live values', variable=self.live_var, command=self.toggle_live, state='disabled')
        self.live_chk.grid(row=0, column=0, sticky='w', **PAD)
        self.live_lbls = {}
        for i, k in enumerate(('RPM', 'Speed km/h', 'Pedal %', 'Clutch', 'Brake')):
            ttk.Label(h, text=k).grid(row=1, column=i, **PAD)
            self.live_lbls[k] = ttk.Label(h, text='-', style='Big.TLabel'); self.live_lbls[k].grid(row=2, column=i, **PAD)
        self.log3 = T.text(t, height=9, state='disabled'); self.log3.pack(fill='both', expand=True, padx=px(8), pady=px(4))
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
                        f'{self.ecu_cal} is not supported yet, so the patches need porting first: go to tab 3. The addresses '
                        'are already filled in there.')
                self.guide_target = self.t2; self.guide_next.config(text='Go to tab 3')
            self.guide_next.pack(side='right', padx=px(8), pady=px(8))
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
        self.conn_lbl.config(text=f'Connected ({v}). ECU calibration: {cal}' + ('' if self.A3 else ' - not supported yet (port it in tab 3)'))
        self.btn_conn.config(text='Disconnect'); self._enable3(True)
        self.snaps = {}; self.found = {}; self.found_lbl.config(text='')
        for k, b in self.snap_btns.items(): b.config(text=b['text'].split('  ')[0])
        self.guide_next_capture()

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
        self.cal_var.set(self.ecu_cal); self.clutch_var.set(f'0x{c:08X}'); self.brake_var.set(f'0x{b:08X}')   # tab 3 (port)
        self.log_to(self.log3, f'Remembered for {self.ecu_cal}: clutch 0x{c:08X}, brake 0x{b:08X}.')
        if self.rom_path and self.A and self.A['cal'].upper() == self.ecu_cal.upper():
            self.load_rom(self.rom_path)                             # the file already in tab 2 picks them up
        self.guide('done')

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
                for k, v in vals.items(): self.ui(self.live_lbls[k].config, {'text': v})
            except Exception as e:
                self.ui(self.log_to, self.log3, f'Live read failed: {e}'); self.live_on = False
                self.ui(self.live_var.set, False); break
            threading.Event().wait(0.25)


if __name__ == '__main__':
    App().mainloop()

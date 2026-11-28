"""Tab 3: table editor for the ECU file loaded in tab 2, using the NC Flash / EcuFlash definition on the user's PC.

Navigator: search, Favourites, Frequently accessed, Differs from compare, then the categories; every table has a tick box
(select) and a star (favourite). Grid: drawn cells (high contrast), click / drag / Shift-click / Ctrl-click selection, then
set, add or multiply the selection. Compare: load a second file of the same calibration; values that differ are red, and
ticked tables can be copied across from it. Edits change the same in-memory file tab 2 patches. Only changed cells are
written; the original file is never overwritten; nothing is written to the ECU."""
import os, struct
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import core, defs, descriptions

FAV, FREQ, DIFFG = '★ Favourites', 'Frequently accessed', 'Differs from compare'


def _close(a, b):
    return a == b or (a == a and b == b and abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b)))


class EditorTab:
    def __init__(self, app, frame, px, PAD, T):
        self.app, self.px, self.T = app, px, T
        self.D = None; self.base = None; self.cmp = None; self.cmp_name = ''
        self.table = None; self.items = {}; self.ticked = set(); self.diff_tables = set(); self.edited = set()
        self.sel = set(); self.anchor = None; self.edit = None
        # ---- top bar
        bar = ttk.Frame(frame); bar.pack(fill='x', padx=px(8), pady=(px(6), px(2)))
        ttk.Button(bar, text='Load definition...', command=self.browse_def).pack(side='left')
        ttk.Button(bar, text='Compare with...', command=self.load_compare).pack(side='left', padx=px(6))
        self.cmp_lbl = ttk.Label(bar, text='', style='Hint.TLabel'); self.cmp_lbl.pack(side='left')
        self.btn_cmp_clear = ttk.Button(bar, text='Close compare', command=self.close_compare)
        self.btn_save = ttk.Button(bar, text='Save edited file...', command=self.save, state='disabled', style='Accent.TButton')
        self.btn_save.pack(side='right')
        self.info = ttk.Label(frame, text='Load an ECU file in tab 2 first.', style='Hint.TLabel', wraplength=px(880))
        self.info.pack(fill='x', padx=px(8))
        pw = ttk.PanedWindow(frame, orient='horizontal'); pw.pack(fill='both', expand=True, padx=px(8), pady=px(6))
        left = ttk.Frame(pw); right = ttk.Frame(pw); pw.add(left, weight=2); pw.add(right, weight=5)
        # ---- navigator
        self.q = tk.StringVar(); self.q.trace_add('write', lambda *_: self.fill_tree())
        se = ttk.Entry(left, textvariable=self.q); se.pack(fill='x', pady=(0, px(4)))
        se.insert(0, ''); self._ph(se)
        tf = ttk.Frame(left); tf.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(tf, columns=('fav', 'sel'), selectmode='browse')
        self.tree.heading('#0', text='Name', anchor='w'); self.tree.heading('fav', text='★'); self.tree.heading('sel', text='✓')
        self.tree.column('#0', width=px(250), stretch=True); self.tree.column('fav', width=px(28), anchor='center', stretch=False)
        self.tree.column('sel', width=px(28), anchor='center', stretch=False)
        sb = ttk.Scrollbar(tf, orient='vertical', command=self.tree.yview); self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True); sb.pack(side='right', fill='y')
        self.tree.tag_configure('group', foreground=T.TEXT2, font=('Segoe UI Semibold', 10))
        self.tree.tag_configure('special', foreground=T.ACCENT, font=('Segoe UI Semibold', 10))
        self.tree.tag_configure('diff', foreground=T.DIFF); self.tree.tag_configure('edited', foreground=T.EDITED)
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.show_selected())
        self.tree.bind('<Button-1>', self.tree_click, add='+')
        nb = ttk.Frame(left); nb.pack(fill='x', pady=(px(4), 0))
        self.btn_copy = ttk.Button(nb, text='Copy ticked from compare', command=self.copy_ticked, state='disabled')
        self.btn_copy.pack(side='left')
        ttk.Button(nb, text='Clear ticks', command=self.clear_ticks).pack(side='left', padx=px(6))
        # ---- table view
        self.title = ttk.Label(right, text='', font=('Segoe UI Semibold', 11)); self.title.pack(anchor='w')
        self.sub = ttk.Label(right, text='', style='Hint.TLabel', wraplength=px(640)); self.sub.pack(anchor='w')
        tb = ttk.Frame(right); tb.pack(fill='x', pady=px(4))
        self.opv = tk.StringVar()
        for txt, op in (('+', 'add'), ('−', 'sub'), ('×', 'mul'), ('%', 'pct'), ('=', 'set')):
            ttk.Button(tb, text=txt, width=3, command=lambda op=op: self.apply_op(op)).pack(side='left', padx=(0, px(3)))
        ttk.Entry(tb, textvariable=self.opv, width=10).pack(side='left', padx=(px(4), 0))
        self.heat = tk.BooleanVar(value=True)
        ttk.Checkbutton(tb, text='Heat map', variable=self.heat, command=lambda: self.draw()).pack(side='left', padx=px(10))
        ttk.Button(tb, text='Revert table', command=self.revert_table).pack(side='left', padx=(px(12), 0))
        self.view = tk.StringVar(value='This file')
        self.view_box = ttk.Combobox(tb, textvariable=self.view, state='readonly', width=14, values=('This file',))
        self.view_box.pack(side='right'); self.view_box.bind('<<ComboboxSelected>>', lambda e: self.draw())
        ttk.Label(tb, text='Show', style='Hint.TLabel').pack(side='right', padx=px(4))
        gf = ttk.Frame(right); gf.pack(fill='both', expand=True)
        self.cv = tk.Canvas(gf, bg=T.GRID_BG, highlightthickness=1, highlightbackground=T.BORDER, takefocus=1)
        gx = ttk.Scrollbar(gf, orient='horizontal', command=self.cv.xview); gy = ttk.Scrollbar(gf, orient='vertical', command=self.cv.yview)
        self.cv.configure(xscrollcommand=gx.set, yscrollcommand=gy.set)
        self.cv.grid(row=0, column=0, sticky='nsew'); gy.grid(row=0, column=1, sticky='ns'); gx.grid(row=1, column=0, sticky='ew')
        gf.rowconfigure(0, weight=1); gf.columnconfigure(0, weight=1)
        for ev, fn in (('<Button-1>', self.click), ('<B1-Motion>', self.drag), ('<Shift-Button-1>', self.shift_click),
                       ('<Control-Button-1>', self.ctrl_click), ('<Double-1>', self.start_edit), ('<Key>', self.key),
                       ('<Control-a>', self.select_all)):
            self.cv.bind(ev, fn)
        self.cv.bind('<MouseWheel>', lambda e: self.cv.yview_scroll(-1 if e.delta > 0 else 1, 'units'))
        self.status = ttk.Label(right, text='', style='Hint.TLabel'); self.status.pack(anchor='w', pady=(px(4), 0))
        ttk.Label(right, text='Click, drag, Shift- or Ctrl-click to select cells; type a number or double-click to change them '
                              '(Enter = keep, Esc = cancel), or type a number in the box and use + − × % =. Red cell = differs '
                              'from the compare file; amber border = changed since the file was loaded. Click a category to see '
                              'its single values in a list.', style='Hint.TLabel', wraplength=px(640)).pack(anchor='w')
        self.cat_tables = None

    @staticmethod
    def _ph(entry):
        """placeholder text in the search box"""
        ph = 'Search...'
        def show(_=None):
            if not entry.get(): entry.insert(0, ph); entry.configure(foreground='#9C9A92')
        def hide(_=None):
            if entry.get() == ph: entry.delete(0, 'end'); entry.configure(foreground='')
        entry.bind('<FocusIn>', hide); entry.bind('<FocusOut>', show); show()

    def query(self):
        q = self.q.get().strip().lower()
        return '' if q == 'search...' else q

    # ---- remembered per calibration: favourites, usage counts
    def _store(self):
        s = core.settings(); e = s.setdefault('editor', {}); return s, e

    def favs(self):
        cal = self.app.A['cal'] if self.app.A else ''
        return set((core.settings().get('editor') or {}).get('favs', {}).get(cal, []))

    def usage(self):
        cal = self.app.A['cal'] if self.app.A else ''
        return (core.settings().get('editor') or {}).get('usage', {}).get(cal, {})

    def toggle_fav(self, name):
        s, e = self._store(); cal = self.app.A['cal']
        f = set(e.setdefault('favs', {}).get(cal, []))
        f.symmetric_difference_update({name}); e['favs'][cal] = sorted(f); core.save_settings(s)

    def notes(self):
        return (core.settings().get('editor') or {}).get('notes', {})

    def set_note(self, name, text):
        s, e = self._store(); n = e.setdefault('notes', {})
        if text.strip(): n[name] = text.strip()
        else: n.pop(name, None)
        core.save_settings(s)

    def edit_note(self, r):
        tb = self.cat_tables[r]; self.cancel_edit()
        x = self.desc_x0 - self.cv.canvasx(0); y = self.y0 + r * self.cell_h - self.cv.canvasy(0)
        v = tk.StringVar(value=self.notes().get(tb.name) or descriptions.PATCH.get(tb.name, ''))
        e = ttk.Entry(self.cv, textvariable=v); e.place(x=x, y=y, width=self.px(760), height=self.cell_h); e.focus_set(); e.icursor('end')
        def done(_=None):
            self.set_note(tb.name, v.get()); self.cancel_edit(); self.draw(); self.cv.focus_set()
        e.bind('<Return>', done); e.bind('<KP_Enter>', done)
        e.bind('<Escape>', lambda _: (self.cancel_edit(), self.cv.focus_set())); e.bind('<FocusOut>', lambda _: self.cancel_edit())
        self.edit = e

    def count_use(self, name):
        s, e = self._store(); u = e.setdefault('usage', {}).setdefault(self.app.A['cal'], {})
        u[name] = u.get(name, 0) + 1; core.save_settings(s)

    # ---- definitions and files
    def rom_loaded(self):
        """tab 2 loaded a file: pick up NC Flash's definition for its calibration automatically"""
        self.edited.clear(); self.ticked.clear(); self.btn_save.config(state='disabled'); self.close_compare(redraw=False)
        self.table = None; self.cat_tables = None; self.draw()
        A = self.app.A
        self.base = bytes(self.app.rom) if self.app.rom else None
        if not self.app.rom or not A:
            self.D = None; self.fill_tree(); self.info.config(text='Load an ECU file NC Patcher recognises in tab 2 first.'); return
        p = core.ncflash_definition(A['cal'])
        if p: self.load_def(p)
        else:
            self.D = None; self.fill_tree()
            self.info.config(text=f'No NC Flash definition for {A["cal"]} found in %APPDATA%\\NCFlash\\metadata. '
                                  'Click "Load definition..." to choose an NC Flash or EcuFlash definition file.')

    def browse_def(self):
        if not self.app.rom: messagebox.showinfo('NC Patcher', 'Load an ECU file in tab 2 first.'); return
        p = filedialog.askopenfilename(title='NC Flash / EcuFlash definition', filetypes=[('Definition', '*.xml')])
        if p: self.load_def(p)

    def load_def(self, path):
        try:
            self.D = defs.Definition(path, self.app.A['cal'] if self.app.A else '')
        except Exception as e:
            self.D = None; self.fill_tree(); self.info.config(text=f'Could not read {os.path.basename(path)}: {e}'); return
        self.info.config(text=f'{len(self.D.tables)} tables from {os.path.basename(path)}'
                              + (f' ({len(self.D.bad)} skipped)' if self.D.bad else '')
                              + '. Edits apply to the file in tab 2 (its "Save patched file" includes them).')
        self.find_diffs(); self.fill_tree()

    def load_compare(self):
        if not self.app.rom or not self.D: messagebox.showinfo('NC Patcher', 'Load an ECU file in tab 2 first.'); return
        p = filedialog.askopenfilename(title='Compare with another ECU file', filetypes=[('ECU files', '*.bin'), ('All files', '*.*')])
        if not p: return
        try:
            rom = core.read_rom(p)
        except (OSError, ValueError) as e:
            messagebox.showerror('NC Patcher', str(e)); return
        A = self.app.A
        if not core.AD.is_cal(rom, A):
            messagebox.showerror('NC Patcher', f'{os.path.basename(p)} is not a {A["cal"]} file. Only files of the same calibration '
                                               'can be compared (their tables are at the same addresses).'); return
        self.cmp, self.cmp_name = bytes(rom), os.path.basename(p); self.app.saved_paths.append(p)
        self.cmp_lbl.config(text=f'Comparing with {self.cmp_name}'); self.btn_cmp_clear.pack(side='left', padx=self.px(6))
        self.btn_copy.config(state='normal'); self.view_box.config(values=('This file', 'Compare file', 'Difference'))
        self.find_diffs(); self.fill_tree(); self.draw()
        self.info.config(text=f'{len(self.diff_tables)} tables differ from {self.cmp_name} (red).')

    def close_compare(self, redraw=True):
        self.cmp = None; self.cmp_name = ''; self.diff_tables = set(); self.cmp_lbl.config(text='')
        self.btn_cmp_clear.pack_forget(); self.btn_copy.config(state='disabled')
        self.view.set('This file'); self.view_box.config(values=('This file',))
        if redraw: self.fill_tree(); self.draw()

    def spans(self, t):
        out = [t.span()]
        for a in (t.x, t.y):
            if a: out.append(a.span())
        return out

    def find_diffs(self):
        self.diff_tables = set()
        if not (self.D and self.cmp): return
        rom = self.app.rom
        for t in self.D.tables:
            if any(rom[s:e] != self.cmp[s:e] for s, e in self.spans(t)): self.diff_tables.add(t.name)

    # ---- navigator
    def fill_tree(self):
        if not hasattr(self, 'tree'): return            # the search placeholder fires before the navigator exists
        open_ = {self.tree.item(i, 'text') for i in self.tree.get_children() if self.tree.item(i, 'open')}
        self.tree.delete(*self.tree.get_children()); self.items = {}
        if not self.D: return
        q = self.query(); favs = self.favs(); use = self.usage()
        byname = {t.name: t for t in self.D.tables}
        match = lambda t: not q or q in t.name.lower() or q in (t.category or '').lower()
        def group(title, tables, tag='group', force_open=False):
            ts = [t for t in tables if match(t)]
            if not ts: return
            g = self.tree.insert('', 'end', text=title, open=bool(q) or force_open or title in open_, tags=(tag,))
            for t in ts:
                tags = ('diff',) if t.name in self.diff_tables else ('edited',) if t.name in self.edited else ()
                i = self.tree.insert(g, 'end', text=t.name, values=('★' if t.name in favs else '☆', '☑' if t.name in self.ticked else '☐'),
                                     tags=tags)
                self.items[i] = t
        group(FAV, [byname[n] for n in sorted(favs) if n in byname], 'special', force_open=True)
        group(FREQ, [byname[n] for n, c in sorted(use.items(), key=lambda kv: -kv[1])[:15] if n in byname], 'special')
        if self.cmp: group(DIFFG, sorted((byname[n] for n in self.diff_tables), key=lambda t: t.name), 'special', force_open=True)
        for cat in sorted(self.D.categories):
            group(cat, sorted(self.D.categories[cat], key=lambda t: t.name))

    def tree_click(self, ev):
        col, row = self.tree.identify_column(ev.x), self.tree.identify_row(ev.y)
        if row not in self.items or col not in ('#1', '#2'): return
        t = self.items[row]
        if col == '#1': self.toggle_fav(t.name)
        else: self.ticked.symmetric_difference_update({t.name})
        y = self.tree.yview()[0]; self.fill_tree(); self.tree.yview_moveto(y)
        return 'break'

    def clear_ticks(self):
        self.ticked.clear(); self.fill_tree()

    def show_selected(self):
        sel = self.tree.selection()
        if not sel: return
        if sel[0] in self.items:
            t = self.items[sel[0]]
            if t is not self.table: self.count_use(t.name)
            self.cat_tables = None; self.show(t)
        else:                                    # a category: its single values as a list (Name | Value | Compare)
            kids = [self.items[i] for i in self.tree.get_children(sel[0]) if i in self.items]
            self.cancel_edit(); self.table = None; self.sel = set(); self.anchor = None
            self.cat_title = self.tree.item(sel[0], 'text')
            self.cat_tables = [t for t in kids if t.elements == 1 and t.type == '1D']
            self.draw()

    def copy_ticked(self):
        if not self.cmp: return
        names = [n for n in self.ticked if n in {t.name for t in self.D.tables}]
        if not names: messagebox.showinfo('NC Patcher', 'Tick the tables to copy (the ✓ column).'); return
        if not messagebox.askyesno('NC Patcher', f'Copy {len(names)} table(s) (values and axes) from {self.cmp_name} into this file?'):
            return
        for t in self.D.tables:
            if t.name in names:
                for s, e in self.spans(t): self.app.rom[s:e] = self.cmp[s:e]
                self.mark_edited(t)
        self.find_diffs(); self.fill_tree(); self.draw()
        self.app.log_to(self.app.log1, f'Copied {len(names)} table(s) from {self.cmp_name}: ' + ', '.join(sorted(names))[:300])

    # ---- the grid: one model for a table (rows x columns) and for a category list (one value per table)
    def show(self, t):
        self.cancel_edit(); self.table = t; self.sel = set(); self.anchor = None
        self.draw(); self.cv.focus_set()

    def data(self, rom, t=None):
        try:
            return (t or self.table).grid(rom)
        except Exception:
            return None

    def model(self):
        """-> dict(rows, cmp, base, xs, ys, scal(r) -> scaling, write(r, c, v), label(r)) or None"""
        rom = self.app.rom
        if self.table:
            t = self.table; cur = self.data(rom)
            if not cur: return None
            cmp = self.data(self.cmp) if self.cmp else None; base = self.data(self.base) if self.base else None
            nx, ny = (len(cur[0]) if cur[0] else None), (len(cur[1]) if cur[1] else None)
            return dict(rows=cur[2], cmp=cmp[2] if cmp else None, base=base[2] if base else None, xs=cur[0], ys=cur[1],
                        scal=lambda r: t.scaling, tables=lambda r: [t],
                        write=lambda r, c, v: t.write_index(rom, t.cell_index(r, c, nx, ny), v))
        if self.cat_tables:
            ts = self.cat_tables; v1 = lambda b, t: t.read_list(b)[0]
            return dict(rows=[[v1(rom, t)] for t in ts], cmp=[[v1(self.cmp, t)] for t in ts] if self.cmp else None,
                        base=[[v1(self.base, t)] for t in ts] if self.base else None, xs=None, ys=None, names=[t.name for t in ts],
                        scal=lambda r: ts[r].scaling, tables=lambda r: [ts[r]], write=lambda r, c, v: ts[r].write_index(rom, 0, v))
        return None

    def mark_edited(self, t):
        self.edited.add(t.name); self.btn_save.config(state='normal')

    @staticmethod
    def heat_color(n):
        """0..1 -> green .. yellow .. orange (like PCMtec's grid; red is kept for "differs from the compare file")"""
        n = max(0.0, min(1.0, n))
        r, g = (int(60 + 380 * n), 225) if n < 0.5 else (250, int(225 - 140 * (n - 0.5) * 2 / 2))
        return f'#{min(255, r):02X}{max(0, min(255, g)):02X}{70:02X}'

    def draw(self):
        cv, T, px = self.cv, self.T, self.px
        cv.delete('all'); self.title.config(text=''); self.sub.config(text=''); self.status.config(text='')
        m = self.model() if self.app.rom else None
        if not m:
            if self.table: self.title.config(text=self.table.name); self.sub.config(text='Cannot show this table.')
            elif self.cat_tables is not None:
                self.title.config(text=self.cat_title); self.sub.config(text='No single-value tables in this group: pick a table.')
            return
        rows, cmp, base, xs, ys = m['rows'], m['cmp'], m['base'], m['xs'], m['ys']
        view = self.view.get(); listing = 'names' in m
        self.shape = (len(rows), len(rows[0]))
        W, H = px(70), px(24)
        TITLE = px(20) if (xs or ys) else 0                     # axis titles (top / rotated on the left)
        AX = px(400) if listing else (px(78) if ys else px(36))
        x0, y0 = AX + (TITLE if ys else 0), TITLE + H
        if not xs: W = px(90) if listing else px(110)
        bold, font = ('Consolas', 10, 'bold'), ('Consolas', 10)
        nums = [v for row in rows for v in row if v == v]
        lo, hi = (min(nums), max(nums)) if nums else (0, 1)
        t = self.table
        if xs: cv.create_text(x0 + W * len(xs) / 2, TITLE / 2, text=t.x.scaling.units or t.x.name, fill=T.TEXT, font=('Segoe UI Semibold', 10))
        if ys: cv.create_text(TITLE / 2, y0 + H * len(rows) / 2, text=t.y.scaling.units or t.y.name, fill=T.TEXT, angle=90, font=('Segoe UI Semibold', 10))
        # header row
        hx = x0 - AX
        cv.create_rectangle(hx, y0 - H, x0, y0, fill=T.GRID_HEAD, outline=T.BORDER)
        if listing: cv.create_text(hx + px(6), y0 - H / 2, text='Name', anchor='w', fill=T.TEXT2, font=bold)
        heads = [t.x.scaling.show(v) for v in xs] if xs else (['Value'] if listing else [(t.scaling.units or 'value')])
        if listing: heads += ['Original'] + (['Compare'] if cmp else [])      # PCMtec-style list columns (+ Units, Description)
        DESC_W, UW = (px(760), px(150)) if listing else (0, 0)
        for c, h in enumerate(heads):
            cv.create_rectangle(x0 + c * W, y0 - H, x0 + (c + 1) * W, y0, fill=T.GRID_HEAD, outline=T.BORDER)
            cv.create_text(x0 + (c + 1) * W - px(6), y0 - H / 2, text=h, anchor='e', fill=T.TEXT2, font=bold)
        if listing:
            ux = x0 + W * len(heads); self.desc_x0 = ux + UW
            cv.create_rectangle(ux, y0 - H, ux + UW, y0, fill=T.GRID_HEAD, outline=T.BORDER)
            cv.create_text(ux + px(6), y0 - H / 2, text='Units', anchor='w', fill=T.TEXT2, font=bold)
            cv.create_rectangle(self.desc_x0, y0 - H, self.desc_x0 + DESC_W, y0, fill=T.GRID_HEAD, outline=T.BORDER)
            cv.create_text(self.desc_x0 + px(6), y0 - H / 2, text='Description  (double-click to write your own)', anchor='w',
                           fill=T.TEXT2, font=bold)
            notes = self.notes()
        for r, row in enumerate(rows):
            yy = y0 + r * H; sc = m['scal'](r)
            cv.create_rectangle(hx, yy, x0, yy + H, fill=T.GRID_HEAD, outline=T.BORDER)
            lab = m['names'][r] if listing else (t.y.scaling.show(ys[r]) if ys else str(r))
            if listing:
                lab = lab.replace(' (custom patch)', ' *')
                if len(lab) > 52: lab = lab[:50] + '...'
            cv.create_text((hx + px(6)) if listing else (x0 - px(6)), yy + H / 2, text=lab, anchor='w' if listing else 'e',
                           fill=T.TEXT if listing else T.TEXT2, font=('Segoe UI', 10) if listing else bold)
            for c, v in enumerate(row):
                xx = x0 + c * W; sel = (r, c) in self.sel
                cvv = cmp[r][c] if cmp else None
                differs = cvv is not None and not _close(v, cvv)
                edited = base is not None and not _close(v, base[r][c])
                if differs: fill, fg = T.DIFF, '#FFFFFF'
                elif self.heat.get() and not listing and hi > lo: fill, fg = self.heat_color((v - lo) / (hi - lo)), '#111111'
                else: fill, fg = (T.GRID_ALT if r % 2 else T.GRID_BG), T.TEXT
                cv.create_rectangle(xx, yy, xx + W, yy + H, fill=fill, outline=T.BORDER)
                shown = v if view == 'This file' or cvv is None else (cvv if view == 'Compare file' else v - cvv)
                txt = sc.show(shown) if view != 'Difference' or cvv is None else (f'{shown:+.4g}' if differs else '0')
                cv.create_text(xx + W - px(6), yy + H / 2, text=txt, anchor='e', fill=fg, font=bold if differs or edited else font)
                if edited and listing:                         # changed from the original: red diamond, like PCMtec
                    cv.create_text(xx + px(10), yy + H / 2, text='◆', fill=T.DIFF if not differs else '#FFFFFF', font=('Segoe UI', 9))
                elif edited: cv.create_rectangle(xx + 2, yy + 2, xx + W - 2, yy + H - 2, outline=T.EDITED, width=2)
                if sel: cv.create_rectangle(xx + 1, yy + 1, xx + W - 1, yy + H - 1, outline='#FFFFFF', width=2)
            if listing:                                        # Original | (Compare) | Units | Description (read-only)
                tb = self.cat_tables[r]; xx = x0 + W
                extra = [(sc.show(base[r][0]) if base else '', T.TEXT2)]
                if cmp: extra.append((sc.show(cmp[r][0]), T.DIFF if not _close(row[0], cmp[r][0]) else T.TEXT2))
                for txt, col in extra:
                    cv.create_rectangle(xx, yy, xx + W, yy + H, fill=T.GRID_HEAD, outline=T.BORDER)
                    cv.create_text(xx + W - px(6), yy + H / 2, text=txt[:11], anchor='e', fill=col, font=font)
                    xx += W
                u = sc.units or ''
                cv.create_rectangle(xx, yy, xx + UW, yy + H, fill=T.GRID_HEAD, outline=T.BORDER)
                cv.create_text(xx + px(6), yy + H / 2, text=u if len(u) <= 20 else u[:19] + '...', anchor='w', fill=T.TEXT2, font=('Segoe UI', 9))
                xx += UW
                d = descriptions.for_table(tb, notes); own = tb.name in notes
                cv.create_rectangle(xx, yy, xx + DESC_W, yy + H, fill=T.GRID_ALT if r % 2 else T.GRID_BG, outline=T.BORDER)
                cv.create_text(xx + px(6), yy + H / 2, text=d if len(d) < 105 else d[:102] + '...', anchor='w',
                               fill=T.TEXT if (own or tb.name in descriptions.PATCH) else T.MUTED, font=('Segoe UI', 9))
        cv.configure(scrollregion=(0, 0, x0 + W * len(heads) + UW + DESC_W + 2, y0 + H * len(rows) + 2))
        self.cell_w, self.cell_h, self.x0, self.y0 = W, H, x0, y0
        if listing:
            self.title.config(text=self.cat_title); self.sub.config(text=f'{len(rows)} single values  (* = added by NC Patcher\'s patches)')
        else:
            s = t.scaling; rng = f'range {s.min:g} to {s.max:g}' if s.min is not None and s.max is not None else ''
            self.title.config(text=t.name + (' (edited)' if t.name in self.edited else ''))
            self.sub.config(text=f'{t.category}  |  {s.units}  {rng}  |  0x{t.address:05X}, {t.type}')
        self.update_status(m)

    def update_status(self, m=None):
        m = m or self.model()
        if not m or not self.sel: self.status.config(text=''); return
        r, c = sorted(self.sel)[0]; s = m['scal'](r)
        txt = f'{len(self.sel)} cell(s) selected  |  ' + (f'{m["names"][r]}: ' if 'names' in m else f'row {r + 1}, column {c + 1}: ') + s.show(m['rows'][r][c])
        if m['cmp']: txt += f'  |  compare: {s.show(m["cmp"][r][c])}'
        if m['base'] and not _close(m['base'][r][c], m['rows'][r][c]): txt += f'  |  as loaded: {s.show(m["base"][r][c])}'
        if 'names' in m: txt += '\n' + descriptions.for_table(self.cat_tables[r], self.notes())
        self.status.config(text=txt)

    def cell_at(self, ev):
        x, y = self.cv.canvasx(ev.x), self.cv.canvasy(ev.y)
        if not (self.table or self.cat_tables) or x < self.x0 or y < self.y0: return None
        r, c = int((y - self.y0) // self.cell_h), int((x - self.x0) // self.cell_w)
        return (r, c) if 0 <= r < self.shape[0] and 0 <= c < self.shape[1] else None

    def rect(self, a, b):
        return {(r, c) for r in range(min(a[0], b[0]), max(a[0], b[0]) + 1) for c in range(min(a[1], b[1]), max(a[1], b[1]) + 1)}

    def click(self, ev):
        self.cv.focus_set(); cell = self.cell_at(ev); self.cancel_edit()
        if cell: self.anchor = cell; self.sel = {cell}; self.draw()

    def drag(self, ev):
        cell = self.cell_at(ev)
        if cell and self.anchor: self.sel = self.rect(self.anchor, cell); self.draw()

    def shift_click(self, ev):
        cell = self.cell_at(ev)
        if cell and self.anchor: self.sel = self.rect(self.anchor, cell); self.draw()
        return 'break'

    def ctrl_click(self, ev):
        cell = self.cell_at(ev)
        if cell: self.sel.symmetric_difference_update({cell}); self.anchor = cell; self.draw()
        return 'break'

    def select_all(self, ev=None):
        if self.table or self.cat_tables: self.sel = self.rect((0, 0), (self.shape[0] - 1, self.shape[1] - 1)); self.draw()
        return 'break'

    def key(self, ev):
        if not (self.table or self.cat_tables): return
        moves = {'Up': (-1, 0), 'Down': (1, 0), 'Left': (0, -1), 'Right': (0, 1)}
        if ev.keysym in moves and self.anchor:
            r = min(self.shape[0] - 1, max(0, self.anchor[0] + moves[ev.keysym][0]))
            c = min(self.shape[1] - 1, max(0, self.anchor[1] + moves[ev.keysym][1]))
            self.anchor = (r, c); self.sel = {(r, c)}; self.draw(); return 'break'
        if self.sel and (ev.char.isdigit() or ev.char in '-.'):
            self.start_edit(None, first=ev.char); return 'break'

    def start_edit(self, ev, first=None):
        if ev is not None and self.cat_tables and not self.table and self.cv.canvasx(ev.x) >= getattr(self, 'desc_x0', 1e9):
            r = int((self.cv.canvasy(ev.y) - self.y0) // self.cell_h)
            if 0 <= r < len(self.cat_tables): self.edit_note(r)
            return
        if ev is not None:
            cell = self.cell_at(ev)
            if not cell: return
            if cell not in self.sel: self.sel = {cell}; self.anchor = cell; self.draw()
        if not self.sel: return
        m = self.model(); r, c = self.anchor if self.anchor in self.sel else sorted(self.sel)[0]
        self.cancel_edit()
        x = self.x0 + c * self.cell_w - self.cv.canvasx(0); y = self.y0 + r * self.cell_h - self.cv.canvasy(0)
        v = tk.StringVar(value=first if first is not None else m['scal'](r).show(m['rows'][r][c]))
        e = ttk.Entry(self.cv, textvariable=v, justify='right', font=('Consolas', 10))
        e.place(x=x, y=y, width=self.cell_w, height=self.cell_h); e.focus_set()
        if first is None: e.select_range(0, 'end')
        else: e.icursor('end')
        e.bind('<Return>', lambda _: self.commit(v.get(), 'set')); e.bind('<KP_Enter>', lambda _: self.commit(v.get(), 'set'))
        e.bind('<Escape>', lambda _: (self.cancel_edit(), self.cv.focus_set())); e.bind('<FocusOut>', lambda _: self.cancel_edit())
        self.edit = e

    def cancel_edit(self):
        if self.edit: self.edit.destroy(); self.edit = None

    def apply_op(self, op):
        if not (self.table or self.cat_tables) or not self.sel: messagebox.showinfo('NC Patcher', 'Select some cells first.'); return
        self.commit(self.opv.get(), op)

    def commit(self, text, op):
        try:
            k = float(text)
        except ValueError:
            messagebox.showerror('NC Patcher', f'"{text}" is not a number.'); return
        m = self.model(); rows = m['rows']
        f = {'set': lambda v: k, 'add': lambda v: v + k, 'sub': lambda v: v - k, 'mul': lambda v: v * k,
             'pct': lambda v: v * (1 + k / 100)}[op]
        new = {cell: f(rows[cell[0]][cell[1]]) for cell in self.sel}
        out = [(cell, v) for cell, v in new.items() if (m['scal'](cell[0]).min is not None and v < m['scal'](cell[0]).min)
               or (m['scal'](cell[0]).max is not None and v > m['scal'](cell[0]).max)]
        if out:
            s0 = m['scal'](out[0][0][0])
            if not messagebox.askyesno('NC Patcher', f'{len(out)} value(s) would be outside the table\'s range '
                                                     f'({s0.min:g} to {s0.max:g}). Use them anyway?'):
                return
        for (r, c), v in new.items():
            m['write'](r, c, v)
            for tb in m['tables'](r): self.mark_edited(tb)
        self.cancel_edit()
        if self.cmp: self.find_diffs()
        self.fill_tree(); self.draw(); self.cv.focus_set()
        self.app.log_to(self.app.log1, f'Edited {self.table.name if self.table else self.cat_title}: {len(new)} cell(s), {op} {k:g}')

    def revert_table(self):
        ts = [self.table] if self.table else (self.cat_tables or [])
        if not ts or not self.base: return
        for t in ts:
            for s, e in self.spans(t): self.app.rom[s:e] = self.base[s:e]
            self.edited.discard(t.name)
        if self.cmp: self.find_diffs()
        self.fill_tree(); self.draw()

    def save(self):
        app = self.app
        stem, ext = os.path.splitext(app.rom_path)
        p = filedialog.asksaveasfilename(title='Save edited ECU file', initialfile=os.path.basename(stem) + ' - edited' + (ext or '.bin'),
                                         initialdir=os.path.dirname(app.rom_path), defaultextension='.bin', filetypes=[('ECU files', '*.bin')])
        if not p: return
        if os.path.abspath(p) == os.path.abspath(app.rom_path):
            messagebox.showerror('NC Patcher', 'Choose a new file name - the original is never overwritten.'); return
        open(p, 'wb').write(app.rom); app.saved_paths.append(p)
        messagebox.showinfo('NC Patcher', f'Saved:\n{p}\n\n{len(self.edited)} table(s) changed. Flash it with NC Flash '
                                          '(it recalculates the checksums).')

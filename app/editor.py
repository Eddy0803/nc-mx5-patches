"""Tab 3: edit tables in the ECU file loaded in tab 2, using the NC Flash / EcuFlash definition on the user's PC.
Edits change the same in-memory file tab 2 patches, so "Save patched file" includes them; "Save edited file" writes a copy.
Only the cells you change are written. The original file is never overwritten. Nothing is written to the ECU."""
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import core, defs


class EditorTab:
    def __init__(self, app, frame, px, PAD, T):
        self.app, self.px, self.T = app, px, T
        self.D = None; self.table = None; self.changed = set(); self.items = {}; self.edit = None
        bar = ttk.Frame(frame); bar.pack(fill='x', padx=px(8), pady=px(6))
        ttk.Button(bar, text='Load definition...', command=self.browse_def).pack(side='left')
        ttk.Label(bar, text='Search').pack(side='left', padx=(px(12), px(4)))
        self.q = tk.StringVar(); self.q.trace_add('write', lambda *_: self.fill_tree())
        ttk.Entry(bar, textvariable=self.q, width=28).pack(side='left')
        self.btn_save = ttk.Button(bar, text='Save edited file...', command=self.save, state='disabled', style='Accent.TButton')
        self.btn_save.pack(side='right')
        self.info = ttk.Label(frame, text='Load an ECU file in tab 2 first.', style='Hint.TLabel', wraplength=px(880))
        self.info.pack(fill='x', padx=px(8))
        pw = ttk.PanedWindow(frame, orient='horizontal'); pw.pack(fill='both', expand=True, padx=px(8), pady=px(6))
        left = ttk.Frame(pw); right = ttk.Frame(pw); pw.add(left, weight=1); pw.add(right, weight=3)
        self.tree = ttk.Treeview(left, show='tree', selectmode='browse')
        sb = ttk.Scrollbar(left, orient='vertical', command=self.tree.yview); self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True); sb.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.show_selected())
        self.title = ttk.Label(right, text='', font=('Segoe UI Semibold', 10)); self.title.pack(anchor='w')
        self.sub = ttk.Label(right, text='', style='Hint.TLabel', wraplength=px(600)); self.sub.pack(anchor='w')
        gf = ttk.Frame(right); gf.pack(fill='both', expand=True, pady=(px(4), 0))
        self.grid = ttk.Treeview(gf, show='headings', selectmode='none')
        gx = ttk.Scrollbar(gf, orient='horizontal', command=self.grid.xview); gy = ttk.Scrollbar(gf, orient='vertical', command=self.grid.yview)
        self.grid.configure(xscrollcommand=gx.set, yscrollcommand=gy.set)
        self.grid.grid(row=0, column=0, sticky='nsew'); gy.grid(row=0, column=1, sticky='ns'); gx.grid(row=1, column=0, sticky='ew')
        gf.rowconfigure(0, weight=1); gf.columnconfigure(0, weight=1)
        self.grid.bind('<Double-1>', self.start_edit)
        ttk.Label(right, text='Double-click a value to change it (Enter = keep, Esc = cancel). The axes are shown read-only. '
                              'The value shown after an edit is what is actually stored.', style='Hint.TLabel',
                  wraplength=px(600)).pack(anchor='w', pady=(px(4), 0))

    # ---- definitions
    def rom_loaded(self):
        """tab 2 loaded a file: pick up NC Flash's definition for its calibration automatically"""
        self.changed.clear(); self.btn_save.config(state='disabled'); self.clear_grid()
        A = self.app.A
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
                              + (f' ({len(self.D.bad)} skipped: {self.D.bad[0]}...)' if self.D.bad else '')
                              + '. Edits apply to the file in tab 2 (its "Save patched file" includes them).')
        self.fill_tree()

    def fill_tree(self):
        self.tree.delete(*self.tree.get_children()); self.items = {}
        if not self.D: return
        q = self.q.get().strip().lower()
        for cat in sorted(self.D.categories):
            ts = [t for t in self.D.categories[cat] if not q or q in t.name.lower() or q in cat.lower()]
            if not ts: continue
            c = self.tree.insert('', 'end', text=cat, open=bool(q))
            for t in sorted(ts, key=lambda t: t.name):
                self.items[self.tree.insert(c, 'end', text=('* ' if t.name in self.changed else '') + t.name)] = t

    # ---- the grid
    def clear_grid(self):
        self.table = None; self.grid.delete(*self.grid.get_children()); self.grid['columns'] = ()
        self.title.config(text=''); self.sub.config(text='')

    def show_selected(self):
        sel = self.tree.selection()
        if sel and sel[0] in self.items: self.show(self.items[sel[0]])

    def show(self, t):
        self.cancel_edit(); self.table = t
        try:
            xs, ys, rows = t.grid(self.app.rom)
        except Exception as e:
            self.clear_grid(); self.title.config(text=t.name); self.sub.config(text=f'Cannot show this table: {e}'); return
        s = t.scaling
        self.shape = (xs, ys)
        cols = ['axis'] + [f'c{i}' for i in range(len(xs) if xs else 1)]
        self.grid.delete(*self.grid.get_children()); self.grid['columns'] = cols
        yname = (t.y.scaling.units if t.y else '') or (t.y.name if t.y else '')
        self.grid.heading('axis', text=yname or ''); self.grid.column('axis', width=self.px(90), anchor='e', stretch=False)
        for i in range(len(cols) - 1):
            h = t.x.scaling.show(xs[i]) if xs else (s.units or 'value')
            self.grid.heading(f'c{i}', text=h); self.grid.column(f'c{i}', width=self.px(70 if xs else 120), anchor='e', stretch=False)
        for r, row in enumerate(rows):
            lab = (t.y.scaling.show(ys[r]) if ys else str(r + 1))
            self.grid.insert('', 'end', iid=str(r), values=[lab] + [s.show(v) for v in row])
        self.title.config(text=('* ' if t.name in self.changed else '') + t.name)
        rng = f'range {s.min:g} to {s.max:g}' if s.min is not None and s.max is not None else ''
        self.sub.config(text=f'{t.category}  |  {s.units}  {rng}  |  0x{t.address:05X}, {t.type}'
                             + (f'  |  across: {t.x.scaling.units or t.x.name}' if xs else ''))

    def start_edit(self, ev):
        if not self.table: return
        row, col = self.grid.identify_row(ev.y), self.grid.identify_column(ev.x)
        if not row or col in ('', '#1'): return               # #1 = the axis column
        c = int(col[1:]) - 2; r = int(row)
        bb = self.grid.bbox(row, col)
        if not bb: return
        self.cancel_edit()
        v = tk.StringVar(value=self.grid.item(row, 'values')[c + 1])
        e = ttk.Entry(self.grid, textvariable=v, justify='right'); e.place(x=bb[0], y=bb[1], width=bb[2], height=bb[3])
        e.focus_set(); e.select_range(0, 'end')
        e.bind('<Return>', lambda _: self.commit(r, c, v.get())); e.bind('<KP_Enter>', lambda _: self.commit(r, c, v.get()))
        e.bind('<Escape>', lambda _: self.cancel_edit()); e.bind('<FocusOut>', lambda _: self.cancel_edit())
        self.edit = e

    def cancel_edit(self):
        if self.edit: self.edit.destroy(); self.edit = None

    def commit(self, r, c, text):
        t, s = self.table, self.table.scaling
        try:
            val = float(text)
        except ValueError:
            messagebox.showerror('NC Patcher', f'"{text}" is not a number.'); return
        if (s.min is not None and val < s.min) or (s.max is not None and val > s.max):
            if not messagebox.askyesno('NC Patcher', f'{val:g} is outside this table\'s range ({s.min:g} to {s.max:g}). Use it anyway?'):
                return
        xs, ys = self.shape
        t.write_index(self.app.rom, t.cell_index(r, c, len(xs) if xs else None, len(ys) if ys else None), val)
        self.changed.add(t.name); self.btn_save.config(state='normal')
        self.cancel_edit(); self.show(t); self.fill_tree()
        self.app.log_to(self.app.log1, f'Edited {t.name}: row {r + 1}, column {c + 1} = {val:g}')

    def save(self):
        app = self.app
        stem, ext = os.path.splitext(app.rom_path)
        p = filedialog.asksaveasfilename(title='Save edited ECU file', initialfile=os.path.basename(stem) + ' - edited' + (ext or '.bin'),
                                         initialdir=os.path.dirname(app.rom_path), defaultextension='.bin', filetypes=[('ECU files', '*.bin')])
        if not p: return
        if os.path.abspath(p) == os.path.abspath(app.rom_path):
            messagebox.showerror('NC Patcher', 'Choose a new file name - the original is never overwritten.'); return
        open(p, 'wb').write(app.rom); app.saved_paths.append(p)
        messagebox.showinfo('NC Patcher', f'Saved:\n{p}\n\n{len(self.changed)} table(s) changed. Flash it with NC Flash '
                                          '(it recalculates the checksums).')

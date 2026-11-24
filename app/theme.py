"""Dark theme for NC Patcher (warm charcoal + coral accent, in the style of the Claude app's dark mode)."""
import sys
import tkinter as tk
from tkinter import ttk

BG = '#262624'        # window
SURFACE = '#30302E'   # cards, drop zones, logs
RAISED = '#3A3A37'    # buttons, inputs, selected tab
HOVER = '#45453F'
BORDER = '#4A4944'
TEXT = '#F5F4EF'
TEXT2 = '#C2C0B6'     # secondary
MUTED = '#9C9A92'     # hints
ACCENT = '#D97757'    # coral
ACCENT_HOVER = '#E08A6D'
ACCENT_PRESS = '#C6613F'
OK = '#8FC08A'
ERR = '#F07D73'
FONT = ('Segoe UI', 10)
MONO = ('Consolas', 10)


def dark_title_bar(win):
    """Windows 10 1809+/11: ask DWM for a dark title bar (ignored elsewhere)."""
    if sys.platform != 'win32': return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        on = ctypes.c_int(1)
        for attr in (20, 19):          # DWMWA_USE_IMMERSIVE_DARK_MODE (20; 19 on older builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), ctypes.sizeof(on)) == 0: break
        for attr, colour in ((35, BG), (34, BORDER)):   # caption + border colour (Windows 11)
            r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
            c = ctypes.c_int(r | g << 8 | b << 16)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(c), ctypes.sizeof(c))
    except Exception:
        pass


def _box(root, fill, edge, tick=None, n=16):
    """a rounded checkbox image, optionally with a tick mark"""
    img = tk.PhotoImage(master=root, width=n + 6, height=n)     # 6 px gap before the label
    px = [[None] * n for _ in range(n)]
    for y in range(n):
        for x in range(n):
            corner = (x in (0, n - 1)) and (y in (0, n - 1))
            if corner: continue
            px[y][x] = edge if x in (0, n - 1) or y in (0, n - 1) else fill
    if tick:
        pts = [(4, 8), (7, 11), (12, 5)]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            steps = max(abs(x1 - x0), abs(y1 - y0)) * 4
            for i in range(steps + 1):
                x = x0 + (x1 - x0) * i / steps; y = y0 + (y1 - y0) * i / steps
                for dx, dy in ((0, 0), (0, 1), (1, 0)):
                    xi, yi = int(round(x)) + dx, int(round(y)) + dy
                    if 0 < xi < n - 1 and 0 < yi < n - 1: px[yi][xi] = tick
    for y in range(n):
        for x in range(n):
            if px[y][x]: img.put(px[y][x], (x, y))
    return img


def apply(root):
    root.configure(bg=BG)
    root.option_add('*Font', FONT)
    for k, v in (('*TCombobox*Listbox.background', RAISED), ('*TCombobox*Listbox.foreground', TEXT),
                 ('*TCombobox*Listbox.selectBackground', ACCENT), ('*TCombobox*Listbox.selectForeground', TEXT),
                 ('*TCombobox*Listbox.font', FONT)):
        root.option_add(k, v)
    s = ttk.Style(root)
    s.theme_use('clam')
    s.configure('.', background=BG, foreground=TEXT, fieldbackground=RAISED, bordercolor=BORDER, lightcolor=BG,
                darkcolor=BG, troughcolor=SURFACE, focuscolor=ACCENT, selectbackground=ACCENT, selectforeground=TEXT,
                insertcolor=TEXT, font=FONT)
    s.map('.', foreground=[('disabled', MUTED)])
    s.configure('TFrame', background=BG)
    s.configure('TLabel', background=BG, foreground=TEXT)
    s.configure('Hint.TLabel', foreground=MUTED)
    s.configure('Big.TLabel', font=('Segoe UI', 13, 'bold'), foreground=ACCENT)
    s.configure('TLabelframe', background=BG, bordercolor=BORDER, lightcolor=BG, darkcolor=BG, relief='solid', borderwidth=1)
    s.configure('TLabelframe.Label', background=BG, foreground=TEXT2, font=('Segoe UI Semibold', 10))
    # tabs
    s.configure('TNotebook', background=BG, bordercolor=BORDER, lightcolor=BG, darkcolor=BG, tabmargins=(2, 4, 2, 0))
    s.configure('TNotebook.Tab', background=BG, foreground=MUTED, bordercolor=BG, lightcolor=BG, darkcolor=BG,
                padding=(10, 6), font=FONT)
    s.map('TNotebook.Tab', background=[('selected', RAISED), ('active', SURFACE)],
          foreground=[('selected', TEXT), ('active', TEXT2)],
          bordercolor=[('selected', BORDER)], lightcolor=[('selected', RAISED)])
    # buttons
    s.configure('TButton', background=RAISED, foreground=TEXT, bordercolor=BORDER, lightcolor=RAISED, darkcolor=RAISED,
                padding=(12, 5), focusthickness=0, relief='flat')
    s.map('TButton', background=[('disabled', SURFACE), ('pressed', BORDER), ('active', HOVER)],
          lightcolor=[('disabled', SURFACE), ('active', HOVER)], darkcolor=[('disabled', SURFACE), ('active', HOVER)],
          foreground=[('disabled', MUTED)], bordercolor=[('disabled', SURFACE)])
    s.configure('Accent.TButton', background=ACCENT, foreground='#1F1E1D', lightcolor=ACCENT, darkcolor=ACCENT,
                bordercolor=ACCENT, font=('Segoe UI Semibold', 10))
    s.map('Accent.TButton', background=[('disabled', SURFACE), ('pressed', ACCENT_PRESS), ('active', ACCENT_HOVER)],
          lightcolor=[('disabled', SURFACE), ('active', ACCENT_HOVER)], darkcolor=[('disabled', SURFACE), ('active', ACCENT_HOVER)],
          bordercolor=[('disabled', SURFACE), ('active', ACCENT_HOVER)], foreground=[('disabled', MUTED)])
    # check boxes
    root._chk = imgs = {k: _box(root, *v) for k, v in {
        'off': (RAISED, BORDER), 'off_hover': (HOVER, MUTED), 'off_dis': (SURFACE, SURFACE),
        'on': (ACCENT, ACCENT, '#1F1E1D'), 'on_hover': (ACCENT_HOVER, ACCENT_HOVER, '#1F1E1D'),
        'on_dis': (SURFACE, BORDER, MUTED)}.items()}          # keep references (Tk drops unreferenced images)
    s.element_create('Dark.Checkbutton.indicator', 'image', imgs['off'],
                     ('disabled', 'selected', imgs['on_dis']), ('disabled', imgs['off_dis']),
                     ('selected', 'active', imgs['on_hover']), ('selected', imgs['on']),
                     ('active', imgs['off_hover']), border=0, sticky='w')
    s.layout('TCheckbutton', [('Checkbutton.padding', {'sticky': 'nswe', 'children': [
        ('Dark.Checkbutton.indicator', {'side': 'left', 'sticky': ''}),
        ('Checkbutton.label', {'side': 'left', 'sticky': 'nswe'})]})])
    s.configure('TCheckbutton', background=BG, foreground=TEXT, focusthickness=0, padding=(0, 2))
    s.map('TCheckbutton', background=[('active', BG)], foreground=[('disabled', MUTED)])
    # inputs
    s.configure('TEntry', fieldbackground=RAISED, foreground=TEXT, bordercolor=BORDER, lightcolor=RAISED, darkcolor=RAISED,
                insertcolor=TEXT, padding=4)
    s.map('TEntry', bordercolor=[('focus', ACCENT)], lightcolor=[('focus', ACCENT)],
          fieldbackground=[('disabled', SURFACE)], foreground=[('disabled', MUTED)])
    s.configure('TCombobox', fieldbackground=RAISED, background=RAISED, foreground=TEXT, arrowcolor=TEXT2,
                bordercolor=BORDER, lightcolor=RAISED, darkcolor=RAISED, padding=4)
    s.map('TCombobox', fieldbackground=[('readonly', RAISED), ('disabled', SURFACE)],
          foreground=[('readonly', TEXT), ('disabled', MUTED)], selectbackground=[('readonly', RAISED)],
          selectforeground=[('readonly', TEXT)], bordercolor=[('focus', ACCENT)], arrowcolor=[('active', TEXT)],
          background=[('active', HOVER)])
    s.configure('Horizontal.TProgressbar', background=ACCENT, troughcolor=SURFACE, bordercolor=BORDER,
                lightcolor=ACCENT, darkcolor=ACCENT, thickness=10)
    s.configure('Horizontal.TScale', background=ACCENT, troughcolor=RAISED, bordercolor=BORDER, lightcolor=ACCENT,
                darkcolor=ACCENT, sliderthickness=14, gripcount=0)
    s.map('Horizontal.TScale', background=[('active', ACCENT_HOVER)])
    s.configure('Vertical.TScrollbar', background=RAISED, troughcolor=SURFACE, bordercolor=SURFACE, arrowcolor=TEXT2,
                lightcolor=RAISED, darkcolor=RAISED)
    dark_title_bar(root)


def text(parent, **kw):
    """a log box in the theme"""
    return tk.Text(parent, bg=SURFACE, fg=TEXT2, insertbackground=TEXT, selectbackground=ACCENT, selectforeground=TEXT,
                   relief='flat', highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER,
                   font=MONO, padx=8, pady=6, **kw)

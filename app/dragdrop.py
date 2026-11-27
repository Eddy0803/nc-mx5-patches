"""Accept files dragged from Explorer onto a tkinter widget or a whole window (Windows, no extra packages).

Uses DragAcceptFiles + a window subclass to catch WM_DROPFILES. A file dropped on a child window that doesn't accept
files goes to the nearest parent that does, so enabling the top-level window makes the whole window a drop target.

Running as administrator: Windows normally blocks drag-and-drop from Explorer (which runs as a normal user) into an
elevated program. ChangeWindowMessageFilterEx lets the drop messages through for these windows only.
"""
import ctypes
from ctypes import wintypes as wt

WM_DROPFILES, WM_COPYDATA, WM_COPYGLOBALDATA = 0x0233, 0x004A, 0x0049
MSGFLT_ALLOW = 1
LRESULT = ctypes.c_ssize_t
UINT_PTR = ctypes.c_size_t
SUBCLASSPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, UINT_PTR, UINT_PTR)

shell32, comctl32, user32 = ctypes.windll.shell32, ctypes.windll.comctl32, ctypes.windll.user32
shell32.DragAcceptFiles.argtypes = [wt.HWND, wt.BOOL]
shell32.DragQueryFileW.argtypes = [wt.HANDLE, wt.UINT, wt.LPWSTR, wt.UINT]
shell32.DragQueryFileW.restype = wt.UINT
shell32.DragFinish.argtypes = [wt.HANDLE]
comctl32.SetWindowSubclass.argtypes = [wt.HWND, SUBCLASSPROC, UINT_PTR, UINT_PTR]
comctl32.SetWindowSubclass.restype = wt.BOOL
comctl32.DefSubclassProc.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
comctl32.DefSubclassProc.restype = LRESULT
user32.GetParent.argtypes = [wt.HWND]
user32.GetParent.restype = wt.HWND

_keep = []          # keep the callbacks alive


def _allow_when_elevated(hwnd):
    """let Explorer's drop messages reach this window even if the app runs as administrator (Windows 7+)"""
    try:
        f = user32.ChangeWindowMessageFilterEx
        f.argtypes = [wt.HWND, wt.UINT, wt.DWORD, ctypes.c_void_p]
        f.restype = wt.BOOL
        for m in (WM_DROPFILES, WM_COPYDATA, WM_COPYGLOBALDATA):
            f(hwnd, m, MSGFLT_ALLOW, None)
    except (AttributeError, OSError):
        pass


def _hook(hwnd, widget, on_drop):
    # The window procedure runs inside Tk's event loop, where calling back into tkinter (even widget.after) corrupts
    # tkinter's thread state and aborts Python ("PyEval_RestoreThread ... GIL is released"). So it only records the
    # files, and a normal tkinter timer hands them to on_drop.
    pending = []

    def proc(h, msg, wp, lp, uid, ref):
        if msg == WM_DROPFILES:
            files = []
            count = shell32.DragQueryFileW(wp, 0xFFFFFFFF, None, 0)
            for i in range(count):
                n = shell32.DragQueryFileW(wp, i, None, 0)
                buf = ctypes.create_unicode_buffer(n + 1)
                shell32.DragQueryFileW(wp, i, buf, n + 1)
                files.append(buf.value)
            shell32.DragFinish(wp)
            pending.append(files)                       # no tkinter calls here
            return 0
        return comctl32.DefSubclassProc(h, msg, wp, lp)

    def poll():
        try:
            while pending:
                on_drop(pending.pop(0))
        finally:
            try:
                widget.after(100, poll)
            except Exception:                           # widget destroyed
                pass

    cb = SUBCLASSPROC(proc)
    _keep.append(cb)
    _allow_when_elevated(hwnd)
    shell32.DragAcceptFiles(hwnd, True)
    comctl32.SetWindowSubclass(hwnd, cb, len(_keep), 0)
    widget.after(100, poll)
    return hwnd


def enable(widget, on_drop):
    """call on_drop([paths]) when files are dropped on `widget`"""
    widget.update_idletasks()
    return _hook(widget.winfo_id(), widget, on_drop)


def enable_window(toplevel, on_drop):
    """call on_drop([paths]) when files are dropped anywhere on a tkinter Tk / Toplevel window (widgets that accept
    drops themselves, like a drop box, still get theirs first)"""
    toplevel.update_idletasks()
    inner = toplevel.winfo_id()
    frame = user32.GetParent(inner) or inner          # Tk's outer (window-manager) frame
    hooked = [_hook(frame, toplevel, on_drop)]
    if inner != frame: hooked.append(_hook(inner, toplevel, on_drop))
    return hooked

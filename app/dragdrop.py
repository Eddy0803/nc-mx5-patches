"""Accept files dragged from Explorer onto a tkinter widget (Windows, no extra packages).

Uses DragAcceptFiles + a window subclass to catch WM_DROPFILES. Note: Windows blocks drag-and-drop from Explorer
into a program running as administrator, so don't run the app elevated.
"""
import ctypes
from ctypes import wintypes as wt

WM_DROPFILES = 0x0233
LRESULT = ctypes.c_ssize_t
UINT_PTR = ctypes.c_size_t
SUBCLASSPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, UINT_PTR, UINT_PTR)

shell32, comctl32 = ctypes.windll.shell32, ctypes.windll.comctl32
shell32.DragAcceptFiles.argtypes = [wt.HWND, wt.BOOL]
shell32.DragQueryFileW.argtypes = [wt.HANDLE, wt.UINT, wt.LPWSTR, wt.UINT]
shell32.DragQueryFileW.restype = wt.UINT
shell32.DragFinish.argtypes = [wt.HANDLE]
comctl32.SetWindowSubclass.argtypes = [wt.HWND, SUBCLASSPROC, UINT_PTR, UINT_PTR]
comctl32.SetWindowSubclass.restype = wt.BOOL
comctl32.DefSubclassProc.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
comctl32.DefSubclassProc.restype = LRESULT

_keep = []          # keep the callbacks alive


def enable(widget, on_drop):
    """call on_drop([paths]) when files are dropped on `widget`"""
    widget.update_idletasks()
    hwnd = widget.winfo_id()

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
            widget.after(0, on_drop, files)
            return 0
        return comctl32.DefSubclassProc(h, msg, wp, lp)

    cb = SUBCLASSPROC(proc)
    _keep.append(cb)
    shell32.DragAcceptFiles(hwnd, True)
    comctl32.SetWindowSubclass(hwnd, cb, len(_keep), 0)

"""Match auxiliary Tk surfaces to the desktop workspace's translucency.

The workspace uses a tinted alpha surface, not a desktop screenshot or a
live-blur shader. Tk widgets stay native and retain focus/input behavior.
Never apply this to the pet's UpdateLayeredWindow artwork window.
"""
import ctypes
import os
import tkinter as tk
from ctypes import wintypes
from flat_workspace import PANEL_REST

OPACITY = PANEL_REST / 255.0
_MENU_HOOKS = {}


def watch_menu_surfaces():
    """First-show notification works inside Windows' native menu modal loop.

    Tk timers can be suspended there; a process/thread-scoped Windows event
    hook styles the newly created popup before pointer selection is needed.
    One hook per Tk thread lives until process exit, with its callback retained.
    """
    if os.name != 'nt':return False
    u = ctypes.WinDLL('user32', use_last_error=True)
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.GetCurrentThreadId.restype = wintypes.DWORD
    tid = k.GetCurrentThreadId()
    if tid in _MENU_HOOKS:return True
    callback = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD,
                                 wintypes.HWND, ctypes.c_long, ctypes.c_long,
                                 wintypes.DWORD, wintypes.DWORD)
    u.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE,
                                 callback, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
    u.SetWinEventHook.restype = wintypes.HANDLE
    def shown(hook, event, hwnd, obj, child, thread, when):
        native_menu_surfaces()
    proc = callback(shown)
    handle = u.SetWinEventHook(6, 6, None, proc, os.getpid(), tid, 0)
    if handle:_MENU_HOOKS[tid] = (handle, proc)
    return bool(handle)


def apply_surface(win):
    """Tk preserves an existing rounded-corner color key when alpha is set."""
    win.attributes('-alpha', OPACITY)


def native_menu_surfaces():
    """Style native popup HWNDs belonging only to this Tk thread/process.

    Tk menus are native HMENUs; their winfo_id isn't the popup's HWND. Menu
    selection/post events therefore discover only class #32768 on our thread.
    Existing window style bits are preserved, including mouse interaction.
    """
    if os.name != 'nt':
        return []
    u = ctypes.WinDLL('user32', use_last_error=True)
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    get = u.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else u.GetWindowLongW
    put = u.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else u.SetWindowLongW
    get.argtypes = [wintypes.HWND, ctypes.c_int]; get.restype = ctypes.c_ssize_t
    put.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]; put.restype = ctypes.c_ssize_t
    u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.BYTE, wintypes.DWORD]
    k.GetCurrentThreadId.restype = wintypes.DWORD
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    u.EnumThreadWindows.argtypes = [wintypes.DWORD, callback, wintypes.LPARAM]
    applied = []
    def visit(hwnd, unused):
        name = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(hwnd, name, len(name))
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if name.value == '#32768' and pid.value == os.getpid():
            old = get(hwnd, -20)
            if not old & 0x80000:
                ctypes.set_last_error(0)
                put(hwnd, -20, old | 0x80000)
                if ctypes.get_last_error():return True
            if u.SetLayeredWindowAttributes(hwnd, 0, PANEL_REST, 2):
                applied.append(int(hwnd))
            elif not old & 0x80000:
                put(hwnd, -20, old)  # keep the menu usable if composition fails
        return True
    u.EnumThreadWindows(k.GetCurrentThreadId(), callback(visit), 0)
    return applied


class SurfaceMenu(tk.Menu):
    """Regular Tk menu, with the same alpha on its popup and cascades."""
    def __init__(self, master=None, **kw):
        previous = kw.pop('postcommand', None)
        super().__init__(master, **kw)
        watch_menu_surfaces()
        def post():
            if callable(previous):previous()
            elif previous:self.tk.call(previous)
            self._surface_event()
        self.configure(postcommand=post)
        self.bind('<<MenuSelect>>', self._surface_event, add='+')
        self.bind('<Map>', self._surface_event, add='+')

    def _surface_event(self, event=None):
        native_menu_surfaces()
        # A postcommand can run before Windows creates the native popup.
        # MenuSelect handles cascades; these bounded retries handle first show.
        for delay in (0, 16, 50):
            self.after(delay, native_menu_surfaces)

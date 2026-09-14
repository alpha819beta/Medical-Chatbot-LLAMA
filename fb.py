"""
DeepSeek Private Browser + Silent Screenshot Tool + Live Captions Typer

- Window hidden from screen capture (WDA_EXCLUDEFROMCAPTURE)
- Always on top, no taskbar icon
- Hold Ctrl+Alt + left-click-drag -> region copied to clipboard silently
- Ctrl+Alt+W -> toggle Live Captions tracking
- Ctrl+Alt+Up/Down Arrow -> adjust overall window opacity
- Ctrl+Alt+Z -> hide/show browser window
- Ctrl+Alt+R -> app-level page refresh (location.reload)
- Ctrl+Alt+X -> open Google
- Ctrl+Alt+Left Arrow -> go to previous link/page
- Green circle indicator on top-right of the browser window when captions are active

Dependencies:
    pip install pywebview pywin32 pillow mss uiautomation
"""

import ctypes
import ctypes.wintypes
import io
import queue
import random
import string
import subprocess
import threading
import time

import mss
import win32api
import win32clipboard
import win32con
import webview
from PIL import Image, ImageDraw

# uiautomation is only imported when first needed
_uia = None


def _get_uia():
    global _uia
    if _uia is None:
        import uiautomation as _uia_mod
        _uia = _uia_mod
    return _uia


# Win32 DLLs
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

# Argtypes (prevent 32/64-bit truncation)
user32.GetDC.argtypes = [ctypes.wintypes.HWND]
user32.GetDC.restype = ctypes.wintypes.HDC
user32.ReleaseDC.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.ShowWindow.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = ctypes.wintypes.BOOL
user32.RegisterClassW.argtypes = [ctypes.c_void_p]
user32.RegisterClassW.restype = ctypes.wintypes.ATOM
user32.CreateWindowExW.argtypes = [
    ctypes.c_ulong,
    ctypes.c_wchar_p,
    ctypes.c_wchar_p,
    ctypes.c_ulong,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.wintypes.HWND,
    ctypes.wintypes.HMENU,
    ctypes.wintypes.HINSTANCE,
    ctypes.c_void_p,
]
user32.CreateWindowExW.restype = ctypes.wintypes.HWND
user32.DefWindowProcW.argtypes = [
    ctypes.wintypes.HWND,
    ctypes.wintypes.UINT,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.UpdateLayeredWindow.argtypes = [
    ctypes.wintypes.HWND,
    ctypes.wintypes.HDC,
    ctypes.POINTER(ctypes.wintypes.POINT),
    ctypes.POINTER(ctypes.wintypes.SIZE),
    ctypes.wintypes.HDC,
    ctypes.POINTER(ctypes.wintypes.POINT),
    ctypes.wintypes.COLORREF,
    ctypes.c_void_p,
    ctypes.wintypes.DWORD,
]
user32.UpdateLayeredWindow.restype = ctypes.wintypes.BOOL
user32.SetWindowDisplayAffinity.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.DWORD]
user32.SetWindowDisplayAffinity.restype = ctypes.wintypes.BOOL
user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
user32.FindWindowW.restype = ctypes.wintypes.HWND
user32.SetWindowPos.argtypes = [
    ctypes.wintypes.HWND,
    ctypes.wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_uint,
]
user32.SetWindowPos.restype = ctypes.wintypes.BOOL
user32.GetWindowLongW.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.wintypes.HINSTANCE,
    ctypes.wintypes.DWORD,
]
user32.SetWindowsHookExW.restype = ctypes.wintypes.HHOOK
user32.UnhookWindowsHookEx.argtypes = [ctypes.wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = ctypes.wintypes.BOOL
user32.CallNextHookEx.argtypes = [
    ctypes.wintypes.HHOOK,
    ctypes.c_int,
    ctypes.c_size_t,
    ctypes.c_ssize_t,
]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.GetMessageW.argtypes = [
    ctypes.c_void_p,
    ctypes.wintypes.HWND,
    ctypes.c_uint,
    ctypes.c_uint,
]
user32.GetMessageW.restype = ctypes.wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.c_void_p]
user32.TranslateMessage.restype = ctypes.wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
user32.DispatchMessageW.restype = ctypes.c_ssize_t
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.SetLayeredWindowAttributes.argtypes = [
    ctypes.wintypes.HWND,
    ctypes.wintypes.COLORREF,
    ctypes.c_byte,
    ctypes.wintypes.DWORD,
]
user32.SetLayeredWindowAttributes.restype = ctypes.wintypes.BOOL
user32.PostMessageW.argtypes = [
    ctypes.wintypes.HWND,
    ctypes.c_uint,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
]
user32.PostMessageW.restype = ctypes.wintypes.BOOL
user32.DestroyWindow.argtypes = [ctypes.wintypes.HWND]
user32.DestroyWindow.restype = ctypes.wintypes.BOOL
user32.GetWindowRect.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.RECT)]
user32.GetWindowRect.restype = ctypes.wintypes.BOOL

gdi32.CreateCompatibleDC.argtypes = [ctypes.wintypes.HDC]
gdi32.CreateCompatibleDC.restype = ctypes.wintypes.HDC
gdi32.CreateDIBSection.argtypes = [
    ctypes.wintypes.HDC,
    ctypes.c_void_p,
    ctypes.c_uint,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = ctypes.wintypes.HBITMAP
gdi32.SelectObject.argtypes = [ctypes.wintypes.HDC, ctypes.wintypes.HGDIOBJ]
gdi32.SelectObject.restype = ctypes.wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [ctypes.wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = ctypes.wintypes.BOOL
gdi32.DeleteDC.argtypes = [ctypes.wintypes.HDC]
gdi32.DeleteDC.restype = ctypes.wintypes.BOOL

kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
kernel32.GetModuleHandleW.restype = ctypes.wintypes.HINSTANCE

# Constants
WDA_EXCLUDEFROMCAPTURE = 0x00000011
HWND_TOPMOST = ctypes.wintypes.HWND(-1)
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
GWL_EXSTYLE = -20
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
WS_POPUP = 0x80000000
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
WH_MOUSE_LL = 14
WH_KEYBOARD_LL = 13
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_DESTROY = 0x0002

WM_INDICATOR_SHOW = 0x8000 + 1
WM_INDICATOR_HIDE = 0x8000 + 2

VK_W = 0x57
VK_R = 0x52
VK_X = 0x58
VK_Z = 0x5A
VK_LEFT = 0x25
VK_UP = 0x26
VK_DOWN = 0x28
LWA_ALPHA = 0x02
SW_HIDE = 0
SW_SHOWNA = 8

BROWSER_TITLE = "Fake Rabbit"
WNDCLASS_NAME = "SilentScreenshotOverlay"

current_alpha = 255
wv = None
window_ready = threading.Event()
window_hidden = False

indicator_hwnd = None
indicator_thread = None
indicator_ready = threading.Event()


# Opacity
def set_window_alpha(title: str, alpha: int):
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return
    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if not (ex_style & WS_EX_LAYERED):
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style | WS_EX_LAYERED)
    user32.SetLayeredWindowAttributes(hwnd, 0, alpha, LWA_ALPHA)


def _change_opacity(increment: bool):
    global current_alpha
    current_alpha = min(current_alpha + 25, 255) if increment else max(current_alpha - 25, 30)
    set_window_alpha(BROWSER_TITLE, current_alpha)


def _toggle_browser_visibility():
    global window_hidden
    hwnd = user32.FindWindowW(None, BROWSER_TITLE)
    if not hwnd:
        return

    if window_hidden:
        user32.ShowWindow(hwnd, SW_SHOWNA)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
        set_window_alpha(BROWSER_TITLE, current_alpha)
        window_hidden = False
    else:
        user32.ShowWindow(hwnd, SW_HIDE)
        window_hidden = True


def _refresh_page():
    if wv is not None and window_ready.is_set():
        try:
            wv.evaluate_js("location.reload()")
        except:
            pass


def _open_google():
    if wv is not None and window_ready.is_set():
        try:
            wv.load_url("https://www.google.com/")
        except:
            pass


def _previous_link():
    if wv is not None and window_ready.is_set():
        try:
            wv.evaluate_js("history.back()")
        except:
            pass


# Overlay / Screenshot
_draw_queue = queue.Queue()
_overlay_ready = threading.Event()


def _overlay_thread():
    _overlay_ready.set()
    while True:
        try:
            cmd = _draw_queue.get(timeout=0.1)
            if cmd is None:
                return
        except queue.Empty:
            continue


def _paint(hwnd, ox, oy, ow, oh, x1, y1, x2, y2):
    lx = min(x1, x2) - ox
    ly = min(y1, y2) - oy
    rx = max(x1, x2) - ox
    ry = max(y1, y2) - oy
    img = Image.new("RGBA", (ow, oh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if rx - lx > 4 and ry - ly > 4:
        draw.rectangle([lx + 2, ly + 2, rx - 2, ry - 2], fill=(30, 160, 255, 20))
    draw.rectangle([lx, ly, rx, ry], outline=(60, 180, 255, 230))
    draw.rectangle([lx + 1, ly + 1, rx - 1, ry - 1], outline=(60, 180, 255, 120))
    _blit(hwnd, ox, oy, ow, oh, img)


def _blit(hwnd, ox, oy, w, h, img: Image.Image):
    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h
    bmi.biPlanes = 1
    bmi.biBitCount = 32

    ppvBits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(hdc_screen, ctypes.byref(bmi), 0, ctypes.byref(ppvBits), None, 0)
    old = gdi32.SelectObject(hdc_mem, hbmp)

    bgra = img.tobytes("raw", "BGRA")
    ctypes.memmove(ppvBits, bgra, len(bgra))

    pt_dst = ctypes.wintypes.POINT(ox, oy)
    pt_src = ctypes.wintypes.POINT(0, 0)
    sz = ctypes.wintypes.SIZE(w, h)
    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)

    user32.UpdateLayeredWindow(
        hwnd,
        hdc_screen,
        ctypes.byref(pt_dst),
        ctypes.byref(sz),
        hdc_mem,
        ctypes.byref(pt_src),
        0,
        ctypes.byref(blend),
        ULW_ALPHA,
    )

    gdi32.SelectObject(hdc_mem, old)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(None, hdc_screen)


# Clipboard & Capture
def _to_clipboard(img: Image.Image):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "BMP")
    dib = buf.getvalue()[14:]
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_DIB, dib)
    finally:
        win32clipboard.CloseClipboard()


def _capture(x1, y1, x2, y2):
    time.sleep(0.08)
    left, top = min(x1, x2), min(y1, y2)
    width, height = abs(x2 - x1), abs(y2 - y1)
    if width < 4 or height < 4:
        return
    try:
        with mss.mss() as sct:
            raw = sct.grab({"left": left, "top": top, "width": width, "height": height})
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        _to_clipboard(img)
        print("[screenshot] Region copied.")
    except Exception as e:
        print(f"[screenshot] Error: {e}")


# Live Captions
_captions_active = False
_captions_lock = threading.Lock()
_captions_thread = None
_captions_hwnd = None


def _find_captions_window():
    return user32.FindWindowW(None, "Live Captions")


def _launch_live_captions():
    hwnd = _find_captions_window()
    if hwnd:
        return hwnd
    try:
        subprocess.Popen([r"C:\Windows\System32\LiveCaptions.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        return 0
    for _ in range(50):
        time.sleep(0.1)
        hwnd = _find_captions_window()
        if hwnd:
            return hwnd
    return 0


def _kill_live_captions():
    try:
        subprocess.call(["taskkill", "/F", "/IM", "LiveCaptions.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass


def _extract_new(accumulated: str, current: str, tail_chars: int = 30) -> str:
    if not current:
        return ""
    current_tail = current[-tail_chars:]
    best = 0
    for length in range(min(len(current_tail), len(accumulated)), 9, -1):
        if accumulated.endswith(current_tail[:length]):
            best = length
            break
    return current_tail[best:] if best > 0 else current_tail


def _captions_worker(seed_text=""):
    global _captions_active
    uia = _get_uia()
    time.sleep(0.6)
    hwnd = _captions_hwnd or _find_captions_window()
    if not hwnd:
        with _captions_lock:
            _captions_active = False
        return
    win = uia.ControlFromHandle(hwnd)
    if not win:
        with _captions_lock:
            _captions_active = False
        return

    accumulated, last_current = seed_text, seed_text
    while True:
        with _captions_lock:
            if not _captions_active:
                break
        try:
            win = uia.ControlFromHandle(hwnd)
            if not win:
                time.sleep(0.25)
                continue
            text_ctrl = win.TextControl(AutomationId="CaptionsTextBlock")
            if not text_ctrl.Exists(0):
                text_ctrl = win.TextControl()
            current = text_ctrl.Name if text_ctrl.Exists(0) else ""
            if current and current != last_current:
                new_part = _extract_new(accumulated, current)
                if new_part:
                    accumulated += new_part
                last_current = current
        except:
            pass
        time.sleep(0.25)

    result = accumulated[len(seed_text):].strip()
    if result:
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, result)
            win32clipboard.CloseClipboard()
        except:
            pass


def _toggle_live_captions():
    global _captions_active, _captions_thread, indicator_hwnd
    with _captions_lock:
        turning_on = not _captions_active
        _captions_active = turning_on
    if turning_on:
        seed = ""
        try:
            uia = _get_uia()
            hwnd = _captions_hwnd or _find_captions_window()
            if hwnd:
                win = uia.ControlFromHandle(hwnd)
                if win:
                    ctrl = win.TextControl(AutomationId="CaptionsTextBlock")
                    if not ctrl.Exists(0):
                        ctrl = win.TextControl()
                    seed = ctrl.Name or "" if ctrl.Exists(0) else ""
        except:
            pass
        _captions_thread = threading.Thread(target=_captions_worker, args=(seed,), daemon=True)
        _captions_thread.start()
        if indicator_hwnd:
            user32.PostMessageW(indicator_hwnd, WM_INDICATOR_SHOW, 0, 0)
    else:
        if indicator_hwnd:
            user32.PostMessageW(indicator_hwnd, WM_INDICATOR_HIDE, 0, 0)


# Caption Indicator Window (green circle, top-right of browser)
WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    ctypes.wintypes.HWND,
    ctypes.wintypes.UINT,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)
_indicator_wnd_proc_ref = None


def _create_indicator_image():
    """Create a 24x24 RGBA image with a green circle and white border."""
    size = 24
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 3
    draw.ellipse([margin, margin, size - margin, size - margin], fill=(0, 220, 0, 255))
    draw.ellipse([margin, margin, size - margin, size - margin], outline=(255, 255, 255, 255), width=2)
    return img


def _indicator_wnd_proc(hwnd, msg, wparam, lparam):
    if msg == WM_INDICATOR_SHOW:
        browser_hwnd = user32.FindWindowW(None, BROWSER_TITLE)
        if browser_hwnd:
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(browser_hwnd, ctypes.byref(rect))
            x = rect.right - 80
            y = rect.top + 6
        else:
            screen_w = user32.GetSystemMetrics(0)
            x = screen_w - 80
            y = 10

        user32.ShowWindow(hwnd, 8)  # SW_SHOWNOACTIVATE
        user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, 24, 24, SWP_NOSIZE)
        img = _create_indicator_image()
        _blit(hwnd, x, y, 24, 24, img)
        print(f"[indicator] Green circle shown at ({x}, {y})")
        return 0
    elif msg == WM_INDICATOR_HIDE:
        user32.ShowWindow(hwnd, 0)
        print("[indicator] Green circle hidden")
        return 0
    elif msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _indicator_thread_main():
    global indicator_hwnd, _indicator_wnd_proc_ref
    hinst = kernel32.GetModuleHandleW(None)

    suffix = "".join(random.choices(string.ascii_letters, k=8))
    class_name = f"CaptionIndicator_{suffix}"

    wndclass = WNDCLASSW()
    wndclass.style = 0
    _indicator_wnd_proc_ref = WNDPROC(_indicator_wnd_proc)
    wndclass.lpfnWndProc = ctypes.cast(_indicator_wnd_proc_ref, ctypes.c_void_p)
    wndclass.cbClsExtra = 0
    wndclass.cbWndExtra = 0
    wndclass.hInstance = hinst
    wndclass.hIcon = None
    wndclass.hCursor = None
    wndclass.hbrBackground = None
    wndclass.lpszMenuName = None
    wndclass.lpszClassName = class_name

    atom = user32.RegisterClassW(ctypes.byref(wndclass))
    if not atom:
        print("[indicator] Failed to register window class")
        indicator_ready.set()
        return

    ex_style = WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_NOACTIVATE
    hwnd = user32.CreateWindowExW(
        ex_style,
        class_name,
        "",
        WS_POPUP,
        0,
        0,
        24,
        24,
        None,
        None,
        hinst,
        None,
    )
    if not hwnd:
        print("[indicator] Failed to create indicator window")
        indicator_ready.set()
        return

    indicator_hwnd = hwnd
    user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
    print("[indicator] Indicator window created successfully")
    indicator_ready.set()

    msg = ctypes.wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))

    indicator_hwnd = None


def _start_indicator():
    global indicator_thread
    indicator_ready.clear()
    indicator_thread = threading.Thread(target=_indicator_thread_main, daemon=True)
    indicator_thread.start()
    indicator_ready.wait()


def _stop_indicator():
    global indicator_hwnd, indicator_thread
    if indicator_hwnd:
        user32.PostMessageW(indicator_hwnd, WM_DESTROY, 0, 0)
        indicator_thread.join(timeout=1)
        indicator_hwnd = None


# Mouse / Keyboard hooks
_mouse_hook_handle = None
_mouse_hook_proc = None
_active = False
_x0 = _y0 = 0


def _ctrl_alt() -> bool:
    ctrl = user32.GetAsyncKeyState(win32con.VK_CONTROL) & 0x8000
    alt = user32.GetAsyncKeyState(win32con.VK_MENU) & 0x8000
    return bool(ctrl and alt)


def _mouse_hook_callback(nCode: int, wParam: int, lParam: int) -> int:
    global _active, _x0, _y0
    if nCode >= 0:
        info = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
        mx, my = info.pt.x, info.pt.y

        if wParam == WM_LBUTTONDOWN and _ctrl_alt():
            _active = True
            _x0, _y0 = mx, my
            _draw_queue.put((_x0, _y0, mx, my))
            return 1
        if wParam == WM_MOUSEMOVE and _active:
            _draw_queue.put((_x0, _y0, mx, my))
        if wParam == WM_LBUTTONUP and _active:
            _active = False
            x1, y1, x2, y2 = _x0, _y0, mx, my
            _draw_queue.put("hide")
            threading.Thread(target=_capture, args=(x1, y1, x2, y2), daemon=True).start()
            return 1
    return user32.CallNextHookEx(_mouse_hook_handle, nCode, wParam, lParam)


_kbd_hook_handle = None
_kbd_hook_proc = None


def _kbd_hook_callback(nCode: int, wParam: int, lParam: int) -> int:
    if nCode >= 0 and (wParam == WM_KEYDOWN or wParam == WM_SYSKEYDOWN):
        info = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        if _ctrl_alt():
            if info.vkCode == VK_W:
                threading.Thread(target=_toggle_live_captions, daemon=True).start()
                return 1
            elif info.vkCode == VK_Z:
                threading.Thread(target=_toggle_browser_visibility, daemon=True).start()
                return 1
            elif info.vkCode == VK_UP:
                threading.Thread(target=_change_opacity, args=(True,), daemon=True).start()
                return 1
            elif info.vkCode == VK_DOWN:
                threading.Thread(target=_change_opacity, args=(False,), daemon=True).start()
                return 1
            elif info.vkCode == VK_R:
                threading.Thread(target=_refresh_page, daemon=True).start()
                return 1
            elif info.vkCode == VK_X:
                threading.Thread(target=_open_google, daemon=True).start()
                return 1
            elif info.vkCode == VK_LEFT:
                threading.Thread(target=_previous_link, daemon=True).start()
                return 1
    return user32.CallNextHookEx(_kbd_hook_handle, nCode, wParam, lParam)


def _hook_pump():
    global _mouse_hook_handle, _mouse_hook_proc, _kbd_hook_handle, _kbd_hook_proc
    hmod = kernel32.GetModuleHandleW(None)

    _mouse_hook_proc = HookProcType(_mouse_hook_callback)
    _mouse_hook_handle = user32.SetWindowsHookExW(WH_MOUSE_LL, _mouse_hook_proc, hmod, 0)

    _kbd_hook_proc = HookProcType(_kbd_hook_callback)
    _kbd_hook_handle = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _kbd_hook_proc, hmod, 0)

    msg = ctypes.wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def start_screenshot_tool():
    threading.Thread(target=_overlay_thread, daemon=True).start()
    _overlay_ready.wait()
    threading.Thread(target=_hook_pump, daemon=True).start()

    def _init_captions():
        global _captions_hwnd
        _captions_hwnd = _launch_live_captions()

    threading.Thread(target=_init_captions, daemon=True).start()

    _start_indicator()


def stop_screenshot_tool():
    global _mouse_hook_handle, _kbd_hook_handle
    if _mouse_hook_handle:
        user32.UnhookWindowsHookEx(_mouse_hook_handle)
    if _kbd_hook_handle:
        user32.UnhookWindowsHookEx(_kbd_hook_handle)
    _draw_queue.put(None)
    _stop_indicator()


def setup_window(title: str):
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return
    user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)

    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    new_style = (ex_style | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_TOPMOST) & ~WS_EX_APPWINDOW
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)

    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)


# Structs
class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.c_uint),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.wintypes.HINSTANCE),
        ("hIcon", ctypes.wintypes.HICON),
        ("hCursor", ctypes.wintypes.HANDLE),
        ("hbrBackground", ctypes.wintypes.HBRUSH),
        ("lpszMenuName", ctypes.c_wchar_p),
        ("lpszClassName", ctypes.c_wchar_p),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", ctypes.wintypes.POINT),
        ("mouseData", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


HookProcType = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t)


# Entry point
if __name__ == "__main__":
    start_screenshot_tool()

    wv = webview.create_window(
        BROWSER_TITLE,
        "https://chatgpt.com/",
        width=1100,
        height=720,
    )

    def on_loaded():
        setup_window(BROWSER_TITLE)
        set_window_alpha(BROWSER_TITLE, current_alpha)
        window_ready.set()

    wv.events.loaded += on_loaded

    webview.start()
    window_ready.clear()
    stop_screenshot_tool()

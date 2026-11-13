"""A small badge beside the user's own pointer saying what Orbyn is doing
(Listening, Thinking, Researching...), as HeyClicky's cursor companion does.

It follows the operating system's cursor position, never a model-supplied
point, and points at nothing, so rule 3 is untouched. It is click-through,
topmost, never activated and excluded from screen capture (so perception and
the D179 picture never see it). It draws only in WM_PAINT; its timer moves
the window and invalidates (rule 4). It shows only while Orbyn is busy or
listening, and the island hides it when a full-screen app is in front.

The badge has real per-pixel alpha: it is rendered (Pillow, 4x, then scaled
down) to a premultiplied bitmap that WM_PAINT hands to UpdateLayeredWindow,
so the pill and dot have soft edges on any background, at the display's
scaling. A colour-keyed window can only have hard, stepped edges."""

from __future__ import annotations

import ghostcursor.overlay.dpi  # noqa: F401  (rule 4: before any overlay)

import ctypes
import functools
import math
import time
from ctypes import wintypes

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import win32api
import win32con
import win32gui

from ghostcursor.overlay.window import ensure_class

CLASS = "OrbynCompanion"
OFFSET = (18, 22)  # below-right of the arrow's hotspot, clear of the arrow
SIZE = (132, 28)
TIMER_ID, TIMER_MS = 9, 30
WDA_EXCLUDEFROMCAPTURE = 0x11
BG = (22, 26, 34, 236)  # RGBA: nearly opaque, so the pill reads on any app
TEXT = (249, 247, 242, 255)
AMBER = (239, 182, 96, 255)
BLUE = (64, 156, 235, 255)
SMOOTH = 4  # shapes are drawn this many times larger, then scaled down
ULW_ALPHA, AC_SRC_ALPHA = 2, 1
#: Click-through, always on top, never in Alt+Tab, never takes focus.
EX_STYLE = (
    win32con.WS_EX_LAYERED
    | win32con.WS_EX_TRANSPARENT
    | win32con.WS_EX_TOPMOST
    | win32con.WS_EX_TOOLWINDOW
    | win32con.WS_EX_NOACTIVATE
)
_windows: dict[int, "Companion"] = {}
_scale = 1.0  # display scaling (DPI / 96); sizes are 96-DPI design units

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SetTimer.argtypes = (
    wintypes.HWND,
    ctypes.c_size_t,
    wintypes.UINT,
    ctypes.c_void_p,
)
_user32.SetTimer.restype = ctypes.c_size_t
_user32.SetWindowDisplayAffinity.argtypes = (wintypes.HWND, wintypes.DWORD)
_user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
_user32.KillTimer.argtypes = (wintypes.HWND, ctypes.c_size_t)
_user32.KillTimer.restype = wintypes.BOOL
_user32.GetDC.argtypes = (wintypes.HWND,)
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)


class _Size(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class _Blend(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
        ("bmiColors", wintypes.DWORD * 3),
    ]


_user32.UpdateLayeredWindow.argtypes = (
    wintypes.HWND,
    wintypes.HDC,
    ctypes.c_void_p,
    ctypes.POINTER(_Size),
    wintypes.HDC,
    ctypes.POINTER(wintypes.POINT),
    wintypes.DWORD,
    ctypes.POINTER(_Blend),
    wintypes.DWORD,
)
_user32.UpdateLayeredWindow.restype = wintypes.BOOL
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
_gdi32.CreateCompatibleDC.restype = wintypes.HDC
_gdi32.CreateDIBSection.argtypes = (
    wintypes.HDC,
    ctypes.POINTER(_BitmapInfo),
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
)
_gdi32.CreateDIBSection.restype = wintypes.HBITMAP
_gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
_gdi32.SelectObject.restype = wintypes.HGDIOBJ
_gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
_gdi32.DeleteDC.argtypes = (wintypes.HDC,)


def size_px(scale: float) -> tuple[int, int]:
    """The badge window's size in device pixels at ``scale``."""

    return round(SIZE[0] * scale), round(SIZE[1] * scale)


def label(app, listener, *, fullscreen=False, idle=False) -> str | None:
    """What the badge says, or None to hide it. Generic state only: the
    busy label when it is one of the app's own activity names, never a goal.
    Hidden over a full-screen app, game or presentation. With ``idle`` (the
    companion_idle setting) a quiet Orbyn shows a resting dot: ""."""

    from ghostcursor.workspace.app import ACTIVITY_LABELS

    if fullscreen:
        return None
    if listener is not None and (
        listener.held is not None or listener.clock() < listener.armed_until
    ):
        return "Listening"
    if not app.busy:
        return "" if idle else None
    return app.busy if app.busy in ACTIVITY_LABELS else "Working"


def placement(cursor, size, work, scale=1.0):
    """Top-left of the badge: below-right of the pointer, flipped to the other
    side of it at the right or bottom edge of the work area."""

    (x, y), (width, height), (left, top, right, bottom) = cursor, size, work
    dx, dy = round(OFFSET[0] * scale), round(OFFSET[1] * scale)
    px, py = x + dx, y + dy
    if px + width > right:
        px = x - dx - width
    if py + height > bottom:
        py = y - dy - height
    return max(left, px), max(top, py)


def pulse(elapsed: float) -> float:
    """0..1, one breath every 1.2 s."""

    return 0.5 - 0.5 * math.cos(elapsed * 2 * math.pi / 1.2)


def blinking(elapsed: float) -> bool:
    """The resting dot blinks for 0.15 s every 5 s, as Clicky's does."""

    return elapsed % 5.0 >= 4.85


def radius(text: str, elapsed: float) -> int:
    """The dot's radius this frame: a breath, or for the resting dot a
    slower, smaller breath with a blink now and then (0 = not drawn)."""

    if text:
        return 4 + round(2 * pulse(elapsed))
    return 0 if blinking(elapsed) else 3 + round(pulse(elapsed / 2))


@functools.lru_cache(maxsize=4)
def _font(scale: float):
    try:
        return ImageFont.truetype("seguisb.ttf", round(13 * scale))  # Segoe UI Semibold
    except OSError:
        return ImageFont.load_default(round(13 * scale))


@functools.lru_cache(maxsize=64)
def render(text: str, r: int, scale: float) -> Image.Image:
    """The badge as an RGBA image ``size_px(scale)`` big: a pill with a dot
    and ``text``, or just the dot's disc when ``text`` is "" (the resting
    dot). Shapes are drawn SMOOTH times larger and scaled down, so every
    curve has soft edges; text is drawn at size, so it stays sharp."""

    width, height = size_px(scale)
    font = _font(scale)
    label = text
    left_pad, right_pad = 28 * scale, 12 * scale
    while label and left_pad + font.getlength(label) + right_pad > width:
        label = label[:-2].rstrip(" …") + "…" if len(label) > 2 else ""  # ellipsis to fit
    right = (
        min(width, round(left_pad + font.getlength(label) + right_pad))
        if text
        else height
    )
    big = Image.new("RGBA", (width * SMOOTH, height * SMOOTH), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    draw.rounded_rectangle(
        (0, 0, right * SMOOTH - 1, height * SMOOTH - 1),
        radius=height * SMOOTH // 2,
        fill=BG,
    )
    if r:
        cx = (15 * scale if text else height / 2) * SMOOTH
        cy, rr = height / 2 * SMOOTH, r * scale * SMOOTH
        color = BLUE if text == "Listening" else AMBER
        draw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=color)
    image = big.reduce(SMOOTH)  # box average: exact mixes, no ringing
    if label:
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).text(
            (left_pad, height / 2), label, font=font, fill=TEXT, anchor="lm"
        )
        image = Image.alpha_composite(image, layer)
    return image


def _premultiplied(image: Image.Image) -> bytes:
    """BGRA bytes with colour premultiplied by alpha, as UpdateLayeredWindow
    wants them."""

    rgba = np.asarray(image, dtype=np.uint16)
    alpha = rgba[..., 3:4]
    bgr = (rgba[..., 2::-1] * alpha + 127) // 255
    return np.concatenate([bgr, alpha], axis=-1).astype(np.uint8).tobytes()


def _present(hwnd, image: Image.Image) -> bool:
    """Hand ``image`` to the layered window (per-pixel alpha)."""

    width, height = image.size
    data = _premultiplied(image)
    screen = _user32.GetDC(None)
    memory = _gdi32.CreateCompatibleDC(screen)
    info = _BitmapInfo()
    info.biSize = ctypes.sizeof(_BitmapInfo) - ctypes.sizeof(wintypes.DWORD * 3)
    info.biWidth, info.biHeight = width, -height  # top-down rows
    info.biPlanes, info.biBitCount = 1, 32
    bits = ctypes.c_void_p()
    bitmap = _gdi32.CreateDIBSection(memory, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
    try:
        if not bitmap or not bits.value:
            return False
        ctypes.memmove(bits, data, len(data))
        old = _gdi32.SelectObject(memory, bitmap)
        ok = _user32.UpdateLayeredWindow(
            hwnd,
            screen,
            None,  # keep the position follow() set
            ctypes.byref(_Size(width, height)),
            memory,
            ctypes.byref(wintypes.POINT(0, 0)),
            0,
            ctypes.byref(_Blend(0, 0, 255, AC_SRC_ALPHA)),
            ULW_ALPHA,
        )
        _gdi32.SelectObject(memory, old)
        return bool(ok)
    finally:
        if bitmap:
            _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(memory)
        _user32.ReleaseDC(None, screen)


class Companion:
    def __init__(self, cursor):
        global _scale
        _scale = _user32.GetDpiForSystem() / 96  # the process is dpi aware (rule 4)
        self.cursor = cursor  # () -> (x, y): the OS pointer, never a model point
        self.text: str | None = None
        self.started = time.monotonic()
        self.at = None
        self.frame = None  # the dot radius last painted by the timer
        self.pointer = None  # the cursor position last looked up
        ensure_class(CLASS, _wnd_proc, 0)
        self.hwnd = win32gui.CreateWindowEx(
            EX_STYLE,
            CLASS,
            "Orbyn companion",
            win32con.WS_POPUP,
            0,
            0,
            *size_px(_scale),
            None,
            None,
            win32api.GetModuleHandle(None),
            None,
        )
        # Kept out of screenshots, so perception and the D179 picture never see
        # it. Where Windows refuses (before 10 2004), the badge never shows.
        self.capturable = not _user32.SetWindowDisplayAffinity(
            self.hwnd, WDA_EXCLUDEFROMCAPTURE
        )
        _windows[self.hwnd] = self

    def show(self, text: str | None) -> None:
        """Called on the UI thread each island tick."""

        if self.capturable:
            text = None  # it would appear in screen captures
        if text == self.text:
            return
        if text is None:
            _user32.KillTimer(self.hwnd, TIMER_ID)
            win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
        elif self.text is None:
            self.started = time.monotonic()
            self.follow()
            win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)
            _user32.SetTimer(self.hwnd, TIMER_ID, TIMER_MS, None)
        self.text = text
        win32gui.InvalidateRect(self.hwnd, None, True)

    def follow(self) -> None:
        try:
            cursor = self.cursor()
            if cursor == self.pointer and self.at is not None:
                return  # the pointer has not moved: nothing to look up
            self.pointer = cursor
            monitor = win32api.MonitorFromPoint(
                cursor, win32con.MONITOR_DEFAULTTONEAREST
            )
            work = win32api.GetMonitorInfo(monitor)["Work"]
        except Exception:
            return  # secure desktop or no pointer: stay where it was
        at = placement(cursor, size_px(_scale), work, _scale)
        if at != self.at:
            try:  # a decoration never ends the session
                win32gui.SetWindowPos(
                    self.hwnd,
                    win32con.HWND_TOPMOST,
                    *at,
                    0,
                    0,
                    win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
                )
            except win32gui.error:
                return
            self.at = at

    def destroy(self) -> None:
        if win32gui.IsWindow(self.hwnd):
            win32gui.DestroyWindow(self.hwnd)


def _paint(companion) -> None:
    if companion.text is None:
        return
    elapsed = time.monotonic() - companion.started
    image = render(companion.text, radius(companion.text, elapsed), _scale)
    _present(companion.hwnd, image)


def _wnd_proc(hwnd, msg, wparam, lparam):
    companion = _windows.get(hwnd)
    if msg == win32con.WM_PAINT:
        _hdc, paint = win32gui.BeginPaint(hwnd)
        win32gui.EndPaint(hwnd, paint)
        if companion is not None:
            _paint(companion)  # UpdateLayeredWindow, from WM_PAINT only (rule 4)
        return 0
    if msg == win32con.WM_ERASEBKGND:
        return 1  # the layered bitmap is every pixel; nothing to erase
    if msg == win32con.WM_TIMER and wparam == TIMER_ID and companion is not None:
        companion.follow()
        frame = radius(companion.text or "", time.monotonic() - companion.started)
        if frame != companion.frame:  # repaint only when the dot changes
            companion.frame = frame
            win32gui.InvalidateRect(hwnd, None, False)
        return 0
    if msg == win32con.WM_DESTROY:
        _user32.KillTimer(hwnd, TIMER_ID)
        _windows.pop(hwnd, None)
        return 0
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

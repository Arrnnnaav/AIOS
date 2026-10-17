"""Act on any application (D182): perform one plan step on the control the
harness observed and Jev chose.

The ONLY module allowed to synthesize input (tests/test_no_input_synthesis.py).
Input lands only at the centre of an observed control's current rectangle --
never at a position a model supplied. The session asks the user to approve the
plan first and to confirm risky controls; ESC stops the loop between steps.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.OpenInputDesktop.restype = wintypes.HANDLE
_user32.GetUserObjectInformationW.argtypes = (
    wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p
)  # fmt: skip
_user32.CloseDesktop.argtypes = (wintypes.HANDLE,)
_user32.WindowFromPoint.restype = wintypes.HWND
_user32.WindowFromPoint.argtypes = (wintypes.POINT,)
_user32.GetAncestor.restype = wintypes.HWND
_user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
_user32.GetWindowThreadProcessId.argtypes = (
    wintypes.HWND,
    ctypes.POINTER(wintypes.DWORD),
)

_INPUT_MOUSE, _INPUT_KEYBOARD = 0, 1
_KEYUP, _UNICODE = 0x0002, 0x0004
_MOVE, _LEFTDOWN, _LEFTUP = 0x0001, 0x0002, 0x0004
_ABSOLUTE, _VIRTUALDESK = 0x8000, 0x4000
_ULONG_PTR = ctypes.c_size_t

#: Named keys for "keys" steps; letters, digits and f1-f12 are computed.
_VK = {
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B,
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "space": 0x20,
    "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
}  # fmt: skip


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _UNION)]


def _send(events: list[_INPUT]) -> None:
    if not events:
        return
    array = (_INPUT * len(events))(*events)
    sent = _user32.SendInput(len(events), array, ctypes.sizeof(_INPUT))
    if sent != len(events):
        raise OSError(f"SendInput delivered {sent} of {len(events)} events")


def _key(vk: int = 0, *, up: bool = False, char: str = "") -> _INPUT:
    flags = (_KEYUP if up else 0) | (_UNICODE if char else 0)
    event = _INPUT(type=_INPUT_KEYBOARD)
    event.u.ki = _KEYBDINPUT(vk, ord(char) if char else 0, flags, 0, 0)
    return event


def vk_of(name: str) -> int:
    name = name.strip().casefold()
    if name in _VK:
        return _VK[name]
    if len(name) == 1 and name.isalnum():
        return ord(name.upper())
    if name.startswith("f") and name[1:].isdigit() and 1 <= int(name[1:]) <= 12:
        return 0x70 + int(name[1:]) - 1
    raise ValueError(f"unknown key {name!r}")


def chord_events(chord: str) -> list[_INPUT]:
    """``ctrl+shift+s`` -> modifiers down, key down/up, modifiers up. ESC is
    refused: it is the user's stop key, not the model's."""

    names = [n for n in chord.replace(" ", "").split("+") if n]
    if not names or any(n.casefold() in ("esc", "escape") for n in names):
        raise ValueError(f"refused key chord {chord!r}")
    vks = [vk_of(n) for n in names]
    return [_key(v) for v in vks] + [_key(v, up=True) for v in reversed(vks)]


def text_events(text: str) -> list[_INPUT]:
    events = []
    for char in text.replace("\r\n", "\n"):
        if char == "\n":
            events += [_key(0x0D), _key(0x0D, up=True)]
        else:
            events += [_key(char=char), _key(char=char, up=True)]
    return events


def _open_clipboard(c, tries: int = 5):
    """OpenClipboard, retrying briefly: another process may hold it for a
    moment. Raises OSError if it stays locked."""

    for _ in range(tries):
        try:
            c.OpenClipboard()
            return
        except Exception:
            time.sleep(0.02)
    raise OSError("the clipboard is held by another program")


def get_clipboard_text() -> str | None:
    """The clipboard's text, or None if it holds no text. Read ONLY so the
    user's prior clipboard can be put back after a paste; the value stays on
    this machine -- it is never sent to a model, stored or logged."""

    import win32clipboard as c

    _open_clipboard(c)
    try:
        if c.IsClipboardFormatAvailable(c.CF_UNICODETEXT):
            return c.GetClipboardData(c.CF_UNICODETEXT)
        return None
    finally:
        c.CloseClipboard()


def set_clipboard_text(text: str | None) -> None:
    """Put ``text`` on the clipboard, or clear it when ``text`` is falsy. Used
    to carry known text into an app and to restore the prior clipboard after;
    Orbyn's text is never left behind (restore clears it when the prior
    clipboard was empty or non-text)."""

    import win32clipboard as c

    _open_clipboard(c)
    try:
        c.EmptyClipboard()
        if text:
            c.SetClipboardData(c.CF_UNICODETEXT, text)
    finally:
        c.CloseClipboard()


def click_at(x: int, y: int) -> None:
    left = _user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    top = _user32.GetSystemMetrics(77)
    width = max(2, _user32.GetSystemMetrics(78))
    height = max(2, _user32.GetSystemMetrics(79))
    dx = round((x - left) * 65535 / (width - 1))
    dy = round((y - top) * 65535 / (height - 1))
    events = []
    for flags in (_MOVE, _LEFTDOWN, _LEFTUP):
        event = _INPUT(type=_INPUT_MOUSE)
        event.u.mi = _MOUSEINPUT(dx, dy, 0, flags | _ABSOLUTE | _VIRTUALDESK, 0, 0)
        events.append(event)
    _send(events)


def _elevated(pid: int | None = None) -> bool | None:
    """True if the process runs elevated; None if it cannot be asked."""

    kernel32, advapi32 = ctypes.WinDLL("kernel32"), ctypes.WinDLL("advapi32")
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    advapi32.OpenProcessToken.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)
    )  # fmt: skip
    advapi32.GetTokenInformation.argtypes = (
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )  # fmt: skip
    process = (
        kernel32.GetCurrentProcess()
        if pid is None
        else kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    )
    if not process:
        return None
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(process, 0x0008, ctypes.byref(token)):
            return None
        value, size = wintypes.DWORD(), wintypes.DWORD()
        ok = advapi32.GetTokenInformation(
            token,
            20,
            ctypes.byref(value),
            4,
            ctypes.byref(size),  # TokenElevation
        )
        kernel32.CloseHandle(token)
        return bool(value.value) if ok else None
    finally:
        if pid is not None:
            kernel32.CloseHandle(process)


def blocker(x: int, y: int) -> str | None:
    """Why input at (x, y) must not be sent now, or None (D182; the checks
    Dodaios makes before input). The secure desktop (UAC prompt, lock
    screen) swallows input; an elevated window drops input from a
    non-elevated sender (UIPI), so a click would silently do nothing."""

    desktop = _user32.OpenInputDesktop(0, False, 0x0001)  # DESKTOP_READOBJECTS
    if not desktop:
        return "the screen is locked or a Windows security prompt is open"
    name = ctypes.create_unicode_buffer(64)
    _user32.GetUserObjectInformationW(desktop, 2, name, 128, None)  # UOI_NAME
    _user32.CloseDesktop(desktop)
    if name.value.casefold() != "default":
        return "the screen is locked or a Windows security prompt is open"
    hwnd = _user32.WindowFromPoint(wintypes.POINT(x, y))
    root = _user32.GetAncestor(hwnd, 2) if hwnd else 0  # GA_ROOT
    pid = wintypes.DWORD()
    if root:
        _user32.GetWindowThreadProcessId(root, ctypes.byref(pid))
    if pid.value and _elevated(pid.value) and not _elevated():
        return "that window runs as administrator; Orbyn cannot act in it"
    return None


def perform(
    step,
    target,
    *,
    send=_send,
    click=click_at,
    pause=time.sleep,
    check=blocker,
    set_clip=set_clipboard_text,
    get_clip=get_clipboard_text,
) -> str:
    """Do ``step`` on ``target`` (a Candidate in the latest frame); returns a
    short description for the status line."""

    left, top, right, bottom = target.rect
    x, y = (left + right) // 2, (top + bottom) // 2
    action = step.action
    if action == "none":
        return "nothing to do"
    if action == "keys":
        events = chord_events(step.text)  # validate before touching anything
    reason = check(x, y)
    if reason:
        raise PermissionError(reason)
    click(x, y)  # every other action starts by focusing the observed control
    if action == "click":
        return f"clicked {target.name or target.control_type}"
    pause(0.15)  # let focus land before keys arrive
    if action == "type":
        send(text_events(step.text))
        return f"typed {len(step.text)} characters"
    if action == "paste":
        send(chord_events("ctrl+v"))
        return "pasted"
    if action == "paste_text":
        # Cross-app context carry (D182 activation): put text Orbyn holds on the
        # clipboard, paste it into the observed control, then restore the user's
        # prior clipboard so Orbyn's text is never left behind. The content is
        # Orbyn's to paste (from the plan/brief), not read from the screen.
        if not step.text:
            return "nothing to paste"
        saved = get_clip()
        try:
            set_clip(step.text)
            send(chord_events("ctrl+v"))
            pause(0.2)  # ponytail: fixed wait for the app to read the clipboard
            #            before we restore; a slow app could miss it -- raise it
            #            if that shows up, or gate restore on a paste ack.
        finally:
            set_clip(saved)  # always restore, even if the paste raised
        return f"pasted {len(step.text)} characters"
    if action == "copy":
        send(chord_events("ctrl+c"))
        return "copied the selection"
    send(events)
    return f"pressed {step.text}"

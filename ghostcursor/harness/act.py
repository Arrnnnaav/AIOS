"""Act on any application (D182): perform one plan step on the control the
harness observed and Jev chose.

The ONLY module allowed to synthesize input (tests/test_no_input_synthesis.py).
Input lands only at the centre of an observed control's current rectangle --
never at a position a model supplied. The session asks the user to approve the
plan first and to confirm risky controls; ESC stops the loop between steps.
"""

from __future__ import annotations

import ctypes
import threading
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
_user32.GetWindow.restype = wintypes.HWND
_user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
_user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_user32.GetForegroundWindow.restype = wintypes.HWND

_INPUT_MOUSE, _INPUT_KEYBOARD = 0, 1
#: Stamped in dwExtraInfo of every event Orbyn sends ("ORBN"), so a hook or an
#: audit can tell Orbyn's input from the user's (Aside stamps "SUCE" the same
#: way and skips it in its low-level hooks).
INPUT_SIGNATURE = 0x4E42524F
#: Before acting, Orbyn waits for the user to let go of any key or mouse
#: button (Aside's check, minus its hook). A whole perform() -- this wait, the
#: 0.15 s focus pause and paste_text's two clipboard opens (0.1 s each at
#: worst) -- stays under D020's 0.5 s; a longer hold retries on the next tick.
#: paste_text's restore wait (PASTE_SETTLE_S) and restore run after perform() returns.
MAX_HELD_WAIT_S = 0.1
_VK_ESCAPE = 0x1B
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
    event.u.ki = _KEYBDINPUT(vk, ord(char) if char else 0, flags, 0, INPUT_SIGNATURE)
    return event


def vk_of(name: str) -> int:
    name = name.strip().casefold()
    if name in _VK:
        return _VK[name]
    if len(name) == 1 and name.isascii() and name.isalnum():  # not media keys
        return ord(name.upper())
    if name.startswith("f") and name[1:].isdigit() and 1 <= int(name[1:]) <= 12:
        return 0x70 + int(name[1:]) - 1
    raise ValueError(f"unknown key {name!r}")


def chord_events(chord: str) -> list[_INPUT]:
    """``ctrl+shift+s`` -> modifiers down, key down/up, modifiers up. ESC is
    refused: it is the user's stop key, not the model's. The Windows key and
    Alt+Tab are refused too: they reach the shell or another app, outside the
    window the user approved (Aside's computer-use helper refuses them too)."""

    # An empty part ("ctrl++") reaches vk_of and is refused, not dropped:
    # dropping it would send a different chord from the one the plan showed.
    names = ["".join(n.split()).casefold() for n in chord.split("+")]  # "page down"
    if {"esc", "escape"} & set(names):
        raise ValueError(f"refused key chord {chord!r}")
    vks = [vk_of(n) for n in names]
    # Judged on the key codes, so no spelling of a name slips past.
    if {0x1B, 0x5B, 0x5C} & set(vks) or {0x12, 0x09} <= set(vks):
        raise ValueError(f"refused key chord {chord!r}")
    return [_key(v) for v in vks] + [_key(v, up=True) for v in reversed(vks)]


def text_events(text: str) -> list[_INPUT]:
    events = []
    for char in text.replace("\r\n", "\n"):
        if char == "\n":
            events += [_key(0x0D), _key(0x0D, up=True)]
        else:  # wScan is 16 bits: an emoji goes as its surrogate pair
            units = char.encode("utf-16-le")
            for unit in (units[i : i + 2] for i in range(0, len(units), 2)):
                code = chr(int.from_bytes(unit, "little"))
                events += [_key(char=code), _key(char=code, up=True)]
    return events


def _open_clipboard(c, tries: int = 5, owner=None):
    """OpenClipboard, retrying briefly: another process may hold it for a
    moment. Raises OSError if it stays locked. ``owner`` becomes the
    clipboard's owner (delayed rendering needs one)."""

    for _ in range(tries):
        try:
            c.OpenClipboard(owner) if owner else c.OpenClipboard()
            return
        except Exception:
            time.sleep(0.02)
    raise OSError("the clipboard is held by another program")


def get_clipboard_text() -> str | None:
    """The clipboard's text, or None if it is empty. Read ONLY so the
    user's prior clipboard can be put back after a paste; the value stays on
    this machine -- it is never sent to a model, stored or logged. A picture
    or copied files cannot be put back as text, so paste_text is refused
    then instead of emptying the user's clipboard."""

    import win32clipboard as c

    _open_clipboard(c)
    try:
        if c.IsClipboardFormatAvailable(c.CF_UNICODETEXT):
            # Text beside a picture or files: the restore puts back text only,
            # so the picture would be lost. Refuse that case as for a picture.
            # PNG is a registered format (browsers copy images as it); HTML
            # and RTF are not counted: only formatting is lost with them.
            png = c.RegisterClipboardFormat("PNG")
            if any(c.IsClipboardFormatAvailable(f) for f in (*_NON_TEXT_FORMATS, png)):
                raise PermissionError(
                    "the clipboard holds a picture or files, so Orbyn did not paste over it"
                )
            return c.GetClipboardData(c.CF_UNICODETEXT)
        if c.CountClipboardFormats():
            raise PermissionError(
                "the clipboard holds a picture or files, so Orbyn did not paste over it"
            )
        return None
    finally:
        c.CloseClipboard()


#: CF_BITMAP, CF_METAFILEPICT, CF_TIFF, CF_DIB, CF_ENHMETAFILE, CF_HDROP,
#: CF_DIBV5: what a text-only restore cannot put back.
_NON_TEXT_FORMATS = (2, 3, 6, 8, 14, 15, 17)


#: Registered formats that keep a clipboard entry out of Windows clipboard
#: history, cloud clipboard sync and clipboard monitors: what Orbyn puts there
#: is plan text on its way into one field, not something to keep or upload.
_PRIVATE_FORMATS = (
    ("ExcludeClipboardContentFromMonitorProcessing", b"\x00\x00\x00\x00"),
    ("CanIncludeInClipboardHistory", b"\x00\x00\x00\x00"),
    ("CanUploadToCloudClipboard", b"\x00\x00\x00\x00"),
)


def set_clipboard_text(text: str | None) -> None:
    """Put ``text`` on the clipboard, or clear it when ``text`` is falsy. Used
    to carry known text into an app and to restore the prior clipboard after;
    Orbyn's text is never left behind (restore clears it when the prior
    clipboard was empty or non-text). Neither write enters clipboard history
    or cloud sync: Orbyn's text is not the user's, and the user's restored
    text is already there from when they copied it."""

    import win32clipboard as c

    _open_clipboard(c)
    try:
        _write_clipboard(c, text)
    finally:
        c.CloseClipboard()


def _write_clipboard(c, text) -> None:
    c.EmptyClipboard()
    if text:
        c.SetClipboardData(c.CF_UNICODETEXT, text)
        for name, value in _PRIVATE_FORMATS:
            c.SetClipboardData(c.RegisterClipboardFormat(name), value)


def restore_clipboard_text(text, ours: int, sequence=None) -> bool:
    """Put the user's prior clipboard back, unless they copied something
    since Orbyn set its text (the change counter moved from OURS). Checked
    and written while the clipboard is held open, so a copy cannot slip in
    between the check and the write. Returns whether it restored."""

    import win32clipboard as c

    _open_clipboard(c)
    try:
        if (sequence or clipboard_sequence)() != ours:
            return False  # the user's newer copy stays
        _write_clipboard(c, text)
        return True
    finally:
        c.CloseClipboard()


class DelayedPaste:
    """Orbyn's text offered on the clipboard by delayed rendering: Windows
    asks Orbyn for it (WM_RENDERFORMAT) at the moment an app pastes, which
    is the paste's acknowledgement; the user's clipboard then goes back at
    once instead of after a guessed wait. Checked on this PC 26 Nov: another
    process's read raised the request and it does not move the clipboard's
    change counter. Only a request from the app being pasted into counts
    (``target_pid``): on this PC Remote Desktop's clipboard sync (msrdc.exe)
    read every new clipboard at once, which must not end the wait. Without
    the app's own request the restore waits ``wait_s`` as before."""

    CLASS = "OrbynDelayedPaste"
    _registered = False

    def __init__(self, text: str, target_pid: int | None = None):
        self.text = text
        self.target_pid = target_pid
        self.ours = 0
        self._sent_at = None
        self._rendered_after_send = threading.Event()
        self._ready = threading.Event()
        self._done = threading.Event()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="OrbynDelayedPaste", daemon=True)
        self._thread.start()
        if not self._ready.wait(2) or self._error is not None:
            self.close()
            raise OSError("the clipboard is held by another program")

    def _proc(self, hwnd, msg, wparam, lparam):
        import win32clipboard as c
        import win32con
        import win32gui

        if msg == win32con.WM_RENDERFORMAT and wparam == c.CF_UNICODETEXT:
            reader = _user32.GetOpenClipboardWindow()
            c.SetClipboardData(c.CF_UNICODETEXT, self.text)  # Windows holds it open
            if self._sent_at is not None and self._is_target(reader):
                self._rendered_after_send.set()
            return 0
        if msg == win32con.WM_RENDERALLFORMATS:
            return 0  # leaving: Orbyn's text is not left behind on purpose
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _run(self):
        import win32api
        import win32clipboard as c
        import win32gui

        try:
            module = win32api.GetModuleHandle(None)
            if not DelayedPaste._registered:
                wc = win32gui.WNDCLASS()
                wc.lpszClassName = self.CLASS
                wc.lpfnWndProc = lambda *a: _delayed_proc(*a)
                wc.hInstance = module
                win32gui.RegisterClass(wc)
                DelayedPaste._registered = True
            hwnd = win32gui.CreateWindowEx(0, self.CLASS, "", 0, 0, 0, 0, 0, -3, None, module, None)
            _delayed_by_hwnd[hwnd] = self
            _open_clipboard(c, owner=hwnd)
            try:
                c.EmptyClipboard()
                _set_delayed(c.CF_UNICODETEXT)
                for name, value in _PRIVATE_FORMATS:
                    c.SetClipboardData(c.RegisterClipboardFormat(name), value)
            finally:
                c.CloseClipboard()
            self.ours = clipboard_sequence()
        except Exception as exc:  # noqa: BLE001 - reported to the caller
            self._error = exc
            self._ready.set()
            return
        self._ready.set()
        try:
            while not self._done.is_set():
                win32gui.PumpWaitingMessages()
                self._done.wait(0.005)
        finally:
            _delayed_by_hwnd.pop(hwnd, None)
            win32gui.DestroyWindow(hwnd)

    def _is_target(self, reader: int) -> bool:
        if self.target_pid is None:
            return True
        if not reader:
            return False  # a reader with no window cannot be told apart
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(reader, ctypes.byref(pid))
        return pid.value == self.target_pid

    def sent(self) -> None:
        """Ctrl+V has gone out: a render request from now on is the paste."""

        self._sent_at = time.monotonic()

    def restore_after_paste(self, saved, wait_s: float, sequence=None) -> bool:
        """Wait for the paste (at most WAIT_S), then put the user's clipboard
        back unless they copied something since. Returns whether the paste
        was acknowledged."""

        acknowledged = self._rendered_after_send.wait(wait_s)
        try:
            _quietly(restore_clipboard_text, saved, self.ours, sequence)
        finally:
            self.close()
        return acknowledged

    def close(self) -> None:
        self._done.set()


_delayed_by_hwnd: dict = {}


def _delayed_proc(hwnd, msg, wparam, lparam):
    offer = _delayed_by_hwnd.get(hwnd)
    if offer is not None:
        return offer._proc(hwnd, msg, wparam, lparam)
    import win32gui

    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


def _set_delayed(fmt: int) -> None:
    """SetClipboardData with no data: Windows asks the owner when an app
    reads it (delayed rendering). pywin32 refuses a NULL handle."""

    _user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    _user32.SetClipboardData.restype = ctypes.c_void_p
    _user32.SetClipboardData(fmt, None)


def clipboard_sequence() -> int:
    """Windows' clipboard change counter: it moves on every new copy."""

    get = _user32.GetClipboardSequenceNumber
    get.restype = wintypes.DWORD
    return get()


#: The clipboard restore still running from the last paste_text, if any.
_restoring: list[threading.Thread] = []


def _in_background(job) -> None:
    """Run JOB on a thread perform() does not wait for. Not a daemon: a
    session that quits right after a paste still puts the clipboard back."""

    thread = threading.Thread(target=job, name="OrbynClipboardRestore")
    _restoring[:] = [thread]
    thread.start()


def _quietly(set_clip, *args) -> None:
    try:
        set_clip(*args)
    except Exception:
        pass  # a locked clipboard at restore time must not propagate
        #       or mask the paste's own error (tier-1 review followup)


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
        event.u.mi = _MOUSEINPUT(
            dx, dy, 0, flags | _ABSOLUTE | _VIRTUALDESK, 0, INPUT_SIGNATURE
        )
        events.append(event)
    _send(events)


#: How long a paste_text waits before putting the user's clipboard back
#: (was 0.2 s: a slow app could read the restored clipboard instead).
PASTE_SETTLE_S = 1.0


class UserBusy(PermissionError):
    """The user is holding a key or mouse button; try the step again later."""

    retry = True


def held_input() -> bool:
    """True while any key or mouse button is physically down (GetAsyncKeyState
    high bit; toggle state such as Caps Lock is ignored). ESC is never read
    here: each read clears its "pressed since last call" bit, and the session's
    ESC poll needs that bit to catch a quick tap (review of 436d779)."""

    return any(
        _user32.GetAsyncKeyState(vk) & 0x8000
        for vk in range(1, 255)
        if vk != _VK_ESCAPE
    )


def wait_for_release(held, pause) -> None:
    """Return once nothing is held; raise UserBusy if something still is
    after MAX_HELD_WAIT_S."""

    for _ in range(round(MAX_HELD_WAIT_S / 0.05)):  # a count: floats drift
        if not held():
            return
        pause(0.05)
    if held():
        raise UserBusy("you are holding a key or mouse button, so Orbyn is waiting")


def _foreground_root() -> int:
    hwnd = _user32.GetForegroundWindow()
    return _user32.GetAncestor(hwnd, 2) if hwnd else 0  # GA_ROOT


def _focused_runtime_id() -> tuple[int, ...]:
    """UI Automation runtime id of the element with keyboard focus, or ()."""

    try:
        from pywinauto.uia_defines import IUIA

        element = IUIA().iuia.GetFocusedElement()
        return tuple(int(v) for v in element.GetRuntimeId())
    except Exception:
        return ()


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


def blocker(x: int, y: int, window: int | None = None) -> str | None:
    """Why input at (x, y) must not be sent now, or None (D182; the checks
    Dodaios makes before input). The secure desktop (UAC prompt, lock
    screen) swallows input; an elevated window drops input from a
    non-elevated sender (UIPI), so a click would silently do nothing. With
    WINDOW (the bound window the control was observed in), the point must
    also land on a window of that app: another app's window on top would
    take the click (Aside's computer-use helper refuses the same case).
    Click-through windows, such as Orbyn's own overlay, are not hit."""

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
    if window is not None and not _on_bound_window(root, window):
        return "that control is off screen or covered by another window"
    return None


def _on_bound_window(root: int, window: int) -> bool:
    """True if ROOT, the top-level window under the point, is the bound
    window, a window it owns (its dialogs), or a menu on its UI thread.
    Another window of the same app (a second presentation) is not."""

    bound = _user32.GetAncestor(window, 2) if window else 0  # GA_ROOT
    if not root or not bound:
        return False
    owner = root
    for _ in range(16):  # owner chains are short; a cycle must not hang
        if not owner:
            break
        if owner == bound:
            return True
        owner = _user32.GetWindow(owner, 4)  # GW_OWNER
    name = ctypes.create_unicode_buffer(16)
    _user32.GetClassNameW(root, name, 16)
    return name.value == "#32768" and _user32.GetWindowThreadProcessId(
        root, None
    ) == _user32.GetWindowThreadProcessId(bound, None)


def perform(
    step,
    target,
    *,
    window: int,
    send=_send,
    click=click_at,
    pause=time.sleep,
    check=blocker,
    set_clip=set_clipboard_text,
    get_clip=get_clipboard_text,
    focus=None,
    held=None,
    later=_in_background,
    focused_id=None,
    clip_seq=clipboard_sequence,
) -> str:
    """Do ``step`` on ``target`` (a Candidate in the latest frame); returns a
    short description for the status line. ``window`` is the bound window
    ``target`` was observed in: required, so no caller can skip the check
    that the point and the focus are still on that window."""

    from ghostcursor import policy

    if policy.act_disabled():  # D180: the organisation allows guidance only
        raise PermissionError("your organisation allows Orbyn to guide, not act")
    if not window:
        raise PermissionError("no bound window, so Orbyn will not act")
    left, top, right, bottom = target.rect
    x, y = (left + right) // 2, (top + bottom) // 2
    action = step.action
    if action == "none":
        return "nothing to do"
    for pending in _restoring:  # a paste still restoring finishes first, so a
        pending.join()  # later paste never reads Orbyn's own text as the user's
    if action == "type_focused":
        # Dictation (D188): type into the field the user clicked, where the
        # user left the caret. Never clicks (a click would move the caret);
        # never a line break (Enter can send a message). Not in the plan
        # schema, so a model cannot ask for it.
        if not step.text or not step.text.isprintable():  # no Enter, Tab, ESC
            raise ValueError("dictation is typed as one line of plain text")
        wait_for_release(held or held_input, pause)
        reason = check(x, y, window)
        if reason:
            raise PermissionError(reason)
        if window is None or not _on_bound_window(
            (focus or _foreground_root)(), window
        ):
            raise PermissionError(
                "that window is no longer in front, so nothing was typed"
            )
        if (focused_id or _focused_runtime_id)() != target.runtime_id:
            raise PermissionError(
                "the cursor moved to another field, so nothing was typed"
            )
        send(text_events(step.text))
        return f"typed {len(step.text)} characters"
    if action == "keys":
        events = chord_events(step.text)  # validate before touching anything
    if action == "paste_text" and step.text:
        saved = get_clip()  # refuses a picture or files before anything is sent
    wait_for_release(held or held_input, pause)
    reason = check(x, y, window)
    if reason:
        raise PermissionError(reason)
    click(x, y)  # every other action starts by focusing the observed control
    if action == "click":
        return f"clicked {target.name or target.control_type}"
    pause(0.15)  # let focus land before keys arrive
    # A toast or another app may take focus in that gap; keys must not follow it.
    if window is not None and not _on_bound_window(
        (focus or _foreground_root)(), window
    ):
        raise PermissionError("focus moved to another window, so nothing was typed")
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
        if set_clip is set_clipboard_text:  # the real clipboard: the paste is acknowledged
            pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
            offer = DelayedPaste(step.text, target_pid=pid.value or -1)
            try:
                send(chord_events("ctrl+v"))
                offer.sent()
            except BaseException:
                offer.close()
                _quietly(restore_clipboard_text, saved, offer.ours, clip_seq)
                raise
            later(lambda: offer.restore_after_paste(saved, PASTE_SETTLE_S, clip_seq))
            return f"pasted {len(step.text)} characters"
        try:
            set_clip(step.text)
            ours = clip_seq()
            send(chord_events("ctrl+v"))
        except BaseException:
            _quietly(set_clip, saved)  # always restore, even if the paste raised
            raise

        def restore():  # an injected clipboard (tests): the timed restore
            pause(PASTE_SETTLE_S)
            if clip_seq() == ours:
                _quietly(set_clip, saved)

        later(restore)  # off the step, so Stop is read again within D020's 0.5 s
        return f"pasted {len(step.text)} characters"
    if action == "copy":
        send(chord_events("ctrl+c"))
        return "copied the selection"
    send(events)
    return f"pressed {step.text}"

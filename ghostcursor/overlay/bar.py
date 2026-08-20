"""The control bar: a second, FOCUSABLE window beside the click-through overlay.

The overlay is WS_EX_TRANSPARENT | WS_EX_NOACTIVATE and must never take focus
or receive a click (D006, D009) -- which is exactly why it cannot carry its own
Stop button. This window is its deliberate inverse: it receives clicks, it can
take focus, and it is small and edge-positioned so it never covers the region a
hint might occupy.

It exists primarily as a SAFETY affordance. ESC is otherwise the only way out of
a full-screen topmost overlay and nothing on screen says so.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import win32api
import win32con
import win32gui

from ghostcursor.overlay import dpi
from ghostcursor.overlay.window import ensure_class, pump_messages_nonblocking

BAR_CLASS_NAME = "GhostCursorBar"
BAR_BG = win32api.RGB(28, 28, 34)

#: Edge inset and size, in physical pixels.
_BAR_WIDTH = 520
_BAR_HEIGHT = 56
_BAR_MARGIN = 24

#: Child control ids, sent back to the wnd proc in WM_COMMAND's low word.
ID_STOP = 1101
ID_PAUSE = 1102
ID_ASK = 1103
ID_STATUS = 1104

_BUTTON_WIDTH = 90
_BUTTON_HEIGHT = 32
_BUTTON_GAP = 12
_BUTTON_MARGIN = 12

_bar_brush = None


@dataclass(frozen=True)
class BarState:
    """What the bar has been clicked to request since the last
    `clear_requests()`. The caller (the tour's own loop) polls this -- the
    bar never acts on a request itself, it only records that one happened."""

    stop_requested: bool = False
    pause_requested: bool = False
    ask_requested: bool = False


#: Per-hwnd state. A module dict, not a closure, so `_on_command` stays a
#: module-level function that tests can call directly without synthesising a
#: real click (D006 -- synthesising input would violate it even in a test).
_bar_state: dict[int, BarState] = {}
_bar_status: dict[int, str] = {}
_bar_status_hwnd: dict[int, int] = {}
_panel_hwnd: dict[int, int] = {}
_pending_goal: dict[int, str] = {}

_PANEL_HEIGHT = 32
_PANEL_MARGIN = 12
ID_PANEL_EDIT = 1105


def bar_state(hwnd: int) -> BarState:
    """What has been requested on this bar since the last `clear_requests()`."""
    return _bar_state.get(hwnd, BarState())


def clear_requests(hwnd: int) -> None:
    """Reset every request flag, so a single click reads as one request, not
    one on every later poll."""
    _bar_state[hwnd] = BarState()


def set_status(hwnd: int, text: str) -> None:
    """Update the status line shown on the bar (e.g. "step 2 of 5")."""
    _bar_status[hwnd] = text
    static_hwnd = _bar_status_hwnd.get(hwnd)
    if static_hwnd:
        win32gui.SetWindowText(static_hwnd, text)


def get_status(hwnd: int) -> str:
    """The status text last set via `set_status`, or "" if none yet."""
    return _bar_status.get(hwnd, "")


def panel_is_open(hwnd: int) -> bool:
    """Whether the goal-input box is currently showing on this bar."""
    return hwnd in _panel_hwnd


def open_panel(hwnd: int) -> None:
    """Create the goal-input EDIT control, take focus for it, and record its
    handle. Safe to call again while already open -- it is a no-op then."""
    if hwnd in _panel_hwnd:
        return
    h_instance = win32api.GetModuleHandle(None)
    edit_style = (
        win32con.WS_CHILD
        | win32con.WS_VISIBLE
        | win32con.WS_BORDER
        | win32con.ES_AUTOHSCROLL
    )
    edit_x = _BUTTON_MARGIN
    edit_y = _BAR_HEIGHT
    edit_width = _BAR_WIDTH - 2 * _BUTTON_MARGIN
    edit_hwnd = win32gui.CreateWindowEx(
        0,
        "EDIT",
        "",
        edit_style,
        edit_x,
        edit_y,
        edit_width,
        _PANEL_HEIGHT,
        hwnd,
        ID_PANEL_EDIT,
        h_instance,
        None,
    )
    _panel_hwnd[hwnd] = edit_hwnd
    try:
        win32gui.SetForegroundWindow(hwnd)
    except win32gui.error:
        # Windows' foreground lock refuses this for a process that is not
        # already frontmost (measured repeatedly in this repo -- D038,
        # tests/test_focus.py). Accept the refusal once, silently: no
        # retry, no AttachThreadInput. The design's own principle (spec
        # 2026-08-21-control-bar-design.md S4.4) is that fighting the OS
        # for foreground is how focus-stealing bugs are born.
        pass
    win32gui.SetFocus(edit_hwnd)


def close_panel(hwnd: int) -> None:
    """Destroy the goal-input box without submitting anything. Safe to call
    when the panel is already closed."""
    edit_hwnd = _panel_hwnd.pop(hwnd, None)
    if edit_hwnd:
        try:
            win32gui.DestroyWindow(edit_hwnd)
        except win32gui.error:
            pass


def panel_text(hwnd: int) -> str:
    """The text currently in the goal-input box, or "" if the panel is closed."""
    edit_hwnd = _panel_hwnd.get(hwnd)
    if not edit_hwnd:
        return ""
    return win32gui.GetWindowText(edit_hwnd)


def set_panel_text(hwnd: int, text: str) -> None:
    """Put text in the box directly, without synthesising keystrokes -- doing
    that would violate D006 (never generate input) even in a test."""
    edit_hwnd = _panel_hwnd.get(hwnd)
    if edit_hwnd:
        win32gui.SetWindowText(edit_hwnd, text)


def submit_panel(hwnd: int) -> None:
    """Read the box's text, stash it as the pending goal, and close the
    panel. Does not act on the text in any way -- there is no planner yet."""
    text = panel_text(hwnd)
    _pending_goal[hwnd] = text
    close_panel(hwnd)


def take_submitted_goal(hwnd: int) -> str | None:
    """The goal last submitted on this bar, returned exactly once -- the
    caller polls every tick, so returning it repeatedly would re-announce
    the same goal on every later tick forever."""
    return _pending_goal.pop(hwnd, None)


def _on_command(hwnd: int, control_id: int) -> None:
    """Handle a WM_COMMAND from one of the bar's buttons.

    Kept module-level (not a closure over hwnd) specifically so tests can
    call it directly to exercise the same logic a real click reaches,
    without ever synthesising input (D006). Must NEVER call
    SetForegroundWindow or SetFocus -- doing so would steal focus from the
    app the user is being taught in, exactly what this button must not do.
    """
    state = _bar_state.get(hwnd, BarState())
    if control_id == ID_STOP:
        state = replace(state, stop_requested=True)
    elif control_id == ID_PAUSE:
        state = replace(state, pause_requested=True)
    elif control_id == ID_ASK:
        state = replace(state, ask_requested=True)
    else:
        return
    _bar_state[hwnd] = state


def _bar_wnd_proc(hwnd, msg, wparam, lparam):
    """The bar's own procedure.

    Deliberately does NOT call PostQuitMessage on WM_DESTROY, unlike the
    overlay's. The overlay is destroyed once, at exit, so ending the thread's
    message loop there is right. The bar can be destroyed while the tour is
    still running, and posting WM_QUIT would take the tour's own loop down
    with it.
    """
    if msg == win32con.WM_COMMAND:
        _on_command(hwnd, win32api.LOWORD(wparam))
        return 0
    if msg == win32con.WM_DESTROY:
        _bar_state.pop(hwnd, None)
        _bar_status.pop(hwnd, None)
        _bar_status_hwnd.pop(hwnd, None)
        _panel_hwnd.pop(hwnd, None)
        _pending_goal.pop(hwnd, None)
        return 0
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


def create_bar_window() -> int:
    """Create the control bar, bottom-centre of the virtual desktop (the
    same all-monitors convention the overlay uses -- see dpi.virtual_screen_rect())."""
    global _bar_brush
    if _bar_brush is None:
        _bar_brush = win32gui.CreateSolidBrush(BAR_BG)

    ensure_class(BAR_CLASS_NAME, _bar_wnd_proc, _bar_brush)

    left, top, width, height = dpi.virtual_screen_rect()
    x = left + (width - _BAR_WIDTH) // 2
    y = top + height - _BAR_HEIGHT - _BAR_MARGIN

    ex_style = win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW

    hwnd = win32gui.CreateWindowEx(
        ex_style,
        BAR_CLASS_NAME,
        "Ghost Cursor",
        win32con.WS_POPUP,
        x,
        y,
        _BAR_WIDTH,
        _BAR_HEIGHT,
        None,
        None,
        win32api.GetModuleHandle(None),
        None,
    )

    h_instance = win32api.GetModuleHandle(None)
    button_style = win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON
    button_y = (_BAR_HEIGHT - _BUTTON_HEIGHT) // 2
    labels_and_ids = (("Stop", ID_STOP), ("Pause", ID_PAUSE), ("Ask", ID_ASK))
    for i, (label, control_id) in enumerate(labels_and_ids):
        bx = _BUTTON_MARGIN + i * (_BUTTON_WIDTH + _BUTTON_GAP)
        win32gui.CreateWindowEx(
            0,
            "BUTTON",
            label,
            button_style,
            bx,
            button_y,
            _BUTTON_WIDTH,
            _BUTTON_HEIGHT,
            hwnd,
            control_id,
            h_instance,
            None,
        )

    status_x = _BUTTON_MARGIN + len(labels_and_ids) * (_BUTTON_WIDTH + _BUTTON_GAP)
    status_width = max(_BAR_WIDTH - status_x - _BUTTON_MARGIN, 0)
    static_hwnd = win32gui.CreateWindowEx(
        0,
        "STATIC",
        "",
        win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.SS_LEFT,
        status_x,
        button_y,
        status_width,
        _BUTTON_HEIGHT,
        hwnd,
        ID_STATUS,
        h_instance,
        None,
    )
    _bar_status_hwnd[hwnd] = static_hwnd
    _bar_status[hwnd] = ""
    _bar_state[hwnd] = BarState()

    # SW_SHOWNOACTIVATE: appear without stealing focus from the app the user
    # is working in. The bar CAN take focus later, when the user clicks it --
    # it just must not grab it merely by existing.
    win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
    win32gui.UpdateWindow(hwnd)
    return hwnd


def destroy_bar_window(hwnd: int) -> None:
    """Tear the bar down. Safe to call twice."""
    try:
        win32gui.DestroyWindow(hwnd)
    except win32gui.error:
        pass
    pump_messages_nonblocking()
    _bar_state.pop(hwnd, None)
    _bar_status.pop(hwnd, None)
    _bar_status_hwnd.pop(hwnd, None)
    _panel_hwnd.pop(hwnd, None)
    _pending_goal.pop(hwnd, None)

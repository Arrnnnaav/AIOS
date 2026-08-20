# Control Bar and Intent Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the user a visible Stop button and a way to type what they want to learn, without letting either break the click-through overlay or the keyboard escape hatch.

**Architecture:** A second Win32 window on the same UI thread, styled as the deliberate inverse of the overlay — it receives clicks and can take focus, which the overlay must never do. Collapsed it shows Stop, Pause and status; clicking Ask opens a focused text box, and while the bar is foreground the tour's global SPACE poll is suppressed and ESC is rebound to close the panel rather than quit. No new thread, no new dependency, no message loop of its own.

**Tech Stack:** Python 3.12, pywin32 (`win32gui`/`win32con`/`win32api`), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-21-control-bar-design.md`

## Global Constraints

- **The bar must never be required for escape.** If its window fails to create, the tour runs anyway and ESC still works. Degrading to today's behaviour is mandatory; degrading to a full-screen click-through overlay with no way out is the failure this milestone exists to prevent.
- **ESC always does something.** Collapsed it quits; with the panel focused it closes the panel and the next press quits. There is no state in which ESC is inert.
- **Stop is always mouse-clickable**, in both states, regardless of focus.
- **The overlay's styles must not change.** `WS_EX_TRANSPARENT` and `WS_EX_NOACTIVATE` stay on the overlay (D006, D009). The bar carries neither.
- **`GetForegroundWindow()` is the ground truth** for whether the bar owns the keyboard — never an internal flag.
- **The bar's window procedure must NOT call `PostQuitMessage`.** The overlay's does, on `WM_DESTROY` (`ghostcursor/overlay/window.py`). Sharing that would make closing the bar post `WM_QUIT` to the whole thread.
- **Never move the real cursor or synthesise input** (D006). The bar reads clicks and keys; it never generates them.
- **Mutation-verify** (D018); state property vs invariant (D031); ordered-sequence tests on an injected clock (D026).
- **Commit as soon as your tests pass**, before mutation work. Eleven agents have been lost mid-task on this project to capacity limits, network errors and session ends; every one that had committed early kept its work.

## File Structure

| File | Responsibility |
|---|---|
| `ghostcursor/overlay/window.py` | Gains a shared `_ensure_class()` helper. The overlay's own behaviour is otherwise unchanged. |
| `ghostcursor/overlay/bar.py` *(new)* | The control bar window: creation, teardown, its own window procedure, button and edit-control handling, and the state it exposes. No knowledge of tours, recipes or steps. |
| `tests/test_bar.py` *(new)* | Real-window checks for the bar in isolation: styles, coexistence, clicks, focus. |
| `ghostcursor/run.py` | Creates the bar, suppresses SPACE while it is foreground, rebinds ESC, restores foreground, honours Pause, and degrades if the bar fails. |
| `tests/test_bar_arbitration.py` *(new)* | Key arbitration and degradation, driven with the injectable `key_state` the codebase already has. |

---

### Task 1: GATING SPIKE — prove the two windows actually coexist

**This task is a gate. No other task starts until it passes.** Its output is an answer, not code you keep.

**Files:**
- Create: a throwaway probe under your scratch directory — NOT in the repo
- Create: `docs/superpowers/specs/2026-08-21-control-bar-coexistence-findings.md` (this is the deliverable)

**Interfaces:**
- Consumes: nothing.
- Produces: a recorded finding that later tasks depend on, or a refutation that stops the milestone.

**Why this is a gate.** Every other task assumes a second, focusable, topmost window can coexist with a full-screen topmost click-through overlay — that clicks route correctly, that z-order behaves, and that the overlay still paints. That is reasoned from documented Win32 behaviour and has never been tested in this repo. This project has been surprised three times by exactly that shape: `GetSystemMetrics` silently changing its answer once anything took a screenshot (D010/D013); Discord's `Discord Updater` splash being a separate HWND that fully satisfied `windows_matching`; and `UpdateWindow` painting synchronously, which made a "narrow race" a guaranteed second frame (D027). If this fails, the design is wrong at its foundation and Tasks 2-6 are wasted work.

- [ ] **Step 1: Write the probe**

Put this in your scratch directory. Read `tests/test_overlay.py` first for how this repo drives real windows and captures pixels — reuse `dpi.capture_region()`, never `mss.monitors[1]`, and never capture from a separate process (D012).

```python
"""THROWAWAY probe: can a focusable window coexist with the click-through overlay?

Gates the control-bar milestone. Every task after this one assumes:
  1. both windows can be visible at once
  2. the bar can take focus while the overlay never does
  3. a click lands on the bar even though a full-screen topmost
     click-through window is also on screen
  4. the overlay still paints its hint with the bar present

None of that has been tested in this repo. Documented Win32 behaviour says it
works; this project has been wrong three times about documented Win32 behaviour
in context, which is why this is a gate rather than an assumption.
"""

import sys
import time

sys.path.insert(0, r"D:\PROJECTS\AIOS")

import win32api
import win32con
import win32gui

from ghostcursor.overlay import dpi  # noqa: F401  -- DPI before any window (D010)
from ghostcursor.overlay import window as ov

BAR_CLASS = "GhostCursorCoexistProbe"


def _bar_proc(hwnd, msg, wparam, lparam):
    # Deliberately NOT PostQuitMessage on WM_DESTROY -- see the plan's
    # global constraints. This probe proves that choice is workable too.
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


def make_bar() -> int:
    h_instance = win32api.GetModuleHandle(None)
    cls = win32gui.WNDCLASS()
    cls.lpfnWndProc = _bar_proc
    cls.hInstance = h_instance
    cls.lpszClassName = BAR_CLASS
    cls.hbrBackground = win32gui.CreateSolidBrush(win32api.RGB(30, 30, 40))
    win32gui.RegisterClass(cls)
    return win32gui.CreateWindowEx(
        win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW,
        BAR_CLASS,
        "GhostCursorBar",
        win32con.WS_POPUP | win32con.WS_VISIBLE,
        100,
        100,
        420,
        60,
        None,
        None,
        h_instance,
        None,
    )


def main() -> None:
    overlay = ov.create_overlay_window()
    bar = None
    try:
        bar = make_bar()
        for _ in range(40):
            ov.pump_messages_nonblocking()
            time.sleep(0.01)

        print("1. both windows exist and are visible:")
        print(f"   overlay {overlay} visible={win32gui.IsWindowVisible(overlay)}")
        print(f"   bar     {bar} visible={win32gui.IsWindowVisible(bar)}")

        ov_ex = win32gui.GetWindowLong(overlay, win32con.GWL_EXSTYLE)
        bar_ex = win32gui.GetWindowLong(bar, win32con.GWL_EXSTYLE)
        print("\n2. styles are the intended inverse:")
        print(f"   overlay TRANSPARENT={bool(ov_ex & win32con.WS_EX_TRANSPARENT)} "
              f"NOACTIVATE={bool(ov_ex & win32con.WS_EX_NOACTIVATE)}")
        print(f"   bar     TRANSPARENT={bool(bar_ex & win32con.WS_EX_TRANSPARENT)} "
              f"NOACTIVATE={bool(bar_ex & win32con.WS_EX_NOACTIVATE)}")

        print("\n3. can the bar take foreground while the overlay does not?")
        try:
            win32gui.SetForegroundWindow(bar)
            ok = True
        except Exception as exc:
            ok = False
            print(f"   SetForegroundWindow RAISED: {exc}")
        for _ in range(40):
            ov.pump_messages_nonblocking()
            time.sleep(0.01)
        fg = win32gui.GetForegroundWindow()
        print(f"   attempted={ok} foreground={fg} is_bar={fg == bar} "
              f"is_overlay={fg == overlay}")

        print("\n4. WindowFromPoint over the bar -- who owns that pixel?")
        rect = win32gui.GetWindowRect(bar)
        mid = ((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
        owner = win32gui.WindowFromPoint(mid)
        root = win32gui.GetAncestor(owner, win32con.GA_ROOT) if owner else 0
        print(f"   point {mid} -> hwnd {owner} root {root} "
              f"is_bar={root == bar} is_overlay={root == overlay}")
        print("   (the overlay is WS_EX_TRANSPARENT, so it must NOT own this pixel)")

        print("\n5. does the overlay still paint its hint with the bar up?")
        ov.set_hint(overlay, 600, 400, freshness_source=lambda: None)
        for _ in range(40):
            ov.pump_messages_nonblocking()
            time.sleep(0.01)
        shot = dpi.capture_region(560, 360, 80, 80)
        print(f"   captured {shot.shape}, distinct colours: "
              f"{len(set(map(tuple, shot.reshape(-1, shot.shape[-1]))))}")
        print("   (more than one distinct colour means the ring drew)")
    finally:
        if bar:
            win32gui.DestroyWindow(bar)
        ov.destroy_overlay_window(overlay)
        ov.pump_messages_nonblocking()


if __name__ == "__main__":
    main()
```

Check `ov.set_hint`'s real signature before running — it takes a required `freshness_source` keyword, and the call above must match what the function actually accepts.

- [ ] **Step 2: Run it and read the output**

Run: `python <your scratch dir>/coexist_probe.py`

- [ ] **Step 3: Record the findings**

Write `docs/superpowers/specs/2026-08-21-control-bar-coexistence-findings.md`. **This document is the primary record for these results** — the probe is throwaway and not in the repo, so under D034 the numbers and answers must be written down here before anything cites them. State for each of the five questions what was observed, verbatim where it is short.

State plainly whether the gate PASSES or FAILS. It fails if any of these is true: the bar cannot take foreground; `WindowFromPoint` over the bar returns the overlay; or the overlay stops painting its hint with the bar present.

- [ ] **Step 4: Commit the findings and STOP for review**

```bash
git add docs/superpowers/specs/2026-08-21-control-bar-coexistence-findings.md
git commit -m "docs: control-bar coexistence spike findings"
git push origin <branch>
```

Do not start Task 2. Report the verdict and wait — that is what makes this a gate.

---

### Task 2: The bar window

**Files:**
- Modify: `ghostcursor/overlay/window.py` — extract class registration into a shared helper
- Create: `ghostcursor/overlay/bar.py`
- Test: `tests/test_bar.py`

**Interfaces:**
- Consumes: Task 1's finding that coexistence holds.
- Produces: `create_bar_window() -> int`; `destroy_bar_window(hwnd: int) -> None`; `BAR_CLASS_NAME: str`.

**Property this protects:** the bar can be clicked and focused, and the overlay remains click-through and unfocusable.
**Invariant enforced:** the bar's extended styles carry neither `WS_EX_TRANSPARENT` nor `WS_EX_NOACTIVATE`; the overlay's carry both.
**Does the invariant imply the property?** For the overlay, yes — those two styles are what make it click-through and unfocusable. For the bar it is necessary but not sufficient, which is why Task 1's spike had to observe a real click landing on it rather than inferring from styles.

- [ ] **Step 1: Extract the shared class-registration helper in `window.py`**

`create_overlay_window()` currently guards registration with a module-global `_class_registered`. Replace that with a helper both windows use:

```python
#: Window classes registered by this process, by name. A dict rather than a
#: per-class boolean: two globals tracking two classes is how a third one gets
#: forgotten, and RegisterClass fails if called twice for the same name.
_registered_classes: dict[str, bool] = {}


def _ensure_class(name: str, wnd_proc, background_brush) -> None:
    """Register a window class once per process."""
    if _registered_classes.get(name):
        return
    wnd_class = win32gui.WNDCLASS()
    wnd_class.lpfnWndProc = wnd_proc
    wnd_class.hInstance = win32api.GetModuleHandle(None)
    wnd_class.lpszClassName = name
    wnd_class.hbrBackground = background_brush
    win32gui.RegisterClass(wnd_class)
    _registered_classes[name] = True
```

Then have `create_overlay_window()` call `_ensure_class(_CLASS_NAME, _wnd_proc, _bg_brush)` in place of its inline registration block, deleting `_class_registered`.

- [ ] **Step 2: Write the failing tests**

```python
"""The control bar as a window: styles, coexistence, teardown.

These assert real Win32 state, not appearance -- the same discipline as
tests/test_overlay.py. Every path tears both windows down in a finally block:
a stranded full-screen window is the failure that locks a user out.
"""

import win32con
import win32gui

from ghostcursor.overlay import dpi  # noqa: F401  -- DPI before any window (D010)
from ghostcursor.overlay import bar, window as ov


def test_the_bar_can_be_clicked_and_focused_and_the_overlay_cannot():
    """The two windows are style-inverses, and that is the whole safety
    argument: the overlay must never take a click or the focus, the bar must
    be able to take both."""
    overlay = ov.create_overlay_window()
    bar_hwnd = None
    try:
        bar_hwnd = bar.create_bar_window()
        ov_ex = win32gui.GetWindowLong(overlay, win32con.GWL_EXSTYLE)
        bar_ex = win32gui.GetWindowLong(bar_hwnd, win32con.GWL_EXSTYLE)

        assert ov_ex & win32con.WS_EX_TRANSPARENT, "overlay stopped being click-through"
        assert ov_ex & win32con.WS_EX_NOACTIVATE, "overlay became focusable"
        assert not (bar_ex & win32con.WS_EX_TRANSPARENT), "bar cannot receive clicks"
        assert not (bar_ex & win32con.WS_EX_NOACTIVATE), "bar cannot take focus"
    finally:
        if bar_hwnd:
            bar.destroy_bar_window(bar_hwnd)
        ov.destroy_overlay_window(overlay)


def test_both_windows_are_visible_at_once():
    overlay = ov.create_overlay_window()
    bar_hwnd = None
    try:
        bar_hwnd = bar.create_bar_window()
        ov.pump_messages_nonblocking()
        assert win32gui.IsWindowVisible(overlay)
        assert win32gui.IsWindowVisible(bar_hwnd)
    finally:
        if bar_hwnd:
            bar.destroy_bar_window(bar_hwnd)
        ov.destroy_overlay_window(overlay)


def test_destroying_the_bar_does_not_end_the_message_loop():
    """The overlay's wnd_proc calls PostQuitMessage on WM_DESTROY. The bar's
    must NOT: collapsing or closing the bar would otherwise post WM_QUIT to
    the whole thread and take the tour down with it."""
    overlay = ov.create_overlay_window()
    try:
        bar_hwnd = bar.create_bar_window()
        bar.destroy_bar_window(bar_hwnd)
        # PumpWaitingMessages returns True when it dequeued WM_QUIT.
        assert win32gui.PumpWaitingMessages() != 1, (
            "destroying the bar posted WM_QUIT -- the tour's own loop would end"
        )
        assert win32gui.IsWindow(overlay), "overlay died with the bar"
    finally:
        ov.destroy_overlay_window(overlay)


def test_the_bar_is_not_full_screen():
    """It must never cover the region a hint could occupy."""
    bar_hwnd = bar.create_bar_window()
    try:
        left, top, right, bottom = win32gui.GetWindowRect(bar_hwnd)
        vl, vt, vw, vh = dpi.virtual_screen_rect()
        assert (right - left) < vw // 2, "bar is more than half the desktop wide"
        assert (bottom - top) < vh // 4, "bar is more than a quarter of the desktop tall"
    finally:
        bar.destroy_bar_window(bar_hwnd)
```

- [ ] **Step 3: Run them and verify they fail**

Run: `python -m pytest tests/test_bar.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ghostcursor.overlay.bar'`

- [ ] **Step 4: Write `ghostcursor/overlay/bar.py`**

```python
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

import win32api
import win32con
import win32gui

from ghostcursor.overlay import dpi
from ghostcursor.overlay.window import _ensure_class, pump_messages_nonblocking

BAR_CLASS_NAME = "GhostCursorBar"
BAR_BG = win32api.RGB(28, 28, 34)

#: Edge inset and size, in physical pixels.
_BAR_WIDTH = 520
_BAR_HEIGHT = 56
_BAR_MARGIN = 24

_bar_brush = None


def _bar_wnd_proc(hwnd, msg, wparam, lparam):
    """The bar's own procedure.

    Deliberately does NOT call PostQuitMessage on WM_DESTROY, unlike the
    overlay's. The overlay is destroyed once, at exit, so ending the thread's
    message loop there is right. The bar can be destroyed while the tour is
    still running, and posting WM_QUIT would take the tour's own loop down
    with it.
    """
    if msg == win32con.WM_DESTROY:
        return 0
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


def create_bar_window() -> int:
    """Create the control bar, bottom-centre of the primary monitor."""
    global _bar_brush
    if _bar_brush is None:
        _bar_brush = win32gui.CreateSolidBrush(BAR_BG)

    _ensure_class(BAR_CLASS_NAME, _bar_wnd_proc, _bar_brush)

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
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_bar.py -v`
Expected: 4 passed.

- [ ] **Step 6: Run the fast suite, then commit**

```bash
python -m pytest tests/ --ignore=tests/test_hung_window.py --ignore=tests/test_perception_service_hung.py --ignore=tests/test_run_threaded.py -q
git add ghostcursor/overlay/bar.py ghostcursor/overlay/window.py tests/test_bar.py
git commit -m "feat: a focusable control bar beside the click-through overlay"
git push origin <branch>
```

Never run two pytest sessions at once, and never run the three ignored files — they park a non-pumping window that taxes UI Automation machine-wide (6.28s vs 100.13s measured, D025). The controller runs them.

- [ ] **Step 7: Mutation-verify (D018), one at a time, reverting between**

| # | Mutation | Must fail |
|---|---|---|
| 1 | Add `WS_EX_NOACTIVATE` to the bar's `ex_style` | `test_the_bar_can_be_clicked_and_focused_and_the_overlay_cannot` |
| 2 | Add `WS_EX_TRANSPARENT` to the bar's `ex_style` | same test |
| 3 | Make `_bar_wnd_proc` call `win32gui.PostQuitMessage(0)` on `WM_DESTROY` | `test_destroying_the_bar_does_not_end_the_message_loop` |
| 4 | Make the bar full-screen (`virtual_screen_rect()` size) | `test_the_bar_is_not_full_screen` |

Record each in `docs/superpowers/ledgers/2026-08-21-control-bar-ledger.md` (create it), naming the test that caught it. Per D034, "mutation-verified" must name where it is recorded.

---

### Task 3: Collapsed controls — Stop, Pause, Ask

**Files:**
- Modify: `ghostcursor/overlay/bar.py`
- Test: `tests/test_bar.py` (extend)

**Interfaces:**
- Consumes: `create_bar_window()`, `destroy_bar_window()` (Task 2).
- Produces: `BarState` with fields `stop_requested: bool`, `pause_requested: bool`, `ask_requested: bool`; `bar_state(hwnd: int) -> BarState`; `set_status(hwnd: int, text: str) -> None`; `clear_requests(hwnd: int) -> None`.

**Property this protects:** a user can stop the tour with the mouse, without the keyboard and without focus.
**Invariant enforced:** clicking Stop sets `stop_requested`, and the caller sees it on its next poll.
**Does the invariant imply the property?** Only if the click reaches the bar at all, which Task 1's spike establishes and Task 2's style test guards.

- [ ] **Step 1: Write the failing tests**

```python
def test_clicking_stop_sets_the_request_without_taking_focus():
    """The button must work by mouse alone. Focus is not required, and taking
    it would pull the user out of the app they are being taught."""
    bar_hwnd = bar.create_bar_window()
    try:
        before = win32gui.GetForegroundWindow()
        bar._on_command(bar_hwnd, bar.ID_STOP)
        assert bar.bar_state(bar_hwnd).stop_requested is True
        assert win32gui.GetForegroundWindow() == before, (
            "clicking a bar button stole foreground from the user's app"
        )
    finally:
        bar.destroy_bar_window(bar_hwnd)


def test_requests_clear_so_one_click_is_one_request():
    bar_hwnd = bar.create_bar_window()
    try:
        bar._on_command(bar_hwnd, bar.ID_PAUSE)
        assert bar.bar_state(bar_hwnd).pause_requested is True
        bar.clear_requests(bar_hwnd)
        assert bar.bar_state(bar_hwnd).pause_requested is False, (
            "a single click would be read as a request on every later poll"
        )
    finally:
        bar.destroy_bar_window(bar_hwnd)


def test_status_text_round_trips():
    bar_hwnd = bar.create_bar_window()
    try:
        bar.set_status(bar_hwnd, "step 2 of 5")
        assert bar.get_status(bar_hwnd) == "step 2 of 5"
    finally:
        bar.destroy_bar_window(bar_hwnd)
```

- [ ] **Step 2: Run and verify they fail**

Run: `python -m pytest tests/test_bar.py -v -k "stop or requests or status"`
Expected: FAIL — `AttributeError: module 'ghostcursor.overlay.bar' has no attribute '_on_command'`

- [ ] **Step 3: Implement**

Add to `bar.py`: control ids, a `BarState` frozen dataclass, per-hwnd state held in a module dict, child `BUTTON` controls created in `create_bar_window()` via `CreateWindowEx` with `WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON` and the ids below, a `WM_COMMAND` arm in `_bar_wnd_proc` that calls `_on_command(hwnd, win32api.LOWORD(wparam))`, and a `STATIC` control for status that `set_status` writes with `win32gui.SetWindowText`.

```python
ID_STOP = 1101
ID_PAUSE = 1102
ID_ASK = 1103
```

`_on_command(hwnd, control_id)` sets the matching flag in that window's state. Keep it a module-level function, not a closure, so the tests above can call it directly without synthesising a real click — synthesising input would violate D006 even in a test.

- [ ] **Step 4: Run the tests, then the fast suite, then commit**

```bash
python -m pytest tests/test_bar.py -v
python -m pytest tests/ --ignore=tests/test_hung_window.py --ignore=tests/test_perception_service_hung.py --ignore=tests/test_run_threaded.py -q
git add ghostcursor/overlay/bar.py tests/test_bar.py
git commit -m "feat: Stop, Pause and Ask on the control bar"
git push origin <branch>
```

- [ ] **Step 5: Mutation-verify**

| # | Mutation | Must fail |
|---|---|---|
| 1 | Make `clear_requests` a no-op | `test_requests_clear_so_one_click_is_one_request` |
| 2 | Have `_on_command` call `win32gui.SetForegroundWindow(hwnd)` | `test_clicking_stop_sets_the_request_without_taking_focus` |

Append to the ledger and commit.

---

### Task 4: The input panel

**Files:**
- Modify: `ghostcursor/overlay/bar.py`
- Test: `tests/test_bar.py` (extend)

**Interfaces:**
- Consumes: Task 3's state and ids.
- Produces: `open_panel(hwnd: int) -> None`; `close_panel(hwnd: int) -> None`; `panel_is_open(hwnd: int) -> bool`; `panel_text(hwnd: int) -> str`; `take_submitted_goal(hwnd: int) -> str | None`.

**Property this protects:** typing a goal never triggers a tour action, and the user can always get out of the box.
**Invariant enforced:** while the panel is open the bar holds foreground, and `take_submitted_goal` returns the text exactly once.
**Does the invariant imply the property?** The "never triggers a tour action" half is enforced in Task 5, not here — this task only makes the state observable. That split is deliberate: the loop owns arbitration, the window owns its widgets.

- [ ] **Step 1: Write the failing tests**

```python
def test_opening_the_panel_focuses_it_and_closing_releases():
    bar_hwnd = bar.create_bar_window()
    try:
        assert bar.panel_is_open(bar_hwnd) is False
        bar.open_panel(bar_hwnd)
        assert bar.panel_is_open(bar_hwnd) is True
        assert win32gui.GetForegroundWindow() == bar_hwnd, (
            "the panel opened without taking focus -- keystrokes would go to "
            "the user's application instead of the box"
        )
        bar.close_panel(bar_hwnd)
        assert bar.panel_is_open(bar_hwnd) is False
    finally:
        bar.destroy_bar_window(bar_hwnd)


def test_a_submitted_goal_is_returned_exactly_once():
    """Once, because the caller polls every tick: returning it repeatedly
    would re-announce the same goal on every tick forever."""
    bar_hwnd = bar.create_bar_window()
    try:
        bar.open_panel(bar_hwnd)
        bar.set_panel_text(bar_hwnd, "add a page number")
        bar.submit_panel(bar_hwnd)
        assert bar.take_submitted_goal(bar_hwnd) == "add a page number"
        assert bar.take_submitted_goal(bar_hwnd) is None
    finally:
        bar.destroy_bar_window(bar_hwnd)


def test_submitting_closes_the_panel():
    bar_hwnd = bar.create_bar_window()
    try:
        bar.open_panel(bar_hwnd)
        bar.set_panel_text(bar_hwnd, "export as pdf")
        bar.submit_panel(bar_hwnd)
        assert bar.panel_is_open(bar_hwnd) is False
    finally:
        bar.destroy_bar_window(bar_hwnd)


def test_closing_without_submitting_discards_nothing_and_returns_no_goal():
    bar_hwnd = bar.create_bar_window()
    try:
        bar.open_panel(bar_hwnd)
        bar.set_panel_text(bar_hwnd, "half a thought")
        bar.close_panel(bar_hwnd)
        assert bar.take_submitted_goal(bar_hwnd) is None, (
            "dismissing the box submitted the goal anyway"
        )
    finally:
        bar.destroy_bar_window(bar_hwnd)
```

- [ ] **Step 2: Run and verify they fail**

Run: `python -m pytest tests/test_bar.py -v -k panel`
Expected: FAIL — `AttributeError: module 'ghostcursor.overlay.bar' has no attribute 'panel_is_open'`

- [ ] **Step 3: Implement**

`open_panel` creates an `EDIT` child (`WS_CHILD | WS_VISIBLE | WS_BORDER | ES_AUTOHSCROLL`), calls `win32gui.SetForegroundWindow(hwnd)` then `win32gui.SetFocus(edit_hwnd)`, and records the edit handle in the window's state. `close_panel` destroys the child and clears it. `submit_panel` reads the text with `win32gui.GetWindowText`, stores it as the pending goal, and closes the panel. `take_submitted_goal` returns the pending goal and clears it in one step.

`set_panel_text` exists so tests can put text in the box without synthesising keystrokes — synthesising input would violate D006 (never generate input) even in a test.

- [ ] **Step 4: Run tests, fast suite, commit**

```bash
python -m pytest tests/test_bar.py -v
python -m pytest tests/ --ignore=tests/test_hung_window.py --ignore=tests/test_perception_service_hung.py --ignore=tests/test_run_threaded.py -q
git add ghostcursor/overlay/bar.py tests/test_bar.py
git commit -m "feat: the goal input panel"
git push origin <branch>
```

- [ ] **Step 5: Mutation-verify**

| # | Mutation | Must fail |
|---|---|---|
| 1 | `take_submitted_goal` returns the goal without clearing it | `test_a_submitted_goal_is_returned_exactly_once` |
| 2 | `open_panel` skips `SetForegroundWindow` | `test_opening_the_panel_focuses_it_and_closing_releases` |
| 3 | `close_panel` stores the text as the pending goal | `test_closing_without_submitting_discards_nothing_and_returns_no_goal` |

Append to the ledger and commit.

---

### Task 5: Wire it into `run.py` — arbitration, restoration, pause, degradation

**Files:**
- Modify: `ghostcursor/run.py`
- Test: `tests/test_bar_arbitration.py` *(new)*

**Interfaces:**
- Consumes: everything from Tasks 2-4.
- Produces: no new public surface.

**Property this protects:** typing never triggers a tour action, ESC always does something, and the tour survives the bar failing.
**Invariant enforced:** while `GetForegroundWindow() == bar_hwnd`, the SPACE poll does not run and ESC closes the panel instead of quitting.
**Does the invariant imply the property?** Yes for typing and ESC. The survival half is separate and has its own test, because a bar that fails to create never reaches this code path at all.

- [ ] **Step 1: Write the failing tests**

```python
"""Key arbitration between the bar and the tour, and degradation when the bar
fails to appear.

Driven through the injectable `key_state` that `run.key_was_pressed` already
takes, so no real keys and no synthesised input -- generating input would
violate D006 even in a test.
"""

import ghostcursor.run as run_module


def test_space_is_suppressed_while_the_bar_holds_focus(arbiter):
    """Typing a space into the goal box must never confirm a step."""
    a = arbiter(bar_has_focus=True, panel_open=True)
    assert a.space_would_confirm() is False


def test_space_confirms_when_the_bar_does_not_hold_focus(arbiter):
    a = arbiter(bar_has_focus=False, panel_open=False)
    assert a.space_would_confirm() is True


def test_escape_closes_the_panel_rather_than_quitting(arbiter):
    a = arbiter(bar_has_focus=True, panel_open=True)
    assert a.escape_action() == "close_panel"


def test_a_second_escape_quits_once_the_panel_is_closed(arbiter):
    a = arbiter(bar_has_focus=False, panel_open=False)
    assert a.escape_action() == "quit"


def test_escape_is_never_inert(arbiter):
    """There is no state in which pressing ESC does nothing -- it is what a
    user reaches for when they want out."""
    for has_focus in (True, False):
        for panel in (True, False):
            a = arbiter(bar_has_focus=has_focus, panel_open=panel)
            assert a.escape_action() in ("close_panel", "quit")


def test_the_tour_runs_and_escape_still_works_when_the_bar_fails_to_create(
    tour_harness,
):
    """The bar is a safety improvement and must never become a single point of
    failure for escape. If it cannot be created, we degrade to exactly today's
    behaviour -- never to a full-screen click-through overlay with no way out."""
    h = tour_harness(bar_creation_raises=OSError("no window for you"))
    h.press_escape()
    h.tick()
    assert h.exited is True, "ESC stopped working because the bar failed to appear"
    assert any("bar" in line.lower() for line in h.printed), (
        "the bar's failure was silent"
    )
```

Build the `arbiter` fixture around whatever small function you extract in Step 3, and `tour_harness` on the existing `run_tour` driver in `tests/test_freshness_timeline.py` — read that file and reuse it rather than inventing a second driver. A hand-rolled harness is where this project's subtle test bugs have landed.

- [ ] **Step 2: Run and verify they fail**

Run: `python -m pytest tests/test_bar_arbitration.py -v`
Expected: FAIL — the arbitration function does not exist yet.

- [ ] **Step 3: Implement in `run.py`**

Extract the decision into one testable function rather than scattering conditionals through the loop:

```python
def keyboard_owner(bar_hwnd: int | None, foreground=win32gui.GetForegroundWindow) -> str:
    """Who owns the keyboard right now: "bar" or "tour".

    The test is the OS's answer, never an internal flag. A flag can
    desynchronise from reality; the question that actually matters is where
    the user's keystrokes are going, and only the OS knows that. The same
    answer governs foreground restoration, so one fact serves both.
    """
    if bar_hwnd is None:
        return "tour"
    return "bar" if foreground() == bar_hwnd else "tour"
```

In the tick loop, gate the existing SPACE poll on `keyboard_owner(...) == "tour"`, and route ESC: when the owner is the bar and the panel is open, close the panel; otherwise quit as today.

Create the bar next to the overlay at `run.py`'s existing `hwnd = window.create_overlay_window()`, wrapped so a failure degrades:

```python
        try:
            bar_hwnd = bar.create_bar_window()
        except Exception as exc:
            # The bar is a safety affordance and must never BE the safety
            # risk. Degrade to today's behaviour -- ESC still quits, the tour
            # still runs -- rather than failing the run.
            bar_hwnd = None
            print(f"Control bar unavailable ({exc}); ESC still quits.")
```

Each tick: update status from `tour.step_index` and `len(recipe.steps)`, poll `bar.bar_state`, act on Stop (exit) and Pause (skip `tour.tick()`, nothing else), open the panel on Ask, and drain `take_submitted_goal` to print and display the goal. Then `clear_requests`.

On panel close, restore foreground best-effort, exactly once, per the spec's §4.4 ladder:

```python
def restore_foreground(bar_hwnd: int, title_re: str) -> None:
    """Hand focus back to the target, best-effort, once. Never retried.

    Aggressive focus restoration is itself a form of acting for the user
    (D006). If the user has moved to another application while typing, taking
    focus back is the worst available response -- so we only restore when WE
    are still foreground.
    """
    if win32gui.GetForegroundWindow() != bar_hwnd:
        return
    target = first_matching_hwnd(title_re)
    if not target:
        return
    try:
        win32gui.SetForegroundWindow(target)
    except Exception:
        pass
```

- [ ] **Step 4: Run tests, fast suite, commit**

```bash
python -m pytest tests/test_bar_arbitration.py -v
python -m pytest tests/ --ignore=tests/test_hung_window.py --ignore=tests/test_perception_service_hung.py --ignore=tests/test_run_threaded.py -q
git add ghostcursor/run.py tests/test_bar_arbitration.py
git commit -m "feat: arbitrate the keyboard between the bar and the tour"
git push origin <branch>
```

If a pre-existing test breaks, do NOT weaken its assertion — the likely cause is the bar now existing where a test did not expect it, and the right fix is leaving `bar_hwnd` as `None` in that test's setup, which makes every new path inert.

- [ ] **Step 5: Mutation-verify — the first row is the safety-critical one**

| # | Mutation | Must fail |
|---|---|---|
| 1 | Delete the `keyboard_owner(...) == "tour"` gate on the SPACE poll | `test_space_is_suppressed_while_the_bar_holds_focus` |
| 2 | Make ESC always quit, ignoring the panel | `test_escape_closes_the_panel_rather_than_quitting` |
| 3 | Make `keyboard_owner` read an internal flag instead of `foreground()` | `test_space_is_suppressed_while_the_bar_holds_focus` (drive the fixture with the flag and the OS disagreeing) |
| 4 | Let the bar-creation exception propagate | `test_the_tour_runs_and_escape_still_works_when_the_bar_fails_to_create` |
| 5 | Drop the `GetForegroundWindow() != bar_hwnd` guard in `restore_foreground` | needs a test that asserts no restore happens when the user moved to a third window; add it if row 5 has none |

Row 5 is deliberately phrased as a possible gap: if no existing test covers it, write one rather than recording the mutation as unverified. Append every result to the ledger.

---

### Task 6: Documentation

**Files:**
- Modify: `DECISIONS.md`, `FLOW.md`, `CLAUDE.md`

- [ ] **Step 1: Add the decision entry**

Append to `DECISIONS.md` as the next free number — **check, do not assume**; D038 is the last at time of writing. It must state: that the bar exists primarily as a safety affordance because ESC was the only escape and was invisible; that it is a second window on the same UI thread because `PumpWaitingMessages` already pumps every window on that thread and D021 already guarantees the thread does not block; that its styles are the deliberate inverse of the overlay's; that `GetForegroundWindow` rather than a flag arbitrates the keyboard, and why; that ESC is rebound rather than suppressed so it is never inert; that foreground restoration is best-effort-once because aggressive restoration is itself acting for the user (D006); and that the bar must never be required for escape, degrading to today's behaviour if it cannot be created.

Cite the coexistence findings from Task 1 for anything measured, per D034.

- [ ] **Step 2: Update `FLOW.md`**

`run.py` now creates two windows, arbitrates the keyboard through `keyboard_owner`, and polls bar state each tick. Update the call graph and move the "you are here" marker.

- [ ] **Step 3: Update `CLAUDE.md`**

Two or three sentences in the overlay section: there is now a second, focusable bar window; the overlay itself is unchanged and still must never take focus or clicks; ESC still quits and is now joined by a visible Stop.

- [ ] **Step 4: Independent review — D032, ENFORCED GATE**

These docs must be read by something other than whoever wrote them. Per D036, sweep for siblings when fixing anything found — the last two milestones each shipped a corrected doc while its twin survived elsewhere. Per D038, tell the reviewer the brief is a claim to verify, not authority.

- [ ] **Step 5: Commit**

```bash
git add DECISIONS.md FLOW.md CLAUDE.md
git commit -m "docs: record the control bar decision"
git push origin <branch>
```

---

## Self-Review

**Spec coverage.** §3.1 styles → Task 2's inverse-style test. §3.2 same-thread → Task 2 (no new loop is created anywhere). §3.3 shared class registration → Task 2 Step 1. §4.1 collapsed/expanded → Tasks 3 and 4. §4.2 `GetForegroundWindow` as ground truth → Task 5's `keyboard_owner`, with mutation row 3 specifically guarding against a flag. §4.1's ESC rebind and the three exits → Task 5's `escape_action` tests, including `test_escape_is_never_inert`. §4.4 restoration ladder → Task 5's `restore_foreground` plus mutation row 5. §5 display and session-only storage → Tasks 3 and 4 (nothing writes to the knowledge base). §6 Stop always clickable → Task 3; never-required-for-escape → Task 5's degradation test; pause semantics → Task 5. §7 testing → each task's mutation table. §8's gating spike → Task 1.

**Not covered, deliberately.** §4.3's mic accommodation is a recorded decision, not code — there is nothing to build. Multi-monitor placement is fixed at bottom-centre of the virtual desktop; §8 lists it as unspecified, and this plan picks the simplest defensible answer rather than leaving it open.

**Placeholder scan.** No TBDs. Two fixtures are specified by required surface — `arbiter` and `tour_harness` in Task 5 — both pointing at the existing driver to build on. Mutation row 5 in Task 5 is deliberately phrased as "add the test if it does not exist" rather than assuming coverage.

**Type consistency.** `create_bar_window() -> int` / `destroy_bar_window(hwnd: int)` are defined in Task 2 and used in 3, 4, 5. `BarState` and `bar_state(hwnd) -> BarState` are defined in Task 3 and polled in Task 5. `open_panel` / `close_panel` / `panel_is_open` / `take_submitted_goal` are defined in Task 4 and driven in Task 5. `keyboard_owner(bar_hwnd, foreground=...) -> str` returns the strings `"bar"` and `"tour"` in both its definition and its tests.

**The risk worth naming for the executor.** Task 5 touches `run.py`'s tick loop, which owns ESC polling — the one escape from a full-screen click-through overlay. A mistake there does not fail a test, it locks a user out of their machine. Every path that creates a window must tear it down in a `finally`, and the degradation test is not optional decoration.

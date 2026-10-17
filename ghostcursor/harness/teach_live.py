"""The live loop for ``--model-teach``: bound windows, a perception worker, the
overlay, ESC and ``--seconds`` (CLAUDE.md rules 3-5).

UIA reads run on their own thread and publish one overwritten frame (D021,
D022); model calls run on the session's request slot; this thread only polls,
draws in the INFERRED colour, and pumps messages. Nothing here synthesizes
input: the user does every click.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

# Import order matters: overlay.window pulls in overlay.dpi, which declares
# DPI awareness before any window exists.
from ghostcursor.overlay import window
from ghostcursor.harness.binding import (
    WindowBinding,
    bind,
    bindable_windows,
    still_bound,
)
from ghostcursor.harness.frame import ObservationFrame, WindowObservation, build_frame
from ghostcursor.harness.teach import ModelTeachSession, Phase
from ghostcursor.harness.uia_reader import is_minimized, read_window, window_facts

TICK_S = 0.1
OBSERVE_INTERVAL_S = 0.4


class Observer(threading.Thread):
    """Reads every bound window and publishes the newest frame. A window that
    is gone or changed identity ends the session (TARGET_LOST, never rebound)."""

    def __init__(self, bindings: tuple[WindowBinding, ...], *, unnamed: bool = False):
        super().__init__(name="harness-observer", daemon=True)
        self.bindings = bindings
        self.unnamed = unnamed  # keep icon-only controls (pictures on, D179)
        self.lost: str | None = None
        self._latest: ObservationFrame | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def latest(self) -> ObservationFrame | None:
        with self._lock:
            return self._latest

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        import pythoncom

        pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
        try:
            frame_id = 0
            while not self._stop.is_set():
                observations = []
                for binding in self.bindings:
                    rect, controls, timed_out = read_window(binding.hwnd)
                    if rect is None or not still_bound(binding):
                        self.lost = binding.label
                        return
                    title, owned = window_facts(
                        binding.hwnd, binding.identity.pid, binding.identity.executable
                    )
                    observations.append(
                        WindowObservation(
                            binding,
                            rect,
                            controls,
                            timed_out,
                            is_minimized(binding.hwnd),
                            title,
                            owned,
                        )
                    )
                frame_id += 1
                frame = build_frame(
                    frame_id, time.monotonic(), observations, unnamed=self.unnamed
                )
                with self._lock:
                    self._latest = frame
                self._stop.wait(OBSERVE_INTERVAL_S)
        finally:
            pythoncom.CoUninitialize()


def choose_windows() -> list[int]:
    """Ask on the console which windows to bind; titles are shown locally only."""

    choices = bindable_windows()
    for number, choice in enumerate(choices, start=1):
        print(f"  {number:2}. {choice.executable:<22} {choice.title[:60]}")
    raw = input("Windows to guide across (e.g. 1 3): ").split()
    return [
        choices[int(n) - 1].hwnd
        for n in raw
        if n.isdigit() and 0 < int(n) <= len(choices)
    ]


def _console_enter() -> bool:
    """True if Enter was pressed in this console since the last poll. Read
    from the console's own input, so the key never reaches the guided app (a
    Space there would also press whatever control has focus -- review F5)."""

    import msvcrt

    pressed = False
    while msvcrt.kbhit():
        pressed = msvcrt.getwch() in ("\r", "\n") or pressed
    return pressed


def _escape_pressed() -> bool:
    """Polled like run.escape_pressed: down now or tapped since the last poll."""

    import win32api
    import win32con

    return bool(win32api.GetAsyncKeyState(win32con.VK_ESCAPE) & 0x8001)


#: take_mark's result when ESC or the session deadline ended it: the session
#: must stop, not start without a mark (review of D171).
ABORTED = object()


def take_mark(
    observer: Observer,
    deadline: float,
    *,
    escape=_escape_pressed,
    enter=_console_enter,
    cursor=None,
    clock=time.monotonic,
    say=print,
):
    """Wait for the user to hover over what they mean and press Enter in this
    console; resolve the cursor point locally against the newest frame (D171).
    Reads the cursor position only; never moves it. Returns a mark, or ABORTED on
    ESC or at the deadline; a point over no control asks again."""

    from ghostcursor.harness.spatial import SpatialReference, point

    if cursor is None:
        import win32api

        cursor = win32api.GetCursorPos
    say("Point: hover the mouse over what you mean, then press Enter here.")
    while clock() < deadline:
        if escape():
            return ABORTED
        if enter():
            frame = observer.latest()
            if frame is None:
                say("Nothing observed yet - try again.")
                continue
            mark = SpatialReference.from_mark(point(*cursor()), frame)
            under = mark.current(frame)
            if not under:
                say("No control under the pointer - point again, or ESC.")
                continue
            say(f"Marked: {under[0].name[:40]}")
            return mark
        time.sleep(TICK_S)
    return ABORTED


def _acting_banner() -> int:  # pragma: no cover - needs a desktop
    """A small topmost strip, top centre: Orbyn is in control and ESC stops
    it (D182). Click-through, never focused, hidden from capture."""

    import ctypes

    import win32api
    import win32con
    import win32gui

    width, height = 360, 30
    left = (win32api.GetSystemMetrics(0) - width) // 2
    hwnd = win32gui.CreateWindowEx(
        win32con.WS_EX_TOPMOST
        | win32con.WS_EX_TOOLWINDOW
        | win32con.WS_EX_NOACTIVATE
        | win32con.WS_EX_TRANSPARENT
        | win32con.WS_EX_LAYERED,
        "STATIC",
        "  Orbyn is acting - press ESC to stop",
        win32con.WS_POPUP | win32con.WS_BORDER | 0x0201,  # SS_CENTER|SS_CENTERIMAGE
        left,
        8,
        width,
        height,
        None,
        None,
        None,
        None,
    )
    win32gui.SetLayeredWindowAttributes(hwnd, 0, 235, win32con.LWA_ALPHA)
    ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x11)
    win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
    return hwnd


@dataclass(frozen=True)
class _Pick:
    id: str
    name: str


def drive_live(
    goal: str,
    hwnds: list[int] | None,
    *,
    gateway=None,
    approved: bool = False,
    deny=(),
    max_steps: int = 8,
    seconds: float = 120.0,
    say=print,
    stop=lambda: False,
    _observe=None,
    _perform=None,
):
    """Drive the desktop toward ``goal`` a click at a time (D185), Jev picking
    each control -- no reviewed plan, so it REFUSES unless ``approved=True``,
    never touches a deny-listed control, stops on ESC or the deadline, and is
    bounded by ``max_steps``. Acts through act.perform (visible mouse, the
    lock-screen / elevated-window blocker). Returns a drive Result.

    ``_observe``/``_perform`` are injection points for tests; the live path
    builds them from the harness observer and act.perform."""

    from ghostcursor.harness.drive import drive_until
    from ghostcursor.providers.envelope import Envelope, Tainted
    from ghostcursor.providers.schemas import ExpectedChange, PlanStep

    DONE = "DONE"
    click = PlanStep("click", ExpectedChange.CHOSEN_STATE_CHANGES)  # action="click"
    gateway = gateway or (None if _observe else _default_gateway())
    live = _observe is None
    observer = overlay = banner = None
    if live:
        from ghostcursor.harness.binding import bind

        observer = Observer(bind(hwnds or choose_windows()))
        observer.start()
        overlay = window.create_overlay_window(hidden_from_capture=True)
        banner = _acting_banner()
    deadline = time.monotonic() + seconds
    state = {"frame": None}

    def observe():
        if _observe is not None:
            frame = _observe()
        else:
            frame = observer.latest()
        state["frame"] = frame
        return [] if frame is None else [_Pick(c.cid, c.name) for c in frame.candidates]

    def choose(goal_text, controls):
        tainted = {c.id: Tainted.of("uia_name", c.name) for c in controls}
        envelope = Envelope(
            task="drive",
            trusted={"goal": goal_text, "done_means": "the goal is already met"},
            tainted=tainted,
        )
        return gateway.choose(
            envelope,
            tuple(c.id for c in controls) + (DONE,),
            question="Which control should be clicked next to reach the goal, "
            "or DONE if the goal is already met?",
        )

    def act(pick):
        target = state["frame"].get(pick.id)
        if target is None:
            raise RuntimeError("the control went away")
        did = (_perform or _live_perform)(click, target)
        say(f"[drive] {did}")

    def stopped():
        return stop() or _escape_pressed() or time.monotonic() >= deadline

    try:
        return drive_until(
            goal,
            observe=observe,
            choose=choose,
            act=act,
            approved=approved,
            deny=deny,
            max_steps=max_steps,
            stop=stopped,
        )
    finally:
        if observer is not None:
            observer.stop()
        if overlay is not None:
            window.destroy_overlay_window(overlay)
        if banner:
            import win32gui

            win32gui.DestroyWindow(banner)


def _default_gateway():
    from ghostcursor.providers import Gateway

    return Gateway()


def _live_perform(step, target):
    from ghostcursor.harness import act as act_mod

    return act_mod.perform(step, target)


def run_model_teach(
    goal: str,
    hwnds: list[int] | None,
    *,
    seconds: float,
    gateway=None,
    point: bool = False,
    plan=None,
    outcome: list | None = None,
    say=print,
    confirm=_console_enter,
    stop=lambda: False,
    act: bool = False,
    deny=(),
) -> int:
    """``outcome`` receives (step, why) for each completed step. A UI passes
    ``say`` (status lines), ``confirm`` (step done) and ``stop`` (its Stop
    button); ESC and the deadline stop the session regardless (rule 4)."""

    from ghostcursor.providers import Gateway
    from ghostcursor.reasoning.staleness import Freshness

    from ghostcursor import settings

    bindings = bind(hwnds or choose_windows())
    seeing = settings.jev_vision()
    observer = Observer(bindings, unnamed=seeing)
    observer.start()
    # One deadline for the whole session, the point prompt included (rule 4).
    deadline = time.monotonic() + seconds
    mark = (
        take_mark(
            observer,
            deadline,
            escape=lambda: _escape_pressed() or stop(),
            enter=confirm,
            say=say,
        )
        if point
        else None
    )
    if mark is ABORTED:
        observer.stop()
        say("Stopped before guidance started.")
        return 0
    look = None
    if seeing:
        from ghostcursor.harness.vision import pictures as look

        say(
            "Jev may see redacted pictures of these windows when text is not "
            "enough (only buttons, tabs and menus; the rest is grey)."
        )
    perform = None
    if act:  # D182: the user approves the plan; Orbyn performs each step
        from ghostcursor.harness.act import perform
    session = ModelTeachSession(
        goal,
        gateway or Gateway(),
        mark=mark,
        plan=plan,
        look=look,
        act=perform,
        deny=deny,
    )
    overlay = window.create_overlay_window(hidden_from_capture=True)
    banner = _acting_banner() if act else None
    say(
        f"{'Act' if act else 'Model Teach'} across "
        f"{', '.join(b.label + ' ' + b.identity.executable for b in bindings)}. "
        + (
            "Enter = approve the plan / a risky step. "
            if act
            else "Pointers are suggestions (amber). Enter = step done. "
        )
        + f"ESC stops (auto-stops after {seconds:g}s)."
    )
    reported = 0
    shown = None
    code = 0
    try:
        while True:
            if _escape_pressed() or stop():
                say("Stopped - exiting.")
                break
            if time.monotonic() >= deadline:
                say("Time limit reached - exiting.")
                break
            if observer.lost:
                say(f"Window {observer.lost} is gone or changed - stopping.")
                code = 3
                break
            done = confirm()
            display = session.tick(observer.latest(), confirm=done)
            for number, why in session.completed[reported:]:
                say(f"[done] step {number}: {why}")
            reported = len(session.completed)
            target = display.target
            if target is None:
                window.clear_hint(overlay)
            else:
                left, top, right, bottom = target.rect
                radius = max(14, min(60, max(right - left, bottom - top) // 2 + 6))
                window.set_hint(
                    overlay,
                    (left + right) // 2,
                    (top + bottom) // 2,
                    radius,
                    Freshness.INFERRED,
                )
            if display.message != shown:
                say(f"[{display.phase.value}] {display.message}")
                shown = display.message
            if display.phase in (Phase.DONE, Phase.BLOCKED):
                code = 0 if display.phase is Phase.DONE else 2
                break
            window.pump_messages_nonblocking()
            time.sleep(TICK_S)
    except KeyboardInterrupt:
        say("Interrupted - exiting.")
    finally:
        session.stop()
        observer.stop()
        window.destroy_overlay_window(overlay)
        if banner:
            import win32gui

            win32gui.DestroyWindow(banner)
        if outcome is not None:
            outcome.extend(session.completed)
        if act:  # D183: an honest local record of what Act did (no screen text)
            _audit(bindings, session.completed, code)
    return code


def _audit(bindings, completed, code: int) -> None:
    """Append one line per Act run to a local audit log: which apps, how each
    step ended, and the exit code. Each ``why`` is already screen-text-free
    ("observed <change>", "you confirmed", "acted (no change seen)"); no
    control name, goal or screen text is written (privacy rule 6). Never fatal."""

    import json
    import os
    import time
    from pathlib import Path

    try:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        path = Path(base) / "GhostCursor" / "act-audit.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = {
            "at": round(time.time(), 3),
            "apps": [b.identity.executable for b in bindings],
            "steps": [{"step": n, "why": why} for n, why in completed],
            "code": code,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except Exception:
        pass

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

    def __init__(self, bindings: tuple[WindowBinding, ...]):
        super().__init__(name="harness-observer", daemon=True)
        self.bindings = bindings
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
                frame = build_frame(frame_id, time.monotonic(), observations)
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
) -> int:
    """``outcome`` receives (step, why) for each completed step. A UI passes
    ``say`` (status lines), ``confirm`` (step done) and ``stop`` (its Stop
    button); ESC and the deadline stop the session regardless (rule 4)."""

    from ghostcursor.providers import Gateway
    from ghostcursor.reasoning.staleness import Freshness

    bindings = bind(hwnds or choose_windows())
    observer = Observer(bindings)
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
    session = ModelTeachSession(goal, gateway or Gateway(), mark=mark, plan=plan)
    overlay = window.create_overlay_window()
    say(
        f"Model Teach across {', '.join(b.label + ' ' + b.identity.executable for b in bindings)}. "
        f"Pointers are suggestions (amber). Enter = step done. "
        f"ESC quits (auto-stops after {seconds:g}s)."
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
        if outcome is not None:
            outcome.extend(session.completed)
    return code

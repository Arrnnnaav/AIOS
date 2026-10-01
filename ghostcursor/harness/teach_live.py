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


def _space_edge(bound: set[int], was_down: bool) -> tuple[bool, bool]:
    """(pressed now as a fresh edge, down now). Only while a bound window has
    focus, so a space typed elsewhere never advances the guide."""

    import win32api
    import win32con
    import win32gui

    down = bool(win32api.GetAsyncKeyState(win32con.VK_SPACE) & 0x8000)
    focused = win32gui.GetForegroundWindow() in bound
    return down and not was_down and focused, down


def _escape_pressed() -> bool:
    """Polled like run.escape_pressed: down now or tapped since the last poll."""

    import win32api
    import win32con

    return bool(win32api.GetAsyncKeyState(win32con.VK_ESCAPE) & 0x8001)


def run_model_teach(
    goal: str, hwnds: list[int] | None, *, seconds: float, gateway=None
) -> int:
    from ghostcursor.providers import Gateway
    from ghostcursor.reasoning.staleness import Freshness

    bindings = bind(hwnds or choose_windows())
    session = ModelTeachSession(goal, gateway or Gateway())
    observer = Observer(bindings)
    observer.start()
    overlay = window.create_overlay_window()
    bound = {b.hwnd for b in bindings}
    print(
        f"Model Teach across {', '.join(b.label + ' ' + b.identity.executable for b in bindings)}. "
        f"Pointers are suggestions (amber). Space in a bound window = step done. "
        f"ESC quits (auto-stops after {seconds:g}s)."
    )
    deadline = time.monotonic() + seconds
    space_down = False
    reported = 0
    shown = None
    code = 0
    try:
        while True:
            if _escape_pressed():
                print("ESC pressed - exiting.")
                break
            if time.monotonic() >= deadline:
                print("Time limit reached - exiting.")
                break
            if observer.lost:
                print(f"Window {observer.lost} is gone or changed - stopping.")
                code = 3
                break
            confirm, space_down = _space_edge(bound, space_down)
            display = session.tick(observer.latest(), confirm=confirm)
            for number, why in session.completed[reported:]:
                print(f"[done] step {number}: {why}")
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
                print(f"[{display.phase.value}] {display.message}")
                shown = display.message
            if display.phase in (Phase.DONE, Phase.BLOCKED):
                code = 0 if display.phase is Phase.DONE else 2
                break
            window.pump_messages_nonblocking()
            time.sleep(TICK_S)
    except KeyboardInterrupt:
        print("Interrupted - exiting.")
    finally:
        session.stop()
        observer.stop()
        window.destroy_overlay_window(overlay)
    return code

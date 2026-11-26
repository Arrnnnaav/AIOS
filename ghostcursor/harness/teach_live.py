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
from ghostcursor.harness.frame import (
    ObservationFrame,
    WindowObservation,
    build_frame,
    resolve,
)
from ghostcursor.harness.teach import (
    HIGH_RISK,
    MAX_FRAME_AGE_S,
    ModelTeachSession,
    Phase,
)
from ghostcursor.harness.uia_reader import is_minimized, read_window, window_facts

TICK_S = 0.1
OBSERVE_INTERVAL_S = 0.4
#: Failed reads in a row before a window that is still bound counts as gone:
#: one UIA hiccup must not end the session (the identity check stays strict).
MAX_READ_MISSES = 3


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
        self._halt = threading.Event()

    def latest(self) -> ObservationFrame | None:
        with self._lock:
            return self._latest

    def stop(self) -> None:
        self._halt.set()

    def run(self) -> None:
        import pythoncom

        pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
        try:
            frame_id = misses = 0
            while not self._halt.is_set():
                observations, missed = [], None
                for binding in self.bindings:
                    rect, controls, timed_out = read_window(binding.hwnd)
                    if not still_bound(binding):  # every window, every round
                        self.lost = binding.label
                        return
                    if rect is None:
                        missed = missed or binding.label
                        continue
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
                if missed is None:
                    misses = 0
                else:
                    misses += 1  # keep the last frame; teach's age check guards it
                    if misses >= MAX_READ_MISSES:
                        self.lost = missed
                        return
                    self._halt.wait(OBSERVE_INTERVAL_S)
                    continue
                frame_id += 1
                frame = build_frame(
                    frame_id, time.monotonic(), observations, unnamed=self.unnamed
                )
                with self._lock:
                    self._latest = frame
                self._halt.wait(OBSERVE_INTERVAL_S)
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


def _require_physical_pixels() -> None:
    """Rule 3 on a mixed-DPI desktop: UIA reports physical pixels, and the
    overlay draws them where they are only if this thread is per-monitor DPI
    aware. A KNOWN other awareness (another library set "system" or
    "unaware" first) would draw every pointer offset from its control, so the
    session is refused. Only per-monitor modes pass; an unknown answer is
    not refused: it cannot be told apart from an older Windows that answers
    no query."""

    from ghostcursor.overlay import dpi

    awareness, _api = dpi.queried_thread_awareness()
    # An allow-list: "unaware-gdi-scaled" (the "System (Enhanced)" override)
    # and any future mode are refused as well as "system" and "unaware".
    if awareness not in ("per-monitor-v2", "per-monitor", dpi.UNKNOWN_AWARENESS):
        raise RuntimeError(
            f"display scaling is in {awareness!r} mode for this window, so Orbyn's "
            "pointer could miss the control; remove any compatibility "
            "'high DPI scaling override' on Python or Orbyn, then restart it"
        )


def _escape_pressed() -> bool:
    """ESC down now or tapped since the last poll (GetAsyncKeyState)."""

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
        windows = {b.label: b.hwnd for b in observer.bindings}
        apps = {b.label: b.identity.executable for b in observer.bindings}
        observer.start()
        try:
            _require_physical_pixels()
            overlay = window.create_overlay_window(hidden_from_capture=True)
            banner = _acting_banner()
        except BaseException:
            observer.stop()
            if overlay is not None:
                window.destroy_overlay_window(overlay)
            raise
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
        chosen = state["frame"].get(pick.id)
        # choose() is a model call that can take seconds: resolve the pick in
        # the latest frame, as Teach does, and never click an old rectangle.
        latest = _observe() if _observe is not None else observer.latest()
        target = None if chosen is None or latest is None else resolve(chosen, latest)
        if target is None:
            raise RuntimeError("the control moved or went away")
        at = getattr(latest, "at", None)  # test fakes may leave it out
        if at is not None and (
            time.monotonic() - at > MAX_FRAME_AGE_S
            or target.window in latest.minimized + latest.incomplete
        ):  # as Teach: a stalled observer must not vouch for an old screen
            raise RuntimeError("the screen reading is out of date")
        if any(d and d.casefold() in (target.name or "").casefold() for d in deny):
            raise PermissionError(f"{target.name!r} is on the deny list")
        if HIGH_RISK.search(target.name or ""):  # renamed in place since choose()
            raise PermissionError(f"Orbyn will not click {target.name!r} without asking")
        did = (
            _perform(click, target)
            if _perform
            else _live_perform(
                click, target, windows[target.window], apps[target.window]
            )
        )
        say(f"[drive] {did}")

    def stopped():
        # The real ESC key is read only on the live path; a test injecting
        # _observe must not depend on the machine's keyboard state.
        return stop() or (live and _escape_pressed()) or time.monotonic() >= deadline

    if approved:
        from ghostcursor import audit

        audit.record("drive_approved", max_steps=max_steps)
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


def _live_perform(step, target, window: int, app: str | None = None, binding=None):
    """``app`` is the bound window's executable, known since binding; without
    it the window is identified here (an OpenProcess on this thread).
    ``binding``: checked right before acting, since the observer's check can
    be seconds old and a reused HWND may now belong to another app."""

    if binding is not None and not still_bound(binding):
        raise PermissionError("the chosen window changed since it was bound; nothing was done")

    from ghostcursor import audit
    from ghostcursor.harness import act as act_mod

    if app is None:
        from ghostcursor.harness.binding import identify

        identity = identify(window)
        app = identity.executable if identity else ""
    from ghostcursor.harness.binding import TERMINALS, denied

    if (app or "").lower() in TERMINALS and getattr(step, "action", "click") not in (
        "click",
        "none",
    ):
        raise PermissionError(
            f"Orbyn does not type or press keys in a command line ({app}); do this step yourself"
        )
    if app and denied(app):
        # Re-checked at every step, not only at bind time: an organisation's
        # AllowedApps/BlockedApps pushed mid-session must stop Act (D180).
        raise PermissionError(f"your organisation does not allow Orbyn to act in {app}")
    fields = dict(
        via="harness",
        action=getattr(step, "action", None),
        control_type=getattr(target, "control_type", None),
        app=app,
    )
    try:
        did = act_mod.perform(step, target, window=window)
    except PermissionError:
        audit.record("act_step", outcome="refused", **fields)
        raise
    except BaseException:
        audit.record("act_step", outcome="failed", **fields)
        raise
    audit.record("act_step", outcome="done", **fields)
    return did


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
    sketch: bool = False,
    speak: bool = False,
    speaker=None,
) -> int:
    """``sketch`` (prototype) draws each step as a hand-drawn circle with an
    arrow from the previous step's control (harness/sketch.py). ``speak``
    (D189) says each step aloud on this PC as its marks draw in.
    ``outcome`` receives (step, why) for each completed step. A UI passes
    ``say`` (status lines), ``confirm`` (step done) and ``stop`` (its Stop
    button); ESC and the deadline stop the session regardless (rule 4)."""

    from ghostcursor.providers import Gateway
    from ghostcursor.reasoning.staleness import Freshness

    from ghostcursor import settings

    bindings = bind(hwnds or choose_windows())
    seeing = settings.jev_vision()
    observer = Observer(bindings, unnamed=seeing)
    observer.start()
    overlay = banner = None
    try:
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
            windows = {b.label: b.hwnd for b in bindings}
            apps = {b.label: b.identity.executable for b in bindings}
            bound = {b.label: b for b in bindings}

            def perform(step, target):
                return _live_perform(
                    step,
                    target,
                    windows[target.window],
                    apps[target.window],
                    bound[target.window],
                )
        session = ModelTeachSession(
            goal,
            gateway or Gateway(),
            mark=mark,
            plan=plan,
            look=look,
            act=perform,
            deny=deny,
        )
        _require_physical_pixels()
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
    except BaseException:  # never leak the observer thread (or the overlay)
        observer.stop()
        if overlay is not None:
            window.destroy_overlay_window(overlay)
        if banner:
            import win32gui

            win32gui.DestroyWindow(banner)
        raise
    reported = 0
    shown = None
    code = 0
    if speak and speaker is None:
        from ghostcursor.speech import Speaker

        speaker = Speaker()
    marks = previous = None
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
            frame = observer.latest()  # one frame per tick, for Teach and the sketch
            display = session.tick(frame, confirm=done)
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
            if sketch:
                marks, previous = _sketch_step(overlay, marks, previous, target, frame)
            if display.message != shown:
                say(f"[{display.phase.value}] {display.message}")
                shown = display.message
                if speaker is not None and display.phase in (
                    Phase.SHOWING,
                    Phase.CONFIRM_RISK,
                    Phase.APPROVE,
                    Phase.BLOCKED,
                    Phase.DONE,
                ):
                    from ghostcursor.speech import spoken

                    speaker.say(spoken(display.message))
            if display.phase in (Phase.DONE, Phase.BLOCKED):
                code = 0 if display.phase is Phase.DONE else 2
                break
            window.pump_messages_nonblocking()
            time.sleep(TICK_S)
    except KeyboardInterrupt:
        say("Interrupted - exiting.")
    finally:
        if speaker is not None:
            speaker.stop()  # ESC, Stop and the deadline silence it too (rule 4)
            if hasattr(speaker, "close"):
                speaker.close()  # its own thread ends; never waited on here
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


def _sketch_step(overlay, marks, previous, target, latest):
    """One tick of Teach's sketch: a new step starts new marks (the old target
    becomes the arrow's tail); otherwise the marks follow their controls and
    vanish if one is lost. Returns (marks, previous)."""

    from ghostcursor.harness import sketch as sketch_mod

    now = time.monotonic()
    if target is None:
        marks = None
    else:
        shown = None if marks is None else marks.control("now")
        if shown is None or shown.runtime_id != target.runtime_id:
            previous = shown or previous
            # The tail is an older control: draw it only where it is now.
            tail = None if previous is None or latest is None else resolve(previous, latest)
            marks = sketch_mod.for_step(target, tail, now)
        elif latest is not None:
            marks = sketch_mod.follow(marks, latest)
    if marks is None:
        window.clear_sketch(overlay)
    else:
        window.set_sketch(overlay, sketch_mod.strokes(marks, now))
    return marks, previous


def _audit(bindings, completed, code: int) -> None:
    """One line per Act run in the audit log (D183, now D187's ``audit.py``):
    the apps, how many steps completed, and the exit code. No control name,
    goal or screen text (privacy rule 6). Never fatal."""

    from ghostcursor import audit

    audit.record(
        "act_run",
        via="harness",
        app=";".join(b.identity.executable for b in bindings),
        code=str(code),
        completed=len(completed),
    )

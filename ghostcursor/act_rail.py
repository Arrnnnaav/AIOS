"""Puts the safety rail on screen for the length of an Act run.

For an object-model node this is the ENTIRE visible product. D109 is explicit
that such a node shows no pointer -- there is no control it is clicking, so a
cursor over one would show an action where it did not happen -- and what it
shows instead is the rail step, a label, and the document changing. The
investor-deck plan is 255 object-model nodes, so without this the whole build
is invisible.

Two rules it exists to keep.

**The rail never counts.** `Step N of M` comes from the executor's own
`ActEvent.ordinal` and `.total`. A rail that counted its own events could
disagree with the executor about which node is running, and the number a user
reads is then not the number the runtime is acting on. Every status string
here is derived from one published event and nothing else.

**A requested stop stays requested.** Once Stop is seen the status reads
`Stopping…` and does not go back to a step number, because the run is still
finishing the node it is in and telling the user it is on step 12 of 255
would suggest it had ignored them.

It is a session-facing surface, so it consumes published values and does not
reinterpret them: it never infers completion, never turns a failure into a
success, and never reconstructs verification state from what it happened to
see.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ghostcursor.overlay import bar

#: Event types that mean the run has finished, whatever the outcome. Held as
#: data rather than as a chain of `if`s so a new terminal event cannot quietly
#: leave the rail showing a step that is no longer running.
_TERMINAL = frozenset({"run_completed", "run_failed", "refused"})

#: What the rail says for each event it knows about. A type absent from here
#: leaves the status alone rather than blanking it: an unrecognised event is
#: not evidence that the previous one stopped being true.
_LABELS = {
    "action_started": "running",
    "action_completed": "done",
    "verification_failed": "unverified",
}


@dataclass
class RailSession:
    """One run's rail. Created with the run and torn down with it."""

    hwnd: int
    #: The last step the EXECUTOR reported, as (ordinal, total). None until
    #: the first node event, because before that there is no step to show and
    #: guessing "1 of N" would be the rail counting.
    step: tuple[int, int] | None = None
    stopping: bool = False
    paused: bool = False
    _finished: bool = False
    _events: list = field(default_factory=list)

    def on_event(self, event) -> None:
        """Consume one published `ActEvent`. The only way status changes."""

        self._events.append(event)
        if event.type in _TERMINAL:
            self._finished = True
            bar.set_status(self.hwnd, _shorten(event.detail))
            return
        if event.ordinal and event.total:
            self.step = (event.ordinal, event.total)
        self._refresh(_LABELS.get(event.type))

    def _refresh(self, label: str | None) -> None:
        if self._finished:
            # Nothing after the end may reword the outcome.
            return
        if self.stopping:
            # Held deliberately. Going back to a step number after Stop was
            # pressed would read as the request having been dropped.
            bar.set_status(self.hwnd, "Stopping…")
            return
        if self.step is None:
            bar.set_status(self.hwnd, "Paused" if self.paused else "Preparing")
            return
        ordinal, total = self.step
        text = f"Step {ordinal} of {total}"
        if self.paused:
            text = f"Paused — {text}"
        elif label:
            text = f"{text} · {label}"
        bar.set_status(self.hwnd, text)

    def poll(self, controls) -> None:
        """Move rail clicks into the run's controls, once each.

        Called from whatever loop is already pumping messages. The rail
        records that a button was pressed; acting on it is the run's job, and
        this is the one place that translation happens.
        """

        state = bar.bar_state(self.hwnd)
        if not (state.stop_requested or state.pause_requested):
            return
        bar.clear_requests(self.hwnd)
        if state.stop_requested:
            self.stopping = True
            controls.stop()
            self._refresh(None)
            return
        # Pause toggles: a second press on a paused run resumes it, which is
        # what a single button has to mean.
        self.paused = not self.paused
        if self.paused:
            controls.pause()
        else:
            controls.resume()
        self._refresh(None)

    @property
    def events(self):
        return tuple(self._events)


def _shorten(detail: str, limit: int = 40) -> str:
    text = (detail or "").strip() or "finished"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def open_rail(*, status: str = "Preparing") -> RailSession:
    """Create the rail and return the session that drives it."""

    hwnd = bar.create_bar_window()
    bar.clear_requests(hwnd)
    bar.set_status(hwnd, status)
    return RailSession(hwnd=hwnd)


def close_rail(session: RailSession) -> None:
    """Tear the rail down. Always call this: a stranded topmost window with
    a Stop button that no longer stops anything is worse than none."""

    bar.destroy_bar_window(session.hwnd)


def rail_pump(session: RailSession, controls) -> Callable[[], bool]:
    """A `keep_running` callable that also services the rail.

    Handed to the presenter so the rail is pumped and read on the same
    callback that decides whether a cue may continue. Two separate loops
    could drift, and the one that drifts is the one holding Stop.
    """

    def keep_running() -> bool:
        bar.pump_messages_nonblocking()
        session.poll(controls)
        return not controls.stop_event.is_set()

    return keep_running


__all__ = ["RailSession", "close_rail", "open_rail", "rail_pump"]

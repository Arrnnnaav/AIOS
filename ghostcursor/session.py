"""Runtime-owned, presentation-neutral session state.

The native rail, manager, diagnostics store, and any future surface consume the
same immutable snapshot.  A surface never counts steps or infers completion;
the executor publishes what is true.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Callable


class SessionStatus(str, Enum):
    UNDERSTANDING = "understanding"
    TARGET_NOT_RUNNING = "target_not_running"
    TARGET_CHOICE_REQUIRED = "target_choice_required"
    PLAN_VALIDATING = "plan_validating"
    PLAN_REJECTED = "plan_rejected"
    READY_TO_START = "ready_to_start"
    GUIDING = "guiding"
    WAITING_FOR_USER = "waiting_for_user"
    VERIFYING = "verifying"
    PAUSED = "paused"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class SessionCapabilities:
    can_pause: bool = False
    can_stop: bool = False
    can_repeat: bool = False
    can_report_problem: bool = False
    can_choose_target: bool = False


@dataclass(frozen=True)
class SessionSnapshot:
    session_id: str
    status: SessionStatus
    goal: str = ""
    intent_id: str | None = None
    plugin_id: str | None = None
    plugin_version: str | None = None
    application: str | None = None
    target_hwnd: int | None = None
    current_step: int = 0
    total_steps: int = 0
    plan_steps: tuple[str, ...] = ()
    instruction: str = ""
    verification_state: str = ""
    elapsed_s: float = 0.0
    error_code: str | None = None
    detail: str = ""
    provenance: tuple[str, ...] = ()
    capabilities: SessionCapabilities = field(default_factory=SessionCapabilities)

    def __post_init__(self) -> None:
        if self.current_step < 0 or self.total_steps < 0:
            raise ValueError("session step counts cannot be negative")
        if self.current_step > self.total_steps:
            raise ValueError("session current step cannot exceed total steps")
        if self.plan_steps and len(self.plan_steps) != self.total_steps:
            raise ValueError("session plan length must equal total steps")
        if self.elapsed_s < 0:
            raise ValueError("session elapsed time cannot be negative")


SessionSink = Callable[[SessionSnapshot], None]


class SessionEventHub:
    """In-process fan-out for presentation surfaces.

    The native rail and manager intentionally share one process.  A hub keeps
    the executor's public launch signature free of policy-bearing injection
    seams while still letting several views consume the same snapshot.  A
    broken optional view cannot turn a valid tour into a failure.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._next_token = 1
        self._subscribers: dict[int, SessionSink] = {}

    def subscribe(self, sink: SessionSink) -> Callable[[], None]:
        if not callable(sink):
            raise TypeError("session sink must be callable")
        with self._lock:
            token = self._next_token
            self._next_token += 1
            self._subscribers[token] = sink

        def unsubscribe() -> None:
            with self._lock:
                self._subscribers.pop(token, None)

        return unsubscribe

    def publish(self, snapshot: SessionSnapshot) -> tuple[Exception, ...]:
        with self._lock:
            subscribers = tuple(self._subscribers.values())
        failures: list[Exception] = []
        for sink in subscribers:
            try:
                sink(snapshot)
            except Exception as exc:  # optional presentation must not abort work
                failures.append(exc)
        return tuple(failures)


class SessionCommand(str, Enum):
    STOP = "stop"
    TOGGLE_PAUSE = "toggle_pause"


class SessionCommandMailbox:
    """Edge-triggered commands from same-process presentation surfaces."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._commands: dict[str, list[SessionCommand]] = {}

    def request(self, session_id: str, command: SessionCommand) -> None:
        if not session_id:
            raise ValueError("session command requires a session id")
        if not isinstance(command, SessionCommand):
            raise TypeError("session command is invalid")
        with self._lock:
            queue = self._commands.setdefault(session_id, [])
            if command is SessionCommand.STOP:
                if command not in queue:
                    queue.append(command)
            else:
                queue.append(command)

    def take(self, session_id: str | None) -> tuple[SessionCommand, ...]:
        if not session_id:
            return ()
        with self._lock:
            return tuple(self._commands.pop(session_id, ()))

    def discard(self, session_id: str | None) -> None:
        if not session_id:
            return
        with self._lock:
            self._commands.pop(session_id, None)


session_events = SessionEventHub()
session_commands = SessionCommandMailbox()


def active_capabilities(*, paused: bool = False) -> SessionCapabilities:
    return SessionCapabilities(
        can_pause=True,
        can_stop=True,
        can_repeat=not paused,
        can_report_problem=True,
    )


def terminal_capabilities() -> SessionCapabilities:
    return SessionCapabilities(can_report_problem=True)

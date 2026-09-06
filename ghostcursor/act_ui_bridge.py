"""One-way bridge from the Act worker to a manager-owned presentation UI.

The signed adapter and verifier wait off the native manager thread.  Win32
overlay creation, painting, message pumping, and destruction must happen on
the manager thread.  This bridge keeps those facts separate: the worker may
request presentation and wait for receipts, but only the owner thread may
service that request against the real ``OverlaySession``.

It carries presentation only.  There is no adapter, verifier, authorization,
selector, or result callback here, so crossing this bridge cannot create an
effect or claim one succeeded.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Callable, Sequence

from ghostcursor.act_protocol import LifecycleState, PresentationRequest, Receipt


class PresentationBridgeClosed(RuntimeError):
    """The UI surface ended before a queued presentation could complete."""


@dataclass
class _Command:
    kind: str
    request: PresentationRequest | None = None
    observation: object | None = None
    sink: Callable[[Receipt, float], None] | None = None
    node: object | None = None
    state: LifecycleState | None = None
    done: threading.Event = field(default_factory=threading.Event)
    receipts: Sequence[Receipt] = ()
    error: BaseException | None = None


class UiThreadPresentationBridge:
    """Worker-facing overlay API serviced by exactly one UI thread."""

    def __init__(self, overlay: object) -> None:
        self._overlay = overlay
        self._owner_thread = threading.get_ident()
        self._commands: queue.Queue[_Command] = queue.Queue()
        self._closed = threading.Event()

    def present(
        self,
        request: PresentationRequest,
        observation: object,
        sink: Callable[[Receipt, float], None] | None = None,
    ) -> Sequence[Receipt]:
        """Queue one cue and wait while the owner thread renders it."""

        if threading.get_ident() == self._owner_thread:
            raise RuntimeError("the UI thread cannot wait on its own presentation bridge")
        if self._closed.is_set():
            raise PresentationBridgeClosed("the presentation surface is closed")
        command = _Command(
            "present", request=request, observation=observation, sink=sink
        )
        self._commands.put(command)
        while not command.done.wait(0.05):
            if self._closed.is_set():
                raise PresentationBridgeClosed("the presentation surface closed")
        if command.error is not None:
            raise command.error
        return command.receipts

    def on_node_state(self, node: object, state: LifecycleState) -> None:
        """Order a repaint/clear behind any cue already in the queue."""

        if self._closed.is_set():
            return
        self._commands.put(_Command("state", node=node, state=state))

    def pump(self, *, maximum: int = 32) -> int:
        """Service queued commands on the thread that created this bridge."""

        self._require_owner()
        handled = 0
        while handled < maximum:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                break
            handled += 1
            try:
                if command.kind == "present":
                    command.receipts = tuple(
                        self._overlay.present(
                            command.request, command.observation, command.sink
                        )
                    )
                elif command.kind == "state":
                    self._overlay.on_node_state(command.node, command.state)
                else:
                    raise RuntimeError("unknown presentation bridge command")
            except BaseException as exc:  # handed back; never lost on UI thread
                command.error = exc
            finally:
                command.done.set()
        return handled

    def close(self) -> None:
        """Release all waiters and clear the real overlay on its owner thread."""

        self._require_owner()
        if self._closed.is_set():
            return
        self._closed.set()
        error = PresentationBridgeClosed("the presentation surface is closed")
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                break
            command.error = error
            command.done.set()
        self._overlay.release()

    def _require_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("presentation UI must be serviced on its owner thread")


__all__ = ["PresentationBridgeClosed", "UiThreadPresentationBridge"]

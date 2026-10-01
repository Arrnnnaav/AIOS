"""A non-blocking, single-slot request runner for model calls.

The UI/tick thread must never wait on a network call (D020/D021). It submits a
request into one overwritten slot and polls for the result on a later tick --
the same shape as the tier-2 OCR request slot. A newer submission supersedes an
older one; cancelling (step change, Stop, Pause, ESC) discards whatever is in
flight, and a result that arrives after cancellation is dropped.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class SlotResult:
    request_id: int
    value: Any = None
    error: BaseException | None = None


class RequestSlot:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generation = 0
        self._result: SlotResult | None = None

    def submit(self, work: Callable[[Callable[[], bool]], Any]) -> int:
        """Start ``work(cancelled)`` on a worker thread; return its request id.

        ``cancelled`` tells the work whether it has been superseded, so a
        provider call can stop early. Never blocks.
        """

        with self._lock:
            self._generation += 1
            request_id = self._generation
            self._result = None

        def cancelled() -> bool:
            with self._lock:
                return self._generation != request_id

        def run() -> None:
            try:
                outcome = SlotResult(request_id, value=work(cancelled))
            except BaseException as exc:  # reported, never raised on the worker
                outcome = SlotResult(request_id, error=exc)
            with self._lock:
                if self._generation == request_id:
                    self._result = outcome

        threading.Thread(
            target=run, name=f"provider-request-{request_id}", daemon=True
        ).start()
        return request_id

    def poll(self, request_id: int) -> SlotResult | None:
        """The result for ``request_id`` if it has arrived and is still current."""

        with self._lock:
            if self._result is not None and self._result.request_id == request_id:
                return self._result
            return None

    def cancel(self) -> None:
        """Supersede whatever is in flight; its result will be discarded."""

        with self._lock:
            self._generation += 1
            self._result = None

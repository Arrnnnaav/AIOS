"""One normalised failure type for every provider call.

A caller never sees an HTTP status or an exception from a transport library;
it sees one of these kinds and decides what to do. None of them is ever a
reason to guess: a failed or invalid model answer means "unavailable".
"""

from __future__ import annotations

from enum import Enum


class FailureKind(str, Enum):
    NOT_CONFIGURED = "not_configured"  # no provider or no key
    UNAVAILABLE = "unavailable"  # connection failed, 5xx after retry
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"  # 429 / quota: becomes NEEDS_USER, never a guess
    AUTH_FAILED = "auth_failed"
    INVALID_OUTPUT = "invalid_output"  # unparseable or outside the closed schema
    BUDGET_EXCEEDED = "budget_exceeded"  # session request or token cap reached
    CANCELLED = "cancelled"


class ProviderError(RuntimeError):
    def __init__(self, kind: FailureKind, detail: str = "") -> None:
        super().__init__(f"{kind.value}: {detail}" if detail else kind.value)
        self.kind = kind
        self.detail = detail

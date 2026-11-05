"""Crash reports for maintenance (D191): HeyClicky ships Sentry; Orbyn sends a
minimal, content-free crash event to a Sentry-compatible endpoint, only when
the organisation named one (``CrashEndpoint`` policy, a Sentry DSN) AND the
person switched crash reports on (``settings.crash_reports``). A policy alone
never adds a destination (rule 6).

What goes: the exception's type name; for each stack frame inside Orbyn its
package-relative file, function and line; for any other frame its module name
only; the Orbyn, Python and Windows versions; a random event id. What never
goes: the exception message (it can hold screen text, a path or a name),
local variables, source lines, file paths outside the package, the user or
machine name. Sending never raises and never blocks Stop (rule 4).
"""

from __future__ import annotations

import json
import platform
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

PACKAGE = Path(__file__).resolve().parent
MAX_FRAMES = 40
TIMEOUT_S = 5.0


def endpoint(dsn: str | None) -> tuple[str, str] | None:
    """(envelope URL, public key) from a DSN like https://KEY@host/PROJECT."""

    if not dsn:
        return None
    try:
        parts = urlsplit(dsn)
        project = parts.path.strip("/")
        if (
            parts.scheme != "https"
            or not parts.hostname
            or not parts.username
            or not project.isdigit()
        ):
            return None
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return None
    return f"https://{parts.hostname}{port}/api/{project}/envelope/", parts.username


def enabled() -> bool:
    from ghostcursor import policy, settings

    return settings.crash_reports() and policy.allows("crash")


def _frame(filename: str, function: str, lineno: int, module: str) -> dict:
    try:
        rel = Path(filename).resolve().relative_to(PACKAGE)  # Orbyn's own code only
        return {
            "filename": f"ghostcursor/{rel.as_posix()}",
            "function": function,
            "lineno": lineno,
            "in_app": True,
        }
    except (ValueError, OSError):
        return {"module": module, "function": function, "in_app": False}


def event(exc: BaseException, *, clock=time.time) -> dict:
    """The whole event: nothing outside this dict is sent."""

    from ghostcursor import __version__

    values = []
    seen = 0
    current: BaseException | None = exc
    while current is not None and seen < 5:  # the cause chain, newest last
        frames = []
        tb = current.__traceback__
        while tb is not None:
            code = tb.tb_frame.f_code
            module = str(tb.tb_frame.f_globals.get("__name__", ""))[:120]
            frames.append(
                _frame(code.co_filename, code.co_name[:120], tb.tb_lineno, module)
            )
            tb = tb.tb_next
        kind = type(current)
        values.insert(
            0,
            {
                "type": kind.__qualname__[:120],
                "module": kind.__module__[:120],
                "stacktrace": {"frames": frames[-MAX_FRAMES:]},
            },
        )
        current = current.__cause__ or current.__context__
        seen += 1
    return {
        "event_id": uuid.uuid4().hex,
        "timestamp": round(clock(), 3),
        "platform": "python",
        "level": "fatal",
        "release": f"orbyn@{__version__}",
        "contexts": {
            "os": {"name": "Windows", "version": platform.version()[:40]},
            "runtime": {"name": "CPython", "version": platform.python_version()},
        },
        "exception": {"values": values},  # oldest cause first, as Sentry expects
    }


def send(exc: BaseException, *, transport=None, dsn: str | None = None) -> bool:
    """Send one crash event if this person and the organisation allow it.
    Returns True only if the endpoint accepted it; never raises."""

    try:
        if dsn is None:
            from ghostcursor import policy

            if not enabled():
                return False
            dsn = policy.crash_endpoint()
        target = endpoint(dsn)
        if target is None:
            return False
        url, key = target
        body = event(exc)
        envelope = "\n".join(
            [
                json.dumps({"event_id": body["event_id"]}),
                json.dumps({"type": "event"}),
                json.dumps(body),
            ]
        )
        import httpx

        with httpx.Client(
            transport=transport, timeout=TIMEOUT_S, follow_redirects=False
        ) as client:
            response = client.post(
                url,
                content=envelope.encode("utf-8"),
                headers={
                    "Content-Type": "application/x-sentry-envelope",
                    "X-Sentry-Auth": f"Sentry sentry_version=7, sentry_key={key}, sentry_client=orbyn/1",
                },
            )
        from ghostcursor import audit

        audit.record(
            "egress",
            provider="crash",
            failure="" if response.is_success else str(response.status_code),
        )
        return response.is_success
    except Exception:
        return False


def install() -> None:
    """Report unhandled exceptions on any thread, after the usual handling.
    A crash on the main thread waits up to TIMEOUT_S to send; a worker
    thread's crash is sent in the background."""

    if getattr(sys.excepthook, "_orbyn", False):  # once per process
        return
    previous, previous_thread = sys.excepthook, threading.excepthook

    def on_crash(kind, value, tb):
        previous(kind, value, tb)
        if not issubclass(kind, KeyboardInterrupt):
            send(value)

    def on_thread_crash(args):
        previous_thread(args)
        if args.exc_value is not None and not isinstance(args.exc_value, SystemExit):
            threading.Thread(target=send, args=(args.exc_value,), daemon=True).start()

    on_crash._orbyn = True
    sys.excepthook, threading.excepthook = on_crash, on_thread_crash

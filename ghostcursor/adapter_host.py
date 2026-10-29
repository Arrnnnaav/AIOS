"""Out-of-process host for one signed first-party executable adapter."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ghostcursor.coordinate_space import BracketedGeometry, bracket_from_record


class AdapterProtocolError(RuntimeError):
    """The adapter failed, timed out, or violated its closed protocol."""


@dataclass(frozen=True)
class AdapterResponse:
    request_id: str
    outcome: str
    detail: str
    facts: tuple[str, ...]
    data: Mapping[str, Any]


@dataclass(frozen=True)
class UiaObservation:
    """One read of a control through the adapter's read-only path.

    Identity is authority-bearing and compared by `uia_identity`; the
    rectangle is presentation-only and never enters an authorization
    (D106/D109).
    """

    request_id: str
    identity: Mapping[str, Any]
    rectangle: tuple[int, int, int, int]
    geometry: BracketedGeometry


@dataclass(frozen=True)
class VerifierResponse:
    verified: bool
    detail: str
    observed: Mapping[str, Any]


class VerifierHost:
    """Run one separately signed, read-only verifier after an adapter effect."""

    def __init__(self, descriptor) -> None:
        self.descriptor = descriptor

    def verify(
        self,
        *,
        node,
        validation_sha256: str,
        output_path: str | None,
        target: Mapping[str, Any],
        timeout_s: float = 10.0,
        cancel_event: threading.Event | None = None,
        baseline: Mapping[str, Any] | None = None,
        postconditions: "tuple[str, ...] | None" = None,
    ) -> VerifierResponse:
        """Run the verifier once.

        `baseline` and `postconditions` are sent ONLY when a caller supplies
        them, and their presence is what distinguishes a live-state request
        from an artifact one. An artifact verifier validates its request
        fields exactly and would refuse a frame carrying either, so adding
        them unconditionally would break every already-signed verifier --
        including the one Phase A's 255/255 was measured against.

        The baseline is passed through untouched. Core does not interpret it:
        "a slide was added" is knowledge about PowerPoint, and the comparison
        belongs in signed plugin code.
        """

        nonce = uuid.uuid4().hex
        request = {
            "node": {
                "node_id": node.node_id,
                "operation_id": node.operation_id,
                "parameters": _plain(node.parameters),
            },
            "output_path": output_path,
            "plugin_id": self.descriptor.plugin_id,
            "plugin_version": self.descriptor.plugin_version,
            "session_nonce": nonce,
            "target": _plain(target),
            "type": "verify",
            "validation_sha256": validation_sha256,
            "verifier_sha256": self.descriptor.verifier_sha256,
        }
        if postconditions is not None:
            request["baseline"] = _plain(baseline) if baseline is not None else None
            request["postconditions"] = list(postconditions)
        process = subprocess.Popen(
            _verified_command(
                self.descriptor.verifier,
                self.descriptor.verifier_sha256,
                "--json",
            ),
            cwd=str(self.descriptor.payload_root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            env=_adapter_environment(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        encoded = json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n"
        # communicate() drains stdout and stderr together, so a chatty child
        # never fills a pipe and stalls into a timeout; on its own thread so
        # Stop and the deadline are still polled. A child that closed stdin
        # early is ignored by communicate() instead of leaking the Popen.
        streams: list = []
        pump = threading.Thread(
            target=lambda: streams.append(process.communicate(encoded)),
            name="GhostCursorVerifierPipes",
            daemon=True,
        )
        deadline = time.monotonic() + timeout_s
        try:
            pump.start()
            while pump.is_alive():
                if cancel_event is not None and cancel_event.is_set():
                    process.terminate()
                    raise AdapterProtocolError("verification stopped")
                if time.monotonic() >= deadline:
                    process.terminate()
                    raise AdapterProtocolError("verifier timed out")
                pump.join(0.02)
            raw, error = streams[0] if streams else ("", "")
            error = error[:4096]
        finally:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
            pump.join(2.0)
        if process.returncode != 0:
            detail = error.strip() or "no diagnostic"
            raise AdapterProtocolError(
                f"verifier exited with code {process.returncode}: {detail}"
            )
        if not raw.endswith("\n") or raw.count("\n") != 1:
            raise AdapterProtocolError("verifier emitted an invalid response stream")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AdapterProtocolError("verifier emitted invalid JSON") from exc
        if not isinstance(value, dict) or set(value) != {
            "detail",
            "node_id",
            "observed",
            "outcome",
            "session_nonce",
            "type",
            "validation_sha256",
        }:
            raise AdapterProtocolError("verifier response fields are invalid")
        if (
            value["type"] != "verification_result"
            or value["node_id"] != node.node_id
            or value["session_nonce"] != nonce
            or value["validation_sha256"] != validation_sha256
            or value["outcome"] not in {"verified", "refused"}
            or not isinstance(value["detail"], str)
            or not isinstance(value["observed"], dict)
        ):
            raise AdapterProtocolError("verifier response is invalid or replayed")
        return VerifierResponse(
            verified=value["outcome"] == "verified",
            detail=value["detail"],
            observed=value["observed"],
        )


class AdapterHost:
    """One adapter subprocess with a nonce-bound JSONL request stream.

    The child is deliberately per Act session.  It cannot survive a plugin
    disable, carry authority into another goal, or retain a reusable channel.
    """

    def __init__(
        self,
        descriptor,
        *,
        session_nonce: str,
        session_context: Mapping[str, Any] | None = None,
    ) -> None:
        self.descriptor = descriptor
        self.session_nonce = session_nonce
        self.session_context = _plain(session_context or {})
        self._process: subprocess.Popen[str] | None = None
        self._responses: queue.Queue[object] = queue.Queue()
        self._reader: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, *, timeout_s: float = 10.0) -> "AdapterHost":
        if self.running:
            return self
        process = subprocess.Popen(
            _verified_command(
                self.descriptor.entrypoint,
                self.descriptor.adapter_sha256,
                "--jsonl",
            ),
            cwd=str(self.descriptor.payload_root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            # Nothing reads it: a PIPE would fill and stall a chatty adapter.
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="strict",
            bufsize=1,
            env=_adapter_environment(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._process = process
        self._reader = threading.Thread(
            target=self._read_stdout,
            name=f"GhostCursorAdapterReader-{self.descriptor.plugin_id}",
            daemon=True,
        )
        self._reader.start()
        self._write(
            {
                "adapter_sha256": self.descriptor.adapter_sha256,
                "plugin_id": self.descriptor.plugin_id,
                "plugin_version": self.descriptor.plugin_version,
                "protocol_version": 1,
                "session_nonce": self.session_nonce,
                "session_context": self.session_context,
                "type": "hello",
            }
        )
        message = self._next(timeout_s)
        if not isinstance(message, dict) or set(message) != {
            "adapter_sha256",
            "plugin_id",
            "plugin_version",
            "protocol_version",
            "session_nonce",
            "session_context",
            "type",
        }:
            self.stop()
            raise AdapterProtocolError("adapter handshake fields are invalid")
        expected = {
            "adapter_sha256": self.descriptor.adapter_sha256,
            "plugin_id": self.descriptor.plugin_id,
            "plugin_version": self.descriptor.plugin_version,
            "protocol_version": 1,
            "session_nonce": self.session_nonce,
            "session_context": self.session_context,
            "type": "ready",
        }
        if message != expected:
            self.stop()
            raise AdapterProtocolError(
                "adapter handshake disagrees with signed authority"
            )
        return self

    def execute(
        self,
        operation_id: str,
        parameters: Mapping[str, Any],
        *,
        node_id: str,
        ordinal: int,
        authorization_sha256: str,
        validation_sha256: str,
        timeout_s: float,
        cancel_event: threading.Event | None = None,
    ) -> AdapterResponse:
        request_id = uuid.uuid4().hex
        self._write(
            {
                "authorization_sha256": authorization_sha256,
                "node_id": node_id,
                "operation_id": operation_id,
                "ordinal": ordinal,
                "parameters": _plain(parameters),
                "request_id": request_id,
                "session_nonce": self.session_nonce,
                "type": "execute",
                "validation_sha256": validation_sha256,
            }
        )
        message = self._next_cancellable(timeout_s, cancel_event)
        # Shared with `dispatch_pattern`: two backends returning the same
        # frame must not drift into accepting different things.
        return self._result(message, request_id)

    def observe_control(
        self,
        control_type: str,
        name: str,
        *,
        timeout_s: float,
        cancel_event: threading.Event | None = None,
    ) -> UiaObservation:
        """Resolve one control and read it, without touching it.

        A SEPARATE method from `execute`, not a flag on it. The generic UIA
        adapter validates its request fields exactly, and the object-model
        `execute` frame carries `operation_id`, `parameters`, `node_id`,
        `ordinal` and `validation_sha256` -- none of which that adapter
        accepts. One method with a mode would have to build two disjoint
        frames anyway, and would make it possible to reach a dispatching call
        by passing the wrong mode. This one has no pattern to send, so it
        cannot dispatch even if something asked it to.
        """

        request_id = uuid.uuid4().hex
        self._write(
            {
                "control_type": control_type,
                "name": name,
                "request_id": request_id,
                "session_nonce": self.session_nonce,
                "type": "observe",
            }
        )
        message = self._next_cancellable(timeout_s, cancel_event)
        if not isinstance(message, dict):
            self.stop()
            raise AdapterProtocolError("adapter response is not a message")
        if message.get("type") == "result":
            # The adapter reports a refused observation on the result frame.
            self._refused(message)
        if set(message) != {
            "coordinate_space",
            "identity",
            "outcome",
            "rectangle",
            "request_id",
            "session_nonce",
            "type",
        }:
            self.stop()
            raise AdapterProtocolError("adapter observation fields are invalid")
        try:
            geometry = bracket_from_record(message["coordinate_space"])
        except (TypeError, ValueError) as exc:
            self.stop()
            raise AdapterProtocolError(
                f"adapter observation coordinate space is invalid: {exc}"
            ) from None
        if (
            message["type"] != "observation"
            or message["request_id"] != request_id
            or message["session_nonce"] != self.session_nonce
            or message["outcome"] != "observed"
            or not isinstance(message["identity"], dict)
            or not isinstance(message["rectangle"], list)
            or len(message["rectangle"]) != 4
            or not all(
                isinstance(part, int) and not isinstance(part, bool)
                for part in message["rectangle"]
            )
        ):
            self.stop()
            raise AdapterProtocolError("adapter observation is invalid or replayed")
        rectangle = tuple(message["rectangle"])
        if geometry.rectangles != (rectangle,):
            self.stop()
            raise AdapterProtocolError(
                "adapter observation rectangle disagrees with its coordinate contract"
            )
        if not geometry.held or geometry.before.units != "physical_pixels":
            self.stop()
            raise AdapterProtocolError(
                "UIA geometry was not observed in one stable physical-pixel space"
            )
        return UiaObservation(
            request_id=request_id,
            identity=dict(message["identity"]),
            rectangle=rectangle,
            geometry=geometry,
        )

    def dispatch_pattern(
        self,
        control_type: str,
        name: str,
        pattern: str,
        *,
        authorization_sha256: str,
        expected_identity: Mapping[str, Any],
        expected_rectangle: tuple[int, int, int, int],
        expected_geometry: BracketedGeometry,
        value: Any = None,
        timeout_s: float,
        cancel_event: threading.Event | None = None,
    ) -> AdapterResponse:
        """Dispatch one UIA pattern on a control resolved by name and type.

        The private session pipe carries the core-minted authorization;
        its digest is an audit binding, not an independently signed token.
        The adapter consumes it once and checks the confirmed identity and
        displayed rectangle before invoking the same resolved element.
        """

        request_id = uuid.uuid4().hex
        self._write(
            {
                "authorization_sha256": authorization_sha256,
                "expected_identity": _plain(expected_identity),
                "expected_rectangle": list(expected_rectangle),
                "expected_coordinate_space": expected_geometry.as_record(),
                "control_type": control_type,
                "name": name,
                "pattern": pattern,
                "request_id": request_id,
                "session_nonce": self.session_nonce,
                "type": "execute",
                "value": value,
            }
        )
        message = self._next_cancellable(timeout_s, cancel_event)
        return self._result(message, request_id)

    def _refused(self, message: Mapping[str, Any]) -> None:
        """Turn a refused observation into an error naming the adapter's own
        detail, rather than a field-shape complaint that hides it."""

        detail = message.get("detail")
        self.stop()
        raise AdapterProtocolError(
            "adapter refused the observation: "
            + (detail if isinstance(detail, str) else "")
        )

    def _result(self, message: object, request_id: str) -> AdapterResponse:
        """Validate one `result` frame. Shared by both dispatch paths so they
        cannot drift into accepting different things."""

        if not isinstance(message, dict) or set(message) != {
            "data",
            "detail",
            "facts",
            "outcome",
            "request_id",
            "session_nonce",
            "type",
        }:
            self.stop()
            raise AdapterProtocolError("adapter response fields are invalid")
        if (
            message["type"] != "result"
            or message["request_id"] != request_id
            or message["session_nonce"] != self.session_nonce
            or message["outcome"] not in {"completed", "failed", "refused"}
            or not isinstance(message["detail"], str)
            or not isinstance(message["facts"], list)
            or not all(isinstance(fact, str) for fact in message["facts"])
            or not isinstance(message["data"], dict)
        ):
            self.stop()
            raise AdapterProtocolError("adapter response is invalid or replayed")
        return AdapterResponse(
            request_id=request_id,
            outcome=message["outcome"],
            detail=message["detail"],
            facts=tuple(message["facts"]),
            data=message["data"],
        )

    def preflight(
        self,
        nodes,
        *,
        validation_sha256: str,
        timeout_s: float = 10.0,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """Ask the signed adapter to validate its entire plugin-specific plan.

        No execute request is admitted until this succeeds.  Core validates the
        graph vocabulary and dependencies; the adapter validates closed
        application-specific details such as shape names and animation enums.
        """

        request_id = uuid.uuid4().hex
        self._write(
            {
                "nodes": [
                    {
                        "node_id": node.node_id,
                        "operation_id": node.operation_id,
                        "parameters": _plain(node.parameters),
                    }
                    for node in nodes
                ],
                "request_id": request_id,
                "session_nonce": self.session_nonce,
                "type": "preflight",
                "validation_sha256": validation_sha256,
            }
        )
        message = self._next_cancellable(timeout_s, cancel_event)
        if not isinstance(message, dict) or set(message) != {
            "detail",
            "outcome",
            "request_id",
            "session_nonce",
            "type",
            "validation_sha256",
        }:
            self.stop()
            raise AdapterProtocolError("adapter preflight fields are invalid")
        if (
            message["type"] != "preflight_result"
            or message["request_id"] != request_id
            or message["session_nonce"] != self.session_nonce
            or message["validation_sha256"] != validation_sha256
            or message["outcome"] not in {"accepted", "rejected"}
            or not isinstance(message["detail"], str)
        ):
            self.stop()
            raise AdapterProtocolError("adapter preflight is invalid or replayed")
        if message["outcome"] != "accepted":
            self.stop()
            raise AdapterProtocolError(
                f"adapter rejected complete plan: {message['detail']}"
            )

    def stop(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.poll() is None:
            try:
                if process.stdin is not None:
                    process.stdin.write(
                        json.dumps(
                            {
                                "session_nonce": self.session_nonce,
                                "type": "stop",
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
                    process.stdin.flush()
                process.wait(timeout=1.0)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2.0)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    # On Windows a reader thread may already have observed a
                    # child that exited before its handshake and closed the
                    # underlying handle. Teardown must not replace the real
                    # protocol/digest refusal with a secondary errno 22.
                    pass

    def _read_stdout(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        try:
            for line in self._process.stdout:
                if not line.endswith("\n"):
                    self._responses.put(
                        AdapterProtocolError("adapter emitted a partial line")
                    )
                    return
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    self._responses.put(
                        AdapterProtocolError("adapter emitted invalid JSON")
                    )
                    return
                self._responses.put(value)
        except BaseException as exc:  # reader reports; UI thread never blocks here
            self._responses.put(exc)
        finally:
            self._responses.put(AdapterProtocolError("adapter output closed"))

    def _write(self, value: Mapping[str, Any]) -> None:
        """The single "is the adapter alive" guard.

        `execute`, `observe_control` and `dispatch_pattern` each used to
        repeat it before calling here, which no test could distinguish from
        not repeating it -- three copies of one condition that could drift
        apart and only ever agreed by luck.
        """

        if not self.running or self._process is None or self._process.stdin is None:
            raise AdapterProtocolError("adapter is not running")
        try:
            self._process.stdin.write(
                json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
            )
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self.stop()
            raise AdapterProtocolError("adapter input closed") from exc

    def _next(self, timeout_s: float) -> object:
        try:
            value = self._responses.get(timeout=timeout_s)
        except queue.Empty as exc:
            self.stop()
            raise AdapterProtocolError("adapter timed out") from exc
        if isinstance(value, BaseException):
            self.stop()
            if isinstance(value, AdapterProtocolError):
                raise value
            raise AdapterProtocolError(f"adapter reader failed: {value}") from value
        return value

    def _next_cancellable(
        self, timeout_s: float, cancel_event: threading.Event | None
    ) -> object:
        deadline = time.monotonic() + timeout_s
        while True:
            if cancel_event is not None and cancel_event.is_set():
                self.stop()
                raise AdapterProtocolError("adapter action stopped")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.stop()
                raise AdapterProtocolError("adapter timed out")
            try:
                value = self._responses.get(timeout=min(0.05, remaining))
            except queue.Empty:
                continue
            if isinstance(value, BaseException):
                self.stop()
                if isinstance(value, AdapterProtocolError):
                    raise value
                raise AdapterProtocolError(f"adapter reader failed: {value}") from value
            return value

    def __enter__(self) -> "AdapterHost":
        return self.start()

    def __exit__(self, _type, _value, _traceback) -> None:
        self.stop()


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _adapter_environment() -> dict[str, str]:
    """Inherit application state without Python path injection.

    The child starts with ``-I`` and the trusted bootstrap adds the core root
    only after that bootstrap is running. Keeping PYTHONPATH here would reopen
    the shadowing gap if isolated mode were ever removed.
    """

    environment = dict(os.environ)
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
        environment.pop(name, None)
    return environment


def _verified_command(path: Path, sha256: str, *arguments: str) -> list[str]:
    """Launch trusted core code first; plugin bytes execute only after hash."""

    bootstrap = Path(__file__).resolve().with_name("verified_python.py")
    return [
        sys.executable,
        "-I",
        "-S",
        str(bootstrap),
        "--sha256",
        sha256,
        str(path),
        *arguments,
    ]


__all__ = [
    "AdapterHost",
    "AdapterProtocolError",
    "AdapterResponse",
    "UiaObservation",
    "VerifierHost",
    "VerifierResponse",
]

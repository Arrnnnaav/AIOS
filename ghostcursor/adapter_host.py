"""Out-of-process host for one signed first-party executable adapter."""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping


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
        output_path: str,
        target: Mapping[str, Any],
        timeout_s: float = 10.0,
        cancel_event: threading.Event | None = None,
    ) -> VerifierResponse:
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
        process = subprocess.Popen(
            [sys.executable, str(self.descriptor.verifier), "--json"],
            cwd=str(self.descriptor.payload_root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        encoded = json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n"
        assert process.stdin is not None
        process.stdin.write(encoded)
        process.stdin.close()
        deadline = time.monotonic() + timeout_s
        try:
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    process.terminate()
                    raise AdapterProtocolError("verification stopped")
                if time.monotonic() >= deadline:
                    process.terminate()
                    raise AdapterProtocolError("verifier timed out")
                time.sleep(0.02)
            assert process.stdout is not None
            raw = process.stdout.read()
            assert process.stderr is not None
            error = process.stderr.read(4096)
        finally:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
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
            [sys.executable, str(self.descriptor.entrypoint), "--jsonl"],
            cwd=str(self.descriptor.payload_root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            bufsize=1,
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
        if not self.running:
            raise AdapterProtocolError("adapter is not running")
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

        if not self.running:
            raise AdapterProtocolError("adapter is not running")
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
                stream.close()

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


__all__ = [
    "AdapterHost",
    "AdapterProtocolError",
    "AdapterResponse",
    "VerifierHost",
    "VerifierResponse",
]

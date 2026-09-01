"""Read-only instrumentation for the Act execution boundary (Phase A).

This module observes; it never authorizes, executes, or verifies.  Nothing
here may change which node runs, whether a node is authorized, or whether a
verification passed -- a probe that can alter the run is not a measurement of
the run.  Every failure inside a probe is captured and reported as a probe
fault rather than raised into the caller.

Why the verify boundary specifically.  The PowerPoint adapter calls
``presentation.Save()`` after every non-inspect node, and the separately
signed verifier then opens the saved package in a fresh process.  Between
those two facts sit four distinct states -- the package before the node, the
package the adapter left behind, the package the verifier actually opened,
and the package after verification returned.  A run record carrying one
digest per node cannot tell them apart, so it cannot say whether a missing
transition was never written, was written and then overwritten, or was
written after the verifier had already read the file.
"""

from __future__ import annotations

import hashlib
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class PackagePart:
    """One entry inside an Open Packaging Convention archive."""

    name: str
    sha256: str
    size: int


@dataclass(frozen=True)
class PackageState:
    """Everything observable about the staging artifact at one instant.

    ``stable`` answers a question a single digest cannot: the whole file was
    read twice in succession and both reads agreed.  A disagreement means the
    bytes were still moving while we looked at them, which is the signature of
    a save that has not finished flushing.
    """

    exists: bool
    sha256: str | None = None
    size: int | None = None
    mtime_ns: int | None = None
    stable: bool | None = None
    parts: Mapping[str, PackagePart] = field(default_factory=dict)
    readable_zip: bool | None = None
    fault: str | None = None


def _digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _parts(path: Path) -> tuple[dict[str, PackagePart], bool]:
    """Per-part digests, so a diff names the XML that changed, not just the file.

    A package that cannot be opened as a zip is a finding, not an error: it is
    what a half-written save looks like from outside.
    """

    try:
        with zipfile.ZipFile(path) as archive:
            parts: dict[str, PackagePart] = {}
            for info in archive.infolist():
                if info.is_dir():
                    continue
                payload = archive.read(info.filename)
                parts[info.filename] = PackagePart(
                    info.filename,
                    hashlib.sha256(payload).hexdigest(),
                    len(payload),
                )
            return parts, True
    except (zipfile.BadZipFile, OSError, KeyError, RuntimeError):
        return {}, False


def observe_package(path: Path, *, with_parts: bool = True) -> PackageState:
    """Snapshot the artifact without opening it for write or holding a handle."""

    path = Path(path)
    try:
        if not path.exists():
            return PackageState(False)
        stat = path.stat()
        first, size = _digest(path)
        second, _ = _digest(path)
        parts: dict[str, PackagePart] = {}
        readable: bool | None = None
        if with_parts:
            parts, readable = _parts(path)
        return PackageState(
            True,
            sha256=first,
            size=size,
            mtime_ns=stat.st_mtime_ns,
            stable=first == second,
            parts=parts,
            readable_zip=readable,
        )
    except OSError as exc:
        return PackageState(True, fault=f"{type(exc).__name__}: {exc}")


@dataclass(frozen=True)
class PartDiff:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    modified: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.modified)


def diff_parts(before: PackageState, after: PackageState) -> PartDiff:
    old, new = before.parts, after.parts
    return PartDiff(
        tuple(sorted(set(new) - set(old))),
        tuple(sorted(set(old) - set(new))),
        tuple(
            sorted(
                name
                for name in set(old) & set(new)
                if old[name].sha256 != new[name].sha256
            )
        ),
    )


def _state_record(state: PackageState) -> dict[str, Any]:
    return {
        "exists": state.exists,
        "fault": state.fault,
        "mtime_ns": state.mtime_ns,
        "part_count": len(state.parts),
        "readable_zip": state.readable_zip,
        "sha256": state.sha256,
        "size": state.size,
        "stable": state.stable,
    }


class ActBoundaryProbe:
    """Records the package states that bracket one node's verification.

    Wire it with :meth:`event_sink` (which captures the pre-node state) and
    :meth:`wrap_verify` (which captures the rest).  Used together they emit one
    ``node_boundary`` record per node carrying the pre-node, post-adapter and
    post-verifier states, the parts each transition changed, and the verifier's
    own wall time and answer.
    """

    def __init__(
        self,
        output_path: Path,
        emit: Callable[[Mapping[str, Any]], None],
        *,
        clock: Callable[[], float] = time.monotonic,
        with_parts: bool = True,
    ) -> None:
        self._path = Path(output_path)
        self._emit = emit
        self._clock = clock
        self._with_parts = with_parts
        self._pending: dict[str, PackageState] = {}
        self._faults = 0

    @property
    def probe_faults(self) -> int:
        return self._faults

    def _observe(self) -> PackageState:
        return observe_package(self._path, with_parts=self._with_parts)

    def event_sink(
        self, downstream: Callable[[Any], None] | None = None
    ) -> Callable[[Any], None]:
        """Wrap an ``ActEvent`` sink, snapshotting the package before each node.

        The downstream sink is always called, even when the probe itself
        fails: instrumentation must not be able to suppress a run's own events.
        """

        def sink(event) -> None:
            try:
                if getattr(event, "type", None) == "action_started":
                    node_id = getattr(event, "node_id", None)
                    if node_id is not None:
                        self._pending[node_id] = self._observe()
            except Exception as exc:  # pragma: no cover - defensive
                self._faults += 1
                self._emit(
                    {"fault": f"{type(exc).__name__}: {exc}", "type": "probe_fault"}
                )
            if downstream is not None:
                downstream(event)

        return sink

    def wrap_verify(self, verify: Callable[..., bool]) -> Callable[..., bool]:
        """Bracket the verifier call without being able to change its answer.

        The verifier's result is returned untouched and its exceptions
        propagate unchanged; only timing and package state are added.
        """

        def instrumented(node, operation, response, approval):
            node_id = getattr(node, "node_id", None)
            before = self._pending.pop(node_id, None)
            after_adapter = self._observe()
            started = self._clock()
            verified: bool | None = None
            error: str | None = None
            try:
                verified = verify(node, operation, response, approval)
                return verified
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                elapsed = self._clock() - started
                after_verify = self._observe()
                self._record(
                    node,
                    before,
                    after_adapter,
                    after_verify,
                    verified=verified,
                    error=error,
                    verifier_seconds=elapsed,
                )

        return instrumented

    def _record(
        self,
        node,
        before: PackageState | None,
        after_adapter: PackageState,
        after_verify: PackageState,
        *,
        verified: bool | None,
        error: str | None,
        verifier_seconds: float,
    ) -> None:
        try:
            adapter_diff = (
                diff_parts(before, after_adapter) if before is not None else None
            )
            verifier_diff = diff_parts(after_adapter, after_verify)
            record: dict[str, Any] = {
                "adapter_added_parts": (
                    None if adapter_diff is None else list(adapter_diff.added)
                ),
                "adapter_removed_parts": (
                    None if adapter_diff is None else list(adapter_diff.removed)
                ),
                "adapter_wrote_parts": (
                    None if adapter_diff is None else list(adapter_diff.modified)
                ),
                "after_adapter": _state_record(after_adapter),
                "after_verify": _state_record(after_verify),
                "before_node": None if before is None else _state_record(before),
                "node_id": getattr(node, "node_id", None),
                "operation_id": getattr(node, "operation_id", None),
                "type": "node_boundary",
                "verified": verified,
                "verifier_error": error,
                "verifier_seconds": round(verifier_seconds, 6),
                # A read-only verifier must not change the package.  If it
                # does, the verifier is not read-only and every digest it
                # reported is suspect.
                "verifier_mutated_package": not verifier_diff.empty,
            }
            self._emit(record)
        except Exception as exc:  # pragma: no cover - defensive
            self._faults += 1
            self._emit({"fault": f"{type(exc).__name__}: {exc}", "type": "probe_fault"})


__all__ = [
    "ActBoundaryProbe",
    "PackagePart",
    "PackageState",
    "PartDiff",
    "diff_parts",
    "observe_package",
]

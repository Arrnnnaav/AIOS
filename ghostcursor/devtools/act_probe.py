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

    ``reads_agreed`` answers a question a single digest cannot: the whole file
    was read twice in succession and both reads matched.  A disagreement proves
    the bytes were moving while we looked at them.  Agreement proves only that
    they did not move between those two reads -- it is not evidence that the
    write completed, and the field is named for what it observed rather than
    for the conclusion someone might want to draw from it.
    """

    exists: bool
    sha256: str | None = None
    size: int | None = None
    mtime_ns: int | None = None
    reads_agreed: bool | None = None
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
            reads_agreed=first == second,
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
        "reads_agreed": state.reads_agreed,
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
        self._after_adapter: dict[str, PackageState] = {}
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

    def verify_observer(self):
        """An observer for ``execute_approved_graph(verify_observer=...)``.

        It is told that verification started and what it answered. It cannot
        wrap, replace, skip, or alter the verifier: core calls the signed
        verifier itself and keeps the answer, and whatever this returns is
        discarded. That is deliberate -- a diagnostic seam that COULD return
        ``True`` in place of a verification is a bypass regardless of what its
        docstring promises.
        """

        def observer(phase: str, facts) -> None:
            try:
                if phase == "verify_started":
                    self._after_adapter[facts.get("node_id")] = self._observe()
                elif phase == "verify_finished":
                    node_id = facts.get("node_id")
                    self._record(
                        node_id,
                        facts.get("operation_id"),
                        self._pending.pop(node_id, None),
                        self._after_adapter.pop(node_id, None),
                        self._observe(),
                        verified=facts.get("verified"),
                        error=facts.get("error"),
                        verifier_seconds=float(facts.get("seconds") or 0.0),
                    )
            except Exception as exc:  # pragma: no cover - defensive
                self._faults += 1
                self._emit(
                    {"fault": f"{type(exc).__name__}: {exc}", "type": "probe_fault"}
                )

        return observer

    def _record(
        self,
        node_id: str | None,
        operation_id: str | None,
        before: PackageState | None,
        after_adapter: PackageState | None,
        after_verify: PackageState,
        *,
        verified: bool | None,
        error: str | None,
        verifier_seconds: float,
    ) -> None:
        try:
            adapter_diff = (
                diff_parts(before, after_adapter)
                if before is not None and after_adapter is not None
                else None
            )
            verifier_diff = (
                diff_parts(after_adapter, after_verify)
                if after_adapter is not None
                else None
            )
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
                "after_adapter": (
                    None if after_adapter is None else _state_record(after_adapter)
                ),
                "after_verify": _state_record(after_verify),
                "before_node": None if before is None else _state_record(before),
                "node_id": node_id,
                "operation_id": operation_id,
                "type": "node_boundary",
                "verified": verified,
                "verifier_error": error,
                "verifier_seconds": round(verifier_seconds, 6),
                # The package changed between the adapter's save and the end
                # of verification.  This does NOT prove the verifier changed
                # it -- an external writer would look identical from here --
                # so the field says what was observed and the classifier is
                # careful not to name a culprit.
                "package_changed_during_verification": (
                    None if verifier_diff is None else not verifier_diff.empty
                ),
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

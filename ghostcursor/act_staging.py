"""The approved output path holds a complete deck or nothing at all.

Measured on 3 September 2026: every stopped run left a partial `.pptx` at its
approved path — 36 to 53 KB against ~94 KB for a complete one — because the
PowerPoint adapter saves after every operation, so the file exists from node
one and grows. A person could open one and mistake it for finished.

The fix is that the run never writes the final path. It writes a staging file
the runtime owns, and the final path is created once, atomically, after
everything has verified.

**Scope, as of 4 September 2026:** the only caller is
`devtools/act_acceptance.py`. `act_cli.py` — the production planning and
execution entry point — still passes the caller's real output path straight
to the approval, so a production run is NOT staged. Everything below
describes what the campaign harness does; wiring `act_cli` through here is
outstanding (D032 review, F1).

**The adapter is not told where the final deck goes.** The plan's
`output_path` parameter is materialized to the staging path, so the adapter
has no way to write the approved final artifact even if something asked it
to. That is structural; the alternative is an adapter that merely refrains.

**Publish is a copy, then a rename — not a rename.** Measured, not assumed:
renaming a `.pptx` PowerPoint has open fails with `WinError 32`, a sharing
violation, while READING the same file succeeds. So the staging bytes are
copied beside the final path and that copy is renamed into place. The rename
is the only moment the final path exists, and it is atomic on one volume.

**The incomplete marker is written at the start and removed on success.** Not
written on failure — a crash runs no failure handler, so a failure-written
marker is exactly absent in the case it exists for.

**The published bytes are the verified bytes.** PowerPoint autosaves. The
staging file is digested before the copy and again after, and the copy itself
is digested; any disagreement refuses the publish rather than shipping
something nothing verified.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

#: Name of the directory the runtime stages into, under the owned output root.
STAGING_DIRNAME = ".staging"

#: Suffix of the marker that says a staging file is not a finished artifact.
MARKER_SUFFIX = ".incomplete.json"

#: Suffix of the copy that becomes the final artifact. It lives beside the
#: final path so the last step is a same-directory rename.
PARTIAL_SUFFIX = ".partial"


class StagingError(RuntimeError):
    """A publish that must not happen, or a staging area that cannot be used."""


@dataclass(frozen=True)
class Staging:
    """One run's staging file, its marker, and the path it is destined for."""

    final: Path
    staging: Path
    marker: Path

    @property
    def complete(self) -> bool:
        """Whether the marker has been cleared. A staging file with its marker
        still present is incomplete, whatever its size suggests."""

        return not self.marker.exists()


def _digest(path: Path) -> str:
    reader = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            reader.update(block)
    return reader.hexdigest()


def _same_volume(left: Path, right: Path) -> bool:
    """Whether an atomic rename between these two is possible.

    Checked rather than assumed. A staging area on another volume makes the
    final step a cross-volume copy, which is not atomic, and the whole
    guarantee would quietly become a wish.
    """

    try:
        return os.stat(left).st_dev == os.stat(right).st_dev
    except OSError as exc:
        raise StagingError(f"cannot compare volumes for {left} and {right}") from exc


def open_staging(final: Path, *, owned_root: Path, run_id: str) -> Staging:
    """Claim a staging file for a run that will publish to ``final``.

    Writes the incomplete marker immediately, so a process that dies at any
    point after this leaves a staging file that is explicitly labelled.
    """

    final = Path(final).resolve()
    owned_root = Path(owned_root).resolve()
    if final.exists():
        # The same rule the approval enforces, restated here because this is
        # the function that would otherwise create the conditions to break it.
        raise StagingError(f"the approved output path already exists: {final}")
    if not owned_root.is_dir():
        raise StagingError(f"owned output root is not a directory: {owned_root}")
    if owned_root not in final.parents:
        raise StagingError(f"{final} is not under the owned root {owned_root}")
    if not run_id or not run_id.isalnum():
        raise StagingError("a run id must be a non-empty alphanumeric string")

    staging_dir = owned_root / STAGING_DIRNAME
    staging_dir.mkdir(parents=True, exist_ok=True)
    if not _same_volume(staging_dir, final.parent):
        raise StagingError(
            "the staging directory and the final path are on different volumes, "
            "so the publish could not be atomic"
        )

    staging = staging_dir / f"{run_id}-{final.name}"
    marker = staging.with_name(staging.name + MARKER_SUFFIX)
    if staging.exists() or marker.exists():
        raise StagingError(f"staging file {staging} is already in use")

    marker.write_text(
        json.dumps(
            {
                "final_path": str(final),
                "note": "INCOMPLETE. This staging file was still being written. "
                "It is not a finished artifact and was never published.",
                "run_id": run_id,
                "started_epoch_s": round(time.time(), 3),
                "staging_path": str(staging),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return Staging(final=final, staging=staging, marker=marker)


def publish(area: Staging) -> str:
    """Make the staging bytes appear at the final path, atomically.

    Returns the digest of what was published. Refuses rather than publishing
    anything it cannot prove is the file that verified.
    """

    if not isinstance(area, Staging):
        raise StagingError("publish needs a Staging")
    if not area.staging.is_file():
        raise StagingError(f"nothing was staged at {area.staging}")
    if area.final.exists():
        raise StagingError(f"the approved output path already exists: {area.final}")

    before = _digest(area.staging)
    partial = area.final.with_name(area.final.name + PARTIAL_SUFFIX)
    if partial.exists():
        partial.unlink()

    try:
        # A copy, because the staging file is open in the application and a
        # rename of an open file fails with a sharing violation. Reading it
        # is permitted; that is measured, not assumed.
        with area.staging.open("rb") as source, partial.open("wb") as target:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                target.write(block)
            target.flush()
            os.fsync(target.fileno())

        after = _digest(area.staging)
        if after != before:
            raise StagingError(
                "the staged file changed while it was being published "
                f"({before} -> {after}); nothing was published"
            )
        copied = _digest(partial)
        if copied != before:
            raise StagingError(
                f"the published copy does not match what was staged "
                f"({copied} != {before}); nothing was published"
            )
        # The one moment the final path comes into existence.
        os.replace(partial, area.final)
    except Exception:
        # The final path is untouched on every failing path. `os.replace` is
        # the last statement precisely so that nothing before it can leave a
        # half-written file where a finished one belongs.
        if partial.exists():
            partial.unlink(missing_ok=True)
        raise

    area.marker.unlink(missing_ok=True)
    return before


def abandon(area: Staging, *, remove: bool = False) -> None:
    """End a run without publishing.

    The marker is deliberately LEFT unless the caller asks for removal, so the
    staging file stays labelled rather than becoming an anonymous partial
    `.pptx` someone later mistakes for a deck.
    """

    if not isinstance(area, Staging):
        raise StagingError("abandon needs a Staging")
    if remove:
        area.staging.unlink(missing_ok=True)
        area.marker.unlink(missing_ok=True)
        return
    # Record that the run ENDED without publishing. Without this the call did
    # nothing at all -- deleting it changed no behaviour, which made it
    # decorative cleanup rather than cleanup (D032 re-review). The
    # distinction it now records is real: a staging file left by a run that
    # stopped is a different thing from one left by a process that died, and
    # only the first can say so.
    if not area.marker.exists():
        return
    try:
        record = json.loads(area.marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    record["abandoned_epoch_s"] = round(time.time(), 3)
    record["note"] = (
        "ABANDONED. The run ended without publishing and this staging file "
        "was never delivered. It is not a finished artifact."
    )
    area.marker.write_text(
        json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
    )


def incomplete_files(owned_root: Path) -> tuple[Staging, ...]:
    """Every staging file under this root that is still marked incomplete.

    What a cleanup pass reads. It reports rather than deletes: removing a
    user's partial work without being asked is not this function's call.
    """

    staging_dir = Path(owned_root).resolve() / STAGING_DIRNAME
    if not staging_dir.is_dir():
        return ()
    found = []
    for marker in sorted(staging_dir.glob("*" + MARKER_SUFFIX)):
        try:
            record = json.loads(marker.read_text(encoding="utf-8"))
            final = Path(record["final_path"])
            staging = Path(record["staging_path"])
        except (OSError, ValueError, KeyError):
            # A marker we cannot read still means "something here is
            # incomplete", so it is reported with what can be recovered from
            # its own name rather than skipped.
            staging = marker.with_name(marker.name[: -len(MARKER_SUFFIX)])
            final = staging
        found.append(Staging(final=final, staging=staging, marker=marker))
    return tuple(found)


__all__ = [
    "MARKER_SUFFIX",
    "PARTIAL_SUFFIX",
    "STAGING_DIRNAME",
    "Staging",
    "StagingError",
    "abandon",
    "incomplete_files",
    "open_staging",
    "publish",
]

"""Classify Phase A boundary records into the four competing explanations.

When a node's declared postcondition is not observed, exactly one of a small
set of things happened, and the boundary records distinguish them:

``never_written``
    The adapter's save changed nothing in the package. The effect never
    reached the file at all, so no amount of verifier patience would find it.

``wrong_part``
    The save changed the package, but not the part the verifier reads for this
    node. The effect landed somewhere else.

``bytes_moved_during_read``
    Two full reads of the same file disagreed, so the package was being
    written while it was observed. The converse does not hold: reads that
    agree are not evidence that a write completed.

``unreadable``
    The package could not be opened as an archive at the moment the verifier
    would have opened it.

``package_changed_during_verification``
    The package changed between the adapter's save and the end of
    verification. This does not name a culprit: the signed verifier is
    supposed to be read-only, but an external writer is indistinguishable
    from here. It outranks the other classes because it invalidates the
    digests rather than explaining the failure. Attributing it requires the
    verifier to report the digest it actually opened, which it does not yet
    do.

``written_and_verified_false``
    The adapter wrote the expected part, two reads of the package agreed, it
    opened cleanly, and verification still said no. This NARROWS the search to
    the verifier's lookup or to what the adapter actually wrote; it does not
    conclusively assign the defect, because the records do not yet contain the
    bytes the verifier opened.

The classifier never guesses. ``unclassified`` is a real answer and means the
records do not contain enough to choose, which is itself a finding about the
instrumentation rather than about the run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class BoundaryFinding:
    node_id: str | None
    operation_id: str | None
    verified: bool | None
    classification: str
    detail: str
    adapter_wrote_parts: tuple[str, ...] = ()
    verifier_seconds: float | None = None


def _parts(record: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = record.get(key)
    return tuple(value) if isinstance(value, list) else ()


def classify_boundary(
    record: Mapping[str, Any], *, expected_parts: Sequence[str] = ()
) -> BoundaryFinding:
    """Explain one ``node_boundary`` record.

    ``expected_parts`` are substrings the node's effect should have touched --
    for a slide-scoped operation, the slide's XML. Supplying none disables the
    ``wrong_part`` distinction rather than inventing an expectation.
    """

    node_id = record.get("node_id")
    operation_id = record.get("operation_id")
    verified = record.get("verified")
    after_adapter = record.get("after_adapter") or {}
    written = _parts(record, "adapter_wrote_parts")
    added = _parts(record, "adapter_added_parts")
    touched = written + added
    seconds = record.get("verifier_seconds")

    def finding(classification: str, detail: str) -> BoundaryFinding:
        return BoundaryFinding(
            node_id,
            operation_id,
            verified,
            classification,
            detail,
            touched,
            seconds if isinstance(seconds, (int, float)) else None,
        )

    if record.get("package_changed_during_verification"):
        return finding(
            "package_changed_during_verification",
            "the package changed between the save and the end of verification, "
            "so its digests are not evidence; this does not identify the writer",
        )
    if record.get("verifier_error"):
        return finding("verifier_error", str(record["verifier_error"]))
    if verified is True:
        return finding("verified", "the declared postcondition was observed")
    if verified is not False:
        # Not a pass. A record with no verification result, or a null one that
        # carried no verifier error either, says nothing about the node -- and
        # a classifier that resolves silence into success would hide exactly
        # the runs it exists to explain.
        return finding(
            "unclassified",
            "the record carries no verification result for this node",
        )
    if after_adapter.get("exists") is False:
        return finding("never_written", "the package did not exist after the save")
    if after_adapter.get("readable_zip") is False:
        return finding(
            "unreadable", "the package could not be opened as an archive after the save"
        )
    if after_adapter.get("reads_agreed") is False:
        return finding(
            "bytes_moved_during_read",
            "two full reads of the package disagreed after the save",
        )
    if record.get("before_node") is None:
        return finding(
            "unclassified", "no pre-node observation was recorded for this node"
        )
    if not touched:
        return finding(
            "never_written", "the save changed no part of the package for this node"
        )
    if expected_parts and not any(
        expected in part for part in touched for expected in expected_parts
    ):
        return finding(
            "wrong_part",
            "the save changed " + ", ".join(touched) + " but not the expected part",
        )
    return finding(
        "written_and_verified_false",
        "the expected part was written, two reads of the package agreed, it "
        "opened cleanly, and verification still failed",
    )


def read_records(path: Path) -> list[dict[str, Any]]:
    """Read a diagnostics JSONL file, keeping malformed lines visible."""

    records: list[dict[str, Any]] = []
    for number, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            value = {"type": "malformed_line", "line": number, "fault": str(exc)}
        if not isinstance(value, dict):  # `5` or `[]`: a line, not a record
            value = {"type": "malformed_line", "line": number, "fault": "not an object"}
        records.append(value)
    return records


def summarise(
    records: Iterable[Mapping[str, Any]], *, expected_parts: Sequence[str] = ()
) -> dict[str, Any]:
    records = list(records)
    boundaries = [r for r in records if r.get("type") == "node_boundary"]
    malformed = [r.get("line") for r in records if r.get("type") == "malformed_line"]
    findings = [classify_boundary(r, expected_parts=expected_parts) for r in boundaries]
    failures = [f for f in findings if f.classification != "verified"]
    seconds = [f.verifier_seconds for f in findings if f.verifier_seconds is not None]
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.classification] = counts.get(finding.classification, 0) + 1
    return {
        "classifications": dict(sorted(counts.items())),
        "first_failure": failures[0] if failures else None,
        # A torn last line (a killed run) may be the failing node itself.
        "malformed_lines": malformed,
        "nodes_recorded": len(boundaries),
        "verifier_seconds_max": max(seconds) if seconds else None,
        "verifier_seconds_total": round(sum(seconds), 3) if seconds else None,
    }


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Explain a Phase A Act diagnostics JSONL file"
    )
    parser.add_argument("records", type=Path)
    parser.add_argument(
        "--expected-part",
        action="append",
        default=[],
        help=(
            "Substring the failing node's effect should have written, e.g. "
            "'ppt/slides/slide5.xml'. Repeatable. Without it the wrong_part "
            "case cannot be distinguished and is never claimed."
        ),
    )
    args = parser.parse_args(argv)
    summary = summarise(
        read_records(args.records), expected_parts=tuple(args.expected_part)
    )
    first = summary.pop("first_failure")
    print(json.dumps(summary, indent=2, sort_keys=True))
    if first is None:
        if summary["malformed_lines"]:
            print("\nno failing node recorded, but some lines are unreadable")
            return 2
        print("\nno failing node recorded")
        return 0
    print(
        "\nfirst failure: "
        + json.dumps(
            {
                "adapter_wrote_parts": list(first.adapter_wrote_parts),
                "classification": first.classification,
                "detail": first.detail,
                "node_id": first.node_id,
                "operation_id": first.operation_id,
                "verifier_seconds": first.verifier_seconds,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 3


__all__ = ["BoundaryFinding", "classify_boundary", "read_records", "summarise"]


if __name__ == "__main__":
    raise SystemExit(main())

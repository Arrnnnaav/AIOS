"""Classify Phase A boundary records into the four competing explanations.

When a node's declared postcondition is not observed, exactly one of a small
set of things happened, and the boundary records distinguish them:

``never_written``
    The adapter's save changed nothing in the package. The effect never
    reached the file at all, so no amount of verifier patience would find it.

``wrong_part``
    The save changed the package, but not the part the verifier reads for this
    node. The effect landed somewhere else.

``unflushed``
    The package was still being written when it was observed -- two full reads
    of the same file disagreed. The verifier read a partial package.

``unreadable``
    The package could not be opened as an archive at the moment the verifier
    would have opened it.

``verifier_not_read_only``
    The package changed across the verification itself. Every digest the
    verifier reported about that package is suspect, and this outranks the
    others because it invalidates the evidence rather than explaining it.

``written_and_verified_false``
    The adapter wrote the expected part, the package was stable and readable,
    and the verifier still said no. The defect is in the verifier's lookup or
    in what the adapter actually wrote -- not in the save/read boundary.

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

    if record.get("verifier_mutated_package"):
        return finding(
            "verifier_not_read_only",
            "the package changed across verification, so its digests are not evidence",
        )
    if record.get("verifier_error"):
        return finding("verifier_error", str(record["verifier_error"]))
    if verified is not False:
        return finding("verified", "the declared postcondition was observed")
    if after_adapter.get("exists") is False:
        return finding("never_written", "the package did not exist after the save")
    if after_adapter.get("readable_zip") is False:
        return finding(
            "unreadable", "the package could not be opened as an archive after the save"
        )
    if after_adapter.get("stable") is False:
        return finding(
            "unflushed", "two full reads of the package disagreed after the save"
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
        "the expected part was written to a stable readable package and "
        "verification still failed",
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
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            records.append(
                {"type": "malformed_line", "line": number, "fault": str(exc)}
            )
    return records


def summarise(
    records: Iterable[Mapping[str, Any]], *, expected_parts: Sequence[str] = ()
) -> dict[str, Any]:
    boundaries = [r for r in records if r.get("type") == "node_boundary"]
    findings = [classify_boundary(r, expected_parts=expected_parts) for r in boundaries]
    failures = [f for f in findings if f.classification != "verified"]
    seconds = [f.verifier_seconds for f in findings if f.verifier_seconds is not None]
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.classification] = counts.get(finding.classification, 0) + 1
    return {
        "classifications": dict(sorted(counts.items())),
        "first_failure": failures[0] if failures else None,
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

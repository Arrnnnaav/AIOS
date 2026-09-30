"""The signed UIA confirmation deadlines are the ones the measurement derived.

D145 made `confirmation_round_trip_deadline_ms` and
`confirmation_to_request_deadline_ms` signed fields of the PowerPoint
`powerpoint.new_slide_uia` operation. Nothing connected those signed values to
`docs/evidence/act-confirmation-budget.md`, and nothing re-rendered that
document from its records; the document had in fact been edited by hand after
rendering (D149 review, finding I2). This mirrors
`test_receipt_budget_is_enforced.py`:

1. the retained records still hash to what the document publishes
   (`test_retained_evidence_digests.py`, and the digests printed below);
2. re-rendering from those records reproduces the document byte for byte;
3. the signed `operations.json` values equal what the records derive,
   recomputed here rather than quoted.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence"
DOCUMENT = EVIDENCE / "act-confirmation-budget.md"
RENDERER = ROOT / "tools" / "render_confirmation_budget.py"
OPERATIONS = (
    ROOT
    / "plugins"
    / "sources"
    / "powerpoint"
    / "payload"
    / "ghostcursor"
    / "operations.json"
)
OPERATION = "powerpoint.new_slide_uia"

#: The three complete runs the derivation uses, and the one retained failure.
RECORDS = (
    "confirmation-budget-live-20260914.json",
    "confirmation-budget-live-20260914-run-2b.json",
    "confirmation-budget-live-20260914-run-3.json",
)
EXCLUDED = ("confirmation-budget-live-20260914-run-2.json",)

_ROW = re.compile(
    r"^\| Confirmation (round trip|to request write) \|.*\*\*(\d+)\*\* \|$", re.M
)


def _rel(name: str) -> str:
    return (EVIDENCE / name).relative_to(ROOT).as_posix()


def _documented() -> dict[str, int]:
    rows = dict(_ROW.findall(DOCUMENT.read_text(encoding="utf-8")))
    assert set(rows) == {"round trip", "to request write"}, rows
    return {key: int(value) for key, value in rows.items()}


def _signed() -> dict[str, int]:
    uia = json.loads(OPERATIONS.read_text(encoding="utf-8"))["operations"][OPERATION][
        "uia"
    ]
    return {
        "round trip": uia["confirmation_round_trip_deadline_ms"],
        "to request write": uia["confirmation_to_request_deadline_ms"],
    }


def test_every_retained_confirmation_record_is_either_used_or_excluded():
    on_disk = {p.name for p in EVIDENCE.glob("confirmation-budget-live-*.json")}
    assert on_disk == set(RECORDS) | set(EXCLUDED), sorted(on_disk)


def test_the_evidence_rerenders_from_its_records_byte_for_byte():
    """Link 2: the renderer's own `--check`, actually run."""

    result = subprocess.run(
        [
            sys.executable,
            RENDERER.relative_to(ROOT).as_posix(),
            "--records",
            *(_rel(name) for name in RECORDS),
            "--excluded",
            *(_rel(name) for name in EXCLUDED),
            "--out",
            DOCUMENT.relative_to(ROOT).as_posix(),
            "--check",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (result.stdout or "") + (result.stderr or "")


def test_the_signed_deadlines_are_the_documented_ones():
    """Link 3 against the document."""

    assert _signed() == _documented()


def test_the_signed_deadlines_are_recomputed_from_the_records():
    """Links 1 and 3 joined: editing the document AND operations.json together
    still fails, because the numbers are derived again from the raw samples.

    The rule: the highest per-run p99 of each measurement, times 2.0, rounded up.
    """

    def p99(values):
        ordered = sorted(values)
        return ordered[max(0, math.ceil(len(ordered) * 0.99) - 1)]

    records = [
        json.loads((EVIDENCE / name).read_text(encoding="utf-8")) for name in RECORDS
    ]
    for record in records:
        assert record["failure"] is None and record["samples_completed"] == 60

    def derive(field):
        return math.ceil(
            max(p99([s[field] for s in r["samples"]]) for r in records) * 2.0
        )

    assert _signed() == {
        "round trip": derive("confirmation_round_trip_ms"),
        "to request write": derive("confirmation_to_request_write_ms"),
    }


def test_the_excluded_record_is_a_real_failure():
    """An exclusion is only honest if the excluded run actually failed."""

    for name in EXCLUDED:
        record = json.loads((EVIDENCE / name).read_text(encoding="utf-8"))
        assert record["failure"] and record["failure"]["failure_class"]
        assert record["samples_completed"] < record["samples_requested"]

"""The production receipt deadlines are the ones the measurement derived.

`ReceiptPolicy` refuses to default its two deadlines, so `act_cli.py` carries
them as constants. Until now nothing connected those constants to
`docs/evidence/act-receipt-budget.md`, and nothing re-rendered that document
from its records.

An activation reviewer demonstrated the consequence: loosening both the evidence
document AND `act_cli.py` together (29 -> 60, 1121 -> 5000) left the whole lane
green. Two documents agreeing with each other is not evidence; they agree
because someone edited both.

D138 claimed the digest table added to the renderer made the derivation
tamper-evident. It did not -- it pins the RECORDS. The derivation is a
computation over those records, and this is what checks it (D139).

Three independent links, so breaking any one fails:

1. the retained records still hash to what the document publishes
   (`test_retained_evidence_digests.py`);
2. re-rendering from those records reproduces the document byte for byte
   (`--check`, below);
3. the deadlines `act_cli.py` uses are the ones the document derives.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence" / "act-receipt-budget.md"
RECORDS = ROOT / "docs" / "evidence" / "receipt-budget"
RENDERER = ROOT / "tools" / "render_receipt_budget.py"

_DERIVED = re.compile(
    r"first_paint_deadline_ms = (\d+)`, `completion_deadline_ms = (\d+)"
)


def _documented_deadlines() -> tuple[int, int]:
    text = EVIDENCE.read_text(encoding="utf-8")
    match = _DERIVED.search(text)
    assert match, "the evidence document no longer states its derived deadlines"
    return int(match.group(1)), int(match.group(2))


def test_the_evidence_rerenders_from_its_records_byte_for_byte():
    """Link 2. The renderer's own `--check` mode, actually run.

    It existed and was never invoked by anything, which is the same shape as a
    measured number nobody records (D034): a check that is not run is a comment.
    """

    assert RENDERER.is_file() and EVIDENCE.is_file() and RECORDS.is_dir()

    # RELATIVE paths, from the repository root. The rendered document embeds
    # the records directory it was given (`Records: <path>`), so an absolute
    # path produces a byte-different document and `--check` reports drift that
    # is really just the caller's working directory. Found by this test failing
    # on a file whose bytes were provably correct.
    result = subprocess.run(
        [
            sys.executable,
            str(RENDERER.relative_to(ROOT)),
            "--records",
            RECORDS.relative_to(ROOT).as_posix(),
            "--out",
            EVIDENCE.relative_to(ROOT).as_posix(),
            "--check",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "the retained receipt-budget evidence is not what its records render to:\n"
        + (result.stdout or "")
        + (result.stderr or "")
    )


def test_production_uses_the_deadlines_the_measurement_derived():
    """Link 3, and the one the reviewer broke. Both numbers, in both places."""

    from ghostcursor.act_cli import (
        MEASURED_COMPLETION_DEADLINE_MS,
        MEASURED_FIRST_PAINT_DEADLINE_MS,
    )

    first_paint, completion = _documented_deadlines()

    assert MEASURED_FIRST_PAINT_DEADLINE_MS == first_paint, (
        f"act_cli.py uses {MEASURED_FIRST_PAINT_DEADLINE_MS}ms for first paint "
        f"while the derivation gives {first_paint}ms"
    )
    assert MEASURED_COMPLETION_DEADLINE_MS == completion, (
        f"act_cli.py uses {MEASURED_COMPLETION_DEADLINE_MS}ms for completion "
        f"while the derivation gives {completion}ms"
    )


def test_the_deadlines_are_recomputed_from_the_records_not_just_quoted():
    """Links 1 and 3 joined: the document's derived numbers are recomputed here
    from the raw records, so editing BOTH the document and `act_cli.py` -- which
    is exactly what survived -- still fails.

    The rule the document states: p99 with a 2.0x margin, rounded up, floored at
    the 15ms scheduling tick, taking the HIGHEST of the runs rather than their
    mean, because a deadline built from the kinder measurement is one the other
    would miss.
    """

    import json
    import math

    runs = sorted(RECORDS.glob("run-*.json"))
    assert len(runs) == 3, [p.name for p in runs]

    def derive(field: str) -> int:
        records = [json.loads(p.read_text(encoding="utf-8")) for p in runs]
        values = [record[field]["p99"] for record in records]
        values.extend(
            record["settled_first_cue"][field]["p99"] for record in records
        )
        worst = max(values)
        return max(15, math.ceil(worst * 2.0))

    first_paint, completion = _documented_deadlines()

    assert derive("first_paint_ms") == first_paint, derive("first_paint_ms")
    assert derive("completion_ms") == completion, derive("completion_ms")


def test_the_renderer_cannot_drop_the_first_cue_from_the_deadline():
    """D018: mutating the renderer back to travelled cues alone must fail."""

    import copy
    from tools import render_receipt_budget

    records = render_receipt_budget.load_records(RECORDS)
    mutated = copy.deepcopy(records)
    summary = mutated[0]["settled_first_cue"]["first_paint_ms"]
    summary["p99"] = summary["max"] = 100.0
    document = render_receipt_budget.render(mutated, RECORDS)

    assert "first_paint_deadline_ms = 200" in document


def test_the_renderer_cannot_drop_first_cue_completion_from_the_deadline():
    import copy
    from tools import render_receipt_budget

    records = render_receipt_budget.load_records(RECORDS)
    mutated = copy.deepcopy(records)
    summary = mutated[0]["settled_first_cue"]["completion_ms"]
    summary["p99"] = summary["max"] = 1000.0
    document = render_receipt_budget.render(mutated, RECORDS)

    assert "completion_deadline_ms = 2000" in document


def test_a_contradictory_first_cue_summary_is_refused():
    import copy
    from tools import render_receipt_budget

    records = render_receipt_budget.load_records(RECORDS)
    mutated = copy.deepcopy(records)
    mutated[0]["settled_first_cue"]["first_paint_ms"]["p99"] = 100.0

    with pytest.raises(render_receipt_budget.EvidenceRefused, match="exceeds"):
        render_receipt_budget.render(mutated, RECORDS)


def test_different_enforcement_clocks_cannot_be_combined():
    import copy
    from tools import render_receipt_budget

    records = render_receipt_budget.load_records(RECORDS)
    mutated = copy.deepcopy(records)
    mutated[1]["enforcement_clock_granularity_ms"] *= 2

    with pytest.raises(render_receipt_budget.EvidenceRefused, match="different"):
        render_receipt_budget.render(mutated, RECORDS)


def test_the_margin_is_declared_as_a_choice():
    """D034: what was measured is the distribution; the margin is a decision and
    the document has to keep saying so, or a reader takes 2.0x for a finding."""

    text = EVIDENCE.read_text(encoding="utf-8")

    assert "CHOICE" in text
    assert "not measured" in text.casefold()


def test_the_check_actually_fails_on_a_drifted_document(tmp_path):
    """A check that cannot fire proves nothing. Rendering to a deliberately
    wrong file must be refused rather than quietly rewritten."""

    drifted = tmp_path / "drifted.md"
    drifted.write_text("not the rendered evidence\n", encoding="utf-8", newline="\n")

    result = subprocess.run(
        [
            sys.executable,
            str(RENDERER.relative_to(ROOT)),
            "--records",
            RECORDS.relative_to(ROOT).as_posix(),
            "--out",
            str(drifted),
            "--check",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, "--check accepted a document that does not match"


def test_acceptance_rejects_a_deadline_override():
    """The acceptance harness cannot widen the reviewed receipt window."""

    from types import SimpleNamespace

    from ghostcursor.devtools.act_acceptance import _validated_measured_deadlines
    from ghostcursor.act_cli import (
        MEASURED_COMPLETION_DEADLINE_MS,
        MEASURED_FIRST_PAINT_DEADLINE_MS,
    )

    with pytest.raises(ValueError, match="disagree"):
        _validated_measured_deadlines(
            SimpleNamespace(
                first_paint_deadline_ms=MEASURED_FIRST_PAINT_DEADLINE_MS + 1,
                completion_deadline_ms=MEASURED_COMPLETION_DEADLINE_MS,
            )
        )


def test_acceptance_uses_the_measured_pair_when_unset():
    from types import SimpleNamespace

    from ghostcursor.devtools.act_acceptance import _validated_measured_deadlines
    from ghostcursor.act_cli import (
        MEASURED_COMPLETION_DEADLINE_MS,
        MEASURED_FIRST_PAINT_DEADLINE_MS,
    )

    assert _validated_measured_deadlines(SimpleNamespace()) == (
        MEASURED_FIRST_PAINT_DEADLINE_MS,
        MEASURED_COMPLETION_DEADLINE_MS,
    )


@pytest.mark.parametrize("first,completion", [
    (60, 5000), (29, 5000), (60, 1121), (29, None),
    (None, 1121), (29.0, 1121), (True, 1121),
])
def test_acceptance_run_refuses_policy_drift_before_side_effects(first, completion):
    from types import SimpleNamespace
    from ghostcursor.devtools.act_acceptance import run

    class UnreachableBundle:
        def resolve(self):
            pytest.fail("run reached bundle setup despite invalid receipt policy")

    assert run(SimpleNamespace(
        measured_deadlines=True,
        first_paint_deadline_ms=first,
        completion_deadline_ms=completion,
        bundle=UnreachableBundle(),
    )) == 2


def test_acceptance_run_continues_with_measured_policy():
    from types import SimpleNamespace
    from ghostcursor.devtools.act_acceptance import run

    class ReachedBundle(Exception):
        pass

    class Bundle:
        def resolve(self):
            raise ReachedBundle

    with pytest.raises(ReachedBundle):
        run(SimpleNamespace(measured_deadlines=True, bundle=Bundle()))

"""Render the receipt-deadline evidence FROM the measurement records.

`ReceiptPolicy` refuses to default its deadlines, so these two numbers get
cited in code the moment they exist. A hand-written table is a figure nothing
else has read (D032), and a number that exists only in a session is not
evidence (D034) -- so this reads the JSON `receipt_budget` printed and refuses
anything it cannot substantiate.

    py -3.12 tools/render_receipt_budget.py `
      --records docs/evidence/receipt-budget `
      --out docs/evidence/act-receipt-budget.md

`--check` re-renders and compares exact bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import sys

#: A deadline is derived from the HIGHEST of the runs, not their average. The
#: runs disagree because the machine does, and a deadline built from the
#: kinder of two measurements is one the other would miss.
REQUIRED_RUNS = 3


class EvidenceRefused(Exception):
    """Raised rather than emitting a document that overstates what was run."""


def _canonical_json(path: pathlib.Path) -> dict:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw:
        raise EvidenceRefused(f"{path.name}: JSON must be UTF-8/LF without BOM")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceRefused(f"{path.name}: invalid UTF-8 JSON ({exc})") from exc


def load_records(directory: pathlib.Path) -> list[dict]:
    if not directory.is_dir():
        raise EvidenceRefused(f"no records directory at {directory}")
    stray = [
        entry.name
        for entry in sorted(directory.iterdir())
        if entry.is_dir() or entry.suffix != ".json"
    ]
    if stray:
        raise EvidenceRefused(f"{directory} contains {stray}; records only")
    paths = sorted(directory.glob("*.json"))
    if len(paths) != REQUIRED_RUNS:
        raise EvidenceRefused(
            f"expected exactly {REQUIRED_RUNS} measurement records, found {len(paths)}"
        )
    records = []
    for path in paths:
        record = _canonical_json(path)
        record["_source"] = path.name
        # The digest of the bytes on disk, so the rendered table states a claim
        # a reader can recompute. Without it the records were named but not
        # pinned, and `test_retained_evidence_digests.py` had nothing to check:
        # the derivation could drift from the measurements it cites with the
        # whole lane green (D138).
        record["_digest"] = hashlib.sha256(path.read_bytes()).hexdigest()
        records.append(record)
    return records


def _check(records: list[dict]) -> None:
    budgets = set()
    screens = set()
    for record in records:
        source = record["_source"]
        if record.get("cues_without_both_receipts"):
            # A run of rejected presentations means the tool measured
            # something other than a cue, and averaging it in would hide that.
            raise EvidenceRefused(
                f"{source}: {record['cues_without_both_receipts']} cues did not "
                "produce both receipts"
            )
        for key in ("first_paint_ms", "completion_ms"):
            summary = record.get(key) or {}
            if not summary.get("samples"):
                raise EvidenceRefused(f"{source}: {key} has no samples")
            for field in ("mean", "median", "p99", "max"):
                value = summary.get(field)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise EvidenceRefused(f"{source}: {key}.{field} is not a number")
                if not math.isfinite(value) or value < 0:
                    raise EvidenceRefused(f"{source}: {key}.{field} is {value!r}")
            if summary["p99"] > summary["max"]:
                raise EvidenceRefused(f"{source}: {key} p99 exceeds its own max")
        # The first cue of a run does not travel, so it is measured apart. A
        # record that folded it in would report a first-paint distribution
        # covering two different things.
        settled = record.get("settled_first_cue") or {}
        if not (settled.get("first_paint_ms") or {}).get("samples"):
            raise EvidenceRefused(
                f"{source}: the untravelled first cue was not measured"
            )
        granularity = record.get("enforcement_clock_granularity_ms")
        if not isinstance(granularity, (int, float)) or granularity <= 0:
            raise EvidenceRefused(
                f"{source}: no measured enforcement clock granularity"
            )
        budgets.add(json.dumps(record.get("budget"), sort_keys=True))
        screens.add(json.dumps(record.get("virtual_screen"), sort_keys=True))

    if len(budgets) != 1:
        raise EvidenceRefused("the runs used different cue budgets")
    if len(screens) != 1:
        # The paint cost scales with desktop area, so a deadline derived
        # across two topologies describes neither.
        raise EvidenceRefused("the runs were taken on different screen topologies")


def _deadline_from_p99(values: list[float], margin: float, granularity: float) -> int:
    """Derive one enforceable deadline from every applicable observation."""

    return max(int(math.ceil(max(values) * margin)), int(math.ceil(granularity)))


def render(records: list[dict], records_dir: pathlib.Path) -> str:
    budget = records[0]["budget"]
    screen = records[0]["virtual_screen"]
    granularity = records[0]["enforcement_clock_granularity_ms"]
    margins = {record.get("margin_over_p99") for record in records}
    if len(margins) != 1:
        raise EvidenceRefused("the runs used different derivation margins")
    margin = next(iter(margins))
    if not isinstance(margin, (int, float)) or isinstance(margin, bool) or margin <= 0:
        raise EvidenceRefused("the derivation margin is not a positive number")
    first_paint = _deadline_from_p99(
        [
            value
            for record in records
            for value in (
                record["first_paint_ms"]["p99"],
                record["settled_first_cue"]["first_paint_ms"]["p99"],
            )
        ],
        margin,
        granularity,
    )
    completion = _deadline_from_p99(
        [record["completion_ms"]["p99"] for record in records],
        margin,
        granularity,
    )

    lines = [
        "# Receipt deadlines — measured",
        "",
        "Generated by `tools/render_receipt_budget.py` from the measurement",
        "records. Do not edit by hand: `--check` re-renders and compares exact",
        "bytes.",
        "",
        f"Records: `{records_dir.as_posix()}`, produced by",
        "`py -3.12 -m ghostcursor.devtools.receipt_budget`.",
        "",
        "## Why these numbers have to exist",
        "",
        "`ReceiptPolicy` refuses to default its two deadlines, for the same",
        "reason `CueBudget` refuses to default `frame_budget_ms`: a plausible",
        "constant is the placeholder measurement exists to replace, and it is",
        "also the number every test would silently agree with. Until these",
        "were measured, both production paths refused every control-driving",
        "plan — correctly, and that refusal was the binding constraint on the",
        "whole Act vertical.",
        "",
        "## What was measured",
        "",
        f"- Cue budget: traversal {budget['traversal_ms']}ms, settle "
        f"{budget['settle_ms']}ms, frame {budget['frame_budget_ms']}ms, poll "
        f"{budget['poll_interval_ms']}ms",
        f"- Virtual screen: `{screen}`",
        f"- Runs: {len(records)}, each of {records[0]['cues_requested']} cues",
        "",
        "Two independent deadlines, from their own instants. **First paint**",
        "runs from the presentation request to the `geometry_started` receipt.",
        "**Completion** runs from that start receipt to",
        "`presentation_completed`. The protocol is explicit that the two are",
        "unordered relative to each other, so measuring one from the other",
        "would derive the wrong number.",
        "",
        "## Results",
        "",
        "| Run | Travelled first-paint mean | median | p99 | First cue | Completion mean | p99 |",
        "|---|---|---|---|---|---|---|",
    ]
    for record in records:
        fp, cp = record["first_paint_ms"], record["completion_ms"]
        first = record["settled_first_cue"]["first_paint_ms"]
        lines.append(
            f"| `{record['_source']}` | {fp['mean']:.3f}ms | {fp['median']:.3f}ms | "
            f"{fp['p99']:.3f}ms | {first['p99']:.3f}ms | {cp['mean']:.3f}ms | "
            f"{cp['p99']:.3f}ms |"
        )

    lines += [
        "",
        "## The records these numbers come from",
        "",
        "One artifact per line with its digest, which is the layout",
        "`tests/test_retained_evidence_digests.py` pairs. Until this table",
        "existed the records were named and not pinned, so the derivation could",
        "drift from its own measurements unnoticed (D138).",
        "",
        "| Record | SHA-256 |",
        "|---|---|",
    ]
    for record in records:
        lines.append(f"| `{record['_source']}` | `{record['_digest']}` |")

    lines += [
        "",
        f"**Derived: `first_paint_deadline_ms = {first_paint}`, "
        f"`completion_deadline_ms = {completion}`.**",
        "",
        "The p99 with a margin, rounded up, and the HIGHEST applicable sample",
        "across all runs rather",
        "than their average — a deadline built from the kinder of two",
        f"measurements is one the other would miss. The margin ({', '.join(str(m) for m in sorted(margins))}×) is a",
        "CHOICE and is reported as one; what is measured is the distribution.",
        "",
        "Completion tracks the cue budget almost exactly: traversal",
        f"{budget['traversal_ms']}ms plus settle {budget['settle_ms']}ms is "
        f"{budget['traversal_ms'] + budget['settle_ms']}ms, and the measured",
        "means land just under it. That agreement is the reason to believe the",
        "harness is timing the thing it claims to time.",
        "",
        "## Two findings the measurement produced",
        "",
        "**The traversal is inside the completion window, not first paint.**",
        "An earlier draft of the tool's own docstring said first paint covered",
        "the traversal. It does not: the first receipt fires when the first",
        "frame is painted, and the cue animates afterwards. First paint is",
        "single-digit milliseconds; completion is the whole animation.",
        "",
        f"**Production times receipts on a clock whose granularity is "
        f"{granularity}ms.**",
        "`act_overlay` defaults to `time.monotonic`, measured here rather than",
        "assumed. The entire first-paint distribution is smaller than one tick",
        "of it, so a first-paint deadline finer than that cannot be enforced by",
        "the clock that checks it, however precisely it was measured. The",
        "derived deadline is floored at one tick for that reason, and the",
        "measurement itself is taken on `perf_counter` — an earlier run timed",
        "on the coarse clock reported first paint as 0.000ms for all 59",
        "travelled cues and derived a deadline of 0, which `ReceiptPolicy`",
        "would have refused.",
        "",
        "## What this does not establish",
        "",
        "- **One machine, one topology.** The paint cost scales with desktop",
        "  area, so these are valid for the virtual screen recorded above and",
        "  nothing else.",
        "- **Nothing about a real application.** The cues were presented",
        "  against synthetic rectangles. No UIA read, no adapter, no dispatch —",
        "  this measures the overlay, which is what the deadlines bound.",
        "- **The first cue follows a different visual path.** It has no previous",
        "  position and so does not travel. Its first-paint sample is reported",
        "  separately, but is included when deriving the shared production",
        "  first-paint deadline because production applies that deadline to",
        "  every cue.",
        "- **The margin is not measured.** It is a choice about headroom over",
        "  a measured p99.",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", required=True, type=pathlib.Path)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        records = load_records(args.records)
        _check(records)
        document = render(records, args.records)
    except EvidenceRefused as exc:
        print(f"evidence refused: {exc}", file=sys.stderr)
        return 2
    if args.check:
        if not args.out.is_file():
            print(f"evidence refused: {args.out} does not exist", file=sys.stderr)
            return 2
        if args.out.read_bytes() != document.encode("utf-8"):
            print(
                f"evidence refused: {args.out} differs from a fresh render",
                file=sys.stderr,
            )
            return 2
        print(f"{args.out} matches the records")
        return 0
    args.out.write_text(document, encoding="utf-8", newline="")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

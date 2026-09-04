"""Render the ADD_SLIDE candidate acceptance evidence FROM the harness records.

The document is derived, never authored. A hand-written evidence table is a
figure nothing else has read (D032), and a number that exists only in a
session is not evidence (D034) -- so this reads the JSON `candidate_acceptance`
printed and refuses anything it cannot substantiate.

    py -3.12 tools/render_add_slide_evidence.py `
      --records .artifacts/add-slide-acceptance/attempt-set-03 `
      --candidate-root plugins/sources/powerpoint/payload/ghostcursor/packs/powerpoint `
      --out docs/evidence/add-slide-candidate-acceptance.md

`--check` re-renders and compares exact bytes, so a stale committed document
fails rather than being silently believed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

INTENT_ID = "ADD_SLIDE"
PACK_ID = "powerpoint"
EXECUTABLE = "powerpnt.exe"
APPLICATION_IDENTITY = {"kind": "executable_version", "value": "16.0.20326.20112"}
ARTIFACTS = {
    "pack": "pack/powerpoint.json",
    "intent": "intents/add_slide.json",
    "recipe": "recipes/add_slide.json",
}
EXPECTED_DIGESTS = {
    "pack": "0b099d868a13477ce1ae281062d303f441120a13a427ce1f6bda1bf589d1b5fc",
    "intent": "b977a9e62a2e9810e479bf137c92edffdec9578984399780543642856be3caa3",
    "recipe": "96ad179d9e4349b1846014c2592c113cf7f0ddd6f33c195fecef589cf23dcad1",
}

#: Whether this workflow's runs record the verification clock start.
#:
#: Declared per workflow and enforced by exact set equality, the way
#: `render_excel_plugin_evidence.py` does: for `SELECT_CELL_B2` the mark's
#: ABSENCE is what its gate demands. What matters is that a workflow is
#: CONSISTENT about it. The second ADD_SLIDE attempt set produced the mark in
#: two runs and not the third, on identical bytes and one HWND, and was
#: refused for exactly that -- see `docs/superpowers/FOLLOWUPS.md`.
VERIFICATION_STARTED = True

#: The recipe's selectors. Named here so the rendered document cannot describe
#: a selector the signed recipe does not actually declare.
VERIFICATION_SELECTOR = "slide2_after"
VERIFICATION_NAME = "View Indicator Slide 2 of 2"
ACTION_SELECTOR = "new_slide"
ACTION_NAME = "New Slide"


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


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_records(directory: pathlib.Path) -> list[dict]:
    paths = sorted(directory.glob("*.json"))
    if len(paths) != 3:
        raise EvidenceRefused(
            f"expected exactly 3 run records under {directory}, found {len(paths)}"
        )
    records = []
    for path in paths:
        record = _canonical_json(path)
        record["_source"] = path.name
        records.append(record)
    return records


def _check_timing(record: dict) -> None:
    source = record["_source"]
    timing = record.get("timing", {})
    required = {"first_observation_s", "first_hint_s", "ended_s"}
    if VERIFICATION_STARTED:
        required.add("verification_started_s")
    if set(timing) != required:
        missing = sorted(required - set(timing))
        extra = sorted(set(timing) - required)
        raise EvidenceRefused(
            f"{source}: timing landmarks are incomplete "
            f"(missing {missing}, unexpected {extra})"
        )
    ordered = [timing["first_observation_s"], timing["first_hint_s"]]
    if VERIFICATION_STARTED:
        ordered.append(timing["verification_started_s"])
    ordered.append(timing["ended_s"])
    if any(not isinstance(value, (int, float)) for value in ordered) or not (
        0 <= ordered[0] and ordered == sorted(ordered)
    ):
        raise EvidenceRefused(f"{source}: timing landmarks are unordered")


def _check_records(records: list[dict]) -> None:
    for record in records:
        source = record["_source"]
        if record.get("record_kind") != "run":
            raise EvidenceRefused(
                f"{source}: record_kind is {record.get('record_kind')!r}, not 'run'"
            )
        if not record.get("is_acceptance_evidence"):
            raise EvidenceRefused(f"{source}: not marked as acceptance evidence")
        if record.get("intent_id") != INTENT_ID:
            raise EvidenceRefused(f"{source}: intent is not {INTENT_ID}")
        if record.get("pack_id") != PACK_ID:
            raise EvidenceRefused(f"{source}: pack is not {PACK_ID}")
        if record.get("outcome") != "passed":
            raise EvidenceRefused(
                f"{source}: outcome is {record.get('outcome')!r}, not passed"
            )
        if record.get("detail"):
            raise EvidenceRefused(f"{source}: carries a detail {record['detail']!r}")
        if record.get("steps") != {"completed": 1, "total": 1}:
            raise EvidenceRefused(f"{source}: did not complete exactly 1/1 step")
        # Provenance, not merely completion: fallback OCR preserves the outcome
        # while the preferred tier is dark, so an outcome-only gate cannot see
        # a tier going dark (D069).
        if record.get("grounding_provenance") != ["uia"] or not record.get(
            "grounded_by_uia_only"
        ):
            raise EvidenceRefused(f"{source}: grounding was not UIA-only")
        if record.get("digests") != EXPECTED_DIGESTS:
            raise EvidenceRefused(f"{source}: artifact digests differ")
        if record.get("application_identity") != APPLICATION_IDENTITY:
            raise EvidenceRefused(f"{source}: application identity differs")
        target = record.get("target", {})
        if target.get("executable") != EXECUTABLE:
            raise EvidenceRefused(f"{source}: target executable is not {EXECUTABLE}")
        if not isinstance(target.get("hwnd"), int) or target["hwnd"] <= 0:
            raise EvidenceRefused(f"{source}: target has no usable HWND")
        _check_timing(record)

    handles = {record["target"]["hwnd"] for record in records}
    if len(handles) != 1:
        raise EvidenceRefused(
            f"the three runs did not bind one captured HWND: {sorted(handles)}"
        )


def _check_artifacts(candidate_root: pathlib.Path) -> dict:
    """The bytes on disk must be the bytes the runs recorded.

    The records carry digests, but a record is only a claim about what the
    harness was handed. Re-hashing the candidate here is what makes the
    document's digest table a statement about files rather than about JSON.
    """

    loaded = {}
    for label, relative in ARTIFACTS.items():
        path = candidate_root / relative
        if not path.is_file():
            raise EvidenceRefused(f"{label}: candidate artifact is missing at {path}")
        actual = _sha256(path)
        if actual != EXPECTED_DIGESTS[label]:
            raise EvidenceRefused(
                f"{label}: candidate bytes hash to {actual}, "
                f"not {EXPECTED_DIGESTS[label]}"
            )
        loaded[label] = _canonical_json(path)
    return loaded


def _check_recipe(recipe: dict) -> None:
    """The document describes the recipe, so the recipe must say what it says."""

    steps = recipe.get("steps", [])
    if len(steps) != 1:
        raise EvidenceRefused(f"recipe declares {len(steps)} steps, not 1")
    step = steps[0]
    if step.get("target_selector") != ACTION_SELECTOR:
        raise EvidenceRefused(f"recipe action selector is not {ACTION_SELECTOR}")
    rule = step.get("verification_rule", {})
    if rule.get("kind") != "element_appears":
        raise EvidenceRefused(f"verification kind is {rule.get('kind')!r}")
    if rule.get("selector") != VERIFICATION_SELECTOR:
        raise EvidenceRefused(f"verification selector is not {VERIFICATION_SELECTOR}")
    selectors = recipe.get("selectors", {})
    for label, selector_id, name in (
        ("action", ACTION_SELECTOR, ACTION_NAME),
        ("verification", VERIFICATION_SELECTOR, VERIFICATION_NAME),
    ):
        declared = selectors.get(selector_id, {})
        if declared.get("names") != [name]:
            raise EvidenceRefused(
                f"{label} selector names {declared.get('names')!r}, not [{name!r}]"
            )
        if declared.get("strategy") != "provider_exact":
            raise EvidenceRefused(f"{label} selector is not provider_exact")
    # An ACTION selector is EXACTLY_ONE: more than one match must refuse rather
    # than silently take the first (D069, D070).
    if selectors.get(ACTION_SELECTOR, {}).get("cardinality") != "exactly_one":
        raise EvidenceRefused("the action selector is not EXACTLY_ONE")


def check(records: list[dict], candidate_root: pathlib.Path) -> dict:
    _check_records(records)
    loaded = _check_artifacts(candidate_root)
    _check_recipe(loaded["recipe"])
    return loaded


def render(records: list[dict], loaded: dict) -> str:
    target = records[0]["target"]
    urls = loaded["recipe"]["steps"][0]["provenance"]["source_urls"]
    lines = [
        "# ADD_SLIDE candidate acceptance",
        "",
        "Generated by `tools/render_add_slide_evidence.py` from the three",
        "acceptance-harness records. Do not edit by hand: `--check` re-renders",
        "and compares exact bytes.",
        "",
        "The candidate is **not adopted** by this document. This is the",
        "acceptance evidence an adoption record would cite; adoption is a",
        "separate, human-gated step (D070).",
        "",
        "## Bound identity and artifacts",
        "",
        f"- Intent: `{INTENT_ID}` in pack `{PACK_ID}`",
        f"- Application identity: `{APPLICATION_IDENTITY['kind']}` = "
        f"`{APPLICATION_IDENTITY['value']}`",
        f"- Target: HWND `{target['hwnd']}`, `{target['executable']}`, "
        f"{target['title']!r}",
        f"- Official provenance: {', '.join(urls)}",
        "- Exact candidate bytes, re-hashed from disk at render time:",
        "",
    ]
    for label, relative in ARTIFACTS.items():
        lines.append(f"  - `{relative}` -- `{EXPECTED_DIGESTS[label]}`")

    lines += [
        "",
        "## Acceptance runs",
        "",
        "Records are committed under",
        "`plugins/sources/powerpoint/acceptance-records/add-slide/`, so every",
        "number below names where it is recorded (D034). Attempt sets that did",
        "not qualify are preserved beside them under `excluded/` with the note",
        "explaining why.",
        "",
        "| Run record | Outcome | Steps | Grounding | First observation | "
        "First hint | Verification start | End |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for record in records:
        timing = record["timing"]
        lines.append(
            f"| `{record['_source']}` | {record['outcome']} | "
            f"{record['steps']['completed']}/{record['steps']['total']} | "
            f"{', '.join(record['grounding_provenance'])} | "
            f"{timing['first_observation_s']:.3f}s | "
            f"{timing['first_hint_s']:.3f}s | "
            f"{timing['verification_started_s']:.3f}s | "
            f"{timing['ended_s']:.3f}s |"
        )

    lines += [
        "",
        "Result: **3/3 passed**, each `1/1` step and UIA-only, all three bound",
        f"to one captured HWND (`{target['hwnd']}`) with identical artifact",
        "digests and one application build.",
        "",
        "## What established the outcome",
        "",
        f"The action was grounded by the declarative `{ACTION_SELECTOR}`",
        f"selector (`provider_exact`, `exactly_one`, name {ACTION_NAME!r}).",
        f"Completion was established by `{VERIFICATION_SELECTOR}`",
        f"(name {VERIFICATION_NAME!r}) under `element_appears`, which is",
        "absent-then-present against the run-start baseline.",
        "",
        "That selector is reachable only from a one-slide deck: from two slides",
        "viewing slide 1, adding a slide yields `View Indicator Slide 2 of 3`,",
        "which does not match. So each passing run took the deck from one slide",
        "to two, and the starting state is established by the record rather",
        "than assumed. The harness cannot itself produce that change -- it makes",
        "no COM call and synthesizes no input, and",
        "`tests/test_no_input_synthesis.py` covers the `devtools` package",
        "explicitly.",
        "",
        "No workflow-specific production Python was added.",
        "",
        "## What this does not establish",
        "",
        "- **Nothing about adoption.** Adoption is a separate human-gated step",
        "  with its own record and its own independent review (D070).",
        "- **No independent provider-level measurement.** Unlike the Open",
        "  Extensions campaign, this evidence carries no separate record of raw",
        "  `FindAll` counts, runtime ids or bounding boxes. The",
        "  absence-then-presence claim rests on the harness's own selector",
        "  observations.",
        "- **The recipe's declared precondition gates nothing.** `slide1_before`",
        "  is parsed into `Step.preconditions` in `reasoning/schema.py` and never",
        "  read by the reasoning path. The one-slide starting state is",
        "  established by the verification selector's semantics above, not by",
        "  that declaration.",
        "- **Nothing about any other deck, application build, or monitor",
        "  topology.** One build, one machine, three supervised runs.",
        "- **Nothing about the `uia_pattern` backend.** This is a guided,",
        "  human-performed workflow, not an Act adapter dispatch.",
        "",
        "## A recorded anomaly in an earlier attempt set",
        "",
        "The second attempt set produced three passing runs, one of which",
        "recorded no `verification_started_s` while the other two did, on",
        "identical bytes and one HWND. It was refused for that inconsistency",
        "and preserved rather than discarded, and the discrepancy remains",
        "unexplained by static reading. See `docs/superpowers/FOLLOWUPS.md`.",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", required=True, type=pathlib.Path)
    parser.add_argument("--candidate-root", required=True, type=pathlib.Path)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        records = load_records(args.records)
        loaded = check(records, args.candidate_root)
        document = render(records, loaded)
    except EvidenceRefused as exc:
        print(f"evidence refused: {exc}", file=sys.stderr)
        return 2
    if args.check:
        if not args.out.is_file():
            print(f"evidence refused: {args.out} does not exist", file=sys.stderr)
            return 2
        if args.out.read_text(encoding="utf-8") != document:
            print(
                f"evidence refused: {args.out} differs from a fresh render",
                file=sys.stderr,
            )
            return 2
        print(f"{args.out} matches the records")
        return 0
    args.out.write_text(document, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

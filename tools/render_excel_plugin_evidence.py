"""Render Excel plugin acceptance evidence from exact harness records.

The renderer accepts only the two reviewed candidate graphs, exactly three
passing UIA-only runs for each graph, and the two aborted worksheet attempts
that preceded the clean campaign.  It re-hashes the candidate artifacts so a
record cannot license different bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


APPLICATION_IDENTITY = {
    "kind": "executable_version",
    "value": "16.0.20326.20112",
}
TARGET_TITLE = "plugin-excel-proof.xlsx - Excel"
PACK_DIGEST = "6f98f07ede9c14ddc2c9abe96b018520145243cd7f09c875e422444b8d6f5101"
WORKFLOWS = {
    "SELECT_CELL_B2": {
        "directory": "select-cell-b2",
        "intent_path": "intents/select_cell_b2.json",
        "intent_digest": "4694ddcb3ad6c207edf12e45542bf80ea9705adf15e9c9c08779cbec1683c2f4",
        "recipe_path": "recipes/select_cell_b2.json",
        "recipe_digest": "164f8540c4c4af9439e209b3f3be37c977b5d66b38ebfb4b553586d0e74e5fb2",
        "verification_started": False,
    },
    "ADD_WORKSHEET": {
        "directory": "add-worksheet",
        "intent_path": "intents/add_worksheet.json",
        "intent_digest": "2bfa3e245bdfc93fc41c8c9c8318cd6d256f15b7017d26b886873d4f1cb9e4e7",
        "recipe_path": "recipes/add_worksheet.json",
        "recipe_digest": "daf27bbf867302cf5a0bc83637cb07df294f213b56c4f48903157183f34d976f",
        "verification_started": True,
    },
}
EXPECTED_RECORDS = {
    *(f"select-cell-b2/run-{run}.json" for run in (1, 2, 3)),
    *(f"add-worksheet/run-{run}.json" for run in (1, 2, 3)),
    "excluded/add-worksheet-attempt-1.json",
    "excluded/add-worksheet-attempt-2.json",
}


class EvidenceRefused(Exception):
    """The supplied files do not substantiate the Excel acceptance claim."""


def _canonical_json(path: Path) -> dict:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw:
        raise EvidenceRefused(f"{path}: JSON must be UTF-8/LF without BOM")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceRefused(f"{path}: invalid UTF-8 JSON ({exc})") from exc
    if not isinstance(value, dict):
        raise EvidenceRefused(f"{path}: JSON root must be an object")
    return value


def load_records(root: Path) -> tuple[dict[str, list[dict]], list[dict]]:
    paths = {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*.json")
    }
    if set(paths) != EXPECTED_RECORDS:
        raise EvidenceRefused(
            "record inventory differs; "
            f"missing={sorted(EXPECTED_RECORDS-set(paths))}, "
            f"extra={sorted(set(paths)-EXPECTED_RECORDS)}"
        )
    campaigns: dict[str, list[dict]] = {}
    for intent_id, policy in WORKFLOWS.items():
        records = []
        for run in (1, 2, 3):
            relative = f"{policy['directory']}/run-{run}.json"
            record = _canonical_json(paths[relative])
            record["_source"] = relative
            records.append(record)
        campaigns[intent_id] = records
    excluded = []
    for run in (1, 2):
        relative = f"excluded/add-worksheet-attempt-{run}.json"
        record = _canonical_json(paths[relative])
        record["_source"] = relative
        excluded.append(record)
    return campaigns, excluded


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_artifact(path: Path, expected: str, label: str) -> dict:
    if not path.is_file():
        raise EvidenceRefused(f"{label}: candidate artifact is missing")
    actual = _sha256(path)
    if actual != expected:
        raise EvidenceRefused(f"{label}: candidate bytes hash to {actual}, not {expected}")
    return _canonical_json(path)


def _check_candidate(candidate_root: Path) -> None:
    pack = _check_artifact(candidate_root / "pack/excel.json", PACK_DIGEST, "pack")
    if pack.get("pack_id") != "excel" or pack.get("version_identity") != {
        "kind": "executable_version"
    }:
        raise EvidenceRefused("pack identity policy differs from the accepted candidate")

    for intent_id, policy in WORKFLOWS.items():
        intent = _check_artifact(
            candidate_root / policy["intent_path"], policy["intent_digest"], intent_id
        )
        recipe = _check_artifact(
            candidate_root / policy["recipe_path"], policy["recipe_digest"], intent_id
        )
        if intent.get("intent_id") != intent_id or recipe.get("intent_id") != intent_id:
            raise EvidenceRefused(f"{intent_id}: artifact intent_id differs")
        selectors = recipe.get("selectors", {})
        if not selectors or any(
            selector.get("strategy") != "window_descendants"
            for selector in selectors.values()
        ):
            raise EvidenceRefused(f"{intent_id}: selector strategy differs")

    cell = _canonical_json(candidate_root / WORKFLOWS["SELECT_CELL_B2"]["recipe_path"])
    if cell["selectors"] != {
        "cell_b2": {
            "cardinality": "exactly_one",
            "control_type": "DataItem",
            "names": ["B2"],
            "normalise": "none",
            "result_limit": 4,
            "strategy": "window_descendants",
        }
    } or cell["steps"][0]["verification_rule"] != {
        "args": {"automation_id": "B2"},
        "kind": "focus_moves_to",
        "timeout_s": 20.0,
    }:
        raise EvidenceRefused("SELECT_CELL_B2 action or verification contract differs")

    sheet = _canonical_json(candidate_root / WORKFLOWS["ADD_WORKSHEET"]["recipe_path"])
    if sheet["selectors"] != {
        "add_sheet": {
            "cardinality": "exactly_one",
            "control_type": "Button",
            "names": ["Add Sheet"],
            "normalise": "none",
            "result_limit": 4,
            "strategy": "window_descendants",
        },
        "sheet2": {
            "cardinality": "exactly_one",
            "control_type": "TabItem",
            "names": ["Sheet2"],
            "normalise": "none",
            "result_limit": 4,
            "strategy": "window_descendants",
        },
    } or sheet["steps"][0]["verification_rule"] != {
        "args": {},
        "kind": "element_appears",
        "selector": "sheet2",
        "timeout_s": 20.0,
    }:
        raise EvidenceRefused("ADD_WORKSHEET action or verification contract differs")


def _expected_digests(intent_id: str) -> dict[str, str]:
    policy = WORKFLOWS[intent_id]
    return {
        "pack": PACK_DIGEST,
        "intent": policy["intent_digest"],
        "recipe": policy["recipe_digest"],
    }


def _check_common(record: dict, intent_id: str, *, outcome: str) -> None:
    source = record["_source"]
    if record.get("record_kind") != "run" or not record.get("is_acceptance_evidence"):
        raise EvidenceRefused(f"{source}: not an acceptance harness run")
    if record.get("intent_id") != intent_id or record.get("pack_id") != "excel":
        raise EvidenceRefused(f"{source}: workflow identity differs")
    if record.get("application_identity") != APPLICATION_IDENTITY:
        raise EvidenceRefused(f"{source}: application identity differs")
    if record.get("digests") != _expected_digests(intent_id):
        raise EvidenceRefused(f"{source}: artifact digests differ")
    if record.get("outcome") != outcome:
        raise EvidenceRefused(f"{source}: outcome is not {outcome}")
    if record.get("grounding_provenance") != ["uia"] or not record.get(
        "grounded_by_uia_only"
    ):
        raise EvidenceRefused(f"{source}: grounding was not UIA-only")
    target = record.get("target", {})
    if (
        target.get("executable") != "excel.exe"
        or target.get("title") != TARGET_TITLE
        or not isinstance(target.get("target_ref"), str)
        or not target["target_ref"]
        or not isinstance(target.get("target_scope"), str)
        or not target["target_scope"]
    ):
        raise EvidenceRefused(f"{source}: target differs from the proof workbook")


def _check_timing(record: dict, *, verification_started: bool) -> None:
    source = record["_source"]
    timing = record.get("timing", {})
    required = {"first_observation_s", "first_hint_s", "ended_s"}
    if verification_started:
        required.add("verification_started_s")
    if set(timing) != required:
        raise EvidenceRefused(f"{source}: timing landmarks are incomplete")
    ordered = [timing["first_observation_s"], timing["first_hint_s"]]
    if verification_started:
        ordered.append(timing["verification_started_s"])
    ordered.append(timing["ended_s"])
    if any(not isinstance(value, (int, float)) for value in ordered) or not (
        0 <= ordered[0] and ordered == sorted(ordered)
    ):
        raise EvidenceRefused(f"{source}: timing landmarks are unordered")


def check(
    campaigns: dict[str, list[dict]], excluded: list[dict], candidate_root: Path
) -> None:
    if set(campaigns) != set(WORKFLOWS):
        raise EvidenceRefused("campaigns do not cover both Excel workflows")
    _check_candidate(candidate_root)
    for intent_id, records in campaigns.items():
        if len(records) != 3:
            raise EvidenceRefused(f"{intent_id}: expected exactly three passing runs")
        for record in records:
            _check_common(record, intent_id, outcome="passed")
            if record.get("steps") != {"completed": 1, "total": 1}:
                raise EvidenceRefused(f"{record['_source']}: did not complete 1/1 step")
            _check_timing(
                record,
                verification_started=WORKFLOWS[intent_id]["verification_started"],
            )

    # Scope is per campaign, not per document: these two workflows were run as
    # separate campaigns and carry separate salts, which is exactly why the
    # document says equality is only meaningful within a column. Each campaign
    # must be internally single-scoped, or its own references are incomparable
    # with each other and every claim below about them is empty (D129/D130).
    for intent_id, campaign in campaigns.items():
        scopes = {item["target"].get("target_scope") for item in campaign}
        if len(scopes) != 1 or not all(isinstance(s, str) and s for s in scopes):
            raise EvidenceRefused(
                f"{intent_id}: records do not share one usable campaign scope, "
                "so their target references cannot be compared"
            )
    # The document says the worksheet runs carry three DISTINCT bindings. That
    # sentence was printed without anything checking it -- and across differing
    # scopes distinctness would have been guaranteed regardless of the handles,
    # which is the same tautology D129 exists to remove (D130).
    sheet_handles = {item["target"]["target_ref"] for item in campaigns["ADD_WORKSHEET"]}
    if len(sheet_handles) != len(campaigns["ADD_WORKSHEET"]):
        raise EvidenceRefused(
            "ADD_WORKSHEET records do not carry distinct target bindings, but "
            "the evidence says they do"
        )
    cell_handles = {
        item["target"]["target_ref"] for item in campaigns["SELECT_CELL_B2"]
    }
    if len(cell_handles) != 1:
        raise EvidenceRefused(
            "SELECT_CELL_B2 did not remain bound to one redacted target binding"
        )
    if len(excluded) != 2:
        raise EvidenceRefused("exactly two excluded worksheet attempts are required")
    for record in excluded:
        _check_common(record, "ADD_WORKSHEET", outcome="aborted")
        if record.get("steps") != {"completed": 0, "total": 1}:
            raise EvidenceRefused(f"{record['_source']}: excluded attempt changed")
        if record.get("detail") != "aborted by the operator":
            raise EvidenceRefused(f"{record['_source']}: exclusion reason changed")
        _check_timing(record, verification_started=True)


def render(campaigns: dict[str, list[dict]], excluded: list[dict]) -> str:
    lines = [
        "# Excel plugin candidate acceptance",
        "",
        "Generated by `tools/render_excel_plugin_evidence.py` from the exact",
        "candidate-acceptance records. Do not edit by hand: `--check` re-renders",
        "and compares exact UTF-8/LF bytes.",
        "",
        "The Excel plugin remained **inactive and unsigned** throughout this",
        "campaign. These records precede installation and activation (D070).",
        "",
        "## Bound identity and candidate bytes",
        "",
        f"- Application identity: `executable_version` = `{APPLICATION_IDENTITY['value']}`",
        f"- Target title: `{TARGET_TITLE}`",
        f"- Pack SHA-256: `{PACK_DIGEST}`",
    ]
    for intent_id, policy in WORKFLOWS.items():
        lines += [
            f"- `{intent_id}` intent SHA-256: `{policy['intent_digest']}`",
            f"- `{intent_id}` recipe SHA-256: `{policy['recipe_digest']}`",
        ]

    lines += [
        "",
        "Both workflows use the generic, explicit `window_descendants` strategy.",
        "No Excel-specific production Python participates in matching, grounding,",
        "verification, or execution.",
        "",
        "## Accepted runs",
        "",
        "| Workflow | Run | Target | Outcome | Steps | Grounding | First observation | First hint | Verification start | End |",
        "|---|---:|---:|---|---:|---|---:|---:|---:|---:|",
    ]
    for intent_id in ("SELECT_CELL_B2", "ADD_WORKSHEET"):
        for run, record in enumerate(campaigns[intent_id], 1):
            timing = record["timing"]
            verification = timing.get("verification_started_s")
            lines.append(
                f"| `{intent_id}` | {run} | `{record['target']['target_ref']}` | passed | "
                f"1/1 | UIA | {timing['first_observation_s']:.3f}s | "
                f"{timing['first_hint_s']:.3f}s | "
                f"{f'{verification:.3f}s' if verification is not None else 'n/a'} | "
                f"{timing['ended_s']:.3f}s |"
            )

    lines += [
        "",
        "Results:",
        "",
        "- `SELECT_CELL_B2`: **3/3 passed**, `1/1` step, UIA-only. The user",
        "  clicked declaratively selected `DataItem` `B2`; completion required",
        "  focus AutomationId `B2`.",
        "- `ADD_WORKSHEET`: **3/3 passed**, `1/1` step, UIA-only. The user",
        "  clicked declaratively selected `Button` `Add Sheet`; completion",
        "  required a newly appearing `TabItem` named `Sheet2`.",
        "",
        "Target references are scoped to one workflow: `window-A` under",
        "`SELECT_CELL_B2` and `window-A` under `ADD_WORKSHEET` are not a claim",
        "that the two workflows shared a window. Equality is only meaningful",
        "within a column.",
        "",
        "The three counted worksheet records carry three distinct target",
        "bindings. The references are pseudonyms: they establish that the runs",
        "did not share one binding, and nothing about which windows those were.",
        "The records do not establish why the bindings differ, so this evidence",
        "makes no claim about reset or reopen operations.",
        "",
        "## Excluded attempts",
        "",
        "Two earlier worksheet attempts are retained but do not count toward 3/3:",
        "",
        "| Record | Outcome | Steps | Verification start | End |",
        "|---|---|---:|---:|---:|",
    ]
    for record in excluded:
        timing = record["timing"]
        lines.append(
            f"| `{record['_source']}` | aborted by operator | 0/1 | "
            f"{timing['verification_started_s']:.3f}s | {timing['ended_s']:.3f}s |"
        )
    lines += [
        "",
        "The harness records establish only that both attempts reached verification",
        "and were then aborted by the operator at `0/1`. They do not establish an",
        "abort cause, and none is claimed. The candidate was not widened to accept",
        "an arbitrary sheet; the exact reviewed `Sheet2` postcondition was later",
        "demonstrated 3/3.",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", required=True, type=Path)
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        campaigns, excluded = load_records(args.records)
        check(campaigns, excluded, args.candidate_root)
    except (EvidenceRefused, OSError, KeyError, TypeError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    rendered = render(campaigns, excluded).encode("utf-8")
    if args.check:
        current = args.out.read_bytes() if args.out.exists() else b""
        if current != rendered:
            print(f"refused: {args.out} differs from the records", file=sys.stderr)
            return 1
        print(f"{args.out} matches the Excel acceptance records")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(rendered)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

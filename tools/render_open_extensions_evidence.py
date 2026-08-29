"""Render Task 12 Open Extensions evidence from harness and provider records.

The three acceptance outcomes come from ``candidate_acceptance``.  The
provider measurement is separate because the harness record intentionally
contains only execution facts; Task 12 additionally requires raw FindAll
counts, successful property reads, and pre/post version checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys


INTENT_ID = "OPEN_EXTENSIONS"
APPLICATION_IDENTITY = {
    "kind": "executable_version",
    "value": "1.135.0.0",
}
SOURCE_URL = (
    "https://code.visualstudio.com/docs/configure/extensions/extension-marketplace"
)
EXPECTED_DIGESTS = {
    "pack": "185cd7431e4f7e5ecd2d9e372a15690edd496a26667bafbb59f218762bb2f992",
    "intent": "f4c5f6a24ab494660fa51cd9b1676ed437cc79c5877eb735b34607771446e025",
    "recipe": "b749cca0ff2f12929321effc46383baba7816bfd5b043e1f94e4e38e3ea1cca7",
}
EXPECTED_PHASES = {(run, phase) for run in (1, 2, 3) for phase in ("pre", "post")}


class EvidenceRefused(Exception):
    """The supplied records do not substantiate the Task 12 claim."""


def _canonical_json(path: pathlib.Path) -> dict:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw:
        raise EvidenceRefused(f"{path.name}: JSON must be UTF-8/LF without BOM")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceRefused(f"{path.name}: invalid UTF-8 JSON ({exc})") from exc


def load_records(directory: pathlib.Path) -> list[dict]:
    paths = sorted(directory.glob("*.json"))
    if len(paths) != 3:
        raise EvidenceRefused(f"expected exactly 3 run records, found {len(paths)}")
    records = []
    for path in paths:
        record = _canonical_json(path)
        record["_source"] = path.name
        records.append(record)
    return records


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_records(records: list[dict]) -> None:
    for record in records:
        source = record["_source"]
        if record.get("record_kind") != "run" or not record.get(
            "is_acceptance_evidence"
        ):
            raise EvidenceRefused(f"{source}: not an acceptance run record")
        if record.get("intent_id") != INTENT_ID:
            raise EvidenceRefused(f"{source}: intent is not {INTENT_ID}")
        if record.get("pack_id") != "vscode":
            raise EvidenceRefused(f"{source}: pack is not vscode")
        if record.get("outcome") != "passed":
            raise EvidenceRefused(f"{source}: outcome is not passed")
        if record.get("steps") != {"completed": 1, "total": 1}:
            raise EvidenceRefused(f"{source}: did not complete exactly 1/1 step")
        if record.get("grounding_provenance") != ["uia"] or not record.get(
            "grounded_by_uia_only"
        ):
            raise EvidenceRefused(f"{source}: grounding was not UIA-only")
        if record.get("digests") != EXPECTED_DIGESTS:
            raise EvidenceRefused(f"{source}: artifact digests differ")
        if record.get("application_identity") != APPLICATION_IDENTITY:
            raise EvidenceRefused(f"{source}: application identity differs")
        target = record.get("target", {})
        if target.get("executable") != "code.exe" or "AIOS" not in target.get(
            "title", ""
        ):
            raise EvidenceRefused(f"{source}: target is not the AIOS Code window")
        timing = record.get("timing", {})
        required = {
            "first_observation_s",
            "first_hint_s",
            "verification_started_s",
            "ended_s",
        }
        if set(timing) != required or not (
            0 <= timing["first_observation_s"]
            <= timing["first_hint_s"]
            <= timing["verification_started_s"]
            <= timing["ended_s"]
        ):
            raise EvidenceRefused(f"{source}: timing landmarks are incomplete or unordered")

    handles = {record["target"]["hwnd"] for record in records}
    if len(handles) != 1:
        raise EvidenceRefused("the three runs did not bind one captured HWND")


def _check_artifacts(measurement: dict, candidate_root: pathlib.Path) -> dict:
    paths = measurement.get("artifacts", {})
    if set(paths) != set(EXPECTED_DIGESTS):
        raise EvidenceRefused("measurement does not name exactly pack/intent/recipe")
    loaded = {}
    for label, expected in EXPECTED_DIGESTS.items():
        path = candidate_root / paths[label]
        if not path.is_file():
            raise EvidenceRefused(f"{label}: candidate artifact is missing")
        actual = _sha256(path)
        if actual != expected:
            raise EvidenceRefused(f"{label}: candidate bytes hash to {actual}, not {expected}")
        loaded[label] = _canonical_json(path)

    recipe_urls = loaded["recipe"]["steps"][0]["provenance"]["source_urls"]
    if recipe_urls != [SOURCE_URL] or measurement.get("source_url") != SOURCE_URL:
        raise EvidenceRefused("official provenance URL differs from the recipe")
    return loaded


def _check_measurement(measurement: dict, records: list[dict]) -> None:
    if measurement.get("schema_version") != 1:
        raise EvidenceRefused("provider measurement schema_version is not 1")
    if measurement.get("application_identity") != APPLICATION_IDENTITY:
        raise EvidenceRefused("provider measurement application identity differs")
    if measurement.get("target") != records[0]["target"]:
        raise EvidenceRefused("provider measurement target differs from the run target")

    version_checks = measurement.get("version_checks", [])
    phases = {(item.get("run"), item.get("phase")) for item in version_checks}
    if len(version_checks) != 6 or phases != EXPECTED_PHASES:
        raise EvidenceRefused("version checks do not cover pre/post for runs 1-3")
    if {item.get("value") for item in version_checks} != {"1.135.0.0"}:
        raise EvidenceRefused("application version drifted during the campaign")

    samples = measurement.get("provider_samples", [])
    phases = {(item.get("run"), item.get("phase")) for item in samples}
    if len(samples) != 6 or phases != EXPECTED_PHASES:
        raise EvidenceRefused("provider samples do not cover pre/post for runs 1-3")
    for item in samples:
        phase = item["phase"]
        expected_verification = 0 if phase == "pre" else 1
        expected = {
            "samples": 3,
            "action_raw": 1,
            "action_readable": 1,
            "verification_raw": expected_verification,
            "verification_readable": expected_verification,
        }
        actual = {key: item.get(key) for key in expected}
        if actual != expected:
            raise EvidenceRefused(
                f"run {item.get('run')} {phase}: provider counts differ ({actual})"
            )

    action = measurement.get("action_property_read", {})
    if action.get("name") != "Extensions (Ctrl+Shift+X)" or action.get(
        "control_type"
    ) != "TabItem":
        raise EvidenceRefused("action property read differs from the recipe selector")
    verification = measurement.get("verification_property_read", {})
    if verification.get("name") != "Installed Section" or verification.get(
        "control_type"
    ) != "Button":
        raise EvidenceRefused("verification property read differs from the recipe selector")
    for label, value in (("action", action), ("verification", verification)):
        if not value.get("runtime_id") or len(value.get("bbox", [])) != 4:
            raise EvidenceRefused(f"{label}: property read lacks backend identity or bbox")

    setup = measurement.get("setup_observations", [])
    states = {item.get("state") for item in setup}
    required_states = {
        "extensions-unpinned",
        "restart-badge-present",
        "first-read-after-restart",
    }
    if states != required_states:
        raise EvidenceRefused("setup observations do not preserve all readiness findings")
    by_state = {item["state"]: item for item in setup}
    unpinned = by_state["extensions-unpinned"]
    if any(
        unpinned.get(key) != 0
        for key in (
            "action_raw_count",
            "action_readable_count",
            "bounded_tabitem_matches",
        )
    ):
        raise EvidenceRefused("the unpinned readiness observation was rewritten")
    badge = by_state["restart-badge-present"]
    if badge.get("action_raw_count") != 0 or badge.get("action_readable_count") != 0:
        raise EvidenceRefused("the badge-expanded exact-query refusal was rewritten")
    if badge.get("observed_name") == action["name"]:
        raise EvidenceRefused("the temporary badge name no longer differs from the selector")
    cold = by_state["first-read-after-restart"]
    if any(
        cold.get(key) != 0
        for key in (
            "action_raw_count",
            "action_readable_count",
            "verification_raw_count",
            "verification_readable_count",
        )
    ):
        raise EvidenceRefused("the first post-restart cold read was rewritten")
    if any(not item.get("note") for item in setup):
        raise EvidenceRefused("a readiness observation lost its measured explanation")


def check(
    records: list[dict], measurement: dict, candidate_root: pathlib.Path
) -> None:
    _check_records(records)
    _check_artifacts(measurement, candidate_root)
    _check_measurement(measurement, records)


def render(records: list[dict], measurement: dict) -> str:
    identity = measurement["application_identity"]
    action = measurement["action_property_read"]
    verification = measurement["verification_property_read"]
    lines = [
        "# Open Extensions candidate acceptance",
        "",
        "Generated by `tools/render_open_extensions_evidence.py` from the three",
        "acceptance-harness records and the provider measurement record. Do not",
        "edit by hand: `--check` re-renders and compares exact UTF-8/LF bytes.",
        "",
        "The candidate remained **quarantined** throughout this campaign. This",
        "evidence precedes installation and activation (D070).",
        "",
        "## Bound identity and artifacts",
        "",
        f"- Intent: `{INTENT_ID}`",
        f"- Application identity: `{identity['kind']}` = `{identity['value']}`",
        f"- Target: HWND `{measurement['target']['hwnd']}`, "
        f"`{measurement['target']['executable']}`, "
        f"{measurement['target']['title']!r}",
        f"- Official provenance: {measurement['source_url']}",
        "- Exact candidate bytes:",
        "",
    ]
    for label, digest in EXPECTED_DIGESTS.items():
        lines.append(f"  - `{label}` -- `{digest}`")

    lines += [
        "",
        "## Provider readiness and verification",
        "",
        "The accepted configuration had Extensions pinned, no temporary badge in",
        "its accessible name, and Explorer selected before each run. Every row",
        "below summarizes three consecutive provider reads.",
        "",
        "| Run | Phase | Action raw/readable | Installed Section raw/readable |",
        "|---|---|---|---|",
    ]
    for item in measurement["provider_samples"]:
        lines.append(
            f"| {item['run']} | {item['phase']} | "
            f"{item['action_raw']}/{item['action_readable']} | "
            f"{item['verification_raw']}/{item['verification_readable']} |"
        )
    lines += [
        "",
        "Successful property reads:",
        "",
        "| Role | Name | Type | Runtime id | Bounding box |",
        "|---|---|---|---|---|",
        f"| action | {action['name']} | {action['control_type']} | "
        f"`{action['runtime_id']}` | `{action['bbox']}` |",
        f"| verification | {verification['name']} | "
        f"{verification['control_type']} | `{verification['runtime_id']}` | "
        f"`{verification['bbox']}` |",
        "",
        "Pre-run absence of `Installed Section` and post-run presence distinguish",
        "a completed action from a view that was already open.",
        "",
        "### Readiness observations excluded from the 3/3 campaign",
        "",
    ]
    for item in measurement["setup_observations"]:
        lines.append(f"- `{item['state']}` — {item['note']}")

    lines += [
        "",
        "The first read after restart returned zero for both selectors; the next",
        "two action reads succeeded. This is recorded as consistent with the known",
        "cold Chromium-tree behaviour, not as an isolated causal finding.",
        "",
        "## Acceptance runs",
        "",
        "Version was re-read before and after every run. All six checks returned",
        "`1.135.0.0`; no campaign reset was required.",
        "",
        "| Run record | Outcome | Steps | Grounding | First observation | First hint | Verification start | End |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for record in records:
        timing = record["timing"]
        lines.append(
            f"| `{record['_source']}` | {record['outcome']} | "
            f"{record['steps']['completed']}/{record['steps']['total']} | "
            f"{', '.join(record['grounding_provenance'])} | "
            f"{timing['first_observation_s']:.3f}s | {timing['first_hint_s']:.3f}s | "
            f"{timing['verification_started_s']:.3f}s | {timing['ended_s']:.3f}s |"
        )
    lines += [
        "",
        "Result: **3/3 passed**, each `1/1` step and UIA-only. The action was",
        "grounded by the declarative `provider_exact` / `TabItem` selector, and",
        "completion was established by the declarative `Installed Section` /",
        "`Button` selector. No workflow-specific production Python was added.",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", required=True, type=pathlib.Path)
    parser.add_argument("--measurement", required=True, type=pathlib.Path)
    parser.add_argument("--candidate-root", required=True, type=pathlib.Path)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        records = load_records(args.records)
        measurement = _canonical_json(args.measurement)
        check(records, measurement, args.candidate_root)
    except (EvidenceRefused, OSError, KeyError, TypeError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    rendered = render(records, measurement).encode("utf-8")
    if args.check:
        current = args.out.read_bytes() if args.out.exists() else b""
        if current != rendered:
            print(f"refused: {args.out} differs from the records", file=sys.stderr)
            return 1
        print(f"{args.out} matches its Task 12 records")
        return 0
    args.out.write_bytes(rendered)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

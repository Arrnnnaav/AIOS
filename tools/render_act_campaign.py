"""Check a counted Act campaign and render its evidence document.

A campaign write-up that is prose is a claim; D137 found one that was never
checked. This refuses unless the retained campaign itself shows:

- one binding: the pinned PowerPoint manifest, one commit, one plan digest,
  one application build (evidence is valid only for the build it names);
- exactly three attempts (the 3/3 policy is fixed here, not a flag), numbered
  1..3, none dropped and none extra;
- every attempt ``completed`` with every node verified and published;
- distinct outputs, so three attempts are three artifacts, not one re-read;
- on the harness path, the bundle digest of the binding and one
  campaign-scoped target reference for every attempt;
- on the manager path, the intent the plan answers, one proposal digest per
  attempt, non-decreasing timestamps, the D123 order -- proposal shown,
  foreground handed to the target, then ``Approve & run``, then the one-use
  request dequeued -- and every transcript still hashing to the digest
  recorded when it was written;
- no retained record carrying a raw window handle or process id, at any depth
  or quoted in text.

``--check`` re-renders and compares bytes, so the document cannot drift from
the records it summarises.

    py -3.12 tools/render_act_campaign.py --harness report.json --out doc.md
    py -3.12 tools/render_act_campaign.py --manager <campaign-dir> --out doc.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ghostcursor.devtools.act_campaign import record_leaks  # noqa: E402
from ghostcursor.devtools.campaign_pins import POWERPOINT_MANIFEST_SHA256  # noqa: E402

#: The acceptance policy. Not a parameter: a checker that accepts "1 of 1"
#: renders a sentence that reads like the policy while meaning nothing.
REQUIRED_ATTEMPTS = 3

#: Each signed object-model plan and the one intent it answers.
PLAN_INTENTS = {
    "build-investor-deck-v1": "BUILD_INVESTOR_DECK",
    "animation-catalog-v1": "BUILD_ANIMATION_CATALOG",
}
MANAGER_ORDER = (
    "act_proposal_displayed",
    "target_focus_handoff_completed",
    "approve_and_run_issued",
    "execution_request_dequeued",
    "act_worker_started",
    "act_run_result",
)
#: What each plan's verifier actually establishes, printed in the document so a
#: green campaign is never read as more than it shows (D154, review I4).
PLAN_SCOPE = {
    "build-investor-deck-v1": (
        "Every node passed the signed verifier's check of its declared postcondition."
    ),
    "animation-catalog-v1": (
        "Scope: the verifier confirmed an animation was added to each target object and "
        "that slide-level transition state was written; it does not verify the effect, "
        "category, trigger, direction or order that landed, which the retained decks "
        "below can settle."
    ),
}
#: Records that must not sit beside a counted, completed result.
DISQUALIFYING = frozenset({"interrupt_fired", "interrupt_probe", "publish_refused", "probe_faults"})
PLAN_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "sources" / "powerpoint" / "payload"
_SHA = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")


class CampaignRefused(Exception):
    """The retained campaign does not substantiate a counted result."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CampaignRefused(message)


def _no_raw_handles(records, label: str) -> None:
    for record in records:
        leaked = record_leaks(record)
        _require(
            not leaked,
            f"{label}: a {record.get('type')!r} record carries {sorted(leaked)}",
        )


def _binding(binding: dict) -> None:
    _require(
        binding.get("manifest_sha256") == POWERPOINT_MANIFEST_SHA256,
        f"campaign manifest {str(binding.get('manifest_sha256'))[:8]} is not the pinned "
        f"{POWERPOINT_MANIFEST_SHA256[:8]}",
    )
    _require(
        bool(_COMMIT.fullmatch(str(binding.get("commit", "")))),
        "campaign names no commit",
    )
    _require(
        bool(_SHA.fullmatch(str(binding.get("plan_sha256", "")))),
        "campaign names no plan digest",
    )
    _require(binding.get("plan_id") in PLAN_INTENTS, "campaign names an unknown plan")


def _signed_plan(binding: dict) -> int:
    """The node count of the TRACKED signed plan the binding names, after
    requiring the binding's digest to be that plan's index digest (review I2)."""

    index = json.loads((PLAN_ROOT / "ghostcursor" / "action-plans.json").read_text(encoding="utf-8"))
    entry = index["plans"].get(binding["plan_id"])
    _require(entry is not None, "campaign names a plan the signed index does not list")
    _require(
        entry["sha256"] == binding["plan_sha256"],
        f"campaign plan digest {binding['plan_sha256'][:8]} is not the signed plan's",
    )
    plan = json.loads((PLAN_ROOT / entry["path"]).read_text(encoding="utf-8"))
    return len(plan["nodes"])


def _campaign_id(binding: dict) -> None:
    _require(
        bool(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9-]{1,40}", str(binding.get("campaign_id")))),
        "campaign names no ledgered campaign id",
    )


def _consecutive(indices, label: str) -> None:
    _require(
        list(indices) == list(range(1, REQUIRED_ATTEMPTS + 1)),
        f"{label}: attempts {list(indices)} are not exactly 1..{REQUIRED_ATTEMPTS}",
    )


def _one_build(builds, label: str) -> str:
    _require(
        len(set(builds)) == 1 and all(isinstance(b, str) and b for b in builds),
        f"{label}: attempts do not name one application build: {sorted(set(map(str, builds)))}",
    )
    return builds[0]


def check_harness(report: dict, artifacts: Path | None = None) -> dict:
    _require(
        report.get("schema_version") == 2 and report.get("path") == "harness",
        "not a harness campaign report",
    )
    binding = report.get("binding", {})
    _binding(binding)
    _require(
        bool(_SHA.fullmatch(str(binding.get("bundle_sha256", "")))),
        "campaign names no bundle digest",
    )
    _campaign_id(binding)
    planned = _signed_plan(binding)
    _require(
        report.get("campaign") == "clean",
        f"campaign ended {report.get('campaign')!r}: {report.get('detail')}",
    )
    _require(
        report.get("attempts_requested") == REQUIRED_ATTEMPTS,
        f"campaign requested {report.get('attempts_requested')} attempts, not {REQUIRED_ATTEMPTS}",
    )
    attempts = report.get("attempts", [])
    _consecutive([a.get("index") for a in attempts], "harness")

    rows, references, published, builds = [], [], [], []
    for attempt in attempts:
        label = f"attempt {attempt['index']}"
        records = attempt.get("records", [])
        _no_raw_handles(records, label)
        approved = [r for r in records if r.get("type") == "approved"]
        results = [r for r in records if r.get("type") == "result"]
        _require(
            len(approved) == 1 and len(results) == 1,
            f"{label}: needs one approved and one result record",
        )
        approved, result = approved[0], results[0]
        stray = DISQUALIFYING & {r.get("type") for r in records}
        _require(not stray, f"{label}: carries disqualifying records {sorted(stray)}")
        _require(
            approved.get("plan_id") == binding["plan_id"],
            f"{label}: ran plan {approved.get('plan_id')!r}, not the campaign's",
        )
        _require(approved.get("nodes") == planned, f"{label}: plan has {planned} nodes, attempt ran {approved.get('nodes')}")
        _require(
            approved.get("manifest_sha256") == POWERPOINT_MANIFEST_SHA256,
            f"{label}: ran an unpinned manifest",
        )
        _require(
            approved.get("plan_sha256") == binding["plan_sha256"],
            f"{label}: ran a different plan",
        )
        _require(
            approved.get("bundle_sha256") == binding["bundle_sha256"],
            f"{label}: ran a different bundle",
        )
        total = approved.get("nodes")
        _require(
            result.get("completed") is True
            and result.get("code") == "completed"
            and isinstance(total, int)
            and result.get("completed_nodes") == total == attempt.get("nodes"),
            f"{label}: not completed {total}/{total}",
        )
        digest = result.get("published_sha256")
        _require(
            bool(_SHA.fullmatch(str(digest)))
            and digest == attempt.get("published_sha256"),
            f"{label}: nothing published",
        )
        if artifacts is not None:
            artifact = attempt.get("artifact")
            _require(bool(artifact), f"{label}: its published deck was not retained")
            _require(
                hashlib.sha256((artifacts / artifact).read_bytes()).hexdigest() == digest,
                f"{label}: the retained deck is not the published one",
            )
        references.append((approved.get("target_ref"), approved.get("target_scope")))
        published.append(digest)
        builds.append(approved.get("application_version"))
        rows.append(
            (
                attempt["index"],
                f"{total}/{total}",
                f"{attempt['seconds']:.3f} s",
                digest,
            )
        )
    _require(
        len(set(references)) == 1 and None not in references[0],
        "attempts did not bind one campaign-scoped target",
    )
    _require(
        len(set(published)) == REQUIRED_ATTEMPTS, "published artifacts are not distinct"
    )
    build = _one_build(builds, "harness")
    return {"binding": binding, "build": build, "path": "harness", "rows": rows}


def check_manager(directory: Path) -> dict:
    campaign = json.loads((directory / "campaign.json").read_text(encoding="utf-8"))
    _require(
        campaign.get("schema_version") == 1 and campaign.get("path") == "manager",
        "not a manager campaign",
    )
    binding = campaign.get("binding", {})
    _binding(binding)
    _campaign_id(binding)
    planned = _signed_plan(binding)
    _require(not campaign.get("refusals"), f"campaign recorded refusals: {campaign.get('refusals')}")
    intent = PLAN_INTENTS[binding["plan_id"]]
    _require(binding.get("intent_id") == intent, "campaign binds the wrong intent")
    entries = campaign.get("attempts", [])
    _consecutive([e.get("index") for e in entries], "manager")
    on_disk = sorted(
        p.name for p in directory.glob("act-live-manager-campaign-attempt-*.jsonl")
    )
    _require(
        on_disk == sorted(e["transcript"] for e in entries),
        f"transcripts on disk {on_disk} differ from the campaign's list",
    )

    rows, outputs, builds = [], [], []
    for entry in entries:
        label = f"attempt {entry['index']}"
        raw = (directory / entry["transcript"]).read_bytes()
        _require(
            hashlib.sha256(raw).hexdigest() == entry.get("transcript_sha256"),
            f"{label}: transcript changed after it was recorded",
        )
        records = [
            json.loads(line) for line in raw.decode("utf-8").splitlines() if line
        ]
        _no_raw_handles(records, label)
        _require(
            [r.get("sequence") for r in records] == list(range(1, len(records) + 1)),
            f"{label}: sequence has a gap",
        )
        stamps = [r.get("at_ns") for r in records]
        _require(
            all(isinstance(s, int) for s in stamps) and stamps == sorted(stamps),
            f"{label}: timestamps go backwards",
        )
        types = [r.get("type") for r in records]
        for kind in MANAGER_ORDER:
            _require(types.count(kind) == 1, f"{label}: expected exactly one {kind!r}")
        positions = [types.index(kind) for kind in MANAGER_ORDER]
        _require(
            positions == sorted(positions), f"{label}: lifecycle order violates D123"
        )
        proposal = records[types.index("act_proposal_displayed")]
        _require(
            proposal.get("manifest_sha256") == POWERPOINT_MANIFEST_SHA256,
            f"{label}: proposal bound an unpinned manifest",
        )
        _require(
            proposal.get("intent_id") == intent,
            f"{label}: proposal answered another intent",
        )
        proposals = {
            r.get("proposal_sha256") for r in records if r.get("proposal_sha256")
        }
        _require(
            proposals == {proposal.get("proposal_sha256")} and None not in proposals,
            f"{label}: records name more than one proposal",
        )
        result = records[types.index("act_run_result")]
        totals = {
            r.get("total") for r in records if r.get("type") == "act_runtime_event"
        }
        _require(
            len(totals) == 1, f"{label}: runtime events disagree on the node total"
        )
        total = totals.pop()
        _require(total == planned, f"{label}: plan has {planned} nodes, attempt ran {total}")
        _require(
            result.get("completed") is True
            and result.get("code") == "completed"
            and result.get("completed_nodes") == total,
            f"{label}: not completed {total}/{total}",
        )
        outputs.append(proposal.get("output_path_sha256"))
        builds.append(proposal.get("application_version"))
        seconds = (
            result["at_ns"]
            - records[types.index("execution_request_dequeued")]["at_ns"]
        ) / 1e9
        rows.append(
            (
                entry["index"],
                f"{total}/{total}",
                f"{seconds:.3f} s",
                entry["transcript_sha256"],
            )
        )
    _require(
        None not in outputs and len(set(outputs)) == REQUIRED_ATTEMPTS,
        "attempts did not write distinct outputs",
    )
    build = _one_build(builds, "manager")
    return {"binding": binding, "build": build, "path": "manager", "rows": rows}


def render(summary: dict, sources=()) -> str:
    """The campaign document. ``sources`` are ``(name, sha256)`` pairs for the
    retained files it was rendered from, printed one per line so the
    retained-evidence digest check pins them (D138)."""

    binding = summary["binding"]
    path = summary["path"]
    digest_column = "Published SHA-256" if path == "harness" else "Transcript SHA-256"
    lines = [
        f"# Counted PowerPoint Act campaign — {path} path",
        "",
        "Rendered by `tools/render_act_campaign.py` from the retained campaign;",
        "`--check` re-renders and compares bytes. Do not edit by hand.",
        "",
        f"- Commit: `{binding['commit']}`",
        f"- Manifest: `{binding['manifest_sha256']}` (the pinned manifest)",
        f"- Campaign: `{binding['campaign_id']}`",
        f"- Plan: `{binding['plan_id']}` `{binding['plan_sha256']}`",
        f"- PowerPoint build: `{summary['build']}` (valid for this build only)",
        "",
        f"| Attempt | Nodes | Execution | {digest_column} |",
        "|---:|---:|---:|---|",
    ]
    lines.extend(
        f"| {i} | {nodes} | {seconds} | `{digest}` |"
        for i, nodes, seconds, digest in summary["rows"]
    )
    lines.extend(
        [
            "",
            f"{REQUIRED_ATTEMPTS} of {REQUIRED_ATTEMPTS} consecutive attempts completed.",
            PLAN_SCOPE[binding["plan_id"]],
            "This document states what the retained records show; it is acceptance",
            "evidence only after independent D032 review.",
        ]
    )
    if sources:
        lines.extend(["", "## Source records", ""])
        lines.extend(f"- `{name}` — SHA-256 `{digest}`" for name, digest in sources)
    return "\n".join(lines) + "\n"


def refusal_summary(kind: str, value: dict) -> dict:
    """What a refused or unfinished campaign retains, for its document (N5).

    A committed ledger line needs a cited, rendered record of its outcome; a
    refusal is an outcome. Only structure is checked here -- a refused
    campaign claims nothing, so there is nothing further to substantiate.
    """

    expected = (2, "harness") if kind == "harness" else (1, "manager")
    _require(
        (value.get("schema_version"), value.get("path")) == expected,
        f"not a {kind} campaign record",
    )
    binding = value.get("binding") or {}
    _campaign_id(binding)
    if kind == "harness":
        reasons = [str(value.get("detail") or "")]
        rows = [(a.get("index"), a.get("code"), a.get("nodes")) for a in value.get("attempts", [])]
    else:
        reasons = [str(r) for r in value.get("refusals", [])] or ["fewer than three attempts ran"]
        rows = [(a.get("index"), f"exit {a.get('manager_exit')}", None) for a in value.get("attempts", [])]
    _require(all(reasons), "a refused campaign must say why")
    _no_raw_handles([{"reasons": reasons}], "refusal")
    return {"binding": binding, "path": kind, "reasons": reasons, "rows": rows, "status": value.get("campaign", "refused")}


def render_refusal(summary: dict, sources=()) -> str:
    binding = summary["binding"]
    lines = [
        f"# Campaign `{binding['campaign_id']}` — {summary['path']} path — NOT counted",
        "",
        "Rendered by `tools/render_act_campaign.py` from the retained record;",
        "`--check` re-renders and compares bytes. This campaign did not produce",
        "three consecutive clean attempts and is not acceptance evidence.",
        "",
        f"- Outcome: `{summary['status']}`",
        f"- Plan: `{binding.get('plan_id')}`",
        "",
        "## Why",
        "",
    ]
    lines.extend(f"- {reason}" for reason in summary["reasons"])
    if summary["rows"]:
        lines.extend(["", "| Attempt | Outcome | Nodes |", "|---:|---|---:|"])
        lines.extend(f"| {i} | {code} | {nodes if nodes is not None else '—'} |" for i, code, nodes in summary["rows"])
    if sources:
        lines.extend(["", "## Source records", ""])
        lines.extend(f"- `{name}` — SHA-256 `{digest}`" for name, digest in sources)
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--harness", type=Path)
    source.add_argument("--manager", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=None,
        help="the git-ignored deck store; when given, every deck is digest-checked",
    )
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    try:
        if arguments.harness is not None:
            value = json.loads(arguments.harness.read_text(encoding="utf-8"))
            sources = [(arguments.harness.name, digest(arguments.harness))]
            if value.get("campaign") != "clean":
                rendered = render_refusal(refusal_summary("harness", value), sources)
            else:
                rendered = render(check_harness(value, artifacts=arguments.artifacts), sources)
        else:
            value = json.loads((arguments.manager / "campaign.json").read_text(encoding="utf-8"))
            files = [arguments.manager / "campaign.json", *sorted(
                arguments.manager.glob("act-live-manager-campaign-attempt-*.jsonl")
            )]
            sources = [(path.name, digest(path)) for path in files]
            if value.get("refusals") or len(value.get("attempts", [])) != REQUIRED_ATTEMPTS:
                rendered = render_refusal(refusal_summary("manager", value), sources)
            else:
                rendered = render(check_manager(arguments.manager), sources)
    except (CampaignRefused, OSError, KeyError, ValueError) as exc:
        print(f"refused: {exc}")
        return 2
    data = rendered.encode("utf-8")
    if arguments.check:
        if not arguments.out.is_file() or arguments.out.read_bytes() != data:
            print("refused: the campaign document is not what its records render to")
            return 2
        return 0
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_bytes(data)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

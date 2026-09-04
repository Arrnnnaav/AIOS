"""Render the ADD_SLIDE candidate acceptance evidence FROM the harness records.

The document is derived, never authored. A hand-written evidence table is a
figure nothing else has read (D032), and a number that exists only in a
session is not evidence (D034) -- so this reads the JSON `candidate_acceptance`
printed and refuses anything it cannot substantiate.

    py -3.12 tools/render_add_slide_evidence.py `
      --records plugins/sources/powerpoint/acceptance-records/add-slide `
      --candidate-root plugins/sources/powerpoint/payload/ghostcursor/packs/powerpoint `
      --out docs/evidence/add-slide-candidate-acceptance.md

`--check` re-renders and compares exact bytes, so a stale committed document
fails rather than being silently believed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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

#: Longest a counted campaign may span, end to end. A CHOICE, not a measured
#: number: three supervised runs happen in one sitting, and this refuses
#: records that plainly are not one.
MAX_CAMPAIGN_SECONDS = 24 * 3600

#: The recipe's selectors. Named here so the rendered document cannot describe
#: a selector the signed recipe does not actually declare.
VERIFICATION_SELECTOR = "slide2_after"
VERIFICATION_NAME = "View Indicator Slide 2 of 2"
ACTION_SELECTOR = "new_slide"
ACTION_NAME = "New Slide"

#: This file lives in `tools/`, so the repository root is its parent's parent.
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _display_path(path: pathlib.Path) -> str:
    """How a directory is NAMED in the document.

    Repo-relative and posix-separated whenever it is inside the repository,
    so the rendered bytes do not depend on whether the renderer was invoked
    with a relative or an absolute path, nor on the platform's separator.
    `--check` compares exact bytes, so either would make a correct document
    fail for a reason that has nothing to do with the evidence.
    """

    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


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
    stray = [
        entry.name
        for entry in sorted(directory.iterdir())
        if entry.is_dir() or entry.suffix != ".json"
    ]
    if stray:
        raise EvidenceRefused(
            f"{directory} contains {stray}; a campaign directory holds exactly "
            "the three run records and nothing else, or a fourth run can sit "
            "where the count cannot see it"
        )

    records = []
    for path in paths:
        record = _canonical_json(path)
        record["_source"] = path.name
        records.append(record)

    # Three files is not three runs. Copying one record under three names
    # rendered a document claiming "3/3 passed" until an independent review
    # tried it, because nothing here looked past the file count.
    #
    # This catches duplication. It does not PROVE distinctness, and the
    # difference matters (D031).
    #
    # `RunRecord` now stamps a run_id and a start time, so a careless copy is
    # caught. Nothing AUTHENTICATES a committed record: the fields are
    # checked, not signed, so a record's stamps can be written by hand and a
    # rejected run can be dressed as an accepted one. An independent review
    # did exactly that on this renderer. The rendered document states this
    # limitation; an earlier version of this comment claimed it did while it
    # did not.
    seen: dict[str, str] = {}
    for record in records:
        payload = json.dumps(
            {k: v for k, v in record.items() if k != "_source"}, sort_keys=True
        )
        if payload in seen:
            raise EvidenceRefused(
                f"{record['_source']} is identical to {seen[payload]}; "
                "three files are not three runs"
            )
        seen[payload] = record["_source"]

    _check_sequence(records, directory)
    return records


def _started(record: dict) -> str:
    value = record.get("started_at")
    if not isinstance(value, str) or not value:
        raise EvidenceRefused(
            f"{record['_source']}: no `started_at`, so nothing establishes "
            "when this run happened or that three runs were consecutive"
        )
    return value


def _check_sequence(records: list[dict], directory: pathlib.Path) -> None:
    """Three runs, distinct, in order, with nothing rejected in between.

    The anti-duplicate check above catches copying one record three times. It
    does NOT catch the worse case an independent review found: three
    genuinely distinct, individually clean records drawn from two DIFFERENT
    already-rejected attempt sets rendered a clean "3/3 passed", because the
    only cross-record checks were a shared HWND and shared digests -- both
    true of every record for this candidate by construction, since it is one
    plugin on one machine.

    What "consecutive" actually means is checkable once records carry a start
    time: the three accepted runs are ordered, and **no rejected run happened
    between the first and the last**. Excluded records are committed beside
    the accepted ones precisely so that question can be asked of the
    repository rather than of the operator's memory.
    """

    ids = [record.get("run_id") for record in records]
    if any(not isinstance(value, str) or not value for value in ids):
        raise EvidenceRefused(
            "every run record must carry a `run_id`; without one, three files "
            "cannot be shown to be three runs"
        )
    if len(set(ids)) != len(ids):
        raise EvidenceRefused(f"two accepted records share a run_id: {sorted(ids)}")

    starts = [_started(record) for record in records]
    # STRICTLY increasing. `!= sorted()` accepts ties, and three ~4s runs
    # cannot begin in the same millisecond on one machine.
    if any(a >= b for a, b in zip(starts, starts[1:])):
        raise EvidenceRefused(
            "the accepted runs do not start strictly in order: "
            + ", ".join(f"{r['_source']}={s}" for r, s in zip(records, starts))
        )

    # A run cannot begin before the previous one ended. Ordering alone allows
    # three overlapping records, which no single operator could have produced.
    for earlier, later in zip(records, records[1:]):
        finished = _finished_at(earlier)
        if finished is not None and finished > _started(later):
            raise EvidenceRefused(
                f"{later['_source']} started at {_started(later)}, before "
                f"{earlier['_source']} finished at {finished}; the runs overlap"
            )

    # A counted campaign is three supervised runs in one sitting. This bound
    # is a CHOICE, not a measurement -- said plainly the way `act_pacing` says
    # it of its delays, so nobody later cites it as though something had been
    # measured (D034). It is deliberately generous; it exists to refuse
    # records that are obviously not one session, such as the three dated
    # 2019, 2025 and 2031 an independent review assembled.
    from datetime import datetime

    try:
        elapsed = datetime.fromisoformat(starts[-1]) - datetime.fromisoformat(starts[0])
    except ValueError as exc:
        raise EvidenceRefused(f"unparseable start time: {exc}") from None
    if elapsed.total_seconds() > MAX_CAMPAIGN_SECONDS:
        raise EvidenceRefused(
            f"the three runs span {elapsed}, longer than the "
            f"{MAX_CAMPAIGN_SECONDS // 3600}h a supervised campaign is taken "
            "to run in; these are not one sitting"
        )

    _check_window(starts, directory.parent / "excluded")


def _finished_at(record: dict) -> "str | None":
    """When a run ended, as an instant comparable with `started_at`.

    Derived from the start plus the executor's own `ended_s` rather than
    stamped separately: two independently written instants could disagree,
    and the run record already carries the elapsed time it measured.
    """

    from datetime import datetime, timedelta

    ended = (record.get("timing") or {}).get("ended_s")
    if not isinstance(ended, (int, float)) or isinstance(ended, bool):
        return None
    if not math.isfinite(ended):
        return None
    try:
        began = datetime.fromisoformat(_started(record))
    except ValueError:
        return None
    return (began + timedelta(seconds=float(ended))).isoformat(
        timespec="milliseconds"
    )


def _rejected_runs(excluded: pathlib.Path) -> tuple[int, int]:
    """How many rejected runs are committed, and how many can be placed in
    time. The second number is what the window check can actually see."""

    if not excluded.is_dir():
        return 0, 0
    total = placed = 0
    for path in sorted(excluded.glob("*.json")):
        total += 1
        when = _canonical_json(path).get("started_at")
        if isinstance(when, str) and when:
            placed += 1
    return total, placed


def _check_window(starts: list[str], excluded: pathlib.Path) -> None:
    first, last = starts[0], starts[-1]
    if not excluded.is_dir():
        # Refused rather than skipped. Without the sibling directory the
        # derived counts all read zero while the document's narrative still
        # describes the recorded anomaly, so the document contradicts itself
        # and silently drops a finding.
        raise EvidenceRefused(
            f"no sibling {excluded} directory; non-qualifying attempt sets are "
            "committed beside the accepted campaign so the sequence check has "
            "something to ask, and a campaign rendered without them reports "
            "counts of zero that mean nothing was looked at"
        )
    for path in sorted(excluded.glob("*.json")):
        when = _canonical_json(path).get("started_at")
        # A record predating run-identity stamping cannot be placed in time.
        # Skipped rather than refused -- old records can never gain a
        # timestamp, so refusing would block every future campaign forever --
        # and the rendered document reports how many were skipped, because a
        # check that silently saw nothing would read as a check that passed.
        if not isinstance(when, str) or not when:
            continue
        if first <= when <= last:
            raise EvidenceRefused(
                f"{path.name} was rejected and ran at {when}, between the "
                f"first accepted run ({first}) and the last ({last}); these "
                "three runs were not consecutive"
            )


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
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        # `json.loads` accepts NaN and Infinity. A NaN compares false against
        # everything, so it slid past the ordering check in every position but
        # the first and rendered a table cell reading "nans".
        or not math.isfinite(value)
        for value in ordered
    ) or not (0 <= ordered[0] and ordered == sorted(ordered)):
        raise EvidenceRefused(
            f"{source}: timing landmarks are unordered or not finite numbers"
        )


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


def _elapsed(first: str, last: str) -> str:
    """How long the campaign took, end to end, in words a reader can check."""

    from datetime import datetime

    try:
        delta = datetime.fromisoformat(last) - datetime.fromisoformat(first)
    except ValueError:  # pragma: no cover - both parsed already
        return "an unparseable span"
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds} seconds apart"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s apart"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m apart"


def _mark_survey(records_dir: pathlib.Path, accepted: list[dict]):
    """Count the timing mark across EVERY committed record, accepted and
    rejected alike.

    Derived rather than written down. A sentence saying "all six records"
    was already stale the moment a fourth attempt set was committed, and a
    stale number in an evidence document is the D034 failure this renderer
    exists to prevent -- so the document counts them at render time.
    """

    seen = [(r["_source"], r) for r in accepted]
    excluded = records_dir.parent / "excluded"
    if excluded.is_dir():
        for path in sorted(excluded.glob("*.json")):
            seen.append((path.name, _canonical_json(path)))

    drains: set[str] = set()
    unmarked: list[str] = []
    marked = 0
    for name, record in seen:
        timing = record.get("timing") or {}
        mark = timing.get("verification_started_s")
        if mark is None:
            # An aborted run never reached verification; its missing mark is
            # explained and is not the anomaly.
            if record.get("outcome") == "passed":
                unmarked.append(name)
            continue
        marked += 1
        drains.add(f"{timing['ended_s'] - mark:.3f}s")
    phrase = " or ".join(sorted(drains)) if drains else "not measured"
    return marked, phrase, sorted(unmarked)


def render(records: list[dict], loaded: dict, records_dir: pathlib.Path) -> str:
    rejected, placed = _rejected_runs(records_dir.parent / "excluded")
    span = _elapsed(records[0]["started_at"], records[-1]["started_at"])
    marked, drains, unmarked = _mark_survey(records_dir, records)
    unmarked_names = (
        ", ".join(f"`{name}`" for name in unmarked) if unmarked else "none"
    )
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
        f"Records read from `{_display_path(records_dir)}`, so every number",
        "below names where it is recorded (D034). This path is the one the",
        "renderer was pointed at, not a fixed string: an earlier draft hardcoded",
        "it and would have",
        "claimed a durable location while rendering from a scratch directory.",
        "Attempt sets that did not qualify are preserved alongside under",
        "`excluded/` with the note explaining why.",
        "",
        "Each record carries a `run_id` minted at capture and the wall-clock",
        "instant the run began, so three files can be shown to be three runs.",
        "The renderer requires distinct ids, start times strictly in order,",
        "and runs that do not overlap in time. It also asks whether any",
        "non-qualifying run committed alongside fell between the first",
        "accepted run and the last -- what that question could answer here is",
        "stated below rather than assumed.",
        "",
        f"Runs from non-qualifying attempt sets, committed under",
        f"`{_display_path(records_dir.parent / 'excluded')}`: {rejected}. Of",
        f"those, {placed} carry a start time and can be placed against this",
        f"window; {rejected - placed} predate run-identity stamping and cannot",
        "be.",
        "",
        *(
            [
                "**On this campaign the window check evaluated zero records and",
                "therefore established nothing.** Every committed non-qualifying",
                "run predates stamping, so consecutiveness here rests on the",
                "start-time ordering and non-overlap of the three accepted runs",
                "alone. The check will constrain a future campaign; it does not",
                "constrain this one, and reporting only its verdict would have",
                "read as a check that passed.",
            ]
            if placed == 0
            else [
                f"The window check evaluated {placed} of them and none fell",
                "between the first accepted run and the last.",
            ]
        ),
        "",
        "What this still does not prove. Nothing AUTHENTICATES a committed",
        "record: its fields are checked, not signed. A record's stamps can be",
        "written by hand, so the gate constrains careless assembly rather than",
        "a deliberate one -- an independent review assembled a document from",
        "records of three different rejected sets by adding two fields to each.",
        "Nor can anything see a rejected run that happened and was never",
        "committed; an operator who deletes a failure leaves no trace of it,",
        "here or anywhere.",
        "",
        "| Run record | Run id | Started (UTC) | Outcome | Steps | Grounding | "
        "First observation | First hint | Verification start | End |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for record in records:
        timing = record["timing"]
        lines.append(
            f"| `{record['_source']}` | `{record['run_id'][:8]}` | "
            f"{record['started_at']} | {record['outcome']} | "
            f"{record['steps']['completed']}/{record['steps']['total']} | "
            f"{', '.join(record['grounding_provenance'])} | "
            f"{timing['first_observation_s']:.3f}s | "
            f"{timing['first_hint_s']:.3f}s | "
            f"{timing['verification_started_s']:.3f}s | "
            f"{timing['ended_s']:.3f}s |"
        )
    lines += [
        "",
        f"First run began {records[0]['started_at']} and the last",
        f"{records[-1]['started_at']}: {span}. The ids and instants are",
        "printed because they are what the consecutiveness claim rests on, and",
        "a reader cannot audit a claim from numbers the document withholds --",
        "an earlier draft showed only relative timings, so records dated years",
        "apart rendered a document indistinguishable from this one.",
    ]

    lines += [
        "",
        "Result: **3/3 passed**, each `1/1` step and UIA-only.",
        "",
        f"All three are also bound to one captured HWND (`{target['hwnd']}`)",
        "with identical artifact digests and one application build. Those are",
        "required gates, not evidence of a campaign: both are true of every",
        "record for this candidate by construction, since it is one plugin on",
        "one machine.",
        "",
        "## What established the outcome",
        "",
        f"The action was grounded by the declarative `{ACTION_SELECTOR}`",
        f"selector (`provider_exact`, `exactly_one`, name {ACTION_NAME!r}).",
        f"Completion was established by `{VERIFICATION_SELECTOR}`",
        f"(name {VERIFICATION_NAME!r}) under `element_appears`, which is",
        "absent-then-present.",
        "",
        "Precisely: the view indicator did not read",
        f"{VERIFICATION_NAME!r} at the last observation before the",
        "verification clock armed, and read exactly that when the rule fired.",
        "**Not** \"when the run started\": `reasoning/loop.py` re-assigns the",
        "baseline on every `OBSERVING` pass while the clock is unarmed, and",
        "re-enters `OBSERVING` on an unexpected-change interrupt, so the",
        "baseline is the last observation before arming. An earlier draft said",
        "run-start, which tracing the loop refutes -- the same failure this",
        "document records against itself further down.",
        "",
        "The harness synthesizes no input -- `tests/test_no_input_synthesis.py`",
        "scans the `devtools` package explicitly -- and makes no COM call, so",
        "the change came from outside the harness. That the person who made it",
        "was the supervising operator rests on procedure, exactly as the",
        "one-slide start does. The cited scan establishes the absence of input",
        "synthesis; it does not by itself establish the absence of COM, which",
        "is why the object-model path exists elsewhere in this repository.",
        "",
        "### What the verification does not establish",
        "",
        "**It does not establish the deck's starting slide count.** An earlier",
        "draft of this document claimed the rule was reachable only from a",
        "one-slide deck. That is wrong, and an independent review caught it.",
        "Other state changes satisfy the same absent-then-present rule with no",
        "slide added:",
        "",
        "- a two-slide deck viewed at slide 1 (`Slide 1 of 2`) where the person",
        "  merely navigates to slide 2, which then reads `Slide 2 of 2`;",
        "- a three-slide deck viewed at slide 2 (`Slide 2 of 3`) where a slide",
        "  is deleted, leaving `Slide 2 of 2`.",
        "",
        "The recipe does observe `slide1_before` on every tick as a context",
        "selector, and that observation is what WOULD settle the starting",
        "state -- but the run record carries no selector results, so it cannot",
        "be reconstructed from the committed evidence. The one-slide start",
        "therefore rests on operator procedure, not on the record.",
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
        "## A recorded anomaly in the earlier attempt sets",
        "",
        f"`verification_started_s` is missing from **{len(unmarked)}** passing",
        f"runs across the excluded sets -- {unmarked_names} -- on identical",
        "bytes and one HWND. An earlier draft of this document said one run;",
        "an independent review found the second. These counts are derived from",
        "the committed records, so they cannot go stale as sets are added.",
        "",
        f"Where the mark is present, `ended_s - verification_started_s` is",
        f"{drains} across all {marked} records that carry it. That is fixed",
        "drain, not a gap between two events: `compiled_tour`'s driver sleeps",
        "0.25s per iteration, and after the rule is satisfied the run still",
        "passes through `VERIFYING` and `OBSERVING` before reaching `DONE`,",
        "where the timing is read. Two sleeps, exactly 0.500s.",
        "",
        "An earlier draft of this document read the same number as one tick",
        "and concluded that arming and satisfaction fell on different ticks.",
        "An independent review traced it and that was wrong. They fall on the",
        "same tick, which makes the absence more surprising: the selector",
        "union changes at the moment the rule is satisfied, so the arming",
        "condition should be true exactly then. It remains unexplained rather",
        "than explained away. See `docs/superpowers/FOLLOWUPS.md`.",
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
        document = render(records, loaded, args.records)
    except EvidenceRefused as exc:
        print(f"evidence refused: {exc}", file=sys.stderr)
        return 2
    if args.check:
        if not args.out.is_file():
            print(f"evidence refused: {args.out} does not exist", file=sys.stderr)
            return 2
        # BYTES, not text. `read_text` applies universal-newline translation,
        # so a CRLF-converted document passed a check the document describes
        # as comparing exact bytes.
        if args.out.read_bytes() != document.encode("utf-8"):
            print(
                f"evidence refused: {args.out} differs from a fresh render",
                file=sys.stderr,
            )
            return 2
        print(f"{args.out} matches the records")
        return 0
    # newline="" so the document keeps the LF bytes it was built from.
    # Otherwise Windows translates them on write and the committed file
    # depends on git's normalisation rather than on this renderer.
    args.out.write_text(document, encoding="utf-8", newline="")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

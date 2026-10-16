"""Hand a mission to a teammate as a file (owner build order 4; the seed of
Multiplayer, Unified Plan 4.2 "Shared Plan -> Handoffs").

What goes in the file is the minimum a teammate needs: the goal, the plan
steps and the research sources, each scrubbed (D180). Never the conversation,
memories, point references or anything read from a screen.

What arrives is someone else's words: it is recorded as an assistant turn and
loaded as a plan proposal for the user to read and edit -- never as the
user's goal and never as authority. Plans only ever guide (Teach).
"""

from __future__ import annotations

import json

from ghostcursor.providers.envelope import sanitize, scrub
from ghostcursor.providers.schemas import (
    MAX_INSTRUCTION_CHARS,
    MAX_PLAN_STEPS,
    ExpectedChange,
    PlanStep,
    TeachPlan,
)

KIND = "orbyn-handoff"
VERSION = 1
MAX_SOURCES = 20
MAX_BYTES = 32 * 1024


def _clean(text: object, limit: int) -> str:
    return scrub(sanitize(text, limit))


def export(ws, sender: str) -> str:
    """The handoff file's text for the current goal and plan."""

    if ws.plan is None:
        raise ValueError("make a plan before handing it off")
    sources = {
        s.url: s.title for graph in ws.research_graphs for s in graph.sources
    }  # ponytail: newest title wins for a repeated URL
    value = {
        "kind": KIND,
        "version": VERSION,
        "from": _clean(sender, 60) or "a teammate",
        "goal": _clean(ws.goal, 300),
        "plan": [
            {
                "instruction": _clean(s.instruction, MAX_INSTRUCTION_CHARS),
                "expected_change": s.expected_change.value,
            }
            for s in ws.plan.steps
        ],
        "sources": [
            {"url": _clean(url, 500), "title": _clean(title, 200)}
            for url, title in list(sources.items())[:MAX_SOURCES]
        ],
    }
    return json.dumps(value, indent=1, ensure_ascii=False)


def parse(text: str) -> dict:
    """A received handoff, strictly checked; ValueError for anything else."""

    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("handoff file is too large")
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise ValueError("not a handoff file") from exc
    if not isinstance(value, dict) or set(value) != {
        "kind",
        "version",
        "from",
        "goal",
        "plan",
        "sources",
    }:
        raise ValueError("not a handoff file")
    if value["kind"] != KIND or value["version"] != VERSION:
        raise ValueError("unsupported handoff version")
    plan, sources = value["plan"], value["sources"]
    if not isinstance(plan, list) or not 1 <= len(plan) <= MAX_PLAN_STEPS:
        raise ValueError(f"a handoff carries 1 to {MAX_PLAN_STEPS} steps")
    if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
        raise ValueError("too many sources")
    steps = []
    for step in plan:
        if not isinstance(step, dict) or set(step) != {
            "instruction",
            "expected_change",
        }:
            raise ValueError("a step is not instruction/expected_change")
        instruction = _clean(step["instruction"], MAX_INSTRUCTION_CHARS)
        if not instruction:
            raise ValueError("a step has no instruction")
        try:
            change = ExpectedChange(step["expected_change"])
        except ValueError as exc:
            raise ValueError("a step's expected change is unknown") from exc
        steps.append(PlanStep(instruction, change))
    clean_sources = []
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"url", "title"}:
            raise ValueError("a source is not url/title")
        url = _clean(source["url"], 500)
        if not url.startswith("https://"):
            raise ValueError("a source must be an https link")
        clean_sources.append((url, _clean(source["title"], 200)))
    return {
        "from": _clean(value["from"], 60) or "a teammate",
        "goal": _clean(value["goal"], 300),
        "plan": TeachPlan(tuple(steps)),
        "sources": tuple(clean_sources),
    }


def receive(ws, text: str) -> str:
    """Load a handoff into an empty workspace: an assistant turn says what
    arrived and from whom, and its plan becomes revision 1 for the user to
    read. Refused once the workspace has a plan."""

    if ws.plan is not None:
        raise ValueError("this topic already has a plan; open a new topic")
    received = parse(text)
    lines = [
        f"[handoff from {received['from']}] Their goal: {received['goal'] or '(none)'}"
    ]
    lines += [f"Source: {title or url} -- {url}" for url, title in received["sources"]]
    lines.append(
        "Say what you want to do with it; the plan is theirs until you edit it."
    )
    ws._say("assistant", "\n".join(lines))
    ws._propose(received["plan"])
    return received["from"]

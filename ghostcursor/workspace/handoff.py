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
import re

from ghostcursor.providers.schemas import (
    ACTIONS,
    MAX_ACTION_TEXT,
    MAX_INSTRUCTION_CHARS,
    MAX_PLAN_STEPS,
    ExpectedChange,
    PlanStep,
    TeachPlan,
)

KIND = "orbyn-handoff"
VERSION = 2  # v2 adds the plan revision, per-step action/text and done steps
MAX_SOURCES = 20
MAX_BYTES = 48 * 1024
_DONE = re.compile(r"\bstep (\d+) done\b")


def _clean(text: object, limit: int) -> str:
    return scrub(sanitize(text, limit))


def _text(value: object, limit: int) -> str:
    """A received field: a string, or the handoff is refused."""

    if not isinstance(value, str):
        raise ValueError("a handoff field is not text")
    return _clean(value, limit)


def export(ws, sender: str) -> str:
    """The handoff file's text for the current goal and plan. Refused when
    the organisation allows nothing to leave (D180 level 0)."""

    from ghostcursor import policy

    if policy.max_egress() < policy.TEXT:
        raise ValueError("your organisation does not allow handing work off")
    if ws.plan is None:
        raise ValueError("make a plan before handing it off")
    done = sorted(
        {
            int(n)
            for t in ws.turns
            if t.speaker == "assistant" and t.text.startswith("[teach r")
            for n in _DONE.findall(t.text)
        }
    )
    sources = {
        s.url: s.title for graph in ws.research_graphs for s in graph.sources
    }  # ponytail: newest title wins for a repeated URL
    value = {
        "kind": KIND,
        "version": VERSION,
        "from": _clean(sender, 60) or "a teammate",
        "goal": _clean(ws.goal, 300),
        "revision": ws.proposal.revision if ws.proposal else 1,
        "done": [n for n in done if 1 <= n <= len(ws.plan.steps)],
        "plan": [
            {
                "instruction": _clean(s.instruction, MAX_INSTRUCTION_CHARS),
                "expected_change": s.expected_change.value,
                "action": s.action,
                "text": _clean(s.text, MAX_ACTION_TEXT),
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
    base = {"kind", "version", "from", "goal", "plan", "sources"}
    extra = {"revision", "done"}
    if not isinstance(value, dict) or not base <= set(value) <= base | extra:
        raise ValueError("not a handoff file")
    if (
        value["kind"] != KIND
        or type(value["version"]) is not int
        or (value["version"] not in (1, 2))
    ):
        raise ValueError("unsupported handoff version")
    plan, sources = value["plan"], value["sources"]
    if not isinstance(plan, list) or not 1 <= len(plan) <= MAX_PLAN_STEPS:
        raise ValueError(f"a handoff carries 1 to {MAX_PLAN_STEPS} steps")
    if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
        raise ValueError("too many sources")
    steps = []
    for step in plan:
        if not isinstance(step, dict) or not {
            "instruction",
            "expected_change",
        } <= set(step) <= {"instruction", "expected_change", "action", "text"}:
            raise ValueError("a step is not instruction/expected_change")
        instruction = _text(step["instruction"], MAX_INSTRUCTION_CHARS)
        if not instruction:
            raise ValueError("a step has no instruction")
        try:
            change = ExpectedChange(step["expected_change"])
        except ValueError as exc:
            raise ValueError("a step's expected change is unknown") from exc
        action = step.get("action", "click")
        if action not in ACTIONS:
            raise ValueError("a step's action is unknown")
        steps.append(
            PlanStep(
                instruction,
                change,
                action,
                _text(step.get("text", ""), MAX_ACTION_TEXT),
            )
        )
    clean_sources = []
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"url", "title"}:
            raise ValueError("a source is not url/title")
        url = _text(source["url"], 500)
        if not url.startswith("https://"):
            raise ValueError("a source must be an https link")
        clean_sources.append((url, _text(source["title"], 200)))
    revision = value.get("revision", 1)
    if type(revision) is not int or not 1 <= revision <= 10_000:
        raise ValueError("a handoff revision is not a whole number")
    done = value.get("done", [])
    if not isinstance(done, list) or any(
        type(n) is not int or not 1 <= n <= len(steps) for n in done
    ):
        raise ValueError("a handoff done list is invalid")
    return {
        "from": _text(value["from"], 60) or "a teammate",
        "goal": _text(value["goal"], 300),
        "revision": revision,
        "done": sorted(set(done)),
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
    if received["done"]:
        spans = ", ".join(str(n) for n in received["done"])
        lines.append(
            f"They had finished step(s) {spans} of this plan (revision {received['revision']})."
        )
    # Jev injection screen (D179): a teammate's file is untrusted. Flag it for
    # the user if its goal or a step reads like an instruction to the assistant
    # rather than a task; it is never auto-run regardless, this just warns.
    screen = " ".join(
        [received["goal"]] + [s.instruction for s in received["plan"].steps]
    )
    if (
        getattr(ws.gateway, "injection_risk", None)
        and ws.gateway.injection_risk(screen) >= 0.8
    ):
        lines.append(
            "[caution] Parts of this handoff read like instructions to Orbyn, "
            "not a task. Read the steps before you run any of them."
        )
    lines += [f"Source: {title or url} -- {url}" for url, title in received["sources"]]
    lines.append(
        "Say what you want to do with it; the plan is theirs until you edit it."
    )
    ws._say("assistant", "\n".join(lines))
    ws._propose(received["plan"])
    return received["from"]

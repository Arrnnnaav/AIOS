"""Turn a task into a shareable step-by-step guide (D186, rec #1): Orbyn's
private answer to Scribe/Tango/Guidde. Those watch a task and upload clicks +
screenshots to the cloud; this renders the steps Orbyn already planned/observed
into a numbered how-to (SOP) entirely on-device, with embedded secrets scrubbed
(the D186 DLP recognizers) before the guide can be shared.

Data only: a guide DESCRIBES steps, it executes nothing and mints no input. The
capture side -- recording a live Teach/Act run into these steps -- rides the
existing observed-control pipeline; this module is the render + redact piece.
"""

from __future__ import annotations

from ghostcursor import redact

#: How each observed action reads in a human guide. Keys are the harness ACTIONS.
_ACTION_PHRASING = {
    "type": 'Type "{text}"',
    "paste": 'Paste "{text}"',
    "paste_text": 'Paste "{text}"',
    "keys": "Press {text}",
    "copy": "Copy the selection",
}


def _step_line(index: int, step, redact_pii: bool) -> str:
    instruction = getattr(step, "instruction", "") or ""
    text = getattr(step, "text", "") or ""
    if redact_pii:
        instruction = redact.scrub(instruction)[0]
        text = redact.scrub(text)[0]
    line = f"{index}. {instruction}"
    phrasing = _ACTION_PHRASING.get(getattr(step, "action", "click"))
    if phrasing:
        needs_text = "{text}" in phrasing
        if not needs_text:  # e.g. "Copy the selection"
            line += f"\n   - {phrasing}"
        elif text:  # type/paste/keys with content
            line += f"\n   - {phrasing.format(text=text)}"
    return line


def render_guide(title: str, plan, *, redact_pii: bool = True) -> str:
    """A numbered step-by-step guide for ``plan`` (a TeachPlan, or anything with
    a ``.steps`` of PlanStep-likes). With ``redact_pii`` (default on) embedded
    secrets in every step are scrubbed, so the guide is safe to share; pass
    False for the owner's own verbatim copy. Returns Markdown."""

    title = " ".join(str(title).split())
    if redact_pii:
        title = redact.scrub(title)[0]
    steps = getattr(plan, "steps", plan)
    if not steps:
        raise ValueError("a guide needs at least one step")
    lines = [f"# How to: {title}", ""]
    lines += [_step_line(i, step, redact_pii) for i, step in enumerate(steps, start=1)]
    return "\n".join(lines) + "\n"

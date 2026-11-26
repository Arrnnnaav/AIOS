"""Watch me, then repeat: the person does a task once in the bound windows
while Orbyn notes which controls they click; the clicks become a plan that
Teach can guide or Act can repeat later (saved as a task skill).

How a click is seen: the left button is polled (GetAsyncKeyState, no hook,
nothing synthesised -- rule 1) and, at each press, the control under the
pointer is looked up in the newest frame the observer already read on its
own thread (rule 5). Nothing typed is recorded: a click into a text field
becomes "Type in <field>" with no text, so a password never enters a skill.
No screenshots. The names stay on this computer in the skill file (rule 6).
"""

from __future__ import annotations

import time

from ghostcursor.harness.spatial import SpatialReference, point
from ghostcursor.providers import ExpectedChange, PlanStep, TeachPlan
from ghostcursor.providers.schemas import MAX_INSTRUCTION_CHARS, MAX_PLAN_STEPS

#: Controls a click types into: the step asks the person to type, Orbyn never does.
TEXT_FIELDS = ("Edit", "Document", "ComboBox")
#: Controls whose name is often content (a mail subject, a chat line, a file
#: name): kept short and with private details hidden before they are saved.
CONTENT_TYPES = ("ListItem", "DataItem", "TreeItem", "Hyperlink", "Text")
POLL_S = 0.015
VK_LBUTTON = 0x01


def _button_down() -> bool:
    """Down now, or pressed since the last read (the low bit): a quick tap
    between two polls still counts once."""

    import ctypes

    return bool(ctypes.windll.user32.GetAsyncKeyState(VK_LBUTTON) & 0x8001)


def _cursor() -> tuple[int, int]:
    import win32api

    return win32api.GetCursorPos()


def step_for(control) -> PlanStep:
    """The plan step one recorded click becomes."""

    kind = control.control_type
    name = " ".join((control.name or "").split())
    if kind in CONTENT_TYPES:
        from ghostcursor import redact, settings

        name = redact.scrub(name[:40], terms=settings.private_terms())[0]
    name = name[:80] or f"the {kind}"
    if kind in TEXT_FIELDS:
        # A click into the field: Act puts the caret there (the focus moving
        # is the step done); what to type is never recorded, so the person types.
        text = f'Click into "{name}" ({kind}) and type'
        return PlanStep(
            text[:MAX_INSTRUCTION_CHARS], ExpectedChange.FOCUS_MOVES_TO_CHOSEN, "click", ""
        )
    text = f'Click "{name}" ({kind})'
    return PlanStep(
        text[:MAX_INSTRUCTION_CHARS], ExpectedChange.CHOSEN_STATE_CHANGES, "click", ""
    )


def watch(
    observer,
    deadline: float,
    *,
    done,
    stop,
    say=print,
    button=_button_down,
    cursor=_cursor,
    clock=time.monotonic,
    sleep=time.sleep,
) -> TeachPlan | None:
    """Record clicks on observed controls until DONE (the person's Done),
    STOP/ESC or the deadline. Returns the plan, or None if nothing usable
    was clicked or the person stopped."""

    steps: list[PlanStep] = []
    last_key = None
    was_down = button()  # a press already held when watching starts is not a click
    while clock() < deadline:
        if stop():
            say("Stopped; nothing was saved.")
            return None
        if done():
            break
        down = button()
        if down and not was_down:
            x, y = cursor()
            frame = observer.latest()
            under = (
                SpatialReference.from_mark(point(x, y), frame).current(frame)
                if frame
                else ()
            )
            if under:  # outside the bound windows (Orbyn's own window too) is ignored
                control = under[0]
                key = (control.window, control.runtime_id)
                if key != last_key:  # a double click is one step
                    steps.append(step_for(control))
                    last_key = key
                    say(f"Step {len(steps)}: {steps[-1].instruction}")
                if len(steps) >= MAX_PLAN_STEPS:
                    say(f"That is {MAX_PLAN_STEPS} steps, the most one plan holds.")
                    break
        was_down = down
        sleep(POLL_S)
    if not steps:
        say("No click on the chosen windows was seen.")
        return None
    return TeachPlan(tuple(steps))

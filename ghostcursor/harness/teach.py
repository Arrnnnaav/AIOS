"""Model-driven Teach across bound windows (D164 step 3; spec sections 4-6).

A prototype behind ``--model-teach``. System Two writes a bounded plan; for each
step System One picks one OBSERVED candidate by frame-local id or abstains; a
deterministic gate decides whether the pointer may be drawn; the step completes
when the harness observes the change the plan promised, or the user confirms.

The session is driven by ``tick`` on the UI thread and never waits on a model:
calls go through one overwritten :class:`RequestSlot` on a worker (spec section
4, D020). Nothing here writes memory: a model-selected target is shown in the
INFERRED colour and never reaches ``kb.sqlite`` (D070, D147; this module
imports no memory code, and a test holds it to that).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from enum import Enum

from ghostcursor.harness.frame import Candidate, ObservationFrame, resolve
from ghostcursor.providers import (
    Envelope,
    ExpectedChange,
    FailureKind,
    ProviderError,
    RequestSlot,
    Tainted,
    TeachPlan,
)

#: Provisional, NOT fitted: spec section 4 fits floor and margin on a dev split
#: in the measurement step. Until then these are placeholders, not results.
CONFIDENCE_FLOOR = 0.6
MARGIN = 0.2
#: A frame older than this is never drawn from (review B1): the observer may
#: be stuck on a hung window, and the screen may have moved since. Provisional:
#: above one observe cycle across several windows; fitted in the measurement step.
MAX_FRAME_AGE_S = 3.0
#: Re-asks per step before the session says it is stuck.
MAX_REASKS = 3
#: Act (D182): after acting, wait this long for the expected change, then
#: count the step done anyway (typing rarely changes what UIA reports).
ACT_SETTLE_S = 2.0

#: A pointer at one of these needs the user's explicit go-ahead first.
HIGH_RISK = re.compile(
    # Stems, not whole words only: "Payment", "Deletes", "Sending" must match.
    r"\b(delet\w*|remov\w*|send\w*|sent|pay\w*|purchas\w*|buy\w*|"
    r"sign[- ]?in|log[- ]?in|password|uninstall\w*|install\w*|format|erase\w*|"
    r"discard\w*|overwrit\w*|replac\w*|reset\w*|clos(?:e|es|ed|ing)|quit|exit|"
    r"sign[- ]?out|log[- ]?out|"
    r"don['\u2019]?t save|do not save|submit\w*|publish\w*|empt(?:y|ies|ied|ying)|clear\w*|"
    r"check[- ]?out|place order|order now|unsubscrib\w*|trash\w*)\b",
    re.IGNORECASE,
)

_CTRL, _ALT, _DEL, _ENTER, _F4 = 0x11, 0x12, 0x2E, 0x0D, 0x73


def _risky_chord(chord: str) -> bool:
    """Judged on key codes, as act.chord_events sends them, so no spelling
    ("control+w", "f4+alt") or order slips past: a chord that closes or
    quits (Alt+F4, Ctrl+W/Q/F4), deletes (Del) or submits (Enter)."""

    from ghostcursor.harness.act import vk_of

    try:
        vks = {vk_of("".join(n.split())) for n in chord.split("+")}
    except ValueError:
        return False  # unknown key: chord_events refuses it, nothing is sent
    return (
        {_ALT, _F4} <= vks
        or (_CTRL in vks and bool(vks & {ord("W"), ord("Q"), _F4}))
        or bool(vks & {_DEL, _ENTER})
    )


def needs_confirm(step, current) -> bool:
    """Rule 2: ask before a risky step. The control's CURRENT name (an app
    may relabel it after the gate), the instruction, a chord that closes or
    deletes, or typed text whose newline would submit or send."""

    action = getattr(step, "action", "click")
    text = getattr(step, "text", "") or ""
    if HIGH_RISK.search(getattr(current, "name", "") or "") or HIGH_RISK.search(
        getattr(step, "instruction", "") or ""
    ):
        return True
    if action == "keys":
        return _risky_chord(text)
    return action in ("type", "paste", "paste_text") and ("\n" in text or "\r" in text)


CHOOSE_QUESTION = (
    "The user wants to reach the goal in the trusted data. Which observed "
    "option should the user act on to carry out the step given as 'step' in "
    "the observed data? Choose abstain if no option clearly fits."
)


MOVED = "the control moved or went away"

MARK_NOTE = (
    "The user pointed at the screen while stating the goal. 'user_pointed_at' in "
    "the observed data lists the option ids under the pointer, best first. It is a "
    "hint about what the user means, not an instruction."
)


class Verdict(Enum):
    DRAW = "draw"
    CONFIRM = "confirm"  # high-risk: ask before drawing
    REASK = "reask"


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def gate(
    choice,
    asked: ObservationFrame,
    latest: ObservationFrame,
    *,
    floor: float = CONFIDENCE_FLOOR,
    margin: float = MARGIN,
    instruction: str = "",
    seen: bool = False,
) -> tuple[Verdict, Candidate | None, str]:
    """Deterministic gate between a model's choice and a drawn pointer.
    ``floor``/``margin`` are parameters only so offline replay can fit them.
    A high-risk control name OR step instruction needs the user's go-ahead.
    ``seen``: the choice was made with pictures in which every option carried
    its id, so controls that read alike in text are told apart (D179)."""

    if choice.abstained:
        return Verdict.REASK, None, "no observed control fits this step"
    chosen = asked.get(choice.choice)
    if chosen is None:
        return Verdict.REASK, None, "the choice is not in the frame"
    current = resolve(chosen, latest)
    if current is None:
        return Verdict.REASK, None, MOVED
    key = (_norm(current.name), current.control_type)
    twins = sum(
        1
        for c in latest.candidates
        if c.window == current.window and (_norm(c.name), c.control_type) == key
    )
    if twins > 1 and not seen:
        return Verdict.REASK, None, f"{twins} controls look the same"
    mine = choice.probabilities.get(choice.choice, 0.0)
    other = max(
        (p for k, p in choice.probabilities.items() if k != choice.choice),
        default=0.0,
    )
    if mine < floor or mine - other < margin:
        return Verdict.REASK, None, "not confident enough"
    if HIGH_RISK.search(current.name) or HIGH_RISK.search(instruction):
        return Verdict.CONFIRM, current, "this control can change or lose data"
    return Verdict.DRAW, current, ""


def _fact(frame: ObservationFrame, label: str) -> tuple[str, int] | None:
    return next(((t, n) for lab, t, n in frame.facts if lab == label), None)


def change_observed(
    change: ExpectedChange,
    chosen: Candidate,
    before: ObservationFrame,
    after: ObservationFrame,
) -> bool:
    """True only for a change attributable to the chosen control or its own
    window (spec section 5). A partial read is never evidence of absence."""

    if (
        chosen.window in after.incomplete
        or chosen.window in after.minimized
        or after.truncated  # the cap may have dropped a control that is still there
    ):
        return False
    now = [
        c
        for c in after.candidates
        if c.window == chosen.window and c.runtime_id == chosen.runtime_id
    ]
    if change is ExpectedChange.CHOSEN_DISAPPEARS:
        return not now
    if change is ExpectedChange.CHOSEN_STATE_CHANGES:
        return len(now) == 1 and bool(chosen.state) and now[0].state != chosen.state
    if change is ExpectedChange.FOCUS_MOVES_TO_CHOSEN:
        return len(now) == 1 and now[0].focused and not chosen.focused
    old, new = _fact(before, chosen.window), _fact(after, chosen.window)
    if old is None or new is None:
        return False
    if change is ExpectedChange.NEW_WINDOW_OF_TARGET:
        return new[1] > old[1]
    if change is ExpectedChange.TITLE_CHANGES:
        return new[0] != old[0]
    return False


#: A window reporting this few controls shows only its title bar (System,
#: Minimize, Maximize, Close): the app stopped exposing UI Automation.
SPARSE_CONTROLS = 4


def _sparse_hint(frame: ObservationFrame) -> str:
    counts = {b.label: 0 for b in frame.windows}
    for c in frame.candidates:
        counts[c.window] = counts.get(c.window, 0) + 1
    sparse = [
        b.identity.executable
        for b in frame.windows
        if counts[b.label] <= SPARSE_CONTROLS
    ]
    if not sparse:
        return ""
    return f"; {', '.join(sparse)} shows almost no controls - restart it and try again"


class Phase(Enum):
    PLANNING = "planning"
    APPROVE = "approve"  # Act: the user reads the whole plan first (D182)
    CHOOSING = "choosing"
    CONFIRM_RISK = "confirm_risk"
    SHOWING = "showing"
    DONE = "done"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class Display:
    """What the UI thread shows this tick. ``target`` is drawn INFERRED."""

    phase: Phase
    message: str
    target: Candidate | None = None


class ModelTeachSession:
    def __init__(
        self,
        goal: str,
        gateway,
        slot: RequestSlot | None = None,
        *,
        clock=time.monotonic,
        mark=None,
        plan: TeachPlan | None = None,
        look=None,
        act=None,
        deny=(),
    ):
        self.goal = goal
        #: Act (D182): ``act(step, target) -> str`` performs a step on the
        #: chosen, freshly resolved control; None means Teach (guide only).
        self.act = act
        #: Act deny list (D182, HeyClicky's idea): control names Act must
        #: never touch even if Jev picks them. Matched case-insensitively as
        #: substrings, so "delete" covers "Delete slide" and "Delete all".
        self.deny = tuple(d.casefold() for d in deny)
        self._acted_at: float | None = None
        #: frame -> {window label: redacted JPEG} when the user allowed Jev to
        #: see pictures (D179); used only after a text-only choice failed.
        self.look = look
        self._looking = False
        self._asked_seen = False
        self.clock = clock
        #: A SpatialReference (D171): context only, never a choice.
        self.mark = mark
        self.gateway = gateway
        self.slot = slot or RequestSlot()
        #: A plan the user already reviewed in the workspace (D173) skips
        #: planning; it is still only guidance, chosen and gated per step.
        self.phase = (
            Phase.PLANNING
            if plan is None
            else Phase.APPROVE
            if act is not None
            else Phase.CHOOSING
        )
        self.plan: TeachPlan | None = plan
        self.step = 0
        self.reasks = 0
        self.message = "planning"
        #: (step number, why it completed) -- "you confirmed" or the observed
        #: change; printed live so a false completion is visible (D167).
        self.completed: list[tuple[int, str]] = []
        self._request: int | None = None
        self._asked: ObservationFrame | None = None
        self._chosen: Candidate | None = None  # identity at draw time
        self._before: ObservationFrame | None = None
        self._target: Candidate | None = None  # latest resolved rectangle

    # --- requests (worker side) ----------------------------------------

    def _verify_says_no(self, step, frame: ObservationFrame, chosen) -> bool:
        """Jev's verdict on whether an acted step took effect (D179). True only
        on a confident 'no'; fail-open (False) on unsure, yes, or any error, so
        a verification outage never stalls Act."""

        judge = getattr(self.gateway, "judge", None)
        if judge is None:
            return False
        current = resolve(chosen, frame)  # CHOSEN: captured on the UI thread
        after = (
            "the control is gone"
            if current is None
            else (f"state={current.state or '(none)'} focused={current.focused}")
        )
        before = f"state={chosen.state or '(none)'} focused={chosen.focused}"
        envelope = Envelope(
            task="verify",
            trusted={
                "ask": "Given the control's before and after, did the step happen?"
            },
            tainted={
                "step": Tainted.of("model_plan_step", step.instruction),
                "before": Tainted.of("uia_state", before),
                "after": Tainted.of("uia_state", after),
            },
        )
        try:
            verdict = judge(
                envelope,
                {
                    "happened": (
                        "Did the step in `step` take effect, judging by `before` vs "
                        "`after`?",
                        {
                            "yes": "it took effect",
                            "no": "it did not",
                            "unsure": "cannot tell",
                        },
                    )
                },
            )["happened"]
        except Exception:
            return False
        return verdict.choice == "no" and verdict.probabilities.get("no", 0.0) >= 0.8

    def _envelope(self, frame: ObservationFrame, **extra) -> Envelope:
        tainted = {"frame": frame.model_view(), **extra}
        trusted = {"goal": self.goal}
        marked = self.mark.model_view(frame) if self.mark is not None else []
        if marked:
            tainted["user_pointed_at"] = marked
            trusted["user_mark"] = MARK_NOTE
        return Envelope(task="teach", trusted=trusted, tainted=tainted)

    def _ask_plan(self, frame: ObservationFrame) -> None:
        envelope = self._envelope(frame)
        self._request = self.slot.submit(
            lambda cancelled: self.gateway.plan(envelope, cancelled=cancelled)
        )

    def _ask_choice(self, frame: ObservationFrame) -> None:
        step = self.plan.steps[self.step]
        envelope = self._envelope(
            frame, step=Tainted.of("model_plan_step", step.instruction)
        )
        ids = frame.ids
        self._asked = frame
        look = self.look if self._looking else None
        self._asked_seen = False

        def ask(cancelled):
            # Pictures are taken on the worker, never on the UI thread (rule 5).
            # A failed capture asks text-only; only pictures actually sent
            # relax the look-alike rule (review of D179).
            extra = {}
            if look is not None:
                try:
                    shots = look(frame)
                except Exception:
                    shots = {}
                if shots:
                    extra = {"pictures": shots}
            self._asked_seen = bool(extra)
            return self.gateway.choose(
                envelope, ids, question=CHOOSE_QUESTION, cancelled=cancelled, **extra
            )

        self._request = self.slot.submit(ask)

    # --- tick (UI thread; never blocks) --------------------------------

    def stop(self) -> None:
        self.slot.cancel()

    def _block(self, message: str) -> None:
        self.phase, self.message = Phase.BLOCKED, message
        self.slot.cancel()

    def _reask(self, reason: str) -> None:
        self.reasks += 1
        self._request = self._acted_at = None
        if self.reasks > MAX_REASKS:
            self._block(f"stuck on step {self.step + 1}: {reason}")
        else:
            self.phase, self.message = Phase.CHOOSING, f"re-looking ({reason})"

    def _advance(self) -> None:
        self.slot.cancel()  # an answer for the step just left is never used
        self.step += 1
        self.reasks = 0
        self._request = self._chosen = self._before = self._target = None
        self._acted_at = None
        self._looking = False  # each step starts text-only again
        if self.step >= len(self.plan.steps):
            self.phase, self.message = Phase.DONE, "all steps done"
        else:
            self.phase, self.message = Phase.CHOOSING, "next step"

    def _instruction(self) -> str:
        step = self.plan.steps[self.step]
        return (
            f"Step {self.step + 1}/{len(self.plan.steps)} (suggested): "
            f"{step.instruction}"
        )

    def _failed(self, error: BaseException) -> None:
        if isinstance(error, ProviderError) and error.kind in (
            FailureKind.TIMEOUT,
            FailureKind.UNAVAILABLE,
            FailureKind.INVALID_OUTPUT,
        ):
            self._reask(f"model {error.kind.value}")
            return
        kind = getattr(getattr(error, "kind", None), "value", type(error).__name__)
        self._block(f"needs you: the model is not available ({kind})")

    def tick(self, frame: ObservationFrame | None, *, confirm: bool = False) -> Display:
        if self.phase in (Phase.DONE, Phase.BLOCKED):
            return Display(self.phase, self.message)
        if frame is None:
            return Display(self.phase, "observing")

        if self.phase is Phase.PLANNING:
            if self._request is None:
                self._ask_plan(frame)
            result = self.slot.poll(self._request)
            if result is not None:
                if result.error is not None:
                    kind = getattr(result.error, "kind", None)
                    self._block(f"no usable plan ({getattr(kind, 'value', 'error')})")
                else:
                    self.plan, self._request = result.value, None
                    self.phase, self.message = Phase.CHOOSING, "finding the control"
                    if self.act is not None:
                        self.phase = Phase.APPROVE
                    confirm = False

        if self.phase is Phase.APPROVE:
            from ghostcursor import policy

            if policy.act_disabled():  # D187: say so before asking to approve
                self._block("your organisation allows Orbyn to guide, not act")
                return Display(self.phase, self.message)
            if not confirm:
                steps = "; ".join(
                    f"{n}. {s.instruction}"
                    for n, s in enumerate(self.plan.steps, start=1)
                )
                return Display(self.phase, f"Approve to let Orbyn do: {steps}")
            from ghostcursor import audit

            audit.record("plan_approved", via="harness", steps=len(self.plan.steps))
            self.phase, self.message = Phase.CHOOSING, "finding the control"
            confirm = False

        if frame.minimized and self.phase in (
            Phase.CHOOSING,
            Phase.CONFIRM_RISK,
            Phase.SHOWING,
        ):  # its controls are off-screen: wait, never re-ask or act (rule 3)
            # ponytail: holds for any minimized bound window, even one the step
            # does not use; narrow to the step's window if multi-window needs it.
            apps = ", ".join(
                b.identity.executable
                for b in frame.windows
                if b.label in frame.minimized
            )
            return Display(self.phase, f"{apps} is minimized - restore it to continue")

        if self.phase is Phase.CHOOSING:
            if self._request is None:
                if not frame.ids:
                    return Display(self.phase, "no controls observed yet")
                self._ask_choice(frame)
            result = self.slot.poll(self._request)
            if result is not None:
                if result.error is not None:
                    self._failed(result.error)
                else:
                    verdict, current, reason = gate(
                        result.value,
                        self._asked,
                        frame,
                        instruction=self.plan.steps[self.step].instruction,
                        seen=self._asked_seen,
                    )
                    if verdict is Verdict.REASK:
                        if self.look is not None and reason != MOVED:
                            self._looking = True  # text was not enough: look
                        self._reask(reason + _sparse_hint(frame))
                    else:
                        self._chosen = self._target = current
                        self._risk_ok = False  # a new control: not yet confirmed
                        self._before = frame
                        self._request = None
                        self.phase = (
                            Phase.SHOWING
                            if verdict is Verdict.DRAW
                            else Phase.CONFIRM_RISK
                        )
                        self.message = self._instruction()
                        confirm = False  # a stale key press never counts

        if self.phase is Phase.CONFIRM_RISK:
            if confirm:
                current = resolve(self._chosen, frame)
                if current is None:
                    self._reask("the control moved or went away")
                else:
                    self._target, self.phase = current, Phase.SHOWING
                    self._risk_ok = True  # the user said yes to this control
                confirm = False
            else:
                return Display(
                    self.phase,
                    f"{self._instruction()} -- this control can change or lose "
                    "data; press Enter in the Orbyn console to show it",
                )

        if self.phase is Phase.SHOWING:
            step = self.plan.steps[self.step]
            if self.act is not None and self._acted_at is None:
                current = resolve(self._chosen, frame)
                if (
                    current is None
                    or self.clock() - frame.at > MAX_FRAME_AGE_S
                    or current.window in frame.minimized + frame.incomplete
                ):  # as drive_live: never act on a window that was not fully read
                    self._reask("the control moved or went away")
                    return Display(self.phase, self.message)
                if not getattr(self, "_risk_ok", False) and needs_confirm(step, current):
                    # Relabelled since the gate, or a risky chord/text: ask first.
                    self._chosen = self._target = current
                    self.phase = Phase.CONFIRM_RISK
                    self.message = self._instruction()
                    return Display(self.phase, self.message)
                name = (current.name or "").casefold()
                if any(d and d in name for d in self.deny):
                    self._block(
                        f'step {self.step + 1} would act on "{current.name}", '
                        "which you told Orbyn not to touch"
                    )
                    return Display(self.phase, self.message)
                try:
                    did = self.act(step, current)
                except Exception as exc:  # a refused chord, a failed SendInput
                    if getattr(exc, "retry", False):  # the user is busy: next tick
                        self.message = f"{self._instruction()} -- {exc}"
                        return Display(self.phase, self.message)
                    self._block(f"could not act on step {self.step + 1}: {exc}")
                    return Display(self.phase, self.message)
                self._acted_at = self.clock()
                self.message = f"{self._instruction()} -- {did}"
                return Display(self.phase, self.message, current)
            settled = (
                self._acted_at is not None
                and self.clock() - self._acted_at >= ACT_SETTLE_S
            )
            observed = change_observed(
                step.expected_change, self._chosen, self._before, frame
            )
            settle_why = "acted (no change seen)"
            if settled and not observed and not confirm and self.act is not None:
                # Step-verification (D179): no deterministic change was seen, so
                # ask Jev whether the step actually happened. A confident "no"
                # re-looks instead of counting a false completion; anything else
                # (yes, unsure, Jev down) lets the settle stand (fail-open).
                if getattr(self.gateway, "judge", None) is not None:
                    # On the worker like every model call: the UI loop polls
                    # ESC and Stop and must never wait on Jev (rule 4, D020).
                    if self._request is None:
                        chosen = self._chosen  # never read self on the worker
                        self._request = self.slot.submit(
                            lambda cancelled: self._verify_says_no(step, frame, chosen)
                        )
                    verdict = self.slot.poll(self._request)
                    if verdict is None:
                        return Display(self.phase, self.message)
                    self._request = None
                    if verdict.error is None and verdict.value:
                        if step.action != "click":
                            # Typing or keys again could double the text or
                            # repeat a shortcut: the user decides instead.
                            self._block(
                                f"step {self.step + 1} may not have taken effect; "
                                "check it before running Orbyn again"
                            )
                            return Display(self.phase, self.message)
                        self._reask("the step did not take effect")
                        return Display(self.phase, self.message)
                    settle_why = "acted (Jev: likely done)"
            if confirm or observed or settled:
                why = (
                    "you confirmed"
                    if confirm
                    else f"observed {step.expected_change.value}"
                    if observed
                    else settle_why
                )
                self.completed.append((self.step + 1, why))
                self._advance()
                return self.tick(frame)
            current = resolve(self._chosen, frame)
            if current is None:
                self._reask("the control moved or went away")
            else:
                self._target = current
                if self.clock() - frame.at > MAX_FRAME_AGE_S or current.window in (
                    frame.minimized + frame.incomplete
                ):
                    return Display(
                        self.phase, f"{self.message} (waiting for a fresh look)"
                    )
                return Display(self.phase, self.message, current)

        return Display(self.phase, self.message)

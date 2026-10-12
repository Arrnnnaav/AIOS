"""Offline replay evaluation for model-driven Teach (D164 step 4; spec section 9).

A corpus is JSONL, one labelled step per line. A record holds exactly what a
model would see for that step -- the frame's model view, with document names
already hidden -- plus the step instruction and the acceptable answers. It
never holds a handle, PID, runtime id, rectangle or window title, so a record
cannot leak them (spec section 7, I10).

Replay feeds each step to a chooser (a lexical baseline, a recorded cassette,
or the live gateway in a separately named lane), runs the REAL deterministic
gate from ``ghostcursor.harness.teach`` on the answer, and counts the primary
harm: a pointer shown at a control no label accepts. ``fit`` picks the gate's
floor and margin on the dev split only.

Read-only: nothing here observes a live screen or acts on one (D063-D067).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from ghostcursor.harness.binding import Identity, WindowBinding
from ghostcursor.harness.frame import Candidate, ObservationFrame
from ghostcursor.harness.teach import (
    CHOOSE_QUESTION,
    CONFIDENCE_FLOOR,
    HIGH_RISK,
    MARGIN,
    Verdict,
    gate,
)
from ghostcursor.providers.envelope import Envelope, Tainted
from ghostcursor.providers.errors import ProviderError
from ghostcursor.providers.schemas import ABSTAIN, Choice

SCHEMA = "orbyn.teach-corpus/1"
SPLITS = ("dev", "test", "adversarial")
_CANDIDATE_KEYS = {"cid", "window", "type", "name", "region"}
_RECORD_KEYS = {
    "schema",
    "step_id",
    "split",
    "goal",
    "instruction",
    "windows",
    "candidates",
    "labels",
}


@dataclass(frozen=True)
class Step:
    step_id: str
    split: str
    goal: str
    instruction: str
    windows: dict  # label -> application name
    candidates: tuple[dict, ...]  # {cid, window, type, name, region}
    labels: frozenset[str]  # acceptable cids; empty = nothing fits, abstain is right


# --- records -------------------------------------------------------------------


def record_from_frame(
    frame: ObservationFrame,
    *,
    step_id: str,
    split: str,
    goal: str,
    instruction: str,
    labels: Iterable[str],
) -> dict:
    """A corpus record built from the frame's MODEL VIEW only: the scrub is the
    same one that decides what may leave the machine, so the corpus can never
    hold more than a model would have seen."""

    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}")
    labels = sorted(set(labels))
    unknown = set(labels) - set(frame.ids)
    if unknown:
        raise ValueError(f"labels not in the frame: {sorted(unknown)}")
    view = frame.model_view()
    return {
        "schema": SCHEMA,
        "step_id": step_id,
        "split": split,
        "goal": goal,
        "instruction": instruction,
        "windows": {
            label: data["application"].text for label, data in view["windows"].items()
        },
        "candidates": [
            {"cid": cid, **{key: value.text for key, value in data.items()}}
            for cid, data in view["candidates"].items()
        ],
        "labels": labels,
    }


def parse_record(record: dict) -> Step:
    """Strict: a record with any other field (a handle, a title...) is refused."""

    if set(record) != _RECORD_KEYS or record["schema"] != SCHEMA:
        raise ValueError(f"not a {SCHEMA} record: {sorted(record)}")
    if record["split"] not in SPLITS:
        raise ValueError(f"unknown split {record['split']!r}")
    candidates = tuple(record["candidates"])
    for candidate in candidates:
        if set(candidate) != _CANDIDATE_KEYS or not all(
            isinstance(v, str) for v in candidate.values()
        ):
            raise ValueError(f"candidate fields are {sorted(candidate)}")
    windows = record["windows"]
    if not isinstance(windows, dict) or not all(
        isinstance(k, str) and re.fullmatch(r"w[1-9]", k) and isinstance(v, str)
        for k, v in windows.items()
    ):
        raise ValueError("windows must map w1..w9 to application names")
    for text in (record["goal"], record["instruction"], record["step_id"]):
        if not isinstance(text, str):
            raise ValueError("goal, instruction and step_id must be strings")
    ids = {c["cid"] for c in candidates}
    labels = frozenset(record["labels"])
    if not labels <= ids:
        raise ValueError(f"step {record['step_id']}: labels not among candidates")
    return Step(
        str(record["step_id"]),
        record["split"],
        str(record["goal"]),
        str(record["instruction"]),
        windows,
        candidates,
        labels,
    )


def load_corpus(path: Path) -> list[Step]:
    steps = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                steps.append(parse_record(json.loads(line)))
    if len({s.step_id for s in steps}) != len(steps):
        raise ValueError("duplicate step_id in corpus")
    return steps


def step_frame(step: Step) -> ObservationFrame:
    """A stand-in frame so the real gate and model view run unchanged. Runtime
    ids and rectangles are synthetic: identity re-resolution is a live
    property and is measured in the live lane, not here."""

    labels = sorted(step.windows)
    bindings = tuple(
        WindowBinding(int(label.lstrip("w")), 0, Identity(0, step.windows[label], ""))
        for label in labels
    )
    candidates = tuple(
        Candidate(
            c["cid"],
            c["window"],
            (number,),
            c["name"],  # model_view() re-hides document names (D168)
            c["type"],
            (0, 0, 10, 10),
            c["region"],
        )
        for number, c in enumerate(step.candidates, start=1)
    )
    return ObservationFrame(0, 0.0, bindings, candidates, False, ())


# --- choosers ------------------------------------------------------------------

Chooser = Callable[[Step], Choice]


def lexical_chooser(step: Step) -> Choice:
    """Baseline M4: fuzzy token overlap between the instruction and each
    candidate's name. Scores are not probabilities; the gate treats them as
    confidence, which is what the baseline is compared on."""

    from rapidfuzz import fuzz

    scores = {
        c["cid"]: fuzz.token_set_ratio(step.instruction, c["name"]) / 100
        for c in step.candidates
    }
    if not scores:
        return Choice(ABSTAIN, {})
    best = max(scores, key=scores.get)
    return Choice(best, scores)


def cassette_chooser(path: Path) -> Chooser:
    """Replays recorded answers; a step with no recording is an abstention."""

    recorded = json.loads(path.read_text(encoding="utf-8"))

    def choose(step: Step) -> Choice:
        answer = recorded.get(step.step_id)
        if answer is None:
            return Choice(ABSTAIN, {})
        return Choice(answer["choice"], dict(answer["probabilities"]))

    return choose


def gateway_chooser(gateway, record_to: Path | None = None) -> Chooser:
    """Live provider lane: the same envelope the session sends (teach.py),
    optionally recorded as a cassette for hermetic re-runs."""

    tape: dict = {}

    def choose(step: Step) -> Choice:
        frame = step_frame(step)
        envelope = Envelope(
            task="teach",
            trusted={"goal": step.goal},
            tainted={
                "frame": frame.model_view(),
                "step": Tainted.of("model_plan_step", step.instruction),
            },
        )
        try:
            choice = gateway.choose(envelope, frame.ids, question=CHOOSE_QUESTION)
        except ProviderError:
            choice = Choice(ABSTAIN, {})
        tape[step.step_id] = {
            "choice": choice.choice,
            "probabilities": choice.probabilities,
        }
        if record_to is not None:
            record_to.write_text(json.dumps(tape, indent=1, sort_keys=True), "utf-8")
        return choice

    return choose


# --- scoring -------------------------------------------------------------------


@dataclass
class Tally:
    steps: int = 0
    shown: int = 0
    wrong: int = 0
    wrong_high_risk: int = 0
    withheld_right: int = 0  # nothing fits and nothing was shown
    reasons: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        upper = 1 - 0.05 ** (1 / self.shown) if self.shown and not self.wrong else None
        return {
            "steps": self.steps,
            "pointer_shown": self.shown,
            "wrong_pointer": self.wrong,
            "wrong_pointer_high_risk": self.wrong_high_risk,
            "correct_abstention": self.withheld_right,
            "coverage": round(self.shown / self.steps, 4) if self.steps else None,
            # One-sided 95% bound on the wrong-pointer rate, only when zero failed.
            "wrong_rate_upper_95": round(upper, 4) if upper is not None else None,
            "withheld_reasons": dict(sorted(self.reasons.items())),
        }


def _application(step: Step, cid: str | None) -> str:
    window = next((c["window"] for c in step.candidates if c["cid"] == cid), None)
    if window is None and step.labels:
        first = min(step.labels)
        window = next(c["window"] for c in step.candidates if c["cid"] == first)
    return step.windows.get(window, "(none)") if window else "(none)"


def score(
    steps: Iterable[Step],
    answers: dict[str, Choice],
    *,
    floor: float = CONFIDENCE_FLOOR,
    margin: float = MARGIN,
) -> dict:
    """Per-application and overall tallies through the real gate."""

    tallies: dict[str, Tally] = {}
    overall = Tally()
    for step in steps:
        frame = step_frame(step)
        verdict, target, reason = gate(
            answers[step.step_id],
            frame,
            frame,
            floor=floor,
            margin=margin,
            instruction=step.instruction,
        )
        app = _application(step, target.cid if target else None)
        for tally in (tallies.setdefault(app, Tally()), overall):
            tally.steps += 1
            if verdict is Verdict.REASK:
                tally.reasons[reason] = tally.reasons.get(reason, 0) + 1
                tally.withheld_right += not step.labels
                continue
            tally.shown += 1
            if target.cid not in step.labels:
                tally.wrong += 1
                tally.wrong_high_risk += bool(HIGH_RISK.search(target.name))
    return {
        "floor": floor,
        "margin": margin,
        "overall": overall.as_dict(),
        "by_application": {k: v.as_dict() for k, v in sorted(tallies.items())},
    }


def fit(steps: list[Step], answers: dict[str, Choice]) -> tuple[float, float]:
    """Floor and margin fitted on the DEV split only: most pointers shown with
    zero wrong pointers; ties go to the stricter pair. Falls back to the
    provisional constants when no pair reaches zero."""

    dev = [s for s in steps if s.split == "dev"]
    best: tuple[int, float, float] | None = None
    grid = [round(x * 0.05, 2) for x in range(0, 20)]
    for floor in grid:
        for margin in grid[:11]:
            result = score(dev, answers, floor=floor, margin=margin)["overall"]
            if result["wrong_pointer"]:
                continue
            key = (result["pointer_shown"], floor, margin)
            if best is None or key > best:
                best = key
    return (best[1], best[2]) if best else (CONFIDENCE_FLOOR, MARGIN)


def evaluate(steps: list[Step], chooser: Chooser, *, fit_gate: bool = False) -> dict:
    answers = {step.step_id: chooser(step) for step in steps}
    floor, margin = fit(steps, answers) if fit_gate else (CONFIDENCE_FLOOR, MARGIN)
    return {
        "schema": "orbyn.teach-replay-report/1",
        "fitted_on": "dev" if fit_gate else None,
        **{
            split: score(
                [s for s in steps if s.split == split],
                answers,
                floor=floor,
                margin=margin,
            )
            for split in SPLITS
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument(
        "--chooser",
        default="lexical",
        help="lexical | cassette:<path> | live[:<cassette to record>]",
    )
    parser.add_argument("--fit", action="store_true", help="fit floor/margin on dev")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    steps = load_corpus(args.corpus)
    if args.chooser == "lexical":
        chooser = lexical_chooser
    elif args.chooser.startswith("cassette:"):
        chooser = cassette_chooser(Path(args.chooser.split(":", 1)[1]))
    elif args.chooser.split(":", 1)[0] == "live":
        from ghostcursor.providers.gateway import Gateway

        tape = args.chooser.split(":", 1)[1] if ":" in args.chooser else None
        chooser = gateway_chooser(Gateway(), Path(tape) if tape else None)
    else:
        parser.error(f"unknown chooser {args.chooser!r}")
    report = evaluate(steps, chooser, fit_gate=args.fit)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

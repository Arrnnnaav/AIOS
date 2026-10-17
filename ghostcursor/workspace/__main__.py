"""The workspace console (D173):  py -3.12 -m ghostcursor.workspace <topic>

Type to discuss. Commands:
  /point            bind windows, point at what you mean (Spatial, D171)
  /voice            say your message instead of typing (SayStride, D171)
  /research <q>     a cited answer from web sources
  /evidence [n]     the passages behind research answer n (default: latest)
  /ideate           2-4 approaches, with assumptions and unknowns
  /plan             a step plan from the conversation (a proposal)
  /plan idea <n>    a plan for approach n of /ideate
  /plan edit <n> <text> | drop <n> | add <text>
                    edit the plan; each edit is a new proposal
  /teach <n> [s]    guide plan step n onward on screen for s seconds (default 300)
  /brain [list | search <q> | forget <id> | correct <id> <text> |
          pause | resume | export <file> | erase]
  /stats            counts from this machine's records (no text)
  /act <n> [s]      Orbyn does plan step n onward itself, after you approve
                    the plan (Enter); ESC stops (D182)
  /quit
"""

from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path

from ghostcursor.harness.frame import HIDDEN_NAME, reveals_document
from ghostcursor.workspace.brain import Brain
from ghostcursor.workspace.contracts import SpatialContextReference
from ghostcursor.workspace.session import Workspace

TEACH_SECONDS = 300.0


def reference_from(mark, frame) -> SpatialContextReference | None:
    """The brief's view of a harness mark: names only, no geometry (D143)."""

    under = mark.current(frame)
    if not under:
        return None
    first = under[0]
    apps = {b.label: b.identity.executable for b in frame.windows}
    titles = {label: title for label, title, _ in frame.facts}

    def shown(c) -> str:
        """As a model would see it (D168), and never text from the window
        title: the brief reaches System Two (review of D173)."""

        title = titles.get(c.window, "")
        name = " ".join(c.name.casefold().split())
        in_title = len(name) >= 4 and name in " ".join(title.casefold().split())
        hidden = in_title or reveals_document(c.name, c.control_type, title)
        return HIDDEN_NAME if hidden else c.name

    return SpatialContextReference(
        "point",
        shown(first),
        first.control_type,
        apps.get(first.window, "unknown"),
        # Spatial's point-inside score; nested controls make it ambiguous.
        0.95 if len(under) == 1 else 0.6,
        tuple(shown(c) for c in under[1:4]),
    )


def confirm_reference(
    ref: SpatialContextReference, answer: str
) -> SpatialContextReference | None:
    """The user sees what Orbyn resolved and keeps it (Enter), picks one of
    the alternatives (its number), or discards it (anything else)."""

    answer = answer.strip()
    if not answer:
        return ref
    if answer.isdigit() and 1 <= int(answer) <= len(ref.alternatives):
        return replace(
            ref,
            mark_kind="point, user chose",
            name=ref.alternatives[int(answer) - 1],
            control_type="control",
            confidence=1.0,
            alternatives=(),
        )
    return None


def teach_seconds(args: list[str]) -> float | None:
    """A finite, positive guidance limit, or None: nan or inf would mean the
    deadline never fires (rule 4)."""

    try:
        seconds = float(args[0]) if args else TEACH_SECONDS
    except ValueError:
        return None
    return seconds if 0 < seconds <= 3600 else None


def take_point() -> SpatialContextReference | None:
    from ghostcursor.harness.binding import bind
    from ghostcursor.harness.teach_live import (
        ABORTED,
        Observer,
        choose_windows,
        take_mark,
    )

    observer = Observer(bind(choose_windows()))
    observer.start()
    try:
        mark = take_mark(observer, time.monotonic() + 120)
        frame = observer.latest()
        return None if mark is ABORTED or frame is None else reference_from(mark, frame)
    finally:
        observer.stop()


def brain_command(brain: Brain, args: list[str]) -> str:
    verb = args[0] if args else "list"
    if verb == "list":
        rows = brain.list()
        return "\n".join(
            f"#{m.mid} [{m.kind}, {m.scope}, {m.origin}] {m.text}" for m in rows
        ) or "(no memories)" + (" -- learning is paused" if brain.paused else "")
    if verb == "search" and len(args) > 1:
        return (
            "\n".join(f"#{m.mid} {m.text}" for m in brain.search(" ".join(args[1:])))
            or "(none)"
        )
    if verb == "forget" and len(args) == 2 and args[1].isdigit():
        return "forgotten" if brain.forget(int(args[1])) else "no such memory"
    if verb == "correct" and len(args) > 2 and args[1].isdigit():
        fixed = brain.correct(int(args[1]), " ".join(args[2:]))
        return f"corrected as #{fixed.mid}" if fixed else "no such memory (or refused)"
    if verb in ("pause", "resume"):
        brain.pause(verb == "pause")
        return f"learning {'paused' if verb == 'pause' else 'resumed'}"
    if verb == "export" and len(args) == 2:
        Path(args[1]).write_text(brain.export(), encoding="utf-8")
        return f"exported to {args[1]}"
    if verb == "erase":
        if input("Erase every memory? Type yes: ").strip() == "yes":
            brain.erase_all()
            return "erased"
        return "kept"
    return __doc__.split("/brain", 1)[1].split("/act")[0].strip()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2
    from ghostcursor.providers import Gateway

    brain = Brain()
    workspace = Workspace(argv[0], Gateway(), brain)
    print(
        f"Workspace '{argv[0]}'"
        + (f" -- goal: {workspace.goal}" if workspace.goal else "")
        + ". /quit to leave; type a message or a command."
    )
    try:
        while True:
            try:
                line = input("> ").strip()
            except EOFError:
                break
            if not line:
                continue
            command, _, rest = line.partition(" ")
            if command == "/quit":
                break
            elif command == "/research" and rest:
                print(workspace.research(rest))
            elif command == "/point":
                reference = take_point()
                if reference is not None:
                    print(reference.as_text())
                    options = "".join(
                        f"  {n}. {name}\n"
                        for n, name in enumerate(reference.alternatives, start=1)
                    )
                    reference = confirm_reference(
                        reference,
                        input(
                            f"{options}Enter keeps it"
                            + (", a number picks another" if options else "")
                            + ", x discards: "
                        ),
                    )
                if reference is None:
                    print("No point taken.")
                else:
                    workspace.point(reference)
                    print(reference.as_text())
            elif command == "/voice":
                from ghostcursor.voice import dictate_goal

                said = dictate_goal(time.monotonic() + 120)
                if said:
                    print(workspace.discuss(said))
            elif command == "/evidence":
                print(workspace.evidence(int(rest) if rest.isdigit() else 0))
            elif command == "/ideate":
                ideas = workspace.ideate()
                print(
                    "\n".join(f"{n}. {i.as_text()}" for n, i in enumerate(ideas, 1))
                    or "No ideas: the model is not available."
                )
            elif command == "/plan" and rest and rest.split()[0] != "idea":
                verb, *args = rest.split()
                try:
                    print(workspace.edit_plan(verb, args).as_text())
                except ValueError as exc:
                    print(exc)
            elif command == "/plan":
                try:
                    plan = workspace.make_plan(int((rest.split() + ["", "0"])[1] or 0))
                except ValueError as exc:
                    print(exc)
                    continue
                print(
                    "No plan: the model is not available."
                    if plan is None
                    else "\n".join(
                        f"{n}. {s.instruction}"
                        for n, s in enumerate(plan.steps, start=1)
                    )
                )
            elif command in ("/teach", "/act"):
                parts = rest.split()
                if not parts or not parts[0].isdigit():
                    print(f"usage: {command} <step> [seconds]")
                    continue
                try:
                    plan = workspace.teach_plan(int(parts[0]))
                except ValueError as exc:
                    print(exc)
                    continue
                from ghostcursor.harness.teach_live import run_model_teach

                seconds = teach_seconds(parts[1:])
                if seconds is None:
                    print("seconds must be a number from 1 to 3600")
                    continue
                outcome: list = []
                code = run_model_teach(
                    workspace.goal,
                    None,
                    seconds=seconds,
                    plan=plan,
                    outcome=outcome,
                    act=command == "/act",
                    deny=["delete", "send", "pay", "buy", "purchase", "remove"]
                    if command == "/act"
                    else (),
                )
                print(workspace.record_teach(int(parts[0]), outcome, code))
            elif command == "/stats":
                from ghostcursor.workspace.research import _trace_path
                from ghostcursor.workspace.session import measures

                for name, value in measures(
                    brain, workspace.root, _trace_path()
                ).items():
                    print(f"{name}: {value}")
            elif command == "/brain":
                print(brain_command(brain, rest.split()))
            elif command.startswith("/"):
                print(__doc__)
            else:
                print(workspace.discuss(line))
    finally:
        brain.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

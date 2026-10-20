"""The workspace console (D173):  py -3.12 -m ghostcursor.workspace <topic>

Type to discuss. Commands:
  /point            bind windows, point at what you mean (Spatial, D171)
  /voice            say your message instead of typing (SayStride, D171)
  /dictate [brain]  speak on demand; save the transcript to a file (or the Brain)
  /research <q>     a cited answer from web sources
  /evidence [n]     the passages behind research answer n (default: latest)
  /remember <n>     save research claim n to the Company Brain (owner reviews)
  /clip             save the clipboard selection to the Company Brain (reviews)
  /ideate           2-4 approaches, with assumptions and unknowns
  /plan             a step plan from the conversation (a proposal)
  /plan idea <n>    a plan for approach n of /ideate
  /agent new <need> | save | use <name> [k=v] | list   reusable agents
  /web [url]        open Orbyn's browser, read the page's controls (read-only)
  /plan edit <n> <text> | drop <n> | add <text>
                    edit the plan; each edit is a new proposal
  /convert <src> <fmt>  convert a file locally (image via Pillow; media via
                    FFmpeg if installed) -- no upload, output beside the source
  /do <task>        ONE STEP: state any task, Orbyn picks the capability and runs
                    it (research/deck/plan/remember/skill); a "do X in an app"
                    task becomes a plan you approve with /teach or /act
  /crew <goal>      MANY STEPS: a manager breaks the goal into ordered capability
                    steps (research -> deck/plan ...) and runs them, chaining
                    through the Brain; a plan step only proposes (never acts)
  /crew save <name> <goal> | run <name> | list   reusable named crews: save
                    plans the goal once; run replays it without asking a model
  /deck [topic]     a slide-by-slide deck outline, grounded in Brain facts
  /deck build [topic]  plan to BUILD that deck in PowerPoint; proposes a plan you
                    run with /act (Orbyn never builds it unasked; ESC stops)
  /ask <question>   answer grounded on the clipboard (or: /ask file <path> | <q>);
                    reads nothing else, records nothing
  /notes [brain] <rough notes>  tidy your own notes into a titled summary with
                    key points and action items, locally (no recording); "brain"
                    files the summary as a reviewable Brain candidate
  /deepresearch <q> decompose, research each part (cited), file claims to Brain
  /researchdeck <t> research the topic then build a grounded deck
  /guide            the current plan as a shareable step-by-step guide (SOP)
  /skill save <name> | list | use <name> | from <need>   task skills; "from"
                    drafts a reusable skill from a stated need (auto-creator)
  /teach <n> [s]    guide plan step n onward on screen for s seconds (default 300)
  /providers [signin | signout]   who powers the harness (your accounts first)
  /doctor           what's ready and the one thing to turn on each missing part
  /know [add <source> | <text> | ingest <path> | list | review <id> | approve <id> |
        retire <id> | supersede <old> <new> | conflicts | recall <q>]  org facts
  /brain [list | search <q> | forget <id> | correct <id> <text> |
          pause | resume | export <file> | erase]
  /stats            counts from this machine's records (no text)
  /clips [n [brain]]  recent clipboard history; n puts it back, "brain" files it
  /snippet save <name> <text> | <name> | list | rm <name>   reusable text; a
                    recalled snippet is copied to the clipboard (never typed)
  /capture          Ctrl+Alt+C grabs the clipboard to a log from anywhere
  /x <op> [text]    quick utilities: b64/unb64, urlenc/urldec, hex2rgb/rgb2hex,
                    uuid, pass [n], time [epoch], count -- all local, offline
  (a plain sum like  3 * (4 + 1)  is answered on the spot; a mistyped
   /command gets a "did you mean" instead of the whole help)
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


KNOW_USAGE = (
    "usage: /know add <source> | <text>  |  ingest <path>  |  list [status]  |  review <id>  |  "
    "approve <id>  |  retire <id>  |  verify <id>  |  supersede <old> <new>  |  "
    "export <path>  |  export-md <path>  |  import <path>  |  "
    "relate <subject> | <predicate> | <object> | <source>  |  "
    "review-edge <id>  |  expire <id>  |  expire-edge <id>  |  "
    "private[-edge] <id>  |  unmark[-edge] <id>  |  "
    "private-source <pattern>  |  unmark-source <pattern>  |  private-sources  |  "
    "private-default [on|off]  |  episode <id>  |  "
    "conflicts  |  recall <query> [since:<days>]"
)


def providers_status(gateway, args: list[str]) -> str:
    """BYOK transparency (D182): who powers the harness. ``signin`` starts
    Sign in with ChatGPT; ``signout`` ends it; no arg shows status -- which
    account is in, which providers could answer now (own accounts first), and
    which one answered last. Keys are set in the app, never echoed here."""

    from ghostcursor.providers import chatgpt

    verb = args[0] if args else "status"
    if verb == "signin":
        try:
            chatgpt.sign_in()
            return "signed in to ChatGPT"
        except Exception as exc:  # SignInError, network, timeout
            return f"sign-in failed: {exc}"
    if verb == "signout":
        chatgpt.sign_out()
        return "signed out of ChatGPT"
    avail = gateway.available()
    ready = [n for n, ok in avail.items() if ok]
    lines = [
        "ChatGPT account: "
        + (
            "signed in"
            if chatgpt.signed_in(chatgpt.load())
            else "not signed in (/providers signin)"
        ),
        "Could answer now (your accounts first): "
        + (", ".join(ready) or "none -- /providers signin, or set a key in the app"),
    ]
    if gateway.last_provider:
        lines.append(f"Last answered by: {gateway.last_provider}")
    return "\n".join(lines)


def know_command(knowledge, scope: str, args: list[str]) -> str:
    """Company Brain owner review from the console (D186): add candidates,
    review/approve/retire/supersede facts, add and review relations, see
    conflicts, and test recall. An ``id`` is a fact's fid (an edge's eid for
    review-edge). Candidates are not usable until reviewed."""

    verb = args[0] if args else "list"
    rest = " ".join(args[1:])

    def fid(n):
        return int(n) if n.isdigit() else None

    if verb == "add" and "|" in rest:
        source, _, text = rest.partition("|")
        try:
            f = knowledge.add_candidate(
                text.strip(), source=source.strip(), scope=scope
            )
        except ValueError as exc:
            return str(exc)
        return f"candidate #{f.fid} added (not usable until you review it)"
    if verb == "ingest" and rest:
        from ghostcursor.workspace.knowledge import chunk_document

        root = Path(rest.strip())
        files = (
            [root]
            if root.is_file()
            else sorted(
                p
                for ext in ("*.md", "*.txt", "*.log")
                for p in root.rglob(ext)
                if p.is_file()
            )
            if root.is_dir()
            else []
        )
        if not files:
            return f"no .md/.txt/.log files at {rest.strip()}"
        added = dup = 0
        for path in files:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for action, _fid in knowledge.ingest(
                chunk_document(text), source=path.name, scope=scope
            ):
                added += action == "added"
                dup += action == "duplicate"
        return (
            f"ingested {len(files)} file(s): {added} new candidate(s) to review, "
            f"{dup} already known. Use /know list candidate."
        )
    if verb == "list":
        status = args[1] if len(args) > 1 else None
        rows = knowledge.list(scope=scope, status=status)
        now = knowledge.clock()
        return (
            "\n".join(
                f"#{f.fid} {'🔒 ' if f.sensitivity == 'sensitive' else ''}"
                f"[{'expired' if f.stale(now) else f.status}] "
                f"{f.text}  <- {f.source}"
                + (f" (-> #{f.superseded_by})" if f.superseded_by else "")
                for f in rows
            )
            or "(no facts)"
        )
    if verb in ("review", "approve", "retire", "verify") and len(args) == 2:
        n = fid(args[1])
        if n is None or knowledge.get(n) is None:
            return "no such fact"
        getattr(knowledge, verb)(n)
        return f"#{n} {knowledge.get(n).status}"
    if verb == "supersede" and len(args) == 3 and fid(args[1]) and fid(args[2]):
        try:
            f = knowledge.supersede(int(args[1]), int(args[2]))
        except ValueError as exc:
            return str(exc)
        return "no such fact" if f is None else f"#{args[1]} superseded by #{args[2]}"
    if verb == "relate" and rest.count("|") == 3:
        subject, predicate, obj, source = (p.strip() for p in rest.split("|"))
        try:
            e = knowledge.relate(subject, predicate, obj, source=source, scope=scope)
        except ValueError as exc:
            return str(exc)
        return f"edge #{e.eid} added (candidate; review-edge {e.eid} to use it)"
    if verb == "review-edge" and len(args) == 2 and fid(args[1]):
        e = knowledge.review_edge(int(args[1]))
        return "no such edge" if e is None else f"edge #{args[1]} {e.status}"
    if verb == "expire" and len(args) == 2 and fid(args[1]):
        f = knowledge.expire(int(args[1]))
        return (
            "no such fact" if f is None else f"#{args[1]} expires now (kept as history)"
        )
    if verb == "expire-edge" and len(args) == 2 and fid(args[1]):
        e = knowledge.expire_edge(int(args[1]))
        return "no such edge" if e is None else f"edge #{args[1]} expires now"
    if (
        verb in ("private", "unmark", "private-edge", "unmark-edge")
        and len(args) == 2
        and fid(args[1])
    ):
        sens = "sensitive" if verb.startswith("private") else "normal"
        if verb.endswith("-edge"):
            e = knowledge.classify_edge(int(args[1]), sens)
            return "no such edge" if e is None else f"edge #{args[1]} {sens}"
        f = knowledge.classify(int(args[1]), sens)
        return "no such fact" if f is None else f"#{args[1]} {sens}"
    if verb == "export" and rest:
        import json

        data = knowledge.export_scope(scope)
        Path(rest.strip()).write_text(
            json.dumps(data, indent=1), encoding="utf-8", newline="\n"
        )
        redn = sum(data["redacted"].values())
        return (
            f"exported {len(data['facts'])} fact(s), {len(data['edges'])} relation(s) "
            f"to {rest.strip()} (sensitive facts excluded"
            + (f"; {redn} secret(s) redacted before egress)" if redn else ")")
        )
    if verb == "export-md" and rest:
        text = knowledge.export_markdown(scope)
        Path(rest.strip()).write_text(text, encoding="utf-8", newline="\n")
        return (
            f"exported readable Markdown to {rest.strip()} "
            f"(sensitive facts excluded) -- read it before sharing"
        )
    if verb == "import" and rest:
        import json

        try:
            data = json.loads(Path(rest.strip()).read_text(encoding="utf-8"))
            r = knowledge.import_scope(data, scope)
        except (OSError, ValueError) as exc:
            return f"could not import: {exc}"
        return (
            f"imported as candidates: {r['facts_added']} new, {r['facts_duplicate']} "
            f"already known, {r['edges']} relation(s). Review before use: /know list candidate"
        )
    if verb == "private-source" and rest:
        knowledge.mark_source_sensitive(rest.strip())
        return f"new knowledge from sources matching '{rest.strip()}' is private"
    if verb == "unmark-source" and rest:
        removed = knowledge.unmark_source_sensitive(rest.strip())
        return "removed" if removed else "no such sensitive-source pattern"
    if verb == "private-sources":
        pats = knowledge.sensitive_sources()
        return "\n".join(pats) or "(no private sources)"
    if verb == "episode" and len(args) == 2 and fid(args[1]):
        ep = knowledge.episode_of(int(args[1]))
        return ep.text if ep else "no episode recorded for that fact"
    if verb == "private-default":
        arg = rest.strip().lower()
        if arg in ("on", "off"):
            knowledge.set_private_by_default(arg == "on")
        elif arg:
            return "private-default wants 'on' or 'off' (or nothing to show state)"
        return (
            f"private-by-default is {'on' if knowledge.private_by_default() else 'off'}"
        )
    if verb == "conflicts":
        pairs = knowledge.conflicts(scope)
        return (
            "\n".join(f"#{a.fid} <> #{b.fid}: {a.text}  ||  {b.text}" for a, b in pairs)
            or "(no conflicts)"
        )
    if verb == "recall" and rest:
        # Owner's local view on their own machine: sensitive facts are shown
        # (unlike the model-bound retrieval path, which excludes them). A
        # trailing ``since:<days>`` scopes to recently-learned facts.
        since = None
        words = rest.split()
        if words and words[-1].startswith("since:"):
            val = words[-1][6:]
            if not val.isdigit():
                return "since: wants a whole number of days, e.g. since:7"
            since = knowledge.clock() - int(val) * 86400.0
            rest = " ".join(words[:-1])
        hits = knowledge.recall(rest, scope, include_sensitive=True, since=since)
        return (
            "\n".join(f"#{f.fid} {f.text}  <- {f.source}" for f in hits) or "(nothing)"
        )
    return KNOW_USAGE


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2
    from ghostcursor.providers import Gateway

    from ghostcursor.workspace.knowledge import Knowledge

    brain = Brain()
    workspace = Workspace(argv[0], Gateway(), brain, knowledge=Knowledge())
    from ghostcursor.workspace import tips
    from ghostcursor.workspace.clips import Clips

    clips = Clips()

    print(
        f"Workspace '{argv[0]}'"
        + (f" -- goal: {workspace.goal}" if workspace.goal else "")
        + ". /quit to leave; type a message or a command."
    )
    print(f"\N{ELECTRIC LIGHT BULB} Tip: {tips.tip()}")  # quiet discoverability
    web = {"browser": None}
    try:
        while True:
            try:
                line = input("> ").strip()
            except EOFError:
                break
            if not line:
                continue
            # Fill clipboard history without a watcher: snapshot once per prompt.
            try:
                from ghostcursor.harness import act

                clips.offer(act.get_clipboard_text())
            except Exception:
                pass
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
            elif command == "/dictate":
                # On-demand capture -> SAVE (rule 1: never types into an app).
                # Default sinks to a file; "/dictate brain" files a Brain
                # candidate the owner reviews. (D186)
                from ghostcursor import dictation
                from ghostcursor.voice import dictate_goal

                said = dictate_goal(time.monotonic() + 120)
                if not said:
                    continue
                if rest.strip() == "brain" and workspace.knowledge is None:
                    print("no Company Brain here; saving to a file instead.")
                if rest.strip() == "brain" and workspace.knowledge is not None:
                    fid = dictation.to_brain(
                        said, workspace.knowledge, workspace.kb_scope
                    )
                    print(
                        f"saved to Company Brain as candidate #{fid} (review: /know list candidate)"
                    )
                else:
                    print(f"saved transcript to {dictation.save_transcript(said)}")
            elif command == "/evidence":
                print(workspace.evidence(int(rest) if rest.isdigit() else 0))
            elif command == "/remember" and rest.isdigit():
                print(workspace.remember_claim(int(rest)))
            elif command == "/clip":
                print(workspace.clip_to_brain())
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
            elif command == "/tip":
                from ghostcursor.workspace import tips

                print(tips.tip())
            elif command == "/ask" and rest:
                # Attach-context Q&A (Highlight AI's core): answer grounded on
                # the clipboard by default, or on a file via
                #   /ask file <path> | <question>
                # Read-only; records nothing to the brief or Brain.
                if rest.split()[:1] == ["file"] and "|" in rest:
                    spec, _, question = rest.partition("|")
                    path = spec.split(maxsplit=1)[1].strip().strip('"')
                    try:
                        material = Path(path).read_text(
                            encoding="utf-8", errors="replace"
                        )
                    except OSError as exc:
                        print(f"could not read {path}: {exc}")
                        continue
                else:
                    from ghostcursor.harness import act

                    question = rest
                    try:
                        material = act.get_clipboard_text() or ""
                    except Exception:
                        material = ""
                print(workspace.ask(question, material))
            elif command == "/notes" and rest:
                # Granola-style: tidy the user's OWN rough notes into a
                # structured summary, locally, no recording. "brain" also files
                # the summary as a reviewable Brain candidate.
                to_brain = rest.split()[:1] == ["brain"]
                raw = rest.split(maxsplit=1)[1] if to_brain else rest
                _summary, message = workspace.enhance_notes(raw, to_brain=to_brain)
                print(message)
            elif command == "/do" and rest:
                print(workspace.do(rest))
            elif command == "/crew" and rest:
                # Agent crew (D186): a manager decomposes the goal into ordered
                # capability steps and runs them, chaining through the Brain. A
                # plan step only proposes; the crew never acts (rule 2).
                # Verbs save/run/list manage reusable named crews; anything else
                # is an ad-hoc goal run once.
                from ghostcursor.workspace import crew as _crew

                parts = rest.split(maxsplit=2)
                verb = parts[0]
                if verb == "list":
                    print(
                        "\n".join(_crew.list_crews(workspace.root))
                        or "(no saved crews)"
                    )
                elif verb == "save" and len(parts) == 3:
                    steps = _crew.plan_crew(workspace.gateway, parts[2])
                    if not steps:
                        print("could not plan that goal (model unavailable)")
                    else:
                        try:
                            path = _crew.save_crew(workspace.root, parts[1], steps)
                            print(
                                f"saved crew '{path.stem}' ({len(steps)} steps); "
                                f"replay with /crew run {path.stem}"
                            )
                        except ValueError as exc:
                            print(exc)
                elif verb == "run" and len(parts) >= 2:
                    try:
                        steps = _crew.load_crew(workspace.root, parts[1])
                    except ValueError as exc:
                        print(exc)
                    else:
                        print(
                            _crew.run_crew(workspace, parts[1], steps=steps).as_text()
                        )
                else:
                    print(workspace.crew(rest).as_text())  # ad-hoc goal
                    nudge = workspace.usage.nudge(rest, kind="crew")
                    if nudge:
                        print(nudge)
            elif command == "/convert" and len(rest.split()) >= 2:
                # Local file conversion (Open-Tangerine ported): <src> <format>.
                from ghostcursor.workspace import convert as _convert

                parts = rest.rsplit(" ", 1)
                src, fmt = parts[0].strip().strip('"'), parts[1].strip()
                try:
                    out = _convert.convert(src, fmt)
                    print(f"converted -> {out}")
                except (ValueError, RuntimeError, OSError) as exc:
                    print(f"could not convert: {exc}")
            elif command == "/deck" and rest.split()[:1] == ["build"]:
                # Plan to BUILD the deck in PowerPoint via the gated Act path.
                # Proposes a plan; the user runs /act to execute (never auto-acts).
                topic = rest.split(maxsplit=1)[1] if len(rest.split()) > 1 else ""
                _deck, message = workspace.build_deck(topic)
                print(message)
            elif command == "/deck":
                from ghostcursor.workspace.deck import build_brief

                deck = workspace.make_deck(rest)
                print(
                    build_brief(deck)
                    if deck
                    else "No deck: the model is not available."
                )
            elif command == "/deepresearch" and rest:
                report = workspace.deep_dive(rest)
                lines = [
                    f"Researched '{report.question}' in {len(report.subquestions)} parts:"
                ]
                for sub, graph in zip(report.subquestions, report.graphs):
                    cited = sum(
                        c.status.value in ("supported", "partially_supported")
                        for c in graph.claims
                    )
                    lines.append(f"  - {sub}: {cited} cited claim(s)")
                lines.append(
                    f"filed {report.filed_to_brain} claim(s) to the Brain (review: /know list candidate)"
                )
                print("\n".join(lines))
            elif command == "/researchdeck" and rest:
                from ghostcursor.workspace.deck import build_brief

                deck, report = workspace.research_to_deck(rest)
                if deck is None:
                    print("No deck: the model is not available.")
                else:
                    print(build_brief(deck))
                    if report:
                        print(
                            f"(filed {report.filed_to_brain} research claim(s) to the Brain)"
                        )
            elif command == "/guide":
                try:
                    print(workspace.guide())
                except ValueError as exc:
                    print(exc)
            elif command == "/skill":
                parts = rest.split()
                verb = parts[0] if parts else ""
                if verb == "list":
                    print("\n".join(workspace.saved_skills()) or "(no saved skills)")
                elif verb == "save" and len(parts) >= 2:
                    try:
                        print(workspace.save_skill(" ".join(parts[1:])))
                    except ValueError as exc:
                        print(exc)
                elif verb == "use" and len(parts) >= 2:
                    print(workspace.use_skill(" ".join(parts[1:])))
                elif verb == "from" and len(parts) >= 2:
                    print(
                        workspace.draft_skill(" ".join(parts[1:]))
                        or "No skill: the model is not available."
                    )
                else:
                    print("usage: /skill save <name> | list | use <name> | from <need>")
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
                    deny=(
                        list(workspace.active_deny)
                        or ["delete", "send", "pay", "buy", "purchase", "remove"]
                    )
                    if command == "/act"
                    else (),
                )
                print(workspace.record_teach(int(parts[0]), outcome, code))
            elif command == "/clips":
                # clipboard history: list; "<n>" puts entry n back on the
                # clipboard; "<n> brain" files it as a Brain candidate (D186).
                parts = rest.split()
                if not parts:
                    rows = clips.list()
                    print(
                        "\n".join(
                            f"  {n}. {_preview(t)}" for n, t in enumerate(rows, 1)
                        )
                        or "(clipboard history is empty -- copy something, then /clips)"
                    )
                elif parts[0].isdigit():
                    text = clips.get(int(parts[0]))
                    if text is None:
                        print("no such entry")
                    elif len(parts) > 1 and parts[1] == "brain":
                        print(workspace.clip_to_brain(read=lambda: text))
                    else:
                        from ghostcursor.harness import act

                        act.set_clipboard_text(text)
                        print(f"copied entry {parts[0]} back to the clipboard")
                else:
                    print("usage: /clips  |  /clips <n>  |  /clips <n> brain")
            elif command == "/snippet":
                from ghostcursor.workspace import snippets

                parts = rest.split(maxsplit=1)
                verb = parts[0] if parts else ""
                if verb == "list":
                    print("\n".join(snippets.names(workspace.root)) or "(no snippets)")
                elif verb == "save" and len(parts) == 2 and len(parts[1].split()) >= 2:
                    name, text = parts[1].split(maxsplit=1)
                    try:
                        print(
                            f"saved snippet '{snippets.save(workspace.root, name, text)}'"
                        )
                    except ValueError as exc:
                        print(exc)
                elif verb == "rm" and len(parts) == 2:
                    ok = snippets.remove(workspace.root, parts[1])
                    print("removed" if ok else "no such snippet")
                elif verb and verb not in ("save", "rm"):
                    text = snippets.get(workspace.root, rest)
                    if text is None:
                        print(f"no snippet '{rest}' (/snippet list)")
                    else:
                        from ghostcursor.harness import act

                        act.set_clipboard_text(text)
                        print(f"'{rest}' copied to the clipboard:\n{text}")
                else:
                    print(
                        "usage: /snippet save <name> <text> | <name> | list | rm <name>"
                    )
            elif command == "/x":
                from ghostcursor.workspace import kit

                op, _, arg = rest.partition(" ")
                if not op:
                    print(f"usage: /x <op> [text] -- ops: {', '.join(kit.OPS)}")
                else:
                    print(kit.run(op, arg))
            elif command == "/capture":
                from ghostcursor.workspace import capture

                log = capture.start()
                print(f"Ctrl+Alt+C now captures the clipboard to {log}")
            elif command == "/stats":
                from ghostcursor.workspace.research import _trace_path
                from ghostcursor.workspace.session import measures

                for name, value in measures(
                    brain, workspace.root, _trace_path()
                ).items():
                    print(f"{name}: {value}")
            elif command == "/brain":
                print(brain_command(brain, rest.split()))
            elif command in ("/providers", "/accounts"):
                print(providers_status(workspace.gateway, rest.split()))
            elif command == "/doctor":
                from ghostcursor import doctor

                print(doctor.report())
            elif command == "/know":
                print(
                    know_command(workspace.knowledge, workspace.kb_scope, rest.split())
                )
            elif command == "/agent":
                parts = rest.split(maxsplit=1)
                verb = parts[0] if parts else "list"
                if verb == "new" and len(parts) == 2:
                    spec = workspace.create_agent(parts[1])
                    print(
                        spec.as_text()
                        if spec
                        else "No agent: the model is not available."
                    )
                elif verb == "save":
                    try:
                        print(f"saved {workspace.save_agent().name}")
                    except ValueError as exc:
                        print(exc)
                elif verb == "use" and len(parts) == 2:
                    bits = parts[1].split()
                    name = bits[0]
                    values = dict(kv.split("=", 1) for kv in bits[1:] if "=" in kv)
                    try:
                        spec = workspace.use_agent(name, values)
                        print(f"using {spec.name}: {workspace.goal}")
                    except ValueError as exc:
                        print(exc)
                elif verb == "list":
                    saved = workspace.agents()
                    print(
                        "\n".join(f"- {s.name}: {s.description}" for s in saved)
                        or "no agents yet"
                    )
                else:
                    print("usage: /agent new <need> | save | use <name> [k=v] | list")
            elif command == "/web":
                from ghostcursor.harness import browser

                target = rest.strip()
                if target and not target.startswith(("http://", "https://")):
                    target = "https://" + target
                try:
                    if web["browser"] is None:
                        web["browser"] = browser.Browser.launch("about:blank")
                    page = web["browser"].page()
                    if target:
                        page.navigate(target)
                    controls = page.controls()
                    page.close()
                    print(
                        "\n".join(f"  [{c.role}] {c.name}" for c in controls[:40])
                        or "(no named controls on the page)"
                    )
                    print(f"({len(controls)} controls; read-only)")
                except Exception as exc:
                    print(f"browser unavailable: {exc}")
            elif command.startswith("/"):
                from ghostcursor.workspace import palette

                near = palette.suggest(command)
                if near:
                    shown = ", ".join(palette.highlight(command, c) for c in near)
                    print(f"Unknown command {command}. Did you mean {shown}?")
                else:
                    print(__doc__)
            else:
                from ghostcursor.workspace import palette

                sum_ = palette.calc(line)
                print(sum_ if sum_ is not None else workspace.discuss(line))
    finally:
        if web["browser"] is not None:
            web["browser"].close()
        brain.close()
        workspace.knowledge.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

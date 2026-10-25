"""The workspace app (D178):  py -3.12 -m ghostcursor.workspace.app <topic>

The console workspace (D173) as a docked window: a local page served on
127.0.0.1 and shown by Edge in app mode, so no new dependency. The page is a
view; everything it does goes through the same ``Workspace`` the console uses.

Trust boundary: any local process or web page can reach 127.0.0.1, so every
request must carry the per-launch token and the exact Host (no DNS
rebinding), and every API call is a JSON POST (a cross-site form cannot send
one without a preflight this server never answers). Window handles stay in
this process; the page sees window numbers only. Act uses the same approved
plan and observed-control harness as the console path.
"""

from __future__ import annotations

import ghostcursor.overlay.dpi  # noqa: F401  (rule 4: before any overlay)

import hmac
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ghostcursor import policy, settings
from ghostcursor.brief import brief_path
from ghostcursor.workspace.contracts import POINT_PREFIX

PAGE = Path(__file__).with_name("app.html")
MAX_BODY = 64 * 1024
QUIT_AFTER_S = (
    90.0  # no poll this long: the window is closed (a hidden tab polls ~1/min)
)
APP_TITLE = "Orbyn"  # the page's <title>; its window is never offered for binding
EDGE = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / (
    r"Microsoft\Edge\Application\msedge.exe"
)
ACTIVITY_LABELS = frozenset(
    {
        "Signing in",
        "Thinking",
        "Researching",
        "Asking file",
        "Exploring",
        "Planning",
        "Designing the agent",
        "Saving the agent",
        "Starting the agent",
        "Handing off",
        "Opening",
        "Editing plan",
        "Pointing",
        "Saving point",
        "Acting",
        "Guiding",
        "Listening",
        "Brain",
        "Counting",
        "Work",
    }
)
ACTIVITY_STATES = frozenset(
    {"running", "finished", "stopped", "failed", "interrupted"}
)


class App:
    """One worker thread owns the Workspace and its Brain (sqlite is
    single-thread); request threads only queue jobs and set events."""

    def __init__(self, topic: str, *, make_workspace=None):
        self.jobs = ThreadPoolExecutor(1, thread_name_prefix="orbyn-workspace")
        self.signal = threading.Event()  # Enter / "Done" from the page
        self.stop = threading.Event()  # the page's Stop button
        self.status: deque[str] = deque(maxlen=40)
        self.busy = ""
        self._claim = threading.Lock()
        self.windows: list = []  # the last bindable list; the page sees indexes
        self.pending_point = None
        self.memories: list[dict] = []
        self.seen = time.monotonic()  # the page's last poll
        self.paused = False
        self.downloads = Path.home() / "Downloads"  # where a handoff is saved
        self.ws = self.jobs.submit(
            make_workspace or (lambda: _default_workspace(topic))
        ).result()
        self.activity_path = brief_path(self.ws.root, self.ws.topic).with_suffix(
            ".activity.json"
        )
        self.activity = self._load_activity()
        if any(row["state"] == "running" for row in self.activity):
            for row in self.activity:
                if row["state"] == "running":
                    row["state"] = "interrupted"
            self._save_activity()
        self.jobs.submit(self._refresh).result()

    # --- worker-side ------------------------------------------------------------

    def _load_activity(self) -> list[dict[str, str]]:
        try:
            if self.activity_path.stat().st_size > 64 * 1024:
                raise ValueError("activity history too large")
            rows = json.loads(self.activity_path.read_text(encoding="utf-8"))
            if not isinstance(rows, list) or any(
                not isinstance(row, dict)
                or not isinstance(row.get("label"), str)
                or not isinstance(row.get("state"), str)
                or row.get("label") not in ACTIVITY_LABELS
                or row.get("state") not in ACTIVITY_STATES
                or set(row) != {"label", "state"}
                for row in rows
            ):
                raise ValueError("invalid activity history")
            return rows[-20:]
        except FileNotFoundError:
            return []
        except (OSError, ValueError, UnicodeError, RecursionError):
            self.activity_path = None  # keep an unreadable file intact
            self.say("Activity history could not be read; this session stays in memory.")
            return []

    def _save_activity(self) -> None:
        if self.activity_path is None:
            return
        partial = None
        try:
            self.activity_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.activity_path.parent,
                prefix=self.activity_path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as output:
                partial = Path(output.name)
                json.dump(self.activity, output)
            os.replace(partial, self.activity_path)
        except OSError:
            self.activity_path = None
            self.say("Activity history could not be saved; this session stays in memory.")
        finally:
            if partial is not None:
                try:
                    partial.unlink(missing_ok=True)
                except OSError:
                    pass

    def _refresh(self) -> None:
        brain = self.ws.brain
        self.memories = [
            {
                k: v
                for k, v in asdict(m).items()
                if k in ("mid", "kind", "text", "scope", "origin")
            }
            for m in brain.list()
        ]
        self.plan_memories = [  # read here: sqlite belongs to this thread
            m.text for m in map(brain.get, self.ws.plan_memories) if m is not None
        ]
        self.paused = brain.paused

    def run(self, label: str, fn):
        """Run ``fn`` on the worker; one long job at a time (the page waits)."""

        # Claimed on the request thread, so a second request is refused, not
        # queued, and a Stop pressed before the job starts is kept.
        if not self._claim.acquire(blocking=False):
            raise ValueError(f"busy: {self.busy}")
        self.busy = label
        self.signal.clear()
        self.stop.clear()
        safe_label = label if isinstance(label, str) and label in ACTIVITY_LABELS else "Work"
        row = {"label": safe_label, "state": "running"}
        self.activity.append(row)
        self.activity = self.activity[-20:]
        self._save_activity()

        def job():
            try:
                return fn()
            finally:
                self._refresh()

        try:
            result = self.jobs.submit(job).result()
            row["state"] = "stopped" if self.stop.is_set() else "finished"
            return result
        except BaseException:
            row["state"] = "failed"
            raise
        finally:
            self._save_activity()
            self.busy = ""
            self._claim.release()

    def say(self, line: str) -> None:
        self.status.append(str(line)[:300])

    def heard(self, text: str) -> None:
        """A spoken request ("Hey Bro ..." or the hotkey, D182): a message to
        Orbyn, like typing it. Never acts on its own."""

        if self.busy:
            self.say(f"Heard you, but Orbyn is busy: {self.busy}")
            return
        self.say(f"Heard: {text}")

        def send():
            try:
                self.handle("say", {"text": text})
            except Exception as exc:
                self.say(f"Could not send: {exc}")

        threading.Thread(target=send, daemon=True).start()

    def signalled(self) -> bool:
        if self.signal.is_set():
            self.signal.clear()
            return True
        return False

    def hwnds(self, numbers) -> list[int]:
        chosen = [
            self.windows[n].hwnd
            for n in numbers
            if isinstance(n, int) and 0 <= n < len(self.windows)
        ]
        if not chosen:
            raise ValueError("choose at least one window")
        return chosen

    # --- the page's view --------------------------------------------------------

    def state(self) -> dict:
        ws = self.ws
        proposal = ws.proposal
        return {
            "topic": ws.topic,
            "goal": ws.goal,
            "turns": [{"speaker": t.speaker, "text": t.text} for t in ws.turns[-200:]],
            "plan": None
            if proposal is None
            else {
                "revision": proposal.revision,
                "steps": [s.instruction for s in proposal.plan.steps],
            },
            "memories": self.memories,
            "suggest": ws.suggestion,
            "ideas": [
                {
                    "title": i.title,
                    "summary": i.summary,
                    "assumptions": list(i.assumptions),
                    "unknowns": list(i.unknowns),
                }
                for i in ws.ideas
            ],
            "plan_memories": self.plan_memories,
            "agents": [
                {"name": a.name, "description": a.description} for a in ws.agents()
            ],
            "draft_agent": ws.draft_agent.as_text() if ws.draft_agent else "",
            "paused": self.paused,
            "busy": self.busy,
            "activity": list(reversed(self.activity)),
            "status": list(self.status),
            "research": len(ws.research_graphs),
            "point_prefix": POINT_PREFIX,
            "vision": settings.jev_vision(),
            "egress": policy.max_egress(),  # D180: set by the organisation
            "managed": policy.managed(),
        }

    # --- actions ----------------------------------------------------------------

    def handle(self, action: str, body: dict):
        ws = self.ws
        text = str(body.get("text", "")).strip()
        if action == "state":
            self.seen = time.monotonic()
            return self.state()
        if action == "signal":
            self.signal.set()
            return {}
        if action == "stop":
            self.stop.set()
            return {}
        if action == "vision":
            # The user's own switch (D179); read when the next Teach starts.
            settings.set_jev_vision(body.get("on") is True)
            return {}
        if action == "accounts":  # presence only, never a key (D182)
            from ghostcursor.providers import chatgpt, clients, keys

            return {
                "chatgpt": chatgpt.signed_in(chatgpt.load()),
                "keys": {name: keys.get_key(name) is not None for name in clients.BYOK},
            }
        if action in ("key_set", "key_clear"):
            from ghostcursor.providers import clients, keys

            name = str(body.get("name", ""))
            if name not in clients.BYOK:
                raise ValueError("unknown provider")
            if action == "key_clear":
                keys.delete_key(name)
                return {}
            key = str(body.get("key", "")).strip()
            if not 8 <= len(key) <= 400 or any(c.isspace() for c in key):
                raise ValueError("that does not look like an API key")
            keys.set_key(name, key)
            return {}
        if action == "chatgpt_sign_out":
            from ghostcursor.providers import chatgpt

            chatgpt.sign_out()
            return {}
        if action == "know_list":  # Company Brain review panel (D186)
            if ws.knowledge is None:
                return {"facts": []}
            status = body.get("status") or None
            now = ws.knowledge.clock()
            return {
                "facts": [
                    {
                        "fid": f.fid,
                        "text": f.text,
                        "status": f.status,
                        "source": f.source,
                        "superseded_by": f.superseded_by,
                        "expired": f.stale(now),  # past valid_until: no longer true
                        "sensitive": f.sensitivity == "sensitive",
                    }
                    for f in ws.knowledge.list(scope=ws.kb_scope, status=status)
                ]
            }
        if action == "know_edges":  # Context Graph relationships for the panel
            if ws.knowledge is None:
                return {"edges": []}
            now = ws.knowledge.clock()
            return {
                "edges": [
                    {
                        "eid": e.eid,
                        "subject": e.subject,
                        "predicate": e.predicate,
                        "object": e.object,
                        "source": e.source,
                        "status": e.status,
                        "expired": e.expired(now),
                        "sensitive": e.sensitivity == "sensitive",
                    }
                    for e in ws.knowledge.list_edges(scope=ws.kb_scope)
                ]
            }
        if action in ("know_review_edge", "know_expire_edge"):
            if ws.knowledge is None:
                raise ValueError("no Company Brain")
            eid = int(body.get("eid", 0))
            if ws.knowledge.edge(eid) is None:
                raise ValueError("no such edge")
            meth = "review_edge" if action == "know_review_edge" else "expire_edge"
            getattr(ws.knowledge, meth)(eid)
            return {"status": ws.knowledge.edge(eid).status}
        if action in ("know_classify", "know_classify_edge"):
            if ws.knowledge is None:
                raise ValueError("no Company Brain")
            sens = "sensitive" if body.get("sensitive") else "normal"
            if action == "know_classify_edge":
                eid = int(body.get("eid", 0))
                if ws.knowledge.edge(eid) is None:
                    raise ValueError("no such edge")
                ws.knowledge.classify_edge(eid, sens)
                return {"sensitive": ws.knowledge.edge(eid).sensitivity == "sensitive"}
            fid = int(body.get("fid", 0))
            if ws.knowledge.get(fid) is None:
                raise ValueError("no such fact")
            ws.knowledge.classify(fid, sens)
            return {"sensitive": ws.knowledge.get(fid).sensitivity == "sensitive"}
        if action in (
            "know_review",
            "know_approve",
            "know_retire",
            "know_verify",
            "know_expire",
        ):
            if ws.knowledge is None:
                raise ValueError("no Company Brain")
            fid = int(body.get("fid", 0))
            if ws.knowledge.get(fid) is None:
                raise ValueError("no such fact")
            getattr(ws.knowledge, action.split("_")[1])(fid)
            return {"status": ws.knowledge.get(fid).status}
        if action == "know_add":  # GUI capture: one action to note a fact (D186)
            if ws.knowledge is None:
                raise ValueError("no Company Brain")
            t = " ".join((body.get("text") or "").split())
            if not t:
                raise ValueError("nothing to add")
            f = ws.knowledge.add_candidate(
                t,
                source=(body.get("source") or "note").strip() or "note",
                scope=ws.kb_scope,
            )
            return {"fid": f.fid, "status": f.status}  # candidate until reviewed
        if action == "know_relate":  # GUI: add a relationship (candidate edge)
            if ws.knowledge is None:
                raise ValueError("no Company Brain")
            s = " ".join((body.get("subject") or "").split())
            p = " ".join((body.get("predicate") or "").split())
            o = " ".join((body.get("object") or "").split())
            if not (s and p and o):
                raise ValueError("need subject, predicate and object")
            e = ws.knowledge.relate(
                s,
                p,
                o,
                source=(body.get("source") or "note").strip() or "note",
                scope=ws.kb_scope,
                sensitivity="sensitive" if body.get("sensitive") else "normal",
            )
            return {"eid": e.eid, "status": e.status}  # candidate until reviewed
        if action == "know_private_source":  # register/list private sources (D186)
            if ws.knowledge is None:
                raise ValueError("no Company Brain")
            pat = " ".join((body.get("pattern") or "").split())
            if pat and body.get("remove"):
                ws.knowledge.unmark_source_sensitive(pat)
            elif pat:
                ws.knowledge.mark_source_sensitive(pat)
            return {
                "patterns": ws.knowledge.sensitive_sources(),
                "private_by_default": ws.knowledge.private_by_default(),
            }
        if action == "know_private_default":  # deny-on-unknown posture (D186)
            if ws.knowledge is None:
                raise ValueError("no Company Brain")
            if "on" in body:
                ws.knowledge.set_private_by_default(bool(body.get("on")))
            return {"private_by_default": ws.knowledge.private_by_default()}
        if action == "know_clip":  # GUI capture of the clipboard (owner-initiated)
            if ws.knowledge is None:
                raise ValueError("no Company Brain")
            return {"result": ws.clip_to_brain()}
        if action == "doctor":  # readiness self-check as JSON (agent-reach idea)
            from ghostcursor import doctor

            return {
                "checks": [
                    {"name": c.name, "ready": c.ready, "hint": c.hint}
                    for c in doctor.checks()
                ]
            }
        if action == "know_aging":  # usable facts nobody re-verified lately (D186)
            if ws.knowledge is None:
                return {"aging": []}
            return {
                "aging": [
                    {"fid": f.fid, "text": f.text}
                    for f in ws.knowledge.aging(ws.kb_scope)
                ]
            }
        if action == "know_export":  # readable Brain export to Downloads (D186)
            if ws.knowledge is None:
                raise ValueError("no Company Brain")
            md = ws.knowledge.export_markdown(ws.kb_scope)
            out = self.downloads / f"{ws.kb_scope}.company-brain.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(md, encoding="utf-8", newline="\n")
            return {"path": str(out)}
        if action == "know_conflicts":
            if ws.knowledge is None:
                return {"conflicts": []}
            return {
                "conflicts": [
                    {
                        "a": {"fid": a.fid, "text": a.text},
                        "b": {"fid": b.fid, "text": b.text},
                    }
                    for a, b in ws.knowledge.conflicts(ws.kb_scope)
                ]
            }
        if self.busy:
            raise ValueError(f"busy: {self.busy}")
        if action == "chatgpt_sign_in":
            from ghostcursor.providers import chatgpt

            self.run("Signing in", chatgpt.sign_in)
            return {}
        ws.suggestion = ""  # a suggestion is for the message just answered
        if action == "say":
            if not text:
                raise ValueError("say something")
            return {"reply": self.run("Thinking", lambda: ws.discuss(text))}
        if action == "research":
            if not text:
                raise ValueError("ask a question")
            return {"answer": self.run("Researching", lambda: ws.research(text))}
        if action == "ask_file":
            material = body.get("material")
            if not isinstance(body.get("text"), str) or not text or len(text) > 500:
                raise ValueError("ask a question under 500 characters")
            # shortcut: small text files only; add chunked retrieval for larger documents.
            if (
                not isinstance(material, str)
                or not material.strip()
                or len(material) > 8000
                or "\0" in material
            ):
                raise ValueError("choose a text file under 8,000 characters")
            return {"answer": self.run("Asking file", lambda: ws.ask(text, material))}
        if action == "evidence":
            return {"text": ws.evidence(int(body.get("n", 0)))}
        if action == "ideate":
            if not self.run("Exploring", ws.ideate):
                raise ValueError("No ideas: the model is not available.")
            return {}
        if action == "plan":
            idea = int(body.get("idea", 0) or 0)
            plan = self.run("Planning", lambda: ws.make_plan(idea))
            if plan is None:
                raise ValueError("No plan: the model is not available.")
            return {}
        if action == "agent_create":  # D183: draft a reusable agent from a need
            if not text:
                raise ValueError("say what the agent should do")
            if not self.run("Designing the agent", lambda: ws.create_agent(text)):
                raise ValueError("No agent: the model is not available.")
            return {}
        if action == "agent_save":
            return {"name": self.run("Saving the agent", ws.save_agent).name}
        if action == "agent_use":
            name = str(body.get("name", ""))
            values = body.get("values") if isinstance(body.get("values"), dict) else {}
            return {
                "name": self.run(
                    "Starting the agent", lambda: ws.use_agent(name, values)
                ).name
            }
        if action == "agent_delete":
            from ghostcursor.workspace import agents

            agents.delete(ws.root, str(body.get("name", "")))
            return {}
        if action == "handoff_export":
            from ghostcursor.workspace import handoff

            def save():
                text = handoff.export(ws, str(body.get("name", "")))
                out = self.downloads / f"{ws.topic}.orbyn-handoff.json"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text, encoding="utf-8", newline="\n")
                return str(out)

            return {"path": self.run("Handing off", save)}
        if action == "handoff_import":
            from ghostcursor.workspace import handoff

            data = str(body.get("data", ""))
            return {"from": self.run("Opening", lambda: handoff.receive(ws, data))}
        if action == "plan_edit":
            verb, args = (
                str(body.get("verb", "")),
                [str(a) for a in body.get("args", [])],
            )
            self.run("Editing plan", lambda: ws.edit_plan(verb, " ".join(args).split()))
            return {}
        if action == "windows":
            from ghostcursor.harness.binding import bindable_windows

            self.windows = [
                w for w in bindable_windows() if not w.title.startswith(APP_TITLE)
            ]
            return {
                "windows": [
                    {"n": n, "app": w.executable, "title": w.title[:80]}
                    for n, w in enumerate(self.windows)
                ]
            }
        if action == "point":
            hwnds = self.hwnds(body.get("windows", []))
            ref = self.run("Pointing", lambda: self._point(hwnds))
            if ref is None:
                raise ValueError("No point taken.")
            self.pending_point = ref
            return {"text": ref.as_text(), "alternatives": list(ref.alternatives)}
        if action == "point_keep":
            from ghostcursor.workspace.__main__ import confirm_reference

            ref, self.pending_point = self.pending_point, None
            if ref is None:
                raise ValueError("no point to keep")
            answer = str(body.get("answer", "x"))

            def keep():
                kept = confirm_reference(ref, answer)
                if kept is not None:
                    ws.point(kept)

            self.run("Saving point", keep)
            return {}
        if action in ("teach", "act"):
            from ghostcursor.workspace.__main__ import teach_seconds

            step = int(body.get("step", 0))
            seconds = teach_seconds([str(body.get("seconds", 300))])
            if seconds is None:
                raise ValueError("seconds must be a number from 1 to 3600")
            hwnds = self.hwnds(body.get("windows", []))
            plan = ws.teach_plan(step)
            deny = [str(d) for d in body.get("deny", []) if str(d).strip()]
            return {
                "result": self.run(
                    "Acting" if action == "act" else "Guiding",
                    lambda: self._teach(
                        step, plan, hwnds, seconds, action == "act", deny
                    ),
                )
            }
        if action == "voice":
            return {"draft": self.run("Listening", self._voice) or ""}
        if action == "brain":
            return {"text": self.run("Brain", lambda: self._brain(body))}
        if action == "stats":
            from ghostcursor.workspace.research import _trace_path
            from ghostcursor.workspace.session import measures

            return self.run(
                "Counting", lambda: measures(ws.brain, ws.root, _trace_path())
            )
        raise ValueError("unknown action")

    def _point(self, hwnds):
        from ghostcursor.harness.binding import bind
        from ghostcursor.harness.teach_live import (
            ABORTED,
            Observer,
            _escape_pressed,
            take_mark,
        )
        from ghostcursor.workspace.__main__ import reference_from

        observer = Observer(bind(hwnds))
        observer.start()
        try:
            mark = take_mark(
                observer,
                time.monotonic() + 120,
                escape=lambda: _escape_pressed() or self.stop.is_set(),
                enter=self.signalled,
                say=self.say,
            )
            frame = observer.latest()
            return (
                None
                if mark is ABORTED or frame is None
                else reference_from(mark, frame)
            )
        finally:
            observer.stop()

    def _teach(self, step, plan, hwnds, seconds, act=False, deny=()) -> str:
        from ghostcursor.harness.teach_live import run_model_teach

        outcome: list = []
        code = run_model_teach(
            self.ws.goal,
            hwnds,
            seconds=seconds,
            plan=plan,
            outcome=outcome,
            say=self.say,
            confirm=self.signalled,
            stop=self.stop.is_set,
            act=act,
            deny=deny,
        )
        return self.ws.record_teach(step, outcome, code)

    def _voice(self):
        from ghostcursor.harness.teach_live import _escape_pressed
        from ghostcursor.voice import dictate_goal

        # Enter/Done starts and ends; the draft goes to the composer for the
        # user to correct and send, so ``ask`` keeps it as is.
        return dictate_goal(
            time.monotonic() + 120,
            ask=lambda _prompt: "",
            enter=self.signalled,
            escape=lambda: _escape_pressed() or self.stop.is_set(),
        )

    def _brain(self, body) -> str:
        brain = self.ws.brain
        verb = str(body.get("verb", ""))
        mid = body.get("id")
        if verb == "forget" and isinstance(mid, int):
            return "forgotten" if brain.forget(mid) else "no such memory"
        if verb == "correct" and isinstance(mid, int):
            fixed = brain.correct(mid, str(body.get("text", "")))
            return (
                f"corrected as #{fixed.mid}" if fixed else "no such memory (or refused)"
            )
        if verb in ("pause", "resume"):
            brain.pause(verb == "pause")
            return f"learning {verb}d"
        if verb == "erase" and body.get("confirm") == "yes":
            brain.erase_all()
            return "erased"
        raise ValueError("unknown brain action")

    def close(self) -> None:
        self.stop.set()
        self.jobs.submit(self.ws.brain.close).result()
        self.jobs.shutdown()


def _default_workspace(topic: str):
    from ghostcursor.providers import Gateway
    from ghostcursor.workspace.brain import Brain
    from ghostcursor.workspace.knowledge import Knowledge
    from ghostcursor.workspace.session import Workspace

    return Workspace(topic, Gateway(), Brain(), knowledge=Knowledge())


def make_server(app: App, token: str, port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):  # the page's text never reaches a log
            pass

        def _allowed(self) -> bool:
            host_ok = self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"
            return host_ok

        def _send(self, code: int, body: bytes, kind: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'unsafe-inline'; "
                "style-src 'unsafe-inline'; connect-src 'self'; img-src data:; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path, _, query = self.path.partition("?")
            given = query[2:] if query.startswith("t=") else ""
            if (
                path != "/"
                or not self._allowed()
                or not hmac.compare_digest(given.encode(), token.encode())
            ):
                return self._send(404, b"", "text/plain")
            page = PAGE.read_text(encoding="utf-8").replace("__TOKEN__", token)
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self):
            given = self.headers.get("X-Orbyn-Token", "")
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            # Read the body even when refusing: closing with unread bytes
            # resets the connection instead of delivering the 403.
            raw = self.rfile.read(length) if 0 < length <= MAX_BODY else b""
            if (
                not self.path.startswith("/api/")
                or not self._allowed()
                or not hmac.compare_digest(given.encode(), token.encode())
                or self.headers.get("Content-Type") != "application/json"
                or not 0 <= length <= MAX_BODY
            ):
                return self._send(403, b"{}", "application/json")
            try:
                body = json.loads(raw or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("body must be an object")
                result, code = app.handle(self.path[5:], body), 200
            except (ValueError, PermissionError) as exc:
                result, code = {"error": str(exc)}, 400
            except Exception as exc:  # the page shows it; the app keeps running
                result, code = {"error": f"{type(exc).__name__}: {exc}"[:300]}, 500
            self._send(code, json.dumps(result).encode("utf-8"), "application/json")

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def open_window(url: str) -> None:
    """Edge in app mode, docked right like a sidebar; any browser otherwise."""

    if not EDGE.exists():
        import webbrowser

        webbrowser.open(url)
        return
    import win32api

    width = 460
    screen_w = win32api.GetSystemMetrics(0)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    subprocess.Popen(
        [
            str(EDGE),
            f"--app={url}",
            f"--user-data-dir={Path(base) / 'GhostCursor' / 'app-profile'}",
            f"--window-size={width},860",
            f"--window-position={max(0, screen_w - width - 16)},24",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
        ]
    )


def _lock_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "GhostCursor" / "app.lock"


def _live_instance_url() -> str | None:
    """The URL of an Orbyn already serving on this machine, or None.

    Single-instance guard: double-clicking the app while it is running must
    re-open its window, not silently start a second server behind a locked Edge
    profile (which showed nothing). The lock holds the running instance's URL;
    an instance is "live" only if its port still accepts a connection -- a stale
    lock from a crashed run fails the check and a fresh instance takes over.
    """
    try:
        url = _lock_path().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not url.startswith("http://127.0.0.1:"):
        return None
    try:
        port = int(url.split(":")[2].split("/")[0])
    except (ValueError, IndexError):
        return None
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return url
    except OSError:
        return None


def _write_lock(url: str) -> None:
    try:
        p = _lock_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(url, encoding="utf-8")
    except OSError:
        pass  # a read-only FS just loses the single-instance guard; never fatal


def _clear_lock() -> None:
    try:
        _lock_path().unlink()
    except OSError:
        pass


def _ensure_ollama() -> None:
    """Best-effort: if the local model server is installed but not answering,
    start it so planning/Teach work on first launch instead of reporting
    'model unavailable'. Local only (127.0.0.1:11434); never fatal, never waits."""

    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=1):
            return  # already serving
    except OSError:
        pass

    exe = shutil.which("ollama")
    if not exe:
        return  # not installed; the UI already reports model-unavailable cleanly
    try:
        subprocess.Popen(
            [exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("--version", "-v"):
        from ghostcursor import __version__

        print(f"Orbyn {__version__}")
        return 0
    if argv and argv[0] in ("--help", "-h"):
        print(__doc__)
        return 0
    if len(argv) > 1:  # at most one topic; no arg opens the default workspace
        print(__doc__)
        return 2
    existing = _live_instance_url()
    if existing is not None:  # already running: re-open its window, don't double-start
        open_window(existing)
        return 0
    _ensure_ollama()  # start the local model if it is installed but not running
    app = App(argv[0] if argv else "workspace")
    token = secrets.token_urlsafe(32)
    server = make_server(app, token)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/?t={token}"
    _write_lock(url)
    open_window(url)
    listener = None
    wake, hotkey = settings.listening()
    if wake or hotkey:
        from ghostcursor.listen import Listener

        listener = Listener(app.heard, say=app.say, hotkey=hotkey, wake=wake)
        listener.start()
        app.say(
            'Say "Hey Bro" or press '
            + (hotkey or "the hotkey (off)").title()
            + " to talk to Orbyn."
        )
    try:
        # The page polls while it is open; closing it ends the app. A long
        # job (Teach) keeps it alive until the job ends.
        while app.busy or time.monotonic() - app.seen < QUIT_AFTER_S:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if listener is not None:
            listener.stop()
        server.shutdown()
        app.close()
        _clear_lock()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The workspace app (D178):  py -3.12 -m ghostcursor.workspace.app [--window|--dock] <topic>  |  --ask-file <path>

The console workspace (D173) as a small desktop island with an optional full
window: a local page served on 127.0.0.1 and shown by Edge in app mode. The page is a
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
import math
import os
import re
import secrets
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

from ghostcursor import policy, redact, settings
from ghostcursor.brief import brief_path
from ghostcursor.workspace import connectors
from ghostcursor.workspace.agents import notes as agent_notes
from ghostcursor.workspace.contracts import POINT_PREFIX
from ghostcursor.workspace.github import GitHubConnector

PAGE = Path(__file__).with_name("app.html")
MAX_FILE_CHARS = 100_000
MAX_FILE_BYTES = 400 * 1024


def read_text_file(path: str) -> tuple[str, str]:
    """(file name, text) of a text file the user right-clicked, with Ask a
    file's limits; ValueError for anything else. Read locally; nothing is sent
    until the user asks a question about it."""

    file = Path(path)
    try:
        if not file.is_file() or file.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("choose a text file under 400 KB")
        text = file.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("that file is not UTF-8 text") from None
    except OSError:
        raise ValueError("that file could not be read") from None
    if not text.strip() or len(text) > MAX_FILE_CHARS or "\0" in text:
        raise ValueError("choose a text file under 100,000 characters")
    return file.name[:120], text


MAX_BODY = 512 * 1024  # a 100,000-character file in JSON
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
        "Deep research",
        "Running a crew",
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
        "Extracting facts",
        "Counting",
        "Work",
    }
)
CONNECTOR_ACTIONS = frozenset(
    {
        "calendar_connect",
        "calendar_disconnect",
        "calendar_agenda",
        "mail_connect",
        "mail_disconnect",
        "mail_unread",
        "mail_to_brain",
    }
)
#: Background job kinds -> activity label. All read-only (no Act).
JOB_KINDS = {
    "research": "Researching",
    "deep": "Deep research",
    "crew": "Running a crew",
}
ACTIVITY_STATES = frozenset({"running", "finished", "stopped", "failed", "interrupted"})
ROUTINE_SECONDS = {"hourly": 3600, "daily": 86400, "weekdays": 86400, "weekly": 604800}


def suggested_routines(
    jobs: list[dict], routines: list[dict], dismissed=()
) -> list[str]:
    """Research questions asked at least twice in the job inbox that are not
    routines yet: HeyClicky's proactive suggestions, from Orbyn's own local
    history instead of watching the screen. Only offered; nothing runs until
    the user makes it a routine."""

    def key(text: str) -> str:
        return " ".join(str(text).casefold().split())

    taken = {key(r["question"]) for r in routines} | {key(d) for d in dismissed}
    counts, first = {}, {}
    for job in jobs:
        if job.get("kind", "research") != "research" or job.get("routine"):
            continue
        k = key(job["question"])
        counts[k] = counts.get(k, 0) + 1
        first.setdefault(k, job["question"])
    return [first[k] for k, n in counts.items() if n >= 2 and k not in taken][:3]


def next_due(cadence: str, now: float) -> float:
    """When a routine runs next: one period on, and for ``weekdays`` the next
    Monday-to-Friday day in local time (HeyClicky and Aside schedule the same)."""

    due = now + ROUTINE_SECONDS[cadence]
    while cadence == "weekdays" and time.localtime(due).tm_wday >= 5:
        due += 86400
    return due


def _claims(answer: str) -> list[str]:
    # A rendered answer lists claims as "- text (status) [s1][s2]"; source ids
    # are renumbered every run, so compare the claim text without them.
    return [
        re.sub(r"(\s*\[s\d+\])+$", "", line[2:]).strip()
        for line in answer.splitlines()
        if line.startswith("- ")
    ]


def _same_claim(a: str, b: str) -> bool:
    # A reworded claim is the same claim; a changed number never is.
    from rapidfuzz import fuzz

    numbers = lambda s: set(re.findall(r"\d+(?:[.,]\d+)*", s))
    return (
        numbers(a) == numbers(b)
        and fuzz.token_set_ratio(a.casefold(), b.casefold()) >= 90
    )


def new_claims(answer: str, previous: str) -> list[str]:
    """Claims in a routine's answer that its previous run did not make (as in
    HeyClicky routines: later runs report what changed). Matched on this
    computer only; nothing extra is sent to a model."""

    seen = _claims(previous)
    return [c for c in _claims(answer) if not any(_same_claim(c, s) for s in seen)]


def _tail_lines(path: Path, count: int, chunk: int = 256 * 1024) -> list[str]:
    """The last ``count`` lines of a log, reading only its end, so the receipt
    stays quick however long the log grows. Raises OSError like read_text."""

    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        start = max(0, size - chunk)
        handle.seek(start)
        data = handle.read()
    lines = data.decode("utf-8", "replace").splitlines()
    if start > 0:
        lines = lines[1:]  # the first line is probably cut in half
    return lines[-count:]


def _agent_goals() -> list[dict]:
    """Suggestions waiting for the person (never acted on here)."""

    try:
        from ghostcursor.workspace import agent_inbox

        return [
            {"id": r["id"], "goal": str(r.get("goal", ""))[:300], "why": str(r.get("why", ""))[:200]}
            for r in agent_inbox.waiting()
        ]
    except Exception:
        return []


_last_error_log = [0.0]


def _note_request_error(now=None, gap_s: float = 60.0) -> bool:
    """At most one request-error log a minute, so a request that fails on
    every poll cannot fill the disk."""

    now = time.monotonic() if now is None else now
    if now - _last_error_log[0] < gap_s:
        return False
    _last_error_log[0] = now
    return True


def _fresh(folder: Path, stem: str, suffix: str) -> Path:
    """A new file name in ``folder`` that never overwrites an earlier export:
    stem-YYYYMMDD-HHMMSS.suffix, with -2, -3... if that exists too."""

    folder.mkdir(parents=True, exist_ok=True)
    # A name, never a path: no separators, no "..", whatever the stem holds.
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-") or "export"
    base = f"{safe}-{time.strftime('%Y%m%d-%H%M%S')}"
    n = 1
    while True:
        out = folder / (f"{base}{suffix}" if n == 1 else f"{base}-{n}{suffix}")
        try:  # created here, exclusively: two exports in one second never share it
            out.open("x").close()
            return out
        except FileExistsError:
            n += 1


def _local_model_up() -> bool:
    """Is the local model server (Ollama) accepting connections? A loopback
    connect only; nothing leaves this computer."""

    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=0.2):
            return True
    except OSError:
        return False


class App:
    """One worker thread owns the Workspace and its Brain (sqlite is
    single-thread); request threads only queue jobs and set events."""

    def __init__(self, topic: str, *, make_workspace=None, clock=time.time):
        self.clock = clock
        self.jobs = ThreadPoolExecutor(1, thread_name_prefix="orbyn-workspace")
        self.signal = threading.Event()  # Enter / "Done" from the page
        self.stop = threading.Event()  # the page's Stop button
        self.status: deque[str] = deque(maxlen=40)
        self._codes: dict[str, float] = {}  # one-time launch codes -> expiry
        self._rating: str | None = None  # Right/Wrong on the pointer shown
        self._speaker = None  # read-aloud voice, made on first use
        self._codes_lock = threading.Lock()
        self.busy = ""
        self._claim = threading.Lock()
        self.windows: list = []  # the last bindable list; the page sees indexes
        self.pending_point = None
        self.memories: list[dict] = []
        self.seen = time.monotonic()  # the page's last poll
        self.voice_to = None  # the island's voice(text), when it is shown
        #: A file handed over by "Ask Orbyn about this file" (name, text),
        #: waiting for the page to open it. In memory only; taken once.
        self.offered_file: tuple[str, str] | None = None
        self.paused = False
        self.downloads = Path.home() / "Downloads"  # where a handoff is saved
        self.skills_dir = None  # saved workflows; None is the usual folder
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
        self._job_lock = threading.RLock()
        self.background_id: str | None = None
        self.quit_requested = threading.Event()
        self.github = GitHubConnector()
        self.job_path = brief_path(self.ws.root, self.ws.topic).with_suffix(
            ".jobs.json"
        )
        self.background_jobs = self._load_background_jobs()
        if any(row["state"] == "running" for row in self.background_jobs):
            for row in self.background_jobs:
                if row["state"] == "running":
                    row["state"], row["ended"] = "interrupted", self.clock()
            self._save_background_jobs()
        self.routine_path = brief_path(self.ws.root, self.ws.topic).with_suffix(
            ".routines.json"
        )
        self.routines = self._load_routines()
        self.companion_idle = settings.companion_idle()  # the island reads it live
        self.dismissed_suggestions: set[str] = set()  # this session only
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
            self.say(
                "Activity history could not be read; this session stays in memory."
            )
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
            self.say(
                "Activity history could not be saved; this session stays in memory."
            )
        finally:
            if partial is not None:
                try:
                    partial.unlink(missing_ok=True)
                except OSError:
                    pass

    def _load_background_jobs(self) -> list[dict]:
        try:
            if self.job_path.stat().st_size > 1024 * 1024:
                raise ValueError("job inbox too large")
            rows = json.loads(self.job_path.read_text(encoding="utf-8"))
            keys = {"id", "question", "answer", "state", "created", "ended", "routine"}
            if not isinstance(rows, list) or any(
                not isinstance(row, dict)
                or set(row) - {"pinned", "archived", "kind"} != keys
                or row.get("kind", "research") not in JOB_KINDS
                or not isinstance(row.get("pinned", False), bool)
                or not isinstance(row.get("archived", False), bool)
                or not isinstance(row["id"], str)
                or len(row["id"]) != 16
                or any(c not in "0123456789abcdef" for c in row["id"])
                or not isinstance(row["question"], str)
                or len(row["question"]) > 500
                or not isinstance(row["answer"], str)
                or len(row["answer"]) > 24_000
                or not isinstance(row["state"], str)
                or row["state"] not in ACTIVITY_STATES
                or not isinstance(row["created"], (int, float))
                or row["ended"] is not None
                and not isinstance(row["ended"], (int, float))
                or not isinstance(row["routine"], str)
                or len(row["routine"]) > 16
                for row in rows
            ):
                raise ValueError("invalid job inbox")
            for row in rows:
                row.setdefault("pinned", False)
                row.setdefault("archived", False)
                row.setdefault("kind", "research")
            return rows[-20:]
        except FileNotFoundError:
            return []
        except (OSError, ValueError, UnicodeError, RecursionError):
            self.job_path = None
            self.say("Job inbox could not be read; this session stays in memory.")
            return []

    def _save_background_jobs(self) -> None:
        if self.job_path is None:
            return
        partial = None
        try:
            self.job_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.job_path.parent,
                prefix=self.job_path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as output:
                partial = Path(output.name)
                json.dump(self.background_jobs, output)
            os.replace(partial, self.job_path)
        except OSError:
            self.job_path = None
            self.say("Job inbox could not be saved; this session stays in memory.")
        finally:
            if partial is not None:
                try:
                    partial.unlink(missing_ok=True)
                except OSError:
                    pass

    def _load_routines(self) -> list[dict]:
        try:
            if self.routine_path.stat().st_size > 64 * 1024:
                raise ValueError("routine file too large")
            rows = json.loads(self.routine_path.read_text(encoding="utf-8"))
            if (
                not isinstance(rows, list)
                or len(rows) > 20
                or any(
                    not isinstance(row, dict)
                    or set(row) - {"failures"}
                    != {"id", "question", "cadence", "next_due", "enabled"}
                    or type(row.get("failures", 1)) is not int
                    or not 1 <= row.get("failures", 1) <= 64
                    or not isinstance(row["id"], str)
                    or len(row["id"]) != 16
                    or any(c not in "0123456789abcdef" for c in row["id"])
                    or not isinstance(row["question"], str)
                    or not 1 <= len(row["question"]) <= 500
                    or row["cadence"] not in ROUTINE_SECONDS
                    or not isinstance(row["next_due"], (int, float))
                    or not math.isfinite(row["next_due"])
                    or not isinstance(row["enabled"], bool)
                    for row in rows
                )
            ):
                raise ValueError("invalid routine file")
            return rows
        except FileNotFoundError:
            return []
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
            self.routine_path = None
            self.say("Routines could not be read; this session stays in memory.")
            return []

    def _save_routines(self) -> bool:
        if self.routine_path is None:
            return False
        partial = None
        try:
            self.routine_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.routine_path.parent,
                prefix=self.routine_path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as output:
                partial = Path(output.name)
                json.dump(self.routines, output)
            os.replace(partial, self.routine_path)
            return True
        except OSError:
            self.routine_path = None
            self.say("Routines could not be saved; this session stays in memory.")
            return False
        finally:
            if partial is not None:
                try:
                    partial.unlink(missing_ok=True)
                except OSError:
                    pass

    def has_enabled_routines(self) -> bool:
        with self._job_lock:
            return any(row["enabled"] for row in self.routines)

    def tick_routines(self) -> None:
        if self.busy or self.quit_requested.is_set():
            return
        now = self.clock()
        with self._job_lock:
            due = next(
                (
                    row
                    for row in self.routines
                    if row["enabled"] and row["next_due"] <= now
                ),
                None,
            )
            if due is None:
                return
            missed = due["next_due"]
            due["next_due"] = next_due(due["cadence"], now)
            if not self._save_routines():
                due["enabled"] = False
                self.say(
                    "A routine was paused because its next time could not be saved."
                )
                return
            try:
                self.start_research_job(due["question"], routine=due["id"])
            except ValueError:  # another request claimed the worker: still due,
                due["next_due"] = missed  # so the next free tick runs it, not
                self._save_routines()  # the next period
                return

    def _routine_retry(self, rid: str, failed: bool) -> None:
        """A failed routine run (a network blip) retries in 5, 10, 20... minutes,
        capped at an hour and never later than its next period, instead of
        waiting a whole period. Caller holds _job_lock."""

        row = next((r for r in self.routines if r["id"] == rid), None)
        if row is None:
            return
        if not failed:
            if row.pop("failures", None) is not None:
                self._save_routines()
            return
        # the count is saved with the routine, so a restart keeps the backoff
        row["failures"] = min(row.get("failures", 0) + 1, 64)
        if not row["enabled"]:
            self._save_routines()
            return
        wait = min(300 * 2 ** (row["failures"] - 1), 3600)
        row["next_due"] = min(row["next_due"], self.clock() + wait)
        self._save_routines()

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

    def _begin_run(self, label: str, fn):
        # Claimed on the request thread, so a second request is refused, not
        # queued, and a Stop pressed before the job starts is kept.
        if not self._claim.acquire(blocking=False):
            raise ValueError(f"busy: {self.busy}")
        self.stop.clear()
        if self.quit_requested.is_set():
            self._claim.release()
            raise ValueError("Orbyn is quitting")
        self.busy = label
        self.signal.clear()
        safe_label = (
            label if isinstance(label, str) and label in ACTIVITY_LABELS else "Work"
        )
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
            return self.jobs.submit(job), row
        except BaseException:
            row["state"] = "failed"
            self._save_activity()
            self.busy = ""
            self._claim.release()
            raise

    def _finish_run(self, future, row):
        try:
            result = future.result()
            row["state"] = "stopped" if self.stop.is_set() else "finished"
            return result
        except BaseException:
            row["state"] = "stopped" if self.stop.is_set() else "failed"
            raise
        finally:
            self._save_activity()
            self.busy = ""
            self.background_id = None
            self._claim.release()

    def run(self, label: str, fn):
        """Run ``fn`` on the worker; one long job at a time (the page waits)."""

        future, row = self._begin_run(label, fn)
        return self._finish_run(future, row)

    def start_research_job(
        self, question: str, *, routine: str = "", kind: str = "research"
    ) -> str:
        """A background job (HeyClicky "Jobs", read-only here): cited research,
        deep research (files cited claims to the Brain as candidates), or a
        crew (whose plan steps only propose, rule 2). Stop lands between
        steps."""

        question = " ".join(question.split())
        if not question or len(question) > 500 or "\0" in question:
            raise ValueError("ask a research question under 500 characters")
        if kind not in JOB_KINDS:
            raise ValueError("unknown job kind")
        question = redact.scrub(question)[0][:500]
        jid = secrets.token_hex(8)
        entry = {
            "id": jid,
            "question": question,
            "answer": "",
            "state": "running",
            "created": self.clock(),
            "ended": None,
            "routine": routine,
            "pinned": False,
            "archived": False,
            "kind": kind,
        }
        stop = self.stop.is_set
        work = {
            "research": lambda: self.ws.research(
                question, cancelled=stop, record=False
            ),
            # Background jobs are read-only (CLAUDE.md): nothing filed to the
            # Brain, no skill, plan, brief or deck written behind the person.
            "deep": lambda: self.ws.deep_dive(
                question, cancelled=stop, file_to_brain=False
            ).as_text(),
            "crew": lambda: self.ws.crew(
                question, cancelled=stop, read_only=True
            ).as_text(),
        }[kind]
        future, row = self._begin_run(JOB_KINDS[kind], work)
        self.background_id = jid
        with self._job_lock:
            self.background_jobs.append(entry)
            if len(self.background_jobs) > 20:
                oldest = next(
                    (
                        i
                        for i, job in enumerate(self.background_jobs)
                        if not job["pinned"]
                    ),
                    0,
                )
                self.background_jobs.pop(oldest)
            self._save_background_jobs()

        def done(_):
            try:
                answer = self._finish_run(future, row)
            except BaseException:
                answer = ""
            with self._job_lock:
                entry["state"] = row["state"]
                entry["answer"] = (
                    redact.scrub(str(answer))[0][:24_000]
                    if row["state"] == "finished"
                    else ""
                )
                entry["ended"] = self.clock()
                self._save_background_jobs()
                if routine:
                    self._routine_retry(routine, row["state"] == "failed")

        future.add_done_callback(done)
        return jid

    #: A launch code opens the page once, within this many seconds.
    LAUNCH_CODE_S = 60

    def launch_code(self) -> str:
        """A one-time code for opening the page in a browser that keeps its
        history (no Edge): the URL it leaves behind no longer opens anything,
        unlike the page token."""

        code = secrets.token_urlsafe(24)
        now = self.clock()
        with self._codes_lock:
            for old in [c for c, until in self._codes.items() if until < now]:
                del self._codes[old]  # expired, never used
            self._codes[code] = now + self.LAUNCH_CODE_S
        return code

    def use_launch_code(self, code: str) -> bool:
        with self._codes_lock:
            until = self._codes.pop(code, None)
        return until is not None and self.clock() <= until

    def say(self, line: str) -> None:
        line = str(line)
        # The whole plan is shown before approval (rule 2): never cut it.
        self.status.append(line if line.startswith("Approve to let Orbyn do") else line[:300])

    def heard(self, text: str) -> None:
        """A spoken request ("Hey Bro ..." or the hotkey, D182): a message to
        Orbyn, like typing it. Never acts on its own."""

        if self.voice_to is not None:  # the island shows it and the reply on its card
            self.say(f"Heard: {text}")
            self.voice_to(text)
            return
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
        with self._job_lock:
            background_jobs = [dict(row) for row in reversed(self.background_jobs)]
            background_jobs.sort(key=lambda row: not row["pinned"])
            routines = [dict(row) for row in self.routines]
        done = sorted(
            (
                j
                for j in background_jobs
                if j["routine"] and j["state"] == "finished" and j["answer"]
            ),
            key=lambda j: j["ended"] or 0,
        )
        last: dict[str, str] = {}
        for job in done:
            if job["routine"] in last:
                job["new_claims"] = new_claims(job["answer"], last[job["routine"]])[:20]
            last[job["routine"]] = job["answer"]
        return {
            "offered_file": self.offered_file[0] if self.offered_file else "",
            "topic": ws.topic,
            "goal": ws.goal,
            "turns": [{"speaker": t.speaker, "text": t.text} for t in ws.turns[-200:]],
            "answered_by": getattr(ws.gateway, "last_answer_provider", None),
            "plan": None
            if proposal is None
            else {
                "revision": proposal.revision,
                "steps": [s.describe() for s in proposal.plan.steps],
            },
            "memories": self.memories,
            "company_brain_available": ws.knowledge is not None,
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
                {
                    "name": a.name,
                    "description": a.description,
                    "notes": agent_notes(ws.root, a.name)[-5:],
                }
                for a in ws.agents()
            ],
            "draft_agent": ws.draft_agent.as_text() if ws.draft_agent else "",
            "paused": self.paused,
            "busy": self.busy,
            "activity": list(reversed(self.activity)),
            "jobs": background_jobs,
            "routines": routines,
            "suggested_routines": suggested_routines(
                background_jobs, routines, self.dismissed_suggestions
            ),
            "github_connected": self.github.connected(),
            "calendar_connected": connectors.calendar_connected(),
            "mail_connected": connectors.mail_connected(),
            "background_id": self.background_id,
            "status": list(self.status),
            "research": len(ws.research_graphs),
            "point_prefix": POINT_PREFIX,
            "vision": settings.jev_vision(),
            # D187: offered only when IT named a gateway; the person opts in.
            "company_offered": policy.company_endpoint() is not None,
            "company_on": settings.company_gateway(),
            "crash_offered": policy.crash_endpoint() is not None,
            "crash_on": settings.crash_reports(),
            "companion_idle": self.companion_idle,
            "autostart": autostart_on(),
            "read_aloud": settings.read_aloud(),
            "autostart_possible": _packaged_exe() is not None,
            # Scrub private details before a cloud model: the person's
            # switch, or forced on by the organisation (never forced off).
            "redact": policy.redact_egress() or settings.redact_egress(),
            "redact_forced": policy.redact_egress(),
            "keep_secrets_hidden": settings.keep_secrets_hidden(),
            # Names no pattern can know; shown only on this computer's page.
            "private_terms": list(settings.own_private_terms()),
            # The person's own air gap: only a model on this computer answers.
            "local_only": settings.local_only(),
            # With the air gap on, is a model on this computer answering?
            # None: not asked (the switch is off).
            "local_ready": _local_model_up() if settings.local_only() else None,
            # Read-only access for another agent on this computer.
            "agent_access": settings.agent_access(),
            # Goals another agent suggested, waiting for the person.
            "agent_goals": _agent_goals(),
            "agent_command": f'"{sys.executable}" '
            + ("--agent-server" if getattr(sys, "frozen", False) else "-m ghostcursor.agent_server"),
            "private_terms_org": len(policy.private_terms()),
            "egress": policy.max_egress(),  # D180: set by the organisation
            "managed": policy.managed(),
            "org_egress": policy.org_max_egress(),
        }

    # --- actions ----------------------------------------------------------------

    def handle(self, action: str, body: dict):
        ws = self.ws
        text = body.get("text")
        text = text.strip() if isinstance(text, str) else ""
        if action == "read_aloud":  # say chat replies with Windows' voice
            settings.set_read_aloud(body.get("on") is True)
            if not settings.read_aloud() and self._speaker is not None:
                self._speaker.stop()
            return {}
        if action == "today":  # asked for, never polled: it may reach the calendar and mail
            return self.today()
        if action == "rate_step":  # the person's verdict on the pointer shown
            verdict = str(body.get("verdict", ""))
            if verdict not in ("right", "wrong"):
                raise ValueError("verdict is right or wrong")
            if self.busy != "Guiding":
                raise ValueError("nothing is being shown right now")
            self._rating = verdict
            return {}
        if action == "teach_ratings":
            from ghostcursor.harness import ratings

            return {"apps": ratings.summary()}
        if action == "new_chat":
            ws.new_chat()
            return {}
        if action == "launch_code":
            return {"code": self.launch_code()}
        if action == "state":
            self.seen = time.monotonic()
            return self.state()
        if action == "signal":
            self.signal.set()
            return {}
        if action == "offer_file":  # from a second Orbyn started by the shell verb
            name, material = body.get("name"), body.get("material")
            if (
                not isinstance(name, str) or not isinstance(material, str)
                or not material.strip() or len(material) > MAX_FILE_CHARS
                or "\0" in material
            ):  # fmt: skip
                raise ValueError("choose a text file under 100,000 characters")
            self.offered_file = (" ".join(name.split())[:120] or "file", material)
            return {}
        if action == "take_offered_file":
            offered, self.offered_file = self.offered_file, None
            return {"name": offered[0], "material": offered[1]} if offered else {}
        if action == "stop":
            self.stop.set()
            return {}
        if action == "job_start":
            question = body.get("question")
            if not isinstance(question, str):
                raise ValueError("ask a research question under 500 characters")
            kind = body.get("kind", "research")
            if not isinstance(kind, str):
                raise ValueError("unknown job kind")
            return {"id": self.start_research_job(question, kind=kind)}
        if action == "job_cancel":
            if body.get("id") != self.background_id or not self.background_id:
                raise ValueError("no such running job")
            self.stop.set()
            return {}
        if action == "job_delete":
            jid = body.get("id")
            with self._job_lock:
                row = next(
                    (item for item in self.background_jobs if item["id"] == jid), None
                )
                if row is None or row["state"] == "running":
                    raise ValueError("no such finished job")
                self.background_jobs.remove(row)
                self._save_background_jobs()
            return {}
        if action in ("job_pin", "job_archive"):
            field = "pinned" if action == "job_pin" else "archived"
            jid, selected = body.get("id"), body.get(field)
            if not isinstance(selected, bool):
                raise ValueError(
                    "choose whether to "
                    + ("keep" if field == "pinned" else "archive")
                    + " the result"
                )
            with self._job_lock:
                row = next(
                    (item for item in self.background_jobs if item["id"] == jid), None
                )
                if row is None or row["state"] != "finished" or not row["answer"]:
                    raise ValueError("no such finished result")
                if self.job_path is None:
                    raise ValueError("job inbox is unavailable")
                if (
                    field == "pinned"
                    and selected
                    and not row[field]
                    and sum(job["pinned"] for job in self.background_jobs) >= 5
                ):
                    raise ValueError("keep at most five results")
                previous = row[field]
                row[field] = selected
                self._save_background_jobs()
                if self.job_path is None:
                    row[field] = previous
                    raise ValueError("job inbox could not be saved")
            return {}
        if action == "routine_dismiss":
            question = body.get("question")
            if isinstance(question, str):
                self.dismissed_suggestions.add(question[:500])
            return {}
        if action == "routine_create":
            question, cadence = body.get("question"), body.get("cadence")
            if not isinstance(question, str) or cadence not in ROUTINE_SECONDS:
                raise ValueError("choose a research question and schedule")
            question = " ".join(question.split())
            if not question or len(question) > 500 or "\0" in question:
                raise ValueError("ask a research question under 500 characters")
            question = redact.scrub(question)[0][:500]
            with self._job_lock:
                if len(self.routines) >= 20:
                    raise ValueError("this workspace already has 20 routines")
                item = {
                    "id": secrets.token_hex(8),
                    "question": question,
                    "cadence": cadence,
                    "next_due": next_due(cadence, self.clock()),
                    "enabled": True,
                }
                self.routines.append(item)
                if not self._save_routines():
                    self.routines.remove(item)
                    raise ValueError("routine could not be saved")
            return {"id": item["id"]}
        if action in (
            "routine_pause",
            "routine_resume",
            "routine_delete",
            "routine_run",
        ):
            with self._job_lock:
                item = next(
                    (row for row in self.routines if row["id"] == body.get("id")), None
                )
                if item is None:
                    raise ValueError("no such routine")
                previous = dict(item)
                if action == "routine_delete":
                    self.routines.remove(item)
                elif action == "routine_pause":
                    item["enabled"] = False
                elif action == "routine_resume":
                    item["enabled"] = True
                    item["next_due"] = next_due(item["cadence"], self.clock())
                else:
                    return {
                        "id": self.start_research_job(
                            item["question"], routine=item["id"]
                        )
                    }
                if not self._save_routines():
                    if action == "routine_delete":
                        self.routines.append(item)
                    else:
                        item.update(previous)
                    raise ValueError("routine change could not be saved")
            return {}
        if action == "quit":
            self.quit_requested.set()
            self.stop.set()
            return {}
        if action == "github_connect":
            return {"login": self.github.connect(body.get("token"))}
        if action == "github_disconnect":
            self.github.disconnect()
            return {}
        if action == "github_repos":
            return {"repos": self.github.repos()}
        if action == "github_issues":
            name = body.get("name")
            if not isinstance(name, str):
                raise ValueError("choose a repository")
            return {"issues": self.github.issues(name)}
        if action in CONNECTOR_ACTIONS:  # read-only calendar/mail, never to a model
            from ghostcursor.workspace import connectors

            def words(key: str) -> str:
                value = body.get(key, "")
                return value if isinstance(value, str) else ""

            if action == "calendar_connect":
                return {"events": connectors.connect_calendar(words("url"))}
            if action == "mail_connect":
                connectors.connect_mail(words("host"), words("user"), words("password"))
                return {}
            if action == "calendar_disconnect":
                connectors.disconnect_calendar()
                return {}
            if action == "mail_disconnect":
                connectors.disconnect_mail()
                return {}
            if action == "calendar_agenda":
                days = body.get("days", 1)
                return {
                    "events": connectors.agenda(
                        days=days if isinstance(days, int) else 1
                    )
                }
            if action == "mail_to_brain":  # one picked message -> candidate facts
                if ws.knowledge is None:
                    raise ValueError("no Company Brain")
                from ghostcursor.workspace.knowledge import chunk_document

                subject, text = connectors.message_text(
                    str(body.get("id") or ""), str(body.get("subject") or "")
                )
                did = [
                    result
                    for result, _fid in ws.knowledge.ingest(
                        chunk_document(text),
                        source=("mail: " + subject)[:120],
                        scope=ws.kb_scope,
                        episode=text,
                    )
                ]
                return {"added": did.count("added"), "duplicates": did.count("duplicate")}
            return {"mail": connectors.unread()}
        if action == "autostart":  # start with Windows: a Startup shortcut, the person's choice
            set_autostart(body.get("on") is True)
            return {"on": autostart_on()}
        if action == "companion_idle":  # a resting dot beside the pointer
            self.companion_idle = body.get("on") is True
            settings.set_companion_idle(self.companion_idle)
            return {}
        if action == "crash_reports":  # the person's own opt-in (D191)
            settings.set_crash_reports(body.get("on") is True)
            return {}
        if action == "egress_log":  # the receipt: what left, never its content
            from ghostcursor.providers import gateway as gateway_mod

            rows = []
            try:
                log = getattr(ws.gateway, "log_path", None)
                lines = _tail_lines(log or gateway_mod._default_log_path(), 200)
            except OSError:
                lines = []
            for line in reversed(lines):
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                images, hidden = row.get("images"), row.get("hidden")
                at, scrubbed = row.get("at"), row.get("scrubbed")
                rows.append(
                    {
                        "at": at if isinstance(at, (int, float)) and not isinstance(at, bool) else None,
                        "local": row.get("provider") in policy.LOCAL_PROVIDERS,
                        # None: an older line that did not record it.
                        "scrubbed": scrubbed if isinstance(scrubbed, bool) else None,
                        "provider": str(row.get("provider"))[:40],
                        "model": str(row.get("model"))[:80],
                        "failed": bool(row.get("failure")),
                        "images": images if isinstance(images, int) else 0,
                        # None: written before counts were kept, or the Jev
                        # channel, whose scrub keeps no count.
                        "hidden": hidden if isinstance(hidden, int) else None,
                    }
                )
                if len(rows) == 20:
                    break
            # Web searches and page reads, from the audit log (events only).
            from ghostcursor import audit

            audit.flush()
            try:
                events = _tail_lines(audit.default_path(), 400)
            except OSError:
                events = []
            for line in events:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if (
                    isinstance(row, dict)
                    and row.get("event") == "egress"
                    and row.get("provider") in ("web", "tavily", "duckduckgo", "agents", "updates")
                ):
                    at = row.get("at")
                    rows.append(
                        {
                            "at": at if isinstance(at, (int, float)) and not isinstance(at, bool) else None,
                            "web": {"web": "page", "agents": "agent", "updates": "update"}.get(row["provider"], "search"),
                            "provider": row["provider"],
                            "failed": bool(row.get("failure")),
                        }
                    )
            rows.sort(key=lambda r: r["at"] or 0, reverse=True)
            return {"requests": rows[:20]}
        if action == "private_terms":  # the person's own list; local only
            terms = body.get("terms")
            if not isinstance(terms, list) or not all(
                isinstance(t, str) for t in terms
            ):
                raise ValueError("terms must be a list of words")
            settings.set_private_terms(terms)
            return {"kept": len(settings.own_private_terms())}
        if action == "redact_preview":  # what a cloud model would get; nothing is sent
            text = body.get("text")
            if not isinstance(text, str) or len(text) > 20_000:
                raise ValueError("text must be at most 20,000 characters")
            shown, hidden = redact.scrub(text, terms=settings.private_terms())
            # Rule 7: with hiding off the text would go as typed; say so.
            return {
                "text": shown,
                "hidden": len(hidden),
                "on": policy.redact_egress() or settings.redact_egress(),
            }
        if action == "keep_secrets_hidden":  # only a literal true turns it on
            settings.set_keep_secrets_hidden(body.get("on") is True)
            return {}
        if action == "redact_egress":  # the person can add, never lower
            # Only an explicit false turns it off; anything else keeps it on.
            settings.set_redact_egress(body.get("on") is not False)
            return {}
        if action == "check_update":  # one public read, only when pressed
            from ghostcursor import updates

            return updates.check()
        if action in ("agent_goal_use", "agent_goal_dismiss"):
            from ghostcursor.workspace import agent_inbox

            sid = body.get("id")
            if not isinstance(sid, str) or not sid.isalnum() or len(sid) > 32:
                raise ValueError("choose a suggestion")
            found = agent_inbox.take(sid)
            if found is None:
                raise ValueError("that suggestion is gone")
            # The goal goes to the message box only; the person reads and sends it.
            return {"goal": found["goal"]} if action == "agent_goal_use" else {}
        if action == "agent_access":  # opt-in; anything but true is off
            settings.set_agent_access(body.get("on") is True)
            return {}
        if action == "local_only":  # the person's own air gap (only lowers)
            if not isinstance(body.get("on"), bool):
                # Never switched off by a malformed request.
                raise ValueError("on must be true or false")
            settings.set_local_only(body["on"])
            return {}
        if action == "company_gateway":  # the person's own opt-in (D187)
            settings.set_company_gateway(body.get("on") is True)
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
            eid = _whole(body.get("eid"))
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
                eid = _whole(body.get("eid"))
                if ws.knowledge.edge(eid) is None:
                    raise ValueError("no such edge")
                ws.knowledge.classify_edge(eid, sens)
                return {"sensitive": ws.knowledge.edge(eid).sensitivity == "sensitive"}
            fid = _whole(body.get("fid"))
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
            fid = _whole(body.get("fid"))
            if ws.knowledge.get(fid) is None:
                raise ValueError("no such fact")
            getattr(ws.knowledge, action.split("_")[1])(fid)
            return {"status": ws.knowledge.get(fid).status}
        if action == "know_add":  # GUI capture: one action to note a fact (D186)
            if ws.knowledge is None:
                raise ValueError("no Company Brain")
            t = " ".join(str(body.get("text") or "").split())
            if not t:
                raise ValueError("nothing to add")
            if len(t) > ws.MAX_CLIP_CHARS:
                raise ValueError(
                    "that is too long for one fact; ingest it as a document "
                    "with /know in the console"
                )
            # The same words again are not a second fact to review. Exact match
            # only: a near match may be a correction ("is" against "is not").
            source = str(body.get("source") or "note").strip() or "note"
            stored = redact.scrub(t, redact.SECRETS)[0].casefold()
            for old in ws.knowledge.list(scope=ws.kb_scope):
                if old.status != "retired" and old.text.casefold() == stored:
                    ws.knowledge.tighten(old.fid, source)  # never loosens
                    return {"fid": old.fid, "status": old.status, "duplicate": True}
            f = ws.knowledge.add_candidate(
                t,
                source=source,
                scope=ws.kb_scope,
            )
            # candidate until reviewed
            return {"fid": f.fid, "status": f.status, "duplicate": False}
        if action == "know_extract":  # facts pulled by the LOCAL model, as candidates
            if ws.knowledge is None:
                raise ValueError("no Company Brain")
            material = body.get("material")
            if (
                not isinstance(material, str)
                or not material.strip()
                or len(material) > 20_000
                or "\0" in material
            ):
                raise ValueError("choose a text file under 20,000 characters")
            from ghostcursor.providers.errors import ProviderError

            name = " ".join(str(body.get("name") or "").split())[:120] or "document"
            try:
                # On the worker under the one-job claim (a second click is
                # refused, not stacked) and stoppable from the page.
                facts = self.run(
                    "Extracting facts",
                    lambda: ws.gateway.extract_facts(
                        name, material, cancelled=self.stop.is_set
                    ),
                )
            except ProviderError:
                raise ValueError(
                    "no model on this computer answered: start Ollama, or use Add from file"
                ) from None
            did = [
                result
                for result, _fid in ws.knowledge.ingest(
                    list(facts), source=("extracted: " + name)[:120], scope=ws.kb_scope, episode=material
                )
            ]
            return {"added": did.count("added"), "duplicate": did.count("duplicate"), "found": len(facts)}
        if action == "know_ingest":  # the page's /know ingest: a document's passages
            if ws.knowledge is None:
                raise ValueError("no Company Brain")
            material = body.get("material")
            if (
                not isinstance(material, str)
                or not material.strip()
                or len(material) > MAX_FILE_CHARS
                or "\0" in material
            ):
                raise ValueError("choose a text file under 100,000 characters")
            from ghostcursor.workspace.knowledge import chunk_document, chunk_export

            name = " ".join(str(body.get("name") or "").split())[:120] or "document"
            exported = chunk_export(name, material)  # a ticket or CRM export
            did = [
                action
                for action, _fid in ws.knowledge.ingest(
                    chunk_document(material) if exported is None else exported,
                    source=name,
                    scope=ws.kb_scope,
                )
            ]  # candidates only: nothing is usable, or sent, until reviewed
            return {"added": did.count("added"), "duplicate": did.count("duplicate")}
        if action == "know_relate":  # GUI: add a relationship (candidate edge)
            if ws.knowledge is None:
                raise ValueError("no Company Brain")
            s = " ".join(str(body.get("subject") or "").split())
            p = " ".join(str(body.get("predicate") or "").split())
            o = " ".join(str(body.get("object") or "").split())
            if not (s and p and o):
                raise ValueError("need subject, predicate and object")
            if max(len(s), len(p), len(o)) > 200:
                raise ValueError("keep each part of a link under 200 characters")
            known = {e.eid for e in ws.knowledge.list_edges(scope=ws.kb_scope)}
            e = ws.knowledge.relate(
                s,
                p,
                o,
                source=str(body.get("source") or "note").strip() or "note",
                scope=ws.kb_scope,
                sensitivity="sensitive" if body.get("sensitive") else "normal",
            )
            # candidate until reviewed
            return {"eid": e.eid, "status": e.status, "duplicate": e.eid in known}
        if action == "know_private_source":  # register/list private sources (D186)
            if ws.knowledge is None:
                raise ValueError("no Company Brain")
            pat = " ".join(str(body.get("pattern") or "").split())
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
            out = _fresh(self.downloads, f"{ws.kb_scope}.company-brain", ".md")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(md, encoding="utf-8", newline="\n")
            return {"path": str(out)}
        if action in ("skills_export", "evals_export"):
            # Files meant to be handed to another agent or a model team
            # (YC S26 "Company Brain", W27 "Own Your Intelligence"): what
            # is reviewed and not private, always scrubbed, private words too.
            from ghostcursor.workspace import task_skills

            hide = lambda text: redact.scrub(text, terms=settings.private_terms())[0]
            flows = []
            for name in task_skills.list_skills(dest_dir=self.skills_dir):
                try:
                    plan = task_skills.load_skill(name, dest_dir=self.skills_dir)
                except Exception:  # a hand-edited file out of schema
                    continue
                if plan is not None:  # the name is content too
                    flows.append(
                        (hide(name.replace("-", " ")), [hide(s.instruction) for s in plan.steps])
                    )
            self.downloads.mkdir(parents=True, exist_ok=True)
            if action == "evals_export":
                if not flows:
                    raise ValueError("save a workflow first; each one becomes a test case")
                out = _fresh(self.downloads, f"{ws.kb_scope}.orbyn-evals", ".jsonl")
                out.write_text(
                    "".join(
                        json.dumps(
                            {
                                "id": name,
                                "input": "How do I " + name + "?",
                                "expected_steps": steps,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                        for name, steps in flows
                    ),
                    encoding="utf-8",
                    newline="\n",
                )
                return {"path": str(out), "cases": len(flows)}
            facts = (
                ws.knowledge.export_scope(ws.kb_scope)["facts"]
                if ws.knowledge is not None
                else []
            )
            if not facts and not flows:
                raise ValueError("nothing to export yet: review a fact or save a workflow")
            lines = [
                "---",
                f"name: orbyn-{re.sub(r'[^a-z0-9]+', '-', ws.kb_scope.lower()).strip('-') or 'default'}",
                "description: How this team works. Reviewed facts and step-by-step "
                "workflows exported from Orbyn. Use it before answering or acting on "
                "this team's processes.",
                "---",
                "",
                "# What we know",
                "",
                *[f"- {hide(f['text'])} (source: {hide(f['source'])})" for f in facts],
                *([] if facts else ["_(no reviewed facts yet)_"]),
                "",
                "# Workflows",
                "",
            ]
            for name, steps in flows:
                lines += [f"## {name}", "", *[f"{n}. {s}" for n, s in enumerate(steps, 1)], ""]
            if not flows:
                lines.append("_(no saved workflows yet)_")
            out = _fresh(self.downloads, f"{ws.kb_scope}.orbyn-skills", ".md")
            out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
            return {"path": str(out), "facts": len(facts), "workflows": len(flows)}
        if action == "audit_summary":  # is the record intact, and what is in it
            from ghostcursor import audit

            intact, lines_read, broken = audit.verify()
            since, events, sent = time.time() - 30 * 86400, {}, {}
            oldest = None  # how far back the record goes (log-keeping rules ask)
            try:
                raw = audit.default_path().read_text(encoding="utf-8").splitlines()
            except OSError:
                raw = []
            for line in raw:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                at = row.get("at") if isinstance(row, dict) else None
                if isinstance(at, (int, float)) and not isinstance(at, bool):
                    oldest = at if oldest is None else min(oldest, at)
                if isinstance(at, (int, float)) and at >= since:
                    name = str(row.get("event"))[:40]
                    events[name] = events.get(name, 0) + 1
                    if name == "egress":
                        to = str(row.get("provider"))[:40]
                        sent[to] = sent.get(to, 0) + 1
            return {
                "intact": intact,
                "lines": lines_read,
                "broken_at": broken,
                "days": 30,
                "oldest": oldest,
                "events": events,
                "sent": sent,
            }
        if action == "audit_export":  # a copy for an auditor, verified
            from ghostcursor import audit

            out = _fresh(self.downloads, "orbyn-audit", ".jsonl")
            intact, lines_read, _ = audit.export(out)
            return {"path": str(out), "intact": intact, "lines": lines_read}
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
        if action == "stats":
            # Local counts only, so it never waits for (or blocks) the worker;
            # its own connection, as the worker's belongs to the worker thread.
            from ghostcursor.workspace.brain import Brain
            from ghostcursor.workspace.research import _trace_path
            from ghostcursor.workspace.session import measures

            brain = Brain(ws.brain.path)
            try:
                return measures(brain, ws.root, _trace_path())
            finally:
                brain.close()
        if self.busy:
            raise ValueError(f"busy: {self.busy}")
        if action == "chatgpt_sign_in":
            from ghostcursor.providers import chatgpt

            self.run("Signing in", lambda: chatgpt.sign_in(cancelled=self.stop.is_set))
            return {}
        ws.suggestion = ""  # a suggestion is for the message just answered
        if action == "say":
            if not text:
                raise ValueError("say something")
            reply = self.run("Thinking", lambda: ws.discuss(text, cancelled=self.stop.is_set))
            self.speak(reply)
            return {"reply": reply}
        if action == "research":
            if not text:
                raise ValueError("ask a question")
            return {"answer": self.run("Researching", lambda: ws.research(text))}
        if action == "read_link":  # one page the person named; read-only
            from urllib.parse import urlsplit

            from ghostcursor.workspace import research

            url = body.get("url")
            if (
                not isinstance(url, str)
                or not url.startswith("https://")
                or len(url) > 2000
                or any(c.isspace() or ord(c) < 32 for c in url)
            ):
                raise ValueError("paste a web address that starts with https://")
            if redact.scrub(url, redact.SECRETS)[0] != url:
                # The address itself is sent to that site: no key rides in it.
                raise ValueError("that address holds a key or number; remove it")
            return {
                "name": (urlsplit(url).hostname or "web page")[:120],
                "material": research.read_page(url),
                "link": True,
            }
        if action == "ask_file":
            material = body.get("material")
            if not isinstance(body.get("text"), str) or not text or len(text) > 500:
                raise ValueError("ask a question under 500 characters")
            # Larger files are fine: ws.ask sends only the passages that match.
            if (
                not isinstance(material, str)
                or not material.strip()
                or len(material) > MAX_FILE_CHARS
                or "\0" in material
            ):
                raise ValueError("choose a text file under 100,000 characters")
            answer = self.run(
                "Asking file",
                lambda: ws.ask(text, material, cancelled=self.stop.is_set),
            )
            return {"answer": answer, "sent": ws.last_sent}
        if action == "job_ask":
            question, jid = body.get("text"), body.get("id")
            if (
                not isinstance(question, str)
                or not question.strip()
                or len(question) > 500
                or "\0" in question
            ):
                raise ValueError("ask a question under 500 characters")
            with self._job_lock:
                row = next(
                    (item for item in self.background_jobs if item["id"] == jid), None
                )
                if row is None or row["state"] != "finished" or not row["answer"]:
                    raise ValueError("no such finished result")
                material = row["answer"]  # ws.ask picks the matching passages
            answer = self.run(
                "Asking file",
                lambda: ws.ask(question, material, cancelled=self.stop.is_set),
            )
            return {"answer": answer, "sent": ws.last_sent}
        if action == "evidence":
            return {"text": ws.evidence(_whole(body.get("n")))}
        if action == "ideate":
            if not self.run("Exploring", ws.ideate):
                raise ValueError("No ideas: the model is not available.")
            return {}
        if action == "plan":
            idea = _whole(body.get("idea"))
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
        if action == "agent_note":
            from ghostcursor.workspace import agents

            agents.add_note(ws.root, str(body.get("name", "")), text)
            return {}
        if action == "agent_delete":
            from ghostcursor.workspace import agents

            agents.delete(ws.root, str(body.get("name", "")))
            return {}
        if action == "handoff_export":
            from ghostcursor.workspace import handoff

            def save():
                text = handoff.export(ws, str(body.get("name", "")))
                out = _fresh(self.downloads, f"{ws.topic}.orbyn-handoff", ".json")
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
            from ghostcursor.workspace.__main__ import DEFAULT_ACT_DENY, teach_seconds

            step = _whole(body.get("step"))
            seconds = teach_seconds([str(body.get("seconds", 300))])
            if seconds is None:
                raise ValueError("seconds must be a number from 1 to 3600")
            if not ws.goal.strip():
                # A plan received from a teammate brings their goal only as
                # data; the goal Orbyn works toward is the person's own words.
                raise ValueError(
                    "Say in Chat what you want to get done first; then start this plan"
                )
            hwnds = self.hwnds(body.get("windows", []))
            plan = ws.teach_plan(step)
            typed = [str(d) for d in body.get("deny", []) if str(d).strip()]
            # As the console: the active agent's list too, and never nothing.
            deny = list(dict.fromkeys([*ws.active_deny, *typed])) or list(
                DEFAULT_ACT_DENY
            )
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
            rated=self._take_rating,
        )
        return self.ws.record_teach(step, outcome, code)

    def speak(self, text) -> None:
        """Read a reply aloud when the person turned that on (on this PC,
        on its own thread: never holds the request)."""

        if not isinstance(text, str) or not text.strip() or not settings.read_aloud():
            return
        if self._speaker is None:
            from ghostcursor.speech import Speaker

            self._speaker = Speaker()
        self._speaker.say(text[:1200])

    def today(self) -> dict:
        """The day at a glance: today's events and unread mail headers when
        those read-only views are connected, and research finished in the
        last day. Each part says why it is missing rather than failing."""

        from ghostcursor.workspace import connectors

        out: dict = {"events": [], "mail": [], "finished": [], "notes": []}
        if connectors.calendar_connected():
            try:
                out["events"] = connectors.agenda(days=1)
            except Exception as exc:  # noqa: BLE001 - shown on the card
                out["notes"].append(f"Calendar: {exc}")
        else:
            out["notes"].append("Calendar not connected (Work › Routines, agents and connections).")
        if connectors.mail_connected():
            try:
                out["mail"] = connectors.unread(limit=5)
            except Exception as exc:  # noqa: BLE001 - shown on the card
                out["notes"].append(f"Mail: {exc}")
        else:
            out["notes"].append("Mail not connected (Work › Routines, agents and connections).")
        day_ago = self.clock() - 24 * 3600
        with self._job_lock:
            jobs = list(self.background_jobs)
        out["finished"] = [
            {"question": j.get("question", ""), "id": j.get("id")}
            for j in jobs
            if j.get("state") == "finished" and (j.get("ended") or 0) >= day_ago
        ][-5:]
        return out

    def _take_rating(self):
        verdict, self._rating = self._rating, None
        return verdict

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
        if isinstance(mid, bool):
            mid = None  # true is not memory #1
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


def _whole(value) -> int:
    """A request's id or index as an int; anything else is a plain refusal,
    not a server error (a list, a float, a number SQLite cannot hold)."""

    if value is None or value == "":
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("expected a whole number")
    number = int(value)  # a non-numeric string is a ValueError already
    if abs(number) >= 2**63:
        raise ValueError("expected a whole number")
    return number


#: What a reloaded or restored one-time link shows (it opens Orbyn only once).
USED_LINK = (
    b"<!doctype html><meta charset=utf-8><title>Orbyn</title>"
    b"<body style='font:16px Segoe UI,sans-serif;margin:40px;max-width:520px'>"
    b"<h2>This Orbyn link was already used</h2><p>For your privacy each link "
    b"opens Orbyn once. Open Orbyn again from its bar at the top of the "
    b"screen (Open) or from the Start menu.</p>"
)


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
            code = query[2:] if query.startswith("c=") else ""
            if (
                path != "/"
                or not self._allowed()
                or not (
                    hmac.compare_digest(given.encode(), token.encode())
                    or (code and app.use_launch_code(code))
                )
            ):
                if code and path == "/" and self._allowed():  # reloaded or restored
                    return self._send(410, USED_LINK, "text/html; charset=utf-8")
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
            if length > MAX_BODY:  # drain a bounded amount, then close, so the
                self.close_connection = True  # page sees the 403, not a reset
                left = min(length, 16 * MAX_BODY)
                while left > 0:
                    chunk = self.rfile.read(min(65536, left))
                    if not chunk:
                        break
                    left -= len(chunk)
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
                try:  # and a local, scrubbed record, so it can be found later
                    from ghostcursor.workspace import crashlog

                    if _note_request_error():
                        crashlog.write_crash(exc)
                except Exception:
                    pass
            self._send(code, json.dumps(result).encode("utf-8"), "application/json")

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def _edge_app_windows() -> set[int]:
    import win32api
    import win32con
    import win32gui
    import win32process

    found = set()

    def collect(hwnd, _):
        if win32gui.GetWindowText(hwnd) != APP_TITLE:
            return
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        try:
            process = win32api.OpenProcess(
                win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
                False,
                pid,
            )
            try:
                if (
                    Path(win32process.GetModuleFileNameEx(process, 0)).resolve()
                    == EDGE.resolve()
                ):
                    found.add(hwnd)
            finally:
                process.Close()
        except OSError:
            pass

    win32gui.EnumWindows(collect, None)
    return found


def open_window(url: str, *, docked: bool = False) -> None:
    """Edge app window with native drag and resize; any browser otherwise."""

    if not EDGE.exists():
        import webbrowser

        # Another browser keeps the address in its history and session
        # restore: open it with a one-time code, never the page token.
        try:
            code = _post(url, "launch_code", {})["code"]
        except Exception:  # noqa: BLE001 - say so rather than leak the token
            _notice("Orbyn could not open its window; install Microsoft Edge or try again.")
            return
        webbrowser.open(url.split("?", 1)[0] + "?c=" + code)
        return
    import win32api
    import win32gui

    width, height = (460, 860) if docked else (640, 720)
    screen_w = win32api.GetSystemMetrics(0)
    screen_h = win32api.GetSystemMetrics(1)
    left = max(0, screen_w - width - 16) if docked else max(0, (screen_w - width) // 2)
    top = 24 if docked else max(0, (screen_h - height) // 4)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    before = _edge_app_windows()
    subprocess.Popen(
        [
            str(EDGE),
            "--new-window",
            f"--app={url}",
            f"--user-data-dir={Path(base) / 'GhostCursor' / 'app-profile'}",
            f"--window-size={width},{height}",
            f"--window-position={left},{top}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
        ]
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        new = _edge_app_windows() - before
        if new:
            if len(new) == 1:
                win32gui.MoveWindow(new.pop(), left, top, width, height, True)
            break
        time.sleep(0.05)


def _startup_link() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Orbyn.lnk"


def _packaged_exe() -> Path | None:
    """Orbyn.exe when running packaged; None from source (nothing to start)."""

    exe = Path(sys.executable)
    return exe if getattr(sys, "frozen", False) and exe.name.lower() == "orbyn.exe" else None


def autostart_on() -> bool:
    return _startup_link().exists()


def set_autostart(on: bool, *, exe: Path | None = None) -> None:
    """A shortcut in this user's Startup folder (no registry, no service):
    Orbyn opens as the island when the person signs in. Off removes it."""

    link = _startup_link()
    if not on:
        link.unlink(missing_ok=True)
        return
    exe = exe or _packaged_exe()
    if exe is None:
        raise ValueError("Start with Windows needs the installed Orbyn app")
    import win32com.client

    link.parent.mkdir(parents=True, exist_ok=True)
    shortcut = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(link))
    shortcut.TargetPath = str(exe)
    shortcut.WorkingDirectory = str(exe.parent)
    shortcut.Description = "Orbyn"
    shortcut.Save()


def _lock_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "GhostCursor" / "app.lock"


def _post(url: str, action: str, body: dict) -> dict:
    """One token-protected API call to the running instance at URL."""

    import urllib.parse
    import urllib.request

    parts = urllib.parse.urlparse(url)
    token = urllib.parse.parse_qs(parts.query).get("t", [""])[0]
    data = json.dumps(body, ensure_ascii=False).encode(
        "utf-8"
    )  # \uXXXX would pass MAX_BODY
    if len(data) > MAX_BODY:  # control characters still escape to six bytes each
        raise ValueError("that file is too large to send to Orbyn")
    request = urllib.request.Request(
        f"http://{parts.netloc}/api/{action}",
        data,
        {"Content-Type": "application/json", "X-Orbyn-Token": token},
    )
    # This computer's own app: never through a proxy from the environment
    # (the request carries the file and the page token).
    opened = (
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=10)
        if urllib.request.getproxies()
        else urllib.request.urlopen(request, timeout=10)
    )
    with opened as response:
        return json.load(response)


def _notice(text: str) -> None:
    """Tell the user why a shell-verb launch did nothing (no console there)."""

    try:
        import win32api

        win32api.MessageBox(0, text, "Orbyn", 0x40)
    except Exception:
        print(text)


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


def _find_ollama() -> str | None:
    """ollama.exe from an absolute PATH folder, never the current folder.

    Not shutil.which: on Windows it searches the current folder first even
    when given explicit folders (unless NoDefaultCurrentDirectoryInExePath is
    set), and "Ask Orbyn about this file" can start Orbyn in a folder someone
    else controls, where a planted ollama.exe would run."""

    for folder in os.environ.get("PATH", "").split(os.pathsep):
        folder = folder.strip().strip('"')  # PATH entries may be quoted
        # A drive or UNC prefix: "\tools" is absolute in ntpath yet means
        # "the current drive", which is not a fixed place either.
        if folder and os.path.isabs(folder) and os.path.splitdrive(folder)[0]:
            candidate = os.path.join(folder, "ollama.exe")
            if os.path.isfile(candidate):
                return candidate
    return None


def _ensure_ollama() -> None:
    """Best-effort: if the local model server is installed but not answering,
    start it so planning/Teach work on first launch instead of reporting
    'model unavailable'. Local only (127.0.0.1:11434); never fatal, never waits."""

    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=1):
            return  # already serving
    except OSError:
        pass

    # Absolute PATH entries only: shutil.which on Windows also searches the
    # current folder, and "Ask Orbyn about this file" can start Orbyn in a
    # folder someone else controls (a planted ollama.exe there would run).
    exe = _find_ollama()
    if not exe:
        return  # not installed; the UI already reports model-unavailable cleanly
    dll_dir = None
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        import ctypes

        dll_dir = ctypes.windll.kernel32.SetDllDirectoryW
        dll_dir(None)  # PyInstaller's bundled DLL path must not reach Ollama.
    try:
        subprocess.Popen(
            [exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass
    finally:
        if dll_dir is not None:
            dll_dir(sys._MEIPASS)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    from ghostcursor import crashreport

    crashreport.install()  # sends nothing unless the person opted in (D191)
    if argv and argv[0] in ("--version", "-v"):
        from ghostcursor import __version__

        print(f"Orbyn {__version__}")
        return 0
    if argv and argv[0] in ("--help", "-h"):
        print(__doc__)
        return 0
    if argv and argv[0] == "--agent-server":  # read-only MCP over stdin/stdout
        from ghostcursor import agent_server

        return agent_server.main(argv[1:])
    offered = None
    if (
        len(argv) == 2 and argv[0] == "--ask-file"
    ):  # Explorer: Ask Orbyn about this file
        try:
            offered = read_text_file(argv[1])
        except ValueError as exc:
            _notice(str(exc))
            return 2
        argv = ["--window"]
    docked = bool(argv and argv[0] == "--dock")
    windowed = bool(argv and argv[0] in ("--dock", "--window"))
    if windowed:
        argv = argv[1:]
    if len(argv) > 1:  # at most one topic; no arg opens the default workspace
        print(__doc__)
        return 2
    existing = _live_instance_url()
    if existing is not None and offered is not None:
        try:
            _post(existing, "offer_file", {"name": offered[0], "material": offered[1]})
        except ValueError as exc:
            _notice(str(exc))
            return 2
        except OSError:
            _notice("Orbyn is running but did not accept the file; try again.")
            return 2
    if existing is not None:  # already running: re-open its window, don't double-start
        if not windowed:
            import win32gui
            from ghostcursor.workspace.island import CLASS, SHOW_MESSAGE

            island_hwnd = win32gui.FindWindow(CLASS, None)
            if island_hwnd:
                win32gui.PostMessage(island_hwnd, SHOW_MESSAGE, 0, 0)
                return 0  # reveal the existing island, including after Hide
        open_window(existing, docked=docked)
        return 0
    _ensure_ollama()  # start the local model if it is installed but not running
    app = App(argv[0] if argv else "workspace")
    app.offered_file = offered
    token = secrets.token_urlsafe(32)
    server = make_server(app, token)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/?t={token}"
    _write_lock(url)
    wake, hotkey = settings.listening()
    island = None
    if windowed:
        open_window(url, docked=docked)
    else:
        from ghostcursor.workspace.island import Island

        island = Island(app, url, open_window, voice_hotkey=hotkey)
        app.voice_to = island.voice
    listener = None
    if wake or hotkey:
        from ghostcursor.listen import Listener

        listener = Listener(app.heard, say=app.say, hotkey=hotkey, wake=wake)
        listener.start()
        if island is not None:
            island.listener = listener
        app.say(
            'Say "Hey Bro" or press '
            + (hotkey or "the hotkey (off)").title()
            + " to talk to Orbyn."
        )
    try:
        # Enabled routines keep the process alive after the window closes.
        while not app.quit_requested.is_set() and (
            (island is not None and not island.closed)
            or app.busy
            or app.has_enabled_routines()
            or time.monotonic() - app.seen < QUIT_AFTER_S
        ):
            app.tick_routines()
            if island is not None and not island.closed:
                island.tick()
            if island is not None and not island.closed:
                island.idle(0.25)
            else:
                time.sleep(0.25 if island is not None else 1)
    except KeyboardInterrupt:
        pass
    finally:
        if island is not None and not island.closed:
            import win32gui

            win32gui.DestroyWindow(island.hwnd)
        if listener is not None:
            listener.stop()
        server.shutdown()
        app.close()
        _clear_lock()
    return 0


if __name__ == "__main__":
    sys.exit(main())

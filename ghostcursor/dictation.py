"""On-demand voice dictation (D186): an explicit, user-triggered capture whose
transcript is SAVED -- never always-on.

Typing into an app (D188): ``type_into`` runs only after the user approved
the exact text, and types it through ``ghostcursor.harness.act`` (rule 1: this
module performs NO input synthesis) into the one focused text field Orbyn
observed in the window the user clicked -- never a console, a password field
or a window policy blocks.

Audio capture and transcription are reused from ``ghostcursor.voice`` (local
faster-whisper; audio stays in memory, nothing is sent anywhere).
"""

from __future__ import annotations

import os
import time
from pathlib import Path


def _default_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "GhostCursor" / "dictations"


def save_transcript(
    text: str, *, dest_dir: Path | None = None, clock=time.time
) -> Path | None:
    """Write a non-empty transcript to a timestamped .txt file and return its
    path; return None for an empty/blank transcript (nothing to save). The file
    is the rule-1-safe sink -- no app ever receives keystrokes from here."""

    text = text.strip()
    if not text:
        return None
    directory = dest_dir or _default_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(clock()))
    path = directory / f"dictation-{stamp}.txt"
    # a second capture in the same second never clobbers the first
    n = 1
    while path.exists():
        n += 1
        path = directory / f"dictation-{stamp}-{n}.txt"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def to_brain(
    text: str, knowledge, scope: str, *, source: str = "dictation"
) -> int | None:
    """Optional sink: file the transcript into the Company Brain as a CANDIDATE
    (owner reviews before it is usable). Returns the fid, or None if empty."""

    text = " ".join(text.split())
    if not text:
        return None
    return knowledge.add_candidate(text, source=source, scope=scope).fid


def dictate(stop, *, record=None, transcribe=None, sink=None) -> tuple[str, object]:
    """One explicit capture: record until ``stop()``, transcribe locally, then
    hand the text to ``sink(text)``. Returns (text, sink_result). Dependencies
    are injected so the orchestration is testable without a microphone; the
    defaults are the real local capture + the save-to-file sink.

    This is the whole on-demand flow: the user triggers it (a console command or
    a wake phrase), speaks, and the transcript is saved -- it is never typed
    into another app from here."""

    if record is None or transcribe is None:
        from ghostcursor import voice

        record = record or voice.record_until
        transcribe = transcribe or voice.transcribe
    sink = sink or save_transcript
    samples = record(stop)
    text = transcribe(samples)
    return text, sink(text)


#: Never typed into: a console would run the words as a command.
SHELLS = frozenset(
    {
        "windowsterminal.exe",
        "wt.exe",
        "openconsole.exe",
        "conhost.exe",
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "bash.exe",
        "mintty.exe",
    }
)
TEXT_FIELDS = ("Edit", "Document")
#: Time the user has to click into the field after approving.
CLICK_WINDOW_S = 5.0


def _foreground() -> int:
    try:
        import win32gui

        hwnd = win32gui.GetForegroundWindow()
        return win32gui.GetAncestor(hwnd, 2) if hwnd else 0  # GA_ROOT
    except Exception:
        return 0


def field_in(hwnd: int, *, read=None, identify_window=None):
    """(binding, field): the one focused text field Orbyn observes in HWND, or
    raise ValueError saying why nothing will be typed."""

    from ghostcursor.harness import binding as binding_mod
    from ghostcursor.harness.frame import Candidate

    if read is None:
        from ghostcursor.harness.uia_reader import read_window as read
    bound = binding_mod.bind([hwnd], identify_window=identify_window or binding_mod.identify)[0]
    if bound.identity.executable in SHELLS:
        raise ValueError("Orbyn never types dictation into a console")
    _, controls, timed_out = read(hwnd)
    focused = [c for c in controls if c.focused]
    if any(c.is_password for c in focused):
        raise ValueError("that is a password field")
    fields = [
        c
        for c in focused
        if c.control_type in TEXT_FIELDS
        and c.enabled
        and c.runtime_id
        and c.rect[2] > c.rect[0]
        and c.rect[3] > c.rect[1]
    ]
    if len(fields) != 1:
        raise ValueError(
            "the app answered too slowly" if timed_out else "no text field has the cursor there"
        )
    c = fields[0]
    return bound, Candidate("c1", bound.label, c.runtime_id, c.name, c.control_type, c.rect, "")


def type_into(
    text: str,
    *,
    before: int,
    escape,
    say=print,
    wait_s: float = CLICK_WINDOW_S,
    clock=time.monotonic,
    pause=time.sleep,
    foreground=_foreground,
    field=field_in,
    perform=None,
) -> str:
    """After the user approved TEXT: wait WAIT_S for them to click into a field
    of another window (ESC cancels), then type TEXT there through act.py.
    BEFORE is the window in front when they approved (the console), which is
    never typed into. Returns what happened, for the console."""

    from types import SimpleNamespace

    from ghostcursor import audit

    text = " ".join(text.split())  # a line break would press Enter
    if not text:
        return "nothing to type"
    deadline = clock() + wait_s
    while clock() < deadline:
        if escape():
            return "cancelled; nothing typed"
        pause(0.05)
    hwnd = foreground()
    if not hwnd or hwnd == before:
        return "no other window was clicked; nothing typed"
    try:
        bound, target = field(hwnd)
    except Exception as exc:  # BindingError is a ValueError
        return f"nothing typed: {exc}"
    say(f"Typing into {bound.identity.executable} ({target.control_type})...")
    if escape():  # the read takes up to seconds; a press during it still stops (rule 4)
        return "cancelled; nothing typed"
    if perform is None:
        from ghostcursor.harness.act import perform
    step = SimpleNamespace(action="type_focused", text=text)
    try:
        did = perform(step, target, window=hwnd)
        outcome = "done"
    except Exception as exc:
        did, outcome = f"nothing typed: {exc}", "refused"
    audit.record(
        "act_step",
        via="dictation",
        action="type",
        control_type=target.control_type,
        app=bound.identity.executable,
        outcome=outcome,
    )
    return did

"""On-demand voice dictation (D186): an explicit, user-triggered capture whose
transcript is SAVED -- never always-on, and it never types into another
application by itself.

Rule 1: this module performs NO input synthesis. The safe default sinks the
text to a file (and optionally the Company Brain as a candidate). If dictation
is ever made to insert into the focused app, that insertion MUST go through
``ghostcursor.harness.act`` -- the one sanctioned input-synthesis module -- and
stays approval-gated there; this module must never grow its own SendInput.

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

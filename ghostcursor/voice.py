"""Speak the goal instead of typing it (D171): a local voice DRAFT.

Records from the microphone until Enter in the Orbyn console, transcribes on
this machine with faster-whisper (CPU, int8), cleans the text, and shows it as
a draft the user accepts or corrects before it becomes the trusted goal.
Audio stays in memory and is never written or sent anywhere. Nothing here
types into another application: the transcript only ever becomes Orbyn's own
goal string (CLAUDE.md rule 1).

``filter_whisper`` and the filler rules are ported from SayStride
(``D:\\PROJECTS\\SayStride\\windows\\saystride\\rules.py``, same author).
"""

from __future__ import annotations

import re

RATE = 16000
MAX_SECONDS = 30
WHISPER_MODEL = "base.en"

_GHOSTS = {
    "thank you",
    "thanks for watching",
    "thank you for watching",
    "bye",
    "the end",
    "please subscribe",
    "like and subscribe",
    "so",
    "oh",
    "um",
}


def filter_whisper(text: str, segments: list[dict] | None, seconds: float) -> str:
    """Drop Whisper's hallucinated segments (silence read as "thank you") and
    transcripts faster than anyone speaks. From SayStride."""

    if segments:
        kept = [
            str(s.get("text", "")).strip()
            for s in segments
            if not (s.get("no_speech_prob", 0) > 0.6 and s.get("avg_logprob", 0) < -0.7)
            and s.get("avg_logprob", 0) >= -1.2
            and s.get("compression_ratio", 1) <= 2.4
            and str(s.get("text", "")).lower().strip(" .,!") not in _GHOSTS
        ]
        text = " ".join(kept)
    elif text.lower().strip(" .,!") in _GHOSTS:
        text = ""
    text = " ".join(text.split())
    return "" if seconds > 1 and len(text.split()) / seconds > 6 else text


def strip_fillers(text: str) -> str:
    """Remove um/uh and stuttered repeats. Reduced from SayStride's rules."""

    text = re.sub(r"(?i)(^|[\s,])(?:um+|uh+|uhm|erm?|hmm+|mm+)\b[,.]?\s*", r"\1", text)
    for _ in range(2):
        text = re.sub(r"(?i)\b(\w+)[,.]?\s+\1\b(?=[\s,.!?]|$)", r"\1", text)
    return re.sub(r"^[,\s]+", "", re.sub(r"[ \t]{2,}", " ", text)).strip()


def record_until(stop) -> "object":
    """Microphone samples (float32 mono, 16 kHz) until ``stop()`` is true or
    MAX_SECONDS pass."""

    import time

    import numpy as np
    import sounddevice

    chunks = []
    with sounddevice.InputStream(
        samplerate=RATE,
        channels=1,
        dtype="float32",
        callback=lambda data, *_: chunks.append(data.copy()),
    ):
        started = time.monotonic()
        while not stop() and time.monotonic() - started < MAX_SECONDS:
            time.sleep(0.05)
    return np.concatenate(chunks).reshape(-1) if chunks else np.zeros(0, "float32")


def transcribe(samples) -> str:
    import numpy as np

    if len(samples) < RATE // 10 or float(np.max(np.abs(samples))) < 1e-5:
        return ""
    from faster_whisper import WhisperModel

    print(
        f"Loading {WHISPER_MODEL} (first use downloads model weights; no audio is sent)."
    )
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(samples, language="en", beam_size=1, vad_filter=True)
    segments = list(segments)
    text = " ".join(s.text.strip() for s in segments)
    return strip_fillers(
        filter_whisper(text, [vars(s) for s in segments], len(samples) / RATE)
    )


def _console_enter() -> bool:
    import msvcrt

    pressed = False
    while msvcrt.kbhit():
        pressed = msvcrt.getwch() in ("\r", "\n") or pressed
    return pressed


def _escape_pressed() -> bool:
    import win32api
    import win32con

    return bool(win32api.GetAsyncKeyState(win32con.VK_ESCAPE) & 0x8001)


def dictate_goal(
    deadline: float,
    *,
    ask=input,
    enter=_console_enter,
    escape=_escape_pressed,
    record=record_until,
    transcribe=transcribe,
    clock=None,
) -> str | None:
    """Console flow: Enter starts, Enter ends, then accept (Enter) or type a
    correction. Returns the confirmed goal, or None if nothing was heard, ESC
    was pressed, or the session deadline passed (CLAUDE.md rule 4)."""

    import time

    clock = clock or time.monotonic
    stopped = []

    def over() -> bool:
        if escape() or clock() >= deadline:
            stopped.append(True)
            return True
        return False

    print("Press Enter, then say your goal; press Enter again when done (ESC cancels).")
    while not enter():
        if over():
            return None
        time.sleep(0.05)
    print("Listening...")
    samples = record(lambda: enter() or over())
    if stopped:
        return None
    print("Transcribing on this machine...")
    draft = transcribe(samples)
    if not draft:
        print("Nothing was heard.")
        return None
    correction = ask(f'Goal (draft): "{draft}"\nEnter to use it, or type a correction: ')
    if clock() >= deadline:
        return None
    return correction.strip() or draft

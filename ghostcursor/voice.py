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


# Spoken-number conversion ("twenty five percent" -> "25%"), ported from
# SayStride (rules.apply_numbers/_parse_number, same author). Deterministic
# string cleanup of the spoken GOAL -- it never types into another application
# (rule 1): the transcript only becomes Orbyn's own goal string.
_SMALL = dict(
    zip(
        "zero one two three four five six seven eight nine ten eleven twelve "
        "thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(),
        range(20),
    )
)
_SMALL.update(
    {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
     "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
)  # fmt: skip
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000,
           "billion": 1_000_000_000, "trillion": 1_000_000_000_000}  # fmt: skip
_BIG = {"million", "billion", "trillion"}


def _parse_number(tokens: list[str], start: int):
    def clean(i):
        return tokens[i].lower().strip(",.!?")

    first = clean(start)
    try:
        value = float(first.replace(",", ""))
        n = 1
        scale = clean(start + 1) if start + 1 < len(tokens) else ""
        if scale in _BIG:
            value *= _SCALES[scale]
            n += 1
        return value, "." in first, scale if scale in _BIG else None, n
    except ValueError:
        pass
    total = current = 0.0
    i, decimal, factor, scale, seen = start, False, 0.1, None, False
    while i < len(tokens):
        w = clean(i)
        if decimal:
            if w in _SMALL and _SMALL[w] < 10:
                total += _SMALL[w] * factor
                factor /= 10
                i += 1
                continue
            if w in _BIG:
                total *= _SCALES[w]
                scale = w
                i += 1
            break
        if w in {"a", "an"} and i + 1 < len(tokens) and clean(i + 1) in _SCALES:
            current = 1
            seen = True
        elif w in _SMALL:
            current += _SMALL[w]
            seen = True
        elif w in _SCALES and seen:
            if w == "hundred":
                current = (current or 1) * 100
            else:
                total += (current or 1) * _SCALES[w]
                current = 0
                scale = w if w in _BIG else None
        elif (
            w == "and"
            and seen
            and i + 1 < len(tokens)
            and clean(i + 1) in _SMALL | _SCALES
        ):
            pass
        elif (
            w == "point"
            and seen
            and i + 1 < len(tokens)
            and clean(i + 1) in _SMALL
            and _SMALL[clean(i + 1)] < 10
        ):
            decimal = True
            total += current
            current = 0
        else:
            break
        i += 1
    return (total + current, decimal, scale, i - start) if seen else None


def apply_numbers(text: str) -> str:
    """Spoken numbers -> digits, with $ and % units. From SayStride."""

    tokens = text.split(" ")
    i = 0
    while i < len(tokens):
        parsed = _parse_number(tokens, i)
        if not parsed:
            i += 1
            continue
        value, decimal, scale, count = parsed
        end = i + count
        nxt = tokens[end].lower().strip(",.!?") if end < len(tokens) else ""
        unit = (
            "$"
            if nxt in {"dollar", "dollars", "bucks"}
            else "%"
            if nxt == "percent"
            else ""
        )
        if unit:
            end += 1
        if not (value >= 10 or decimal or unit or scale):
            i += 1
            continue
        if not unit and not scale and tokens[i][:1].isdigit():
            i += 1
            continue
        if scale in _BIG:
            body = f"{value / _SCALES[scale]:g} {scale}"
        elif decimal:
            body = f"{value:g}"
        else:
            body = f"{int(value):,}" if value >= 10_000 else str(int(value))
        punct = re.search(r"[,.!?]+$", tokens[end - 1])
        replacement = ("$" + body if unit == "$" else body + unit) + (
            punct.group() if punct else ""
        )
        tokens[i:end] = [replacement]
        i += 1
    return " ".join(tokens)


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
    return apply_numbers(
        strip_fillers(
            filter_whisper(text, [vars(s) for s in segments], len(samples) / RATE)
        )
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


def read_line(prompt: str, stop, *, getch=None, kbhit=None) -> str | None:
    """A console line that never blocks past ``stop()``: None on ESC (typed
    here or polled globally) or at the deadline. ``input()`` cannot be
    interrupted (review of D173)."""

    import time

    if getch is None or kbhit is None:
        import msvcrt

        getch, kbhit = msvcrt.getwch, msvcrt.kbhit
    print(prompt, end="", flush=True)
    typed: list[str] = []
    while True:
        if stop():
            print()
            return None
        while kbhit():
            char = getch()
            if char in ("\r", "\n"):
                print()
                return "".join(typed)
            if char == "\x1b":
                print()
                return None
            if char == "\b":
                if typed:
                    typed.pop()
                    print("\b \b", end="", flush=True)
            elif char.isprintable():
                typed.append(char)
                print(char, end="", flush=True)
        time.sleep(0.05)


def dictate_goal(
    deadline: float,
    *,
    ask=None,
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
    # On a daemon thread so ESC and the deadline still stop the session while
    # the model loads or runs (rule 4); an abandoned result is discarded.
    import threading

    result: list[str] = []
    worker = threading.Thread(
        target=lambda: result.append(transcribe(samples)), daemon=True
    )
    worker.start()
    while worker.is_alive():
        if over():
            return None
        worker.join(0.05)
    draft = result[0] if result else ""
    if not draft:
        print("Nothing was heard.")
        return None
    prompt = f'Goal (draft): "{draft}"\nEnter to use it, or type a correction: '
    if ask is None:
        correction = read_line(prompt, lambda: escape() or clock() >= deadline)
    else:
        correction = ask(prompt)
    if correction is None or clock() >= deadline:
        return None
    return correction.strip() or draft

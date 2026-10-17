"""Wake Orbyn hands-free (D182): say "Hey Bro", or press the hotkey
(default Ctrl+Alt+Space, ``settings.json`` "hotkey"), then speak the request.

Everything is local: an energy gate finds speech, faster-whisper ``tiny.en``
checks short utterances for the wake phrase, ``base.en`` transcribes the
request. Audio stays in memory and is never written or sent. The request
becomes a message to Orbyn -- it never acts by itself; Act still needs the
user to approve the plan.
"""

from __future__ import annotations

import functools
import queue
import re
import threading
import time

import numpy as np

from ghostcursor.voice import RATE, filter_whisper, strip_fillers

WAKE = "hey bro"
#: What Whisper hears for "hey bro" in practice.
_WAKE_FORMS = ("hey bro", "hey bruh", "hey bra", "hey brow", "hay bro", "a bro",
               "hey bros", "hey, bro", "hey brother", "heybro")  # fmt: skip
DEFAULT_HOTKEY = "ctrl+alt+space"
FRAME = RATE // 50  # 20 ms
END_SILENCE_S = 0.8
MAX_UTTERANCE_S = 15.0
WAKE_MAX_S = 4.0  # longer speech is conversation, not a wake word (unless armed)
ARMED_FOR_S = 8.0  # after the wake word / hotkey, the next utterance is the request


def wake_match(text: str) -> str | None:
    """The request after the wake phrase ("" if none), or None if the text
    does not start with it."""

    words = re.sub(r"[^a-z' ]", " ", text.casefold()).split()
    joined = " ".join(words)
    for form in _WAKE_FORMS:
        form = re.sub(r"[^a-z ]", "", form)
        if joined == form or joined.startswith(form + " "):
            return joined[len(form) :].strip()
    return None


class Utterances:
    """Energy-gated speech segmentation. ``feed`` 20 ms frames; returns a
    finished utterance (samples) or None. The threshold follows the noise
    floor. ponytail: plain RMS gate; swap for Silero VAD if rooms are noisy."""

    def __init__(self, *, floor: float = 0.004):
        self.floor = floor
        self.speech: list[np.ndarray] = []
        self.quiet = 0

    def feed(self, frame: np.ndarray) -> np.ndarray | None:
        rms = float(np.sqrt(np.mean(np.square(frame)))) if len(frame) else 0.0
        loud = rms > max(0.012, self.floor * 3)
        if not self.speech:
            if loud:
                self.speech, self.quiet = [frame], 0
            else:
                self.floor = 0.95 * self.floor + 0.05 * rms
            return None
        self.speech.append(frame)
        self.quiet = 0 if loud else self.quiet + 1
        length = len(self.speech) * len(frame) / RATE
        if self.quiet * len(frame) / RATE >= END_SILENCE_S or length >= MAX_UTTERANCE_S:
            voiced = (len(self.speech) - self.quiet) * len(frame) / RATE
            done = np.concatenate(self.speech)
            self.speech, self.quiet = [], 0
            return done if voiced >= 0.3 else None
        return None


@functools.lru_cache(maxsize=2)
def _model(name: str):
    from faster_whisper import WhisperModel

    return WhisperModel(name, device="cpu", compute_type="int8")


def transcribe(samples: np.ndarray, model: str = "base.en", prompt: str = "") -> str:
    segments, _ = _model(model).transcribe(
        samples, language="en", beam_size=1, initial_prompt=prompt or None
    )
    segments = list(segments)
    text = " ".join(s.text.strip() for s in segments)
    return strip_fillers(
        filter_whisper(text, [vars(s) for s in segments], len(samples) / RATE)
    )


def parse_hotkey(text: str) -> tuple[int, int]:
    """``ctrl+alt+space`` -> (RegisterHotKey modifiers, virtual key)."""

    from ghostcursor.harness.act import vk_of

    mods = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
    names = [n for n in text.replace(" ", "").casefold().split("+") if n]
    if not names or names[-1] in mods or not all(n in mods for n in names[:-1]):
        raise ValueError(f"hotkey {text!r} needs modifiers then one key")
    modifiers = 0x4000  # MOD_NOREPEAT
    for name in names[:-1]:
        modifiers |= mods[name]
    if modifiers == 0x4000:
        raise ValueError("a hotkey needs at least one of ctrl, alt, shift, win")
    return modifiers, vk_of(names[-1])


class Listener:
    """Calls ``on_request(text)`` after "Hey Bro ..." or the hotkey."""

    def __init__(
        self,
        on_request,
        *,
        say=print,
        hotkey: str | None = DEFAULT_HOTKEY,
        wake: bool = True,
        clock=time.monotonic,
        hear=transcribe,
    ):
        self.on_request, self.say, self.clock, self.hear = on_request, say, clock, hear
        self.hotkey, self.wake = hotkey, wake
        self.armed_until = 0.0
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._hotkey_thread_id = 0

    # --- decisions (pure enough to test) ---------------------------------

    def arm(self, why: str) -> None:
        self.armed_until = self.clock() + ARMED_FOR_S
        self.say(f"Listening ({why})… say what you need.")

    def utterance(self, samples: np.ndarray) -> None:
        seconds = len(samples) / RATE
        if self.clock() < self.armed_until:
            self.armed_until = 0.0
            text = self.hear(samples)
            if text:
                self.on_request(text)
            return
        if not self.wake:
            return
        # No initial prompt: Whisper drops a prompted phrase as "already said".
        heard = self.hear(samples[: int(RATE * WAKE_MAX_S)], "tiny.en")
        rest = wake_match(heard)
        if rest is None:
            return
        if seconds > WAKE_MAX_S:  # the whole request in one breath
            full = self.hear(samples)
            rest = wake_match(full) if wake_match(full) is not None else full
        if len(rest.split()) >= 2:
            self.on_request(rest)
        else:
            self.arm("Hey Bro")

    # --- threads ---------------------------------------------------------

    def start(self) -> None:
        # The microphone also carries the request after the hotkey.
        self._threads.append(threading.Thread(target=self._mic, daemon=True))
        if self.hotkey:
            self._threads.append(threading.Thread(target=self._keys, daemon=True))
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._hotkey_thread_id:
            import win32api
            import win32con

            win32api.PostThreadMessage(self._hotkey_thread_id, win32con.WM_QUIT, 0, 0)

    def _mic(self) -> None:  # pragma: no cover - needs a microphone
        import sounddevice

        frames: queue.Queue = queue.Queue()
        gate = Utterances()
        try:
            with sounddevice.InputStream(
                samplerate=RATE,
                channels=1,
                dtype="float32",
                blocksize=FRAME,
                callback=lambda data, *_: frames.put(data[:, 0].copy()),
            ):
                while not self._stop.is_set():
                    try:
                        frame = frames.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    done = gate.feed(frame)
                    if done is not None:
                        try:
                            self.utterance(done)
                        except Exception as exc:  # a model load failure, say
                            self.say(f"Voice unavailable: {exc}")
        except Exception as exc:
            self.say(f"Microphone unavailable: {exc}")

    def _keys(self) -> None:  # pragma: no cover - needs a desktop session
        import ctypes
        from ctypes import wintypes

        import win32api

        user32 = ctypes.windll.user32
        modifiers, vk = parse_hotkey(self.hotkey)
        self._hotkey_thread_id = win32api.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, 1, modifiers, vk):
            self.say(f"Hotkey {self.hotkey} is taken by another app.")
            return
        message = wintypes.MSG()
        try:
            while (
                not self._stop.is_set()
                and user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0
            ):
                if message.message == 0x0312:  # WM_HOTKEY
                    self.arm(self.hotkey)
        finally:
            user32.UnregisterHotKey(None, 1)

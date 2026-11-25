"""Speak a step aloud while its marks draw in (D189): HeyClicky's "draws while
it talks", with Windows' own SAPI voice. Speech is made on this PC; nothing is
sent anywhere. Speaking never blocks the caller, and ``stop`` cuts it off at
once, so ESC, Stop and ``--seconds`` still end a session immediately (rule 4).
"""

from __future__ import annotations

import threading

#: SpeechVoiceSpeakFlags: return at once; drop anything still being spoken.
_ASYNC, _PURGE = 1, 2


class Speaker:
    """One SAPI voice on its own thread. ``say`` and ``stop`` only hand the
    text over and return: creating the voice and a first ``Speak`` can wait
    while the audio device starts, and that wait must never fall on the
    Teach loop, which polls ESC every tick (D020). Every call is a no-op if
    SAPI is unavailable, so a PC without a voice still gets the drawing."""

    def __init__(self, voice=None):
        self._wake = threading.Condition()
        self._next: str | None = None  # only the newest matters: each purges
        self._sent = self._asked = 0
        self._closed = False
        self._thread = threading.Thread(
            target=self._run, args=(voice,), name="orbyn-speech", daemon=True
        )
        self._thread.start()

    def _run(self, voice) -> None:
        com = None
        if voice is None:
            try:
                import pythoncom
                import win32com.client

                pythoncom.CoInitialize()
                com = pythoncom
                voice = win32com.client.Dispatch("SAPI.SpVoice")
            except Exception:
                voice = None
        try:
            while True:
                with self._wake:
                    while self._next is None and not self._closed:
                        self._wake.wait()
                    if self._next is None:
                        return
                    text, self._next, asked = self._next, None, self._asked
                if voice is not None:
                    try:
                        voice.Speak(text, _ASYNC | _PURGE)
                    except Exception:
                        pass
                with self._wake:
                    self._sent = asked
                    self._wake.notify_all()
        finally:
            voice = None
            if com is not None:
                com.CoUninitialize()

    def _post(self, text: str) -> None:
        with self._wake:
            self._next = text
            self._asked += 1
            self._wake.notify_all()

    def say(self, text: str) -> None:
        """Start saying TEXT, replacing whatever was being said."""

        text = " ".join(text.split())
        if text:
            self._post(text)

    def stop(self) -> None:
        self._post("")

    def wait(self, timeout: float = 2.0) -> bool:
        """True once everything asked so far has reached the voice."""

        with self._wake:
            return self._wake.wait_for(lambda: self._sent == self._asked, timeout)

    def close(self) -> None:
        """Silence the voice and let its thread end."""

        self.stop()
        with self._wake:
            self._closed = True
            self._wake.notify_all()


def spoken(message: str) -> str:
    """The part of a Teach status line worth saying: the instruction, without
    "Step 2/5 (suggested):" or the " -- typed 4 characters" tail."""

    text = message.split(": ", 1)[-1] if message.startswith("Step ") else message
    return text.split(" -- ", 1)[0]

"""Speak a step aloud while its marks draw in (D189): HeyClicky's "draws while
it talks", with Windows' own SAPI voice. Speech is made on this PC; nothing is
sent anywhere. Speaking never blocks the caller, and ``stop`` cuts it off at
once, so ESC, Stop and ``--seconds`` still end a session immediately (rule 4).
"""

from __future__ import annotations

#: SpeechVoiceSpeakFlags: return at once; drop anything still being spoken.
_ASYNC, _PURGE = 1, 2


class Speaker:
    """One SAPI voice. Every method is a no-op if SAPI is unavailable, so a
    PC without a voice still gets the drawing."""

    def __init__(self, voice=None):
        if voice is None:
            try:
                import win32com.client

                voice = win32com.client.Dispatch("SAPI.SpVoice")
            except Exception:
                voice = None
        self._voice = voice

    def say(self, text: str) -> None:
        """Start saying TEXT, replacing whatever was being said."""

        text = " ".join(text.split())
        if self._voice is None or not text:
            return
        try:
            self._voice.Speak(text, _ASYNC | _PURGE)
        except Exception:
            pass

    def stop(self) -> None:
        if self._voice is None:
            return
        try:
            self._voice.Speak("", _ASYNC | _PURGE)
        except Exception:
            pass


def spoken(message: str) -> str:
    """The part of a Teach status line worth saying: the instruction, without
    "Step 2/5 (suggested):" or the " -- typed 4 characters" tail."""

    text = message.split(": ", 1)[-1] if message.startswith("Step ") else message
    return text.split(" -- ", 1)[0]

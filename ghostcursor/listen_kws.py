"""Always-on wake detection with a streaming keyword spotter (D185), the
faster rung Dodaios and HeyClicky use. When sherpa-onnx and the KWS model are
present, this spots "Hey Bro" from the mic in well under a second with no
per-utterance Whisper decode. It is OPTIONAL: if the package or the model is
missing, the caller falls back to the Whisper wake path, so nothing breaks.

Only wake DETECTION moves here; the request after the wake word is still
transcribed by faster-whisper (ghostcursor/voice.py). Audio stays in memory.
"""

from __future__ import annotations

import os
from pathlib import Path

RATE = 16000
_MODEL_DIR_NAME = "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"


def model_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "GhostCursor" / "kws" / _MODEL_DIR_NAME


def available() -> bool:
    """True if the fast path can run on this machine."""

    try:
        import sherpa_onnx  # noqa: F401
    except Exception:
        return False
    d = model_dir()
    return (d / "tokens.txt").exists() and (d / "hey-bro.txt").exists()


class Detector:
    """Feed 16 kHz float32 frames; ``feed`` returns True the moment the wake
    phrase is spotted, then resets so the next detection is independent."""

    def __init__(self, keywords_file: str | None = None):
        import sherpa_onnx

        d = model_dir()

        def pick(stem: str) -> str:
            full = d / f"{stem}.int8.onnx"
            return str(full if full.exists() else d / f"{stem}.onnx")

        self._spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(d / "tokens.txt"),
            encoder=pick("encoder-epoch-12-avg-2-chunk-16-left-64"),
            decoder=pick("decoder-epoch-12-avg-2-chunk-16-left-64"),
            joiner=pick("joiner-epoch-12-avg-2-chunk-16-left-64"),
            keywords_file=keywords_file or str(d / "hey-bro.txt"),
            num_threads=1,
            provider="cpu",
        )
        self._stream = self._spotter.create_stream()

    def feed(self, frame) -> bool:
        self._stream.accept_waveform(RATE, frame)
        while self._spotter.is_ready(self._stream):
            self._spotter.decode_stream(self._stream)
        if self._spotter.get_result(self._stream):
            self._stream = self._spotter.create_stream()  # reset for the next one
            return True
        return False

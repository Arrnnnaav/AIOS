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
    keywords = d / "hey-bro.txt"
    if not (d / "tokens.txt").exists() or not keywords.exists():
        return False
    # install() leaves a comment-only placeholder when it cannot generate the
    # keywords; that is not installed, and Whisper's wake check must run.
    try:
        lines = keywords.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    return any(line.strip() and not line.lstrip().startswith("#") for line in lines)


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


# --- one-time model install (D185 fast path) --------------------------------

#: The official sherpa-onnx gigaspeech streaming-KWS model (k2-fsa release).
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/"
    + _MODEL_DIR_NAME
    + ".tar.bz2"
)
#: A detection boost for the wake phrase; sherpa's keyword format is the
#: model's BPE pieces per line, optionally "... :<boost>" to raise recall.
WAKE_PHRASE = "HEY BRO"
WAKE_BOOST = 2.0


def keywords_text(sp) -> str:
    """The sherpa KWS keywords-file line for the wake phrase: the model's own
    BPE pieces (from its bpe.model via ``sp``) joined with spaces, with a recall
    boost. Correct tokens matter -- a wrong line simply never fires (the caller
    falls back to Whisper), so it is generated from the model, not hard-coded."""

    pieces = sp.encode(WAKE_PHRASE, out_type=str)
    return " ".join(pieces) + f" :{WAKE_BOOST}"


def _download(url: str, dest):
    from ghostcursor import policy

    if policy.max_egress() == policy.LOCAL:  # offline: nothing is fetched
        raise RuntimeError("everything stays on this computer: copy the wake-word model in by hand")
    import urllib.request

    with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 (known host)
        dest.write_bytes(resp.read())


def _extract(archive, into) -> None:
    import tarfile

    with tarfile.open(archive, "r:bz2") as tar:
        tar.extractall(into, filter="data")  # filter=data: no paths outside `into`


def install(*, download=_download, extract=_extract, load_sp=None) -> Path:
    """Download and set up the KWS model so the fast wake path turns on, then
    write hey-bro.txt from the model's own tokenizer. Returns the model dir.
    IO is injectable for tests; the real run needs the network and the model's
    bpe.model. Safe to re-run; the Whisper path works throughout."""

    import tempfile

    target = model_dir()
    if not (target / "tokens.txt").exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "kws.tar.bz2"
            download(MODEL_URL, archive)
            extract(archive, target.parent)  # extracts the named dir itself
    bpe = target / "bpe.model"
    keywords = target / "hey-bro.txt"
    if not keywords.exists():
        try:
            if load_sp is None:
                import sentencepiece  # type: ignore

                sp = sentencepiece.SentencePieceProcessor(model_file=str(bpe))
            else:
                sp = load_sp(bpe)
            keywords.write_text(keywords_text(sp) + "\n", encoding="utf-8")
        except Exception as exc:  # sentencepiece missing or bpe absent
            keywords.write_text(
                f"# Could not auto-generate ({exc}). Run sherpa-onnx's\n"
                f"# text2token on bpe.model for {WAKE_PHRASE!r} and save the\n"
                f"# BPE pieces (one line, e.g. '▁HEY ▁B RO :2.0') here.\n",
                encoding="utf-8",
            )
    return target


def main(argv=None) -> int:

    print(f"Installing the Hey Bro wake model to {model_dir()} ...")
    try:
        path = install()
    except Exception as exc:
        print(f"install failed: {exc}")
        return 1
    print("ready" if available() else f"model at {path}; see {path / 'hey-bro.txt'}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

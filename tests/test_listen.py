"""'Hey Bro' and the hotkey (D182): the wake phrase is recognised in the forms
Whisper produces; a request in the same breath is sent, a bare wake word arms
the next utterance; nothing is sent without the wake word or the hotkey."""

from __future__ import annotations

import numpy as np
import pytest

from ghostcursor import listen, settings
from ghostcursor.listen import RATE, Listener, Utterances, parse_hotkey, wake_match


@pytest.mark.parametrize(
    "text, rest",
    [
        ("Hey Bro, copy the totals into my email.", "copy the totals into my email"),
        ("hey bruh open excel", "open excel"),
        ("Hey bro.", ""),
        ("Hey brother can you help", "can you help"),
        ("I said hey bro to him", None),
        ("Hello world", None),
        ("heybro", ""),
    ],
)
def test_wake_match(text, rest):
    assert wake_match(text) == rest


def _tone(seconds, amp):
    return (amp * np.ones(int(RATE * seconds))).astype("float32")


def test_utterances_split_on_silence_and_skip_blips():
    gate = Utterances()
    audio = np.concatenate(
        [
            _tone(0.5, 0.001),
            _tone(1.0, 0.1),
            _tone(1.0, 0.001),
            _tone(0.05, 0.1),
            _tone(1.0, 0.001),
        ]  # fmt: skip
    )
    found = []
    for i in range(0, len(audio), listen.FRAME):
        done = gate.feed(audio[i : i + listen.FRAME])
        if done is not None:
            found.append(len(done) / RATE)
    assert len(found) == 1 and 1.5 <= found[0] <= 2.0  # the blip is dropped


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def _listener(heard):
    sent, clock = [], Clock()
    replies = iter(heard)
    listener = Listener(
        sent.append, say=lambda s: None, clock=clock, hear=lambda *a: next(replies)
    )
    return listener, sent, clock


def test_a_request_in_one_breath_is_sent():
    listener, sent, _ = _listener(["Hey bro open the budget sheet"])
    listener.utterance(_tone(2.0, 0.1))
    assert sent == ["open the budget sheet"]


def test_a_bare_wake_word_arms_the_next_utterance_until_it_expires():
    listener, sent, clock = _listener(["Hey bro", "paste it into word", "stray talk"])
    listener.utterance(_tone(0.6, 0.1))
    assert sent == []
    listener.utterance(_tone(2.0, 0.1))
    assert sent == ["paste it into word"]
    clock.now = 100.0
    listener.utterance(_tone(2.0, 0.1))  # not armed, no wake word
    assert sent == ["paste it into word"]


def test_the_hotkey_arms_without_a_wake_word():
    listener, sent, _ = _listener(["summarise this page"])
    listener.arm("ctrl+alt+space")
    listener.utterance(_tone(2.0, 0.1))
    assert sent == ["summarise this page"]


def test_with_the_wake_word_off_only_the_hotkey_listens():
    listener, sent, _ = _listener(["Hey bro open excel"])
    listener.wake = False
    listener.utterance(_tone(2.0, 0.1))
    assert sent == []


def test_hotkey_parsing():
    assert parse_hotkey("ctrl+alt+space") == (0x4000 | 0x2 | 0x1, 0x20)
    assert parse_hotkey("Win+Shift+O") == (0x4000 | 0x8 | 0x4, ord("O"))
    for bad in ("space", "ctrl+alt", "ctrl+banana", "", "hyper+x"):
        with pytest.raises(ValueError):
            parse_hotkey(bad)


def test_listening_settings(tmp_path):
    path = tmp_path / "s.json"
    assert settings.listening(path) == (True, "ctrl+alt+space")
    path.write_text('{"wake_word": false, "hotkey": "ctrl+shift+o"}')
    assert settings.listening(path) == (False, "ctrl+shift+o")
    path.write_text('{"hotkey": ""}')
    assert settings.listening(path) == (True, None)


def test_a_heard_request_becomes_a_message(tmp_path):
    from ghostcursor.workspace.app import App
    from tests.test_workspace_handoff import _ws

    app = App("voice", make_workspace=lambda: _ws(tmp_path, "voice"))
    try:
        app.heard("make me a plan for the deck")
        for _ in range(100):
            if app.state()["turns"]:
                break
            import time

            time.sleep(0.05)
        assert app.state()["turns"][0]["text"] == "make me a plan for the deck"
    finally:
        app.close()


def test_kws_availability_is_graceful(monkeypatch, tmp_path):
    """available() is a plain bool; a missing model or package never raises."""
    from ghostcursor import listen_kws

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))  # empty -> no model
    assert listen_kws.available() is False


def test_the_whisper_wake_path_is_skipped_when_kws_is_active():
    """With KWS active, utterance() must not run the Whisper wake check; the
    KWS loop arms the wake instead."""
    heard = []
    listener = Listener(lambda t: None, say=lambda s: None, clock=Clock(),
                        hear=lambda *a: heard.append(a) or "hey bro do it")  # fmt: skip
    listener._kws = object()  # pretend the fast path is active
    listener.utterance(_tone(2.0, 0.1))  # not armed, KWS active
    assert heard == []  # Whisper wake check skipped


@pytest.mark.interactive
def test_kws_detector_fires_on_spoken_hey_bro(tmp_path):
    import wave

    from ghostcursor import listen_kws

    if not listen_kws.available():
        pytest.skip("KWS model not installed")
    try:
        import win32com.client
    except Exception:
        pytest.skip("no SAPI")

    def speak(text):
        out = str(tmp_path / "k.wav")
        st = win32com.client.Dispatch("SAPI.SpFileStream")
        fmt = win32com.client.Dispatch("SAPI.SpAudioFormat"); fmt.Type = 18
        st.Format = fmt; st.Open(out, 3)
        v = win32com.client.Dispatch("SAPI.SpVoice"); v.AudioOutputStream = st
        v.Speak(text); st.Close()
        with wave.open(out) as w:
            return (np.frombuffer(w.readframes(w.getnframes()), "int16") / 32768.0).astype("float32")

    def fired(phrase):
        det = listen_kws.Detector()
        a = speak(phrase)
        return any(det.feed(a[i : i + 1600]) for i in range(0, len(a), 1600))

    assert fired("Hey Bro")
    assert not fired("open the settings")


def test_kws_install_places_model_and_writes_keyword_file(tmp_path, monkeypatch):
    """install() downloads+extracts the model and writes hey-bro.txt from the
    model's own BPE tokenizer. IO is injected; no network, no real model."""

    import tarfile

    from ghostcursor import listen_kws

    model = tmp_path / listen_kws._MODEL_DIR_NAME
    monkeypatch.setattr(listen_kws, "model_dir", lambda: model)

    def fake_download(url, dest):
        assert url == listen_kws.MODEL_URL
        # a tar whose single top dir matches the model dir name, holding tokens
        staged = tmp_path / "staged" / listen_kws._MODEL_DIR_NAME
        staged.mkdir(parents=True)
        (staged / "tokens.txt").write_text("a 1\n", encoding="utf-8")
        (staged / "bpe.model").write_bytes(b"x")
        with tarfile.open(dest, "w:bz2") as t:
            t.add(staged, arcname=listen_kws._MODEL_DIR_NAME)

    class FakeSP:
        def __init__(self, bpe):
            assert bpe.name == "bpe.model"

        def encode(self, text, out_type=str):
            assert text == "HEY BRO"
            return ["▁HEY", "▁B", "RO"]

    out = listen_kws.install(download=fake_download, load_sp=FakeSP)
    assert out == model and (model / "tokens.txt").exists()
    assert (model / "hey-bro.txt").read_text(encoding="utf-8").strip() == "▁HEY ▁B RO :2.0"


def test_kws_keyword_fallback_when_tokenizer_missing(tmp_path, monkeypatch):
    from ghostcursor import listen_kws

    model = tmp_path / listen_kws._MODEL_DIR_NAME
    model.mkdir(parents=True)
    (model / "tokens.txt").write_text("a 1\n", encoding="utf-8")  # model already present
    monkeypatch.setattr(listen_kws, "model_dir", lambda: model)

    def boom(_bpe):
        raise RuntimeError("no sentencepiece")

    listen_kws.install(download=lambda u, d: None, load_sp=boom)
    note = (model / "hey-bro.txt").read_text(encoding="utf-8")
    assert "Could not auto-generate" in note  # clear guidance, never a wrong keyword

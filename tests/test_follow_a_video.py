"""Follow a video: what this PC plays is heard (loopback), written down on
this computer, and planned from like a written how-to. Stop keeps nothing;
too little speech is said plainly."""

from __future__ import annotations

import pytest

from ghostcursor.workspace.app import App
from ghostcursor.workspace.brain import Brain
from ghostcursor.workspace.session import Workspace
from tests.test_how_to_guide import PLAN, Planner


def _app(tmp_path):
    return App("video", make_workspace=lambda: Workspace("video", Planner(), Brain(tmp_path / "b.sqlite"), root=tmp_path / "r"))


def test_the_spoken_steps_become_the_plan(tmp_path):
    app = _app(tmp_path)
    try:
        heard = "First open the View menu at the top of the window. Then click Word wrap to turn it on."
        app.signal.set()  # the person pressed Done
        steps = app._from_video("word wrap", record=lambda stop, max_seconds: [0.1] * 10 if stop() else None, transcribe=lambda s: heard)
        assert steps == 1 and app.ws.plan is PLAN
        envelope = app.ws.gateway.envelopes[-1]
        assert "Word wrap" in " ".join(t.text for t in envelope.tainted["outline"])
        assert "Word wrap" not in str(envelope.trusted)  # the video's words are data
    finally:
        app.close()


def test_stop_keeps_nothing_and_silence_is_said_plainly(tmp_path):
    app = _app(tmp_path)
    try:
        app.stop.set()
        with pytest.raises(ValueError, match="Stopped"):
            app._from_video("", record=lambda stop, max_seconds: (stop(), [])[1], transcribe=lambda s: "never")
        app.stop.clear()
        with pytest.raises(ValueError, match="Too little speech"):
            app._from_video("", record=lambda stop, max_seconds: [], transcribe=lambda s: "uh")
        assert app.ws.plan is None
    finally:
        app.close()


def test_the_loopback_capture_returns_16k_mono():
    from ghostcursor import loopback

    assert loopback.RATE == 16_000  # what Whisper listens at


def test_the_resampler_keeps_the_pitch_across_blocks():
    import numpy as np

    from ghostcursor.loopback import _Resampler

    for rate in (44_100, 48_000):
        r = _Resampler(rate)
        t = np.arange(rate * 2) / rate
        tone = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        step = rate // 100  # 10 ms blocks, as Windows hands them over
        out = np.concatenate([r.feed(np.stack([tone[i:i + step]] * 2, axis=1)) for i in range(0, len(tone), step)])
        assert abs(len(out) - 32_000) <= 2
        assert int(np.argmax(np.abs(np.fft.rfft(out[:16_000])))) == 440


def test_the_audio_format_struct_matches_windows_layout():
    import ctypes

    from ghostcursor import loopback

    assert ctypes.sizeof(loopback.WAVEFORMATEX) == 18  # packed, as mmreg.h declares it
    assert ctypes.sizeof(loopback.WAVEFORMATEXTENSIBLE) == 40

"""On-demand dictation (D186): explicit capture -> save. Rule 1: the module
never types into another app; it sinks the transcript to a file or the Brain.
Hermetic -- record/transcribe are injected, no microphone."""

from __future__ import annotations

from ghostcursor import dictation


def test_save_transcript_writes_a_timestamped_file_and_skips_empty(tmp_path):
    path = dictation.save_transcript("resize to 25%", dest_dir=tmp_path)
    assert path is not None and path.exists()
    assert path.read_text(encoding="utf-8") == "resize to 25%"
    assert path.parent == tmp_path and path.suffix == ".txt"
    # empty / whitespace -> nothing saved
    assert dictation.save_transcript("   ", dest_dir=tmp_path) is None


def test_save_transcript_never_clobbers_within_the_same_second(tmp_path):
    frozen = lambda: 1_700_000_000.0  # same timestamp both times
    a = dictation.save_transcript("first", dest_dir=tmp_path, clock=frozen)
    b = dictation.save_transcript("second", dest_dir=tmp_path, clock=frozen)
    assert a != b and a.read_text() == "first" and b.read_text() == "second"


def test_to_brain_files_a_reviewable_candidate(tmp_path):
    from ghostcursor.workspace.knowledge import Knowledge

    kb = Knowledge(tmp_path / "k.sqlite")
    fid = dictation.to_brain("prod runs in us-east-1", kb, "acme")
    fact = kb.get(fid)
    assert fact.status == "candidate" and fact.source == "dictation"
    assert dictation.to_brain("   ", kb, "acme") is None
    kb.close()


def test_dictate_records_transcribes_and_sinks(tmp_path):
    saved = {}
    text, result = dictation.dictate(
        stop=lambda: True,
        record=lambda stop: "AUDIO",  # stub: no mic
        transcribe=lambda samples: "twenty five percent" if samples == "AUDIO" else "",
        sink=lambda t: (saved.__setitem__("text", t), "ok")[1],
    )
    assert text == "twenty five percent"
    assert saved["text"] == "twenty five percent" and result == "ok"


def test_dictate_default_sink_saves_to_file(tmp_path, monkeypatch):
    monkeypatch.setattr(dictation, "_default_dir", lambda: tmp_path)
    text, path = dictation.dictate(
        stop=lambda: True,
        record=lambda stop: "AUDIO",
        transcribe=lambda samples: "note this down",
    )
    assert text == "note this down"
    assert path.exists() and path.read_text() == "note this down"

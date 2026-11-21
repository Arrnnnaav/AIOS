"""Clipboard history, snippets, and capture-log (D186).

All three keep user text local: the ring is session-only, snippets live in one
JSON file, the capture log is an append-only file. None of them type into an
app or send anything off-device (rule 1), so the tests pin the data behaviour.
"""

from __future__ import annotations

from pathlib import Path

from ghostcursor.workspace import capture, snippets
from ghostcursor.workspace.clips import Clips


def test_clips_ring_dedups_and_orders_newest_first():
    c = Clips(maxlen=3)
    assert c.offer("one") and c.offer("two")
    assert not c.offer("two")  # same as latest
    assert not c.offer("") and not c.offer("   ")  # blank
    assert c.offer("one")  # older dup -> front
    assert c.list() == ["one", "two"]
    for x in ("a", "b", "c"):
        c.offer(x)
    assert c.list() == ["c", "b", "a"]  # bounded to maxlen
    assert c.get(1) == "c" and c.get(0) is None and c.get(99) is None


def test_snippets_round_trip(tmp_path: Path):
    assert snippets.names(tmp_path) == []
    assert snippets.save(tmp_path, "sig", "Best,\nArnav") == "sig"
    assert snippets.get(tmp_path, "sig") == "Best,\nArnav"
    assert snippets.names(tmp_path) == ["sig"]
    assert snippets.get(tmp_path, "missing") is None
    assert snippets.remove(tmp_path, "sig") and not snippets.remove(tmp_path, "sig")


def test_snippet_name_and_text_are_required(tmp_path: Path):
    import pytest

    for name, text in (("", "text"), ("name", "   ")):
        with pytest.raises(ValueError):
            snippets.save(tmp_path, name, text)


def test_capture_appends_dated_bullets_and_skips_blank(tmp_path: Path):
    log = tmp_path / "captures.md"
    assert capture.append_capture("hello world", log=log)
    assert not capture.append_capture("  ", log=log)
    assert not capture.append_capture(None, log=log)
    assert capture.append_capture("second", log=log)
    lines = [
        ln
        for ln in log.read_text(encoding="utf-8").splitlines()
        if ln.startswith("- [")
    ]
    assert len(lines) == 2
    assert "hello world" in lines[0] and "second" in lines[1]


def test_a_copied_key_is_not_written_to_the_capture_log(tmp_path):
    from ghostcursor.workspace import capture

    log = tmp_path / "captures.md"
    assert capture.append_capture("token AKIA1234567890ABCDEF here", log=log)
    assert "AKIA1234567890ABCDEF" not in log.read_text(encoding="utf-8")


def test_a_save_that_dies_mid_write_leaves_the_old_snippets_whole(tmp_path, monkeypatch):
    import os

    from ghostcursor.workspace import snippets

    snippets.save(tmp_path, "sig", "Best, Ana")

    def crash(*a, **k):
        raise OSError("power cut")

    monkeypatch.setattr(os, "replace", crash)
    try:
        snippets.save(tmp_path, "addr", "1 Main St")
    except OSError:
        pass
    monkeypatch.undo()
    assert snippets.names(tmp_path) == ["sig"] and snippets.get(tmp_path, "sig") == "Best, Ana"

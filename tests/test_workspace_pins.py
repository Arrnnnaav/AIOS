"""Sticky reference pins (D186): add / remove, ids stable, shown at startup."""

from __future__ import annotations

import pytest

from ghostcursor.workspace import pins
from ghostcursor.workspace.__main__ import _startup_status


def test_ids_stable_and_remove(tmp_path):
    assert pins.add(tmp_path, "staging: https://x.test") == 1
    assert pins.add(tmp_path, "on-call: Arnav") == 2
    assert pins.remove(tmp_path, 1) and not pins.remove(tmp_path, 1)
    assert pins.add(tmp_path, "third") == 3  # not reused
    assert [t for _i, t in pins.items(tmp_path)] == ["on-call: Arnav", "third"]


def test_empty_text_and_render(tmp_path):
    with pytest.raises(ValueError):
        pins.add(tmp_path, "   ")
    assert "no pins" in pins.render(tmp_path)
    pins.add(tmp_path, "note")
    assert "note" in pins.render(tmp_path)


def test_pins_do_not_appear_in_the_todo_status(tmp_path):
    # pins are reference, not pending work -- they must not inflate the todo count
    pins.add(tmp_path, "a reference")
    assert _startup_status(tmp_path) == ""

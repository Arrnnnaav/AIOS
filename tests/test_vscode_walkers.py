"""VS Code walker contracts, driven by fakes (D069).

Hermetic on purpose. `test_uia_elements.py` is a whole-module interactive lane
because it walks a real desktop window; these tests need no desktop at all, and
they guard a contract CHANGE, so they must run in the fast gate that actually
gets run.

The contract: a clean absence still yields an empty successful observation so
executable-bounded OCR can escalate, while a genuine provider fault raises
instead of masquerading as an empty screen.
"""

import pytest

from ghostcursor.perception import uia


class _FakeButton:
    """Stand-in for a pywinauto Button wrapper in the Open Folder walk."""

    def __init__(self, name, bbox=(10, 20, 80, 50)):
        self._name = name
        self._bbox = bbox

    def window_text(self):
        return self._name

    def rectangle(self):
        class _R:
            pass

        r = _R()
        r.left, r.top, r.right, r.bottom = self._bbox
        return r

    @property
    def element_info(self):
        class _Info:
            control_type = "Button"
            automation_id = ""

        return _Info()


def test_vscode_walk_selects_the_glyph_prefixed_open_folder_action(monkeypatch):
    """VS Code 1.134.0 prefixes a Codicon to the accessible name (D069).

    The old provider-side exact query missed it, which is how this workflow's
    tier-1 perception went dark while OCR quietly carried it.
    """
    monkeypatch.setattr(uia, "windows_matching_executable", lambda title, exe: [4242])
    monkeypatch.setattr(
        uia,
        "_vscode_button_walk",
        lambda hwnd: [
            _FakeButton("Minimize"),
            _FakeButton(" Open Folder..."),
            _FakeButton(" Open File..."),
        ],
    )
    monkeypatch.setattr(uia, "is_on_screen", lambda bbox: True)

    elements = uia.iter_vscode_elements(".*Visual Studio Code.*")

    assert len(elements) == 1
    assert elements[0].name == " Open Folder..."
    assert elements[0].control_type == "Button"
    assert elements[0].bbox == (10, 20, 80, 50)


def test_vscode_walk_raises_a_fault_for_a_provider_failure(monkeypatch):
    """Contract change (D069): a fault is no longer flattened into emptiness.

    This test previously asserted the opposite -- that a provider failure
    degrades to an empty list. That behaviour published an empty *successful*
    observation, indistinguishable from "nothing is on screen", which is
    precisely how a dark perception tier stayed invisible. Faults must now be
    observable; only a clean absence yields an empty result.
    """
    monkeypatch.setattr(uia, "windows_matching_executable", lambda title, exe: [4242])

    def blocked(_hwnd):
        raise OSError("provider unavailable")

    monkeypatch.setattr(uia, "_vscode_button_walk", blocked)

    with pytest.raises(uia.ProviderQueryFault):
        uia.iter_vscode_elements(".*Visual Studio Code.*")


def test_vscode_walk_returns_empty_when_the_action_is_simply_absent(monkeypatch):
    """The half that must NOT change: absence still lets OCR escalate."""
    monkeypatch.setattr(uia, "windows_matching_executable", lambda title, exe: [4242])
    monkeypatch.setattr(
        uia, "_vscode_button_walk", lambda hwnd: [_FakeButton("Minimize")]
    )
    monkeypatch.setattr(uia, "is_on_screen", lambda bbox: True)

    assert uia.iter_vscode_elements(".*Visual Studio Code.*") == []

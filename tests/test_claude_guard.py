"""The Claude Code PreToolUse guards (tools/claude_guard.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "claude_guard", Path(__file__).resolve().parents[1] / "tools" / "claude_guard.py"
)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def _write(text):
    return {"tool_input": {"content": text}}


def test_key_shapes_and_stored_keys_are_blocked():
    none = lambda: []  # noqa: E731
    assert guard.check_secrets(_write("x = 'nvapi-" + "a" * 20 + "'"), none)
    assert guard.check_secrets(
        {"tool_input": {"new_string": "apikey_" + "b" * 20}}, none
    )
    assert guard.check_secrets(_write("token " + "q7" * 10), lambda: ["q7" * 10])
    assert guard.check_secrets(_write("keys live in Orbyn/nvidia"), none) is None


def test_commit_is_blocked_only_while_a_campaign_is_open(tmp_path):
    commit = {"tool_input": {"command": 'cd x && git add a && git commit -m "m"'}}
    idle = lambda: False  # noqa: E731
    assert guard.check_shell(commit, tmp_path, idle) is None
    (tmp_path / ".artifacts").mkdir()
    (tmp_path / ".artifacts" / "campaign.lock").write_text("2026-10-01-x\n")
    assert "2026-10-01-x" in guard.check_shell(commit, tmp_path, idle)
    assert (
        guard.check_shell({"tool_input": {"command": "git status"}}, tmp_path, idle)
        is None
    )


def test_a_desktop_lane_waits_for_any_other_test_session(tmp_path):
    lane = {"tool_input": {"command": "py -3.12 -m pytest tests -m interactive"}}
    hermetic = {
        "tool_input": {
            "command": 'py -3.12 -m pytest tests -m "not interactive and not pixel"'
        }
    }
    hung = {"tool_input": {"command": "py -3.12 -m pytest tests\\test_hung_window.py"}}
    busy = lambda: True  # noqa: E731
    assert guard.check_shell(lane, tmp_path, busy)
    assert guard.check_shell(hung, tmp_path, busy)
    assert guard.check_shell(hermetic, tmp_path, busy) is None
    assert guard.check_shell(lane, tmp_path, lambda: False) is None

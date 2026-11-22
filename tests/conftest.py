"""Test-lane ownership.

Keep the categories in one reviewed table instead of scattering decorators
through old modules. New desktop-dependent modules must be added explicitly;
unlisted tests stay in the fast hermetic lane.
"""

from __future__ import annotations

from pathlib import Path

import pytest


INTERACTIVE_MODULES = {
    "test_appinfo.py",
    "test_overlay_freshness.py",
    "test_uia_app.py",
    "test_uia_elements.py",
}

PIXEL_MODULES: set[str] = set()

HUNG_MODULES = {
    "test_hung_window.py",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        name = Path(str(item.path)).name
        if name in INTERACTIVE_MODULES:
            item.add_marker(pytest.mark.interactive)
        if name in PIXEL_MODULES:
            item.add_marker(pytest.mark.pixel)
        if name in HUNG_MODULES:
            item.add_marker(pytest.mark.hung)


@pytest.fixture(autouse=True)
def no_real_team_sequence(monkeypatch):
    """No test writes the team bundle sequence to the real Credential Manager."""

    from ghostcursor.workspace import team

    store: dict[str, str] = {}
    monkeypatch.setattr(
        team.keys, "get_key",
        lambda name, allow_env=True, _real=team.keys.get_key: (
            store.get(name) if name.startswith("TeamBundleSequence") else _real(name, allow_env=allow_env)
        ),
    )
    monkeypatch.setattr(
        team.keys, "set_key",
        lambda name, value, _real=team.keys.set_key: (
            store.__setitem__(name, value) if name.startswith("TeamBundleSequence") else _real(name, value)
        ),
    )


@pytest.fixture(autouse=True)
def no_real_chatgpt_sign_in(monkeypatch, tmp_path_factory):
    """No test reads the owner's real Sign in with ChatGPT record: a signed-in
    machine would otherwise send hermetic-test prompts to their plan."""

    from ghostcursor.providers import chatgpt

    path = tmp_path_factory.mktemp("chatgpt") / "chatgpt.cred"
    monkeypatch.setattr(chatgpt, "store_path", lambda: path)
    monkeypatch.delenv("ORBYN_CHATGPT_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def no_real_user_settings(monkeypatch, tmp_path_factory):
    """No test reads or writes the user's own switches (D179: pictures to Jev)."""

    from ghostcursor import settings

    path = tmp_path_factory.mktemp("settings") / "settings.json"
    monkeypatch.setattr(settings, "_path", lambda: path)
    # Never this PC's own Office names in a test.
    monkeypatch.setattr(settings, "identity_terms", lambda: ())


@pytest.fixture(autouse=True)
def no_real_policy(monkeypatch):
    """No test reads this machine's organisation policy (D180); a test sets
    its own values through ``policy._value``."""

    from ghostcursor import policy

    monkeypatch.setattr(policy, "_value", lambda name: None)

@pytest.fixture(autouse=True)
def no_real_audit_log(monkeypatch, tmp_path_factory):
    """No test appends to this PC's audit log (D187)."""

    from ghostcursor import audit

    path = tmp_path_factory.mktemp("audit") / "audit.jsonl"
    monkeypatch.setattr(audit, "default_path", lambda: path)

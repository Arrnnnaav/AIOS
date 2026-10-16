"""D180: an organisation policy only lowers what leaves; screen text is scrubbed.

Pinned: with no policy nothing changes; MaxEgress 0 sends nothing to any
remote provider or search, 1 refuses pictures, an unreadable value fails
closed; BlockedApps are never bound; emails, URL queries, long numbers and
key-like tokens are masked in every Tainted value, while the local text stays.
"""

from __future__ import annotations

import pytest

from ghostcursor import policy, settings
from ghostcursor.harness.binding import BindingError, Identity, bind, bindable_windows
from ghostcursor.providers.envelope import Tainted, scrub
from ghostcursor.providers.errors import FailureKind, ProviderError
from ghostcursor.providers.gateway import Gateway
from ghostcursor.workspace import research as research_mod
from tests.test_jev_vision import _jev_reply
from tests.test_providers import _envelope, _keys, _transport


def _policy(monkeypatch, **values):
    monkeypatch.setattr(policy, "_value", lambda name: values.get(name))


def test_no_policy_changes_nothing():
    assert policy.max_egress() == policy.PICTURES and not policy.managed()
    assert policy.allows("jev", images=1) and policy.allows("chatgpt")


@pytest.mark.parametrize(
    "raw, level", [(0, 0), (1, 1), (2, 2), (9, 2), (-3, 0), ("x", 0), ("1", 1)]
)
def test_levels_are_clamped_and_an_unreadable_value_fails_closed(
    monkeypatch, raw, level
):
    _policy(monkeypatch, MaxEgress=raw)
    assert policy.max_egress() == level and policy.managed()


def test_local_only_sends_nothing_to_jev_or_any_remote_planner(monkeypatch, tmp_path):
    _policy(monkeypatch, MaxEgress=0)
    transport, calls = _transport(_jev_reply)
    gateway = Gateway(
        transport=transport,
        key_lookup=_keys(typesafe="k", nvidia="k", openrouter="k"),
        log_path=tmp_path / "l",
        system_two=("nvidia", "openrouter"),
    )
    with pytest.raises(ProviderError) as exc:
        gateway.choose(_envelope(), ("c1",), question="q?")
    assert exc.value.kind is FailureKind.NOT_CONFIGURED
    with pytest.raises(ProviderError) as exc:
        gateway.plan(_envelope())
    assert exc.value.kind is FailureKind.NOT_CONFIGURED
    assert calls == [] and gateway.budget.used == 0
    assert gateway.available() == {"jev": False, "nvidia": False, "openrouter": False}
    assert policy.allows("ollama")  # the local model may still answer


def test_text_level_refuses_pictures_but_not_text(monkeypatch, tmp_path):
    _policy(monkeypatch, MaxEgress=1)
    transport, calls = _transport(_jev_reply)
    gateway = Gateway(
        transport=transport, key_lookup=_keys(typesafe="k"), log_path=tmp_path / "l"
    )
    with pytest.raises(ProviderError):
        gateway.choose(_envelope(), ("c1",), question="q?", pictures={"w1": b"x"})
    assert calls == []
    gateway.choose(_envelope(), ("c1",), question="q?")
    assert len(calls) == 1


def test_the_users_picture_switch_is_off_under_a_lower_policy(monkeypatch):
    settings.set_jev_vision(True)
    assert settings.jev_vision()
    _policy(monkeypatch, MaxEgress=1)
    assert not settings.jev_vision()


def test_local_only_research_searches_nothing(monkeypatch, tmp_path):
    _policy(monkeypatch, MaxEgress=0)
    graph, trace = research_mod.research(
        "q",
        Gateway(key_lookup=_keys(), log_path=tmp_path / "l"),
        search=lambda q: pytest.fail("searched under local-only"),
        key_lookup=_keys(),
        trace_path=tmp_path / "t",
    )
    assert trace.search_provider == "none" and trace.failures == (
        "search: PermissionError",
    )
    assert trace.privacy == "question sent to none"


def test_blocked_apps_are_never_bound(monkeypatch):
    _policy(monkeypatch, BlockedApps=" Epic.exe ;; chrome.exe")
    ids = {11: Identity(1, "chrome.exe", "1"), 22: Identity(2, "epic.exe", "1")}
    found = bindable_windows(
        enumerate_windows=lambda: [(11, "a"), (22, "b")],
        identify_window=ids.get,
        own_pid=9,
    )
    assert found == []
    with pytest.raises(BindingError):
        bind([22], identify_window=ids.get, own_pid=9)


@pytest.mark.parametrize(
    "text, sent",
    [
        ("Inbox - bob.smith@acme.com", "Inbox - [email]"),
        ("Call +91 98765 43210", "Call [number]"),
        ("Card 4111 1111 1111 1111", "Card [number]"),
        ("https://x.com/a?token=abc#f", "https://x.com/a?[query]"),
        ("key sk-proj-abcdEFGH1234567890abcd", "key [token]"),
        ("2026-10-16 Order 12345 v1.14.2", "2026-10-16 Order 12345 v1.14.2"),
        ("Accessibility_Settings_Panel", "Accessibility_Settings_Panel"),
    ],
)
def test_screen_text_is_scrubbed_before_it_is_sent(text, sent):
    assert scrub(text) == sent
    assert Tainted.of("uia_name", text).text == sent

"""Personal Brain v1 and MVP contracts (D173).

Properties: only a user-stated, supported, non-temporary, non-sensitive,
confident memory is durable; everything else is session-scoped and expires;
sensitive text is never stored; a correction overrides; pause, forget,
export and erase work; a cited id must exist and be in context.
"""

from __future__ import annotations

import json

import pytest

from ghostcursor.workspace.brain import SESSION_TTL_S, Brain, eligibility
from ghostcursor.workspace.contracts import (
    Claim,
    ClaimStatus,
    CitationError,
    EvidenceGraph,
    Passage,
    Source,
    SourceCategory,
    SpatialContextReference,
    categorize,
)

TURN = "I always prefer dark themes and short bullet summaries in my decks."


@pytest.fixture
def brain(tmp_path):
    now = [1000.0]
    b = Brain(tmp_path / "brain.sqlite", clock=lambda: now[0])
    b.now = now
    yield b
    b.close()


def test_a_supported_user_preference_is_durable(brain):
    m = brain.remember(
        "preference",
        "prefers dark themes",
        origin="user_stated",
        confidence=0.9,
        user_turn=TURN,
    )
    assert m.scope == "durable" and m.expires is None


@pytest.mark.parametrize(
    "text, origin, confidence, turn",
    [
        ("prefers dark themes", "model_inferred", 0.99, TURN),  # inferred, not stated
        ("prefers serif fonts", "user_stated", 0.9, TURN),  # not in the user's words
        ("prefers dark themes", "user_stated", 0.5, TURN),  # not confident
        (
            "use dark themes for now",
            "user_stated",
            0.9,
            "use dark themes for now",
        ),  # temporary
    ],
)
def test_unsupported_or_temporary_memories_stay_session_scoped(
    brain, text, origin, confidence, turn
):
    m = brain.remember(
        "preference", text, origin=origin, confidence=confidence, user_turn=turn
    )
    assert m.scope == "session"
    brain.now[0] += SESSION_TTL_S + 1
    assert brain.list() == []  # expired


@pytest.mark.parametrize(
    "text",
    [
        "my password is hunter2",
        "api key nvapi-abc",
        "card 4111111111111111",
        "token sk-abc",
    ],
)
def test_sensitive_text_is_never_stored(brain, text):
    assert (
        brain.remember("fact", text, origin="user_stated", confidence=1, user_turn=text)
        is None
    )
    assert brain.list(include_inactive=True) == []


def test_unknown_class_is_refused():
    assert eligibility("opinion", "x y", "user_stated", 1, "x y") == "refused"


def test_a_restated_preference_supersedes_and_a_correction_overrides(brain):
    first = brain.remember(
        "preference",
        "prefers dark themes",
        origin="user_stated",
        confidence=0.9,
        user_turn=TURN,
    )
    second = brain.remember(
        "preference",
        "prefers dark themes always",
        origin="user_stated",
        confidence=0.9,
        user_turn=TURN + " always",
    )
    assert (
        brain.get(first.mid).status == "superseded"
        and brain.get(second.mid).status == "active"
    )
    fixed = brain.correct(second.mid, "prefers light themes")
    assert fixed.origin == "user_corrected" and fixed.scope == "durable"
    assert [m.text for m in brain.list()] == ["prefers light themes"]


def test_pause_forget_export_and_erase(brain):
    brain.pause()
    assert (
        brain.remember(
            "goal",
            "ship the deck",
            origin="user_stated",
            confidence=1,
            user_turn="ship the deck",
        )
        is None
    )
    brain.pause(False)
    m = brain.remember(
        "goal",
        "ship the deck",
        origin="user_stated",
        confidence=1,
        user_turn="ship the deck",
    )
    assert json.loads(brain.export())[0]["text"] == "ship the deck"
    assert brain.search("deck")[0].mid == m.mid
    assert brain.forget(m.mid) and brain.list() == []
    brain.remember(
        "goal",
        "ship the deck",
        origin="user_stated",
        confidence=1,
        user_turn="ship the deck",
    )
    brain.erase_all()
    assert brain.list(include_inactive=True) == [] and not brain.paused


def test_relevant_is_minimized_and_ranked(brain):
    for text in ("ship the investor deck", "prefers dark themes", "likes hiking"):
        brain.remember(
            "goal" if "deck" in text else "preference",
            text,
            origin="user_stated",
            confidence=1,
            user_turn=text,
        )
    top = brain.relevant("finish the investor deck", k=2)
    assert top[0].text == "ship the investor deck" and len(top) == 2


# --- contracts ------------------------------------------------------------------


def _graph(*claims):
    return EvidenceGraph(
        "q",
        (
            Source(
                "s1", "https://docs.python.org/3/", "Docs", SourceCategory.PRIMARY_DOCS
            ),
        ),
        (Passage("p1", "s1", "text"),),
        claims,
    )


def test_citations_must_exist_and_supported_claims_must_cite():
    _graph(
        Claim("a", ClaimStatus.SUPPORTED, ("p1",)),
        Claim("b", ClaimStatus.UNRESOLVED, ()),
    ).validate()
    with pytest.raises(CitationError):
        _graph(Claim("a", ClaimStatus.SUPPORTED, ("p9",))).validate()
    with pytest.raises(CitationError):
        _graph(Claim("a", ClaimStatus.SUPPORTED, ())).validate()
    with pytest.raises(CitationError):
        EvidenceGraph("q", (), (Passage("p1", "s9", "t"),)).validate()


def test_sources_get_a_category_never_a_score():
    assert categorize("https://docs.python.org/3/x") is SourceCategory.PRIMARY_DOCS
    assert categorize("https://www.cdc.gov/a") is SourceCategory.GOVERNMENT
    assert categorize("https://arxiv.org/abs/1") is SourceCategory.ACADEMIC
    assert categorize("https://stackoverflow.com/q/1") is SourceCategory.COMMUNITY
    assert categorize("https://example.com") is SourceCategory.UNKNOWN


def test_spatial_reference_carries_no_geometry():
    ref = SpatialContextReference("point", "Insert", "TabItem", "powerpnt.exe", 0.95)
    assert set(vars(ref)) == {
        "mark_kind",
        "name",
        "control_type",
        "application",
        "confidence",
        "alternatives",
        "version",
    }
    assert "Insert" in ref.as_text() and len(ref.digest()) == 64


@pytest.mark.parametrize("text", ["my PIN is 1234", "pw: hunter2"])
def test_short_pins_and_passwords_are_refused(brain, text):
    assert brain.remember("fact", text, origin="user_stated", confidence=1, user_turn=text) is None


def test_a_refused_correction_keeps_the_original(brain):
    kept = brain.remember(
        "preference",
        "I prefer dark slides",
        origin="user_stated",
        confidence=0.9,
        user_turn="I prefer dark slides",
    )
    assert brain.correct(kept.mid, "my password is hunter2") is None
    assert [m.mid for m in brain.list()] == [kept.mid]


def test_a_correction_applies_while_learning_is_paused(brain):
    kept = brain.remember(
        "preference",
        "I prefer dark slides",
        origin="user_stated",
        confidence=0.9,
        user_turn="I prefer dark slides",
    )
    brain.pause()
    fixed = brain.correct(kept.mid, "I prefer light slides")
    assert fixed is not None and fixed.origin == "user_corrected"
    assert [m.text for m in brain.list()] == ["I prefer light slides"]


def test_a_forgotten_memory_is_not_left_in_the_file(brain):
    secret = "zebra-quokka-unusual-marker"
    kept = brain.remember(
        "fact",
        f"my project codename is {secret}",
        origin="user_stated",
        confidence=0.9,
        user_turn=f"my project codename is {secret}",
    )
    brain.forget(kept.mid)
    brain.close()
    assert secret.encode() not in brain.path.read_bytes()


def test_a_memory_restated_each_turn_is_kept_once(brain):
    first = brain.remember(
        "preference", "prefers dark themes", origin="model_inferred", confidence=0.9
    )
    again = brain.remember(
        "preference", "Prefers dark themes", origin="model_inferred", confidence=0.9
    )
    assert again.mid == first.mid and len(brain.list()) == 1
    durable = brain.remember(  # now stated by the user: promoted, not dropped
        "preference",
        "prefers dark themes",
        origin="user_stated",
        confidence=0.9,
        user_turn=TURN,
    )
    assert durable.scope == "durable"

"""Deck planning (D186): a goal -> a reviewable DeckSpec, grounded in the
owner's reviewed Company Brain facts, built from the first System-Two provider
that answers validly. Hermetic: an injected MockTransport plays the reply."""

from __future__ import annotations

import json

import httpx

from ghostcursor.providers import Gateway, SlideLayout
from ghostcursor.workspace.deck import plan_deck
from ghostcursor.workspace.knowledge import Knowledge

DECK = {
    "title": "Platform Review",
    "slides": [
        {"title": "Platform Review", "bullets": [], "layout": "title"},
        {
            "title": "Where we run",
            "bullets": ["Prod is in us-east-1"],
            "layout": "bullets",
        },
    ],
}


def _transport(capture):
    def handler(request):
        capture.append(request)
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [{"message": {"content": json.dumps(DECK)}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 7},
            },
        )

    return httpx.MockTransport(handler)


def _gateway(capture, **kw):
    return Gateway(
        system_two=("openrouter",),
        transport=_transport(capture),
        key_lookup=lambda name: "k" if name == "openrouter" else None,
        **kw,
    )


def test_plan_deck_returns_a_closed_deck_spec(tmp_path):
    calls = []
    gw = _gateway(calls, log_path=tmp_path / "l")
    deck = plan_deck(gw, "review the platform")
    assert deck.title == "Platform Review" and len(deck.slides) == 2
    assert deck.slides[0].layout is SlideLayout.TITLE


def test_plan_deck_grounds_in_reviewed_brain_facts(tmp_path):
    kb = Knowledge(tmp_path / "k.sqlite")
    f = kb.add_candidate("Prod runs in us-east-1.", source="runbook", scope="acme")
    kb.approve(f.fid)
    secret = kb.add_candidate(
        "Root password is hunter2.",
        source="vault",
        scope="acme",
        sensitivity="sensitive",
    )
    kb.approve(secret.fid)

    calls = []
    gw = _gateway(calls, log_path=tmp_path / "l")
    # goal shares a stem with the fact so BM25 recall surfaces it as grounding
    plan_deck(gw, "where does prod run", scope="acme", knowledge=kb)

    body = calls[0].content.decode()
    assert "us-east-1" in body  # reviewed fact is grounding
    assert "hunter2" not in body  # sensitive fact never reaches the model path
    kb.close()


def test_plan_deck_rejects_an_empty_goal(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        plan_deck(_gateway([], log_path=tmp_path / "l"), "   ")


def test_build_brief_renders_every_slide_in_order():
    """The DeckSpec -> Act bridge: a plain-string build goal the existing Teach/
    Act loop runs. Data only -- it names what to build, not which control."""

    from ghostcursor.providers import DeckSpec, Slide, SlideLayout
    from ghostcursor.workspace.deck import build_brief

    spec = DeckSpec(
        title="Q3 Review",
        slides=(
            Slide("Q3 Review", (), SlideLayout.TITLE),
            Slide("Wins", ("Shipped DLP", "3 accounts"), SlideLayout.BULLETS),
        ),
    )
    brief = build_brief(spec)
    assert "Q3 Review" in brief
    assert "Slide 1 [title]: Q3 Review" in brief
    assert "Slide 2 [bullets]: Wins" in brief
    # bullets kept, in order, under their slide
    assert brief.index("Shipped DLP") < brief.index("3 accounts")
    assert "- Shipped DLP" in brief

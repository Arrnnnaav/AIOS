"""The drive_until engine (D185): a gated, goal-driven loop. Autonomy over
plan-approval Act, so it refuses without approval, never touches the deny
list, stops on ESC, is bounded, and returns a typed Result -- never a guess."""

from __future__ import annotations

from dataclasses import dataclass

from ghostcursor.harness.drive import CONFIDENCE_FLOOR, drive_until
from ghostcursor.providers.schemas import ABSTAIN, Choice


@dataclass(frozen=True)
class C:
    id: str
    name: str


def _choice(cid, p=0.9):
    return Choice(cid, {cid: p, ABSTAIN: 1 - p})


def _engine(picks, controls=None, **kw):
    controls = controls if controls is not None else [C("a", "Save"), C("b", "Next")]
    acted = []
    seq = iter(picks)
    kw.setdefault("approved", True)
    r = drive_until(
        "reach the goal",
        observe=lambda: controls,
        choose=lambda g, cs: next(seq),
        act=lambda c: acted.append(c.id),
        **kw,
    )
    return r, acted


def test_refuses_without_approval():
    r, acted = _engine([_choice("a")], approved=False)
    assert r.status == "not_approved" and acted == []


def test_acts_then_finishes_on_done():
    r, acted = _engine([_choice("a"), Choice("DONE", {"DONE": 1.0})])
    assert r.status == "done" and acted == ["a"] and r.history == ("Save",)


def test_low_confidence_hands_back():
    r, acted = _engine([Choice("a", {"a": CONFIDENCE_FLOOR - 0.1, ABSTAIN: 0.1})])
    assert r.status == "handed_back" and "confidence" in r.reason and acted == []


def test_a_tie_hands_back():
    r, acted = _engine([Choice("a", {"a": 0.5, "b": 0.45})])  # margin < 0.2
    assert r.status == "handed_back" and acted == []


def test_abstain_hands_back():
    r, acted = _engine([Choice(ABSTAIN, {ABSTAIN: 0.9})])
    assert r.status == "handed_back" and acted == []


def test_deny_blocks_even_when_chosen():
    r, acted = _engine([_choice("a")], controls=[C("a", "Delete all")], deny=["delete"])
    assert r.status == "blocked" and "deny" in r.reason and acted == []


def test_empty_surface_blocks():
    r = drive_until("g", observe=lambda: [], choose=lambda g, c: None,
                    act=lambda c: None, approved=True)  # fmt: skip
    assert r.status == "blocked"


def test_stop_ends_before_acting():
    r, acted = _engine([_choice("a")], stop=lambda: True)
    assert r.status == "stopped" and acted == []


def test_bounded_by_max_steps():
    r, acted = _engine([_choice("a")] * 10, max_steps=3)
    assert r.status == "max_steps" and len(acted) == 3


def test_an_action_that_raises_blocks():
    def boom(c):
        raise RuntimeError("gone")

    r = drive_until("g", observe=lambda: [C("a", "Save")],
                    choose=lambda g, c: _choice("a"), act=boom, approved=True)  # fmt: skip
    assert r.status == "blocked" and "could not act" in r.reason


def test_drive_live_wiring_without_a_desktop(monkeypatch):
    """drive_live over injected observe/perform: refuses unapproved, then
    clicks the Jev pick and stops on DONE. No real window, no real click."""
    from ghostcursor.harness import teach_live
    from ghostcursor.providers.schemas import Choice

    @dataclass(frozen=True)
    class Cand:
        cid: str
        name: str

    class Frame:
        candidates = (Cand("w1-1", "Insert"), Cand("w1-2", "Delete"))

        def get(self, cid):
            return next((c for c in self.candidates if c.cid == cid), None)

    acted = []
    calls = {"n": 0}

    class G:
        def choose(self, envelope, option_ids, **kw):
            calls["n"] += 1
            assert "DONE" in option_ids and "w1-1" in option_ids
            if calls["n"] == 1:
                return Choice("w1-1", {"w1-1": 0.95})
            return Choice("DONE", {"DONE": 1.0})

    common = dict(
        gateway=G(),
        _observe=lambda: Frame(),
        _perform=lambda step, target: acted.append((target.cid, step.action)) or "clicked",
    )
    refused = teach_live.drive_live("open insert", None, approved=False, **common)
    assert refused.status == "not_approved" and acted == []

    ok = teach_live.drive_live("open insert", None, approved=True, deny=["delete"], **common)
    assert ok.status == "done" and acted == [("w1-1", "click")]

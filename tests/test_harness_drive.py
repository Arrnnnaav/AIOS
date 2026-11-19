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
        window: str = "w1"
        rect: tuple = (0, 0, 40, 20)

        @property
        def runtime_id(self):
            return (self.cid,)

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


def test_a_busy_user_costs_a_step_not_the_run():
    class Busy(PermissionError):
        retry = True

    tries = []

    def act(c):
        tries.append(c.id)
        if len(tries) == 1:
            raise Busy("holding a key")

    picks = iter([_choice("a"), _choice("a"), _choice("DONE")])
    r = drive_until("g", observe=lambda: [C("a", "Save")],
                    choose=lambda g, c: next(picks), act=act, approved=True)  # fmt: skip
    assert r.status == "done" and tries == ["a", "a"]


def test_drive_live_never_clicks_a_control_that_moved_during_the_model_call():
    from ghostcursor.harness import teach_live
    from ghostcursor.providers.schemas import Choice

    @dataclass(frozen=True)
    class Cand:
        cid: str
        name: str
        rect: tuple
        window: str = "w1"

        @property
        def runtime_id(self):
            return (self.cid,)

    class Frame:
        def __init__(self, rect):
            self.candidates = (Cand("w1-1", "Insert", rect),)

        def get(self, cid):
            return next((c for c in self.candidates if c.cid == cid), None)

    frames = iter([Frame((0, 0, 40, 20)), Frame((500, 500, 540, 520))])

    class G:
        def choose(self, envelope, option_ids, **kw):
            return Choice("w1-1", {"w1-1": 0.95})

    acted = []
    r = teach_live.drive_live(
        "open insert", None, approved=True, gateway=G(),
        _observe=lambda: next(frames),
        _perform=lambda step, target: acted.append(target.cid) or "clicked",
    )  # fmt: skip
    assert r.status == "blocked" and "moved" in r.reason and acted == []


def test_drive_live_rechecks_the_deny_list_on_the_name_it_would_click():
    from ghostcursor.harness import teach_live
    from ghostcursor.providers.schemas import Choice

    @dataclass(frozen=True)
    class Cand:
        cid: str
        name: str
        rect: tuple = (0, 0, 40, 20)
        window: str = "w1"

        @property
        def runtime_id(self):
            return (self.cid,)

    class Frame:
        def __init__(self, name):
            self.candidates = (Cand("w1-1", name),)

        def get(self, cid):
            return next((c for c in self.candidates if c.cid == cid), None)

    frames = iter([Frame("Insert"), Frame("Delete all")])  # renamed during choose()

    class G:
        def choose(self, envelope, option_ids, **kw):
            return Choice("w1-1", {"w1-1": 0.95})

    acted = []
    r = teach_live.drive_live(
        "open insert", None, approved=True, gateway=G(), deny=["delete"],
        _observe=lambda: next(frames),
        _perform=lambda step, target: acted.append(target.cid) or "clicked",
    )  # fmt: skip
    assert r.status == "blocked" and "deny" in r.reason and acted == []



def test_held_key_retries_are_not_counted_as_steps():
    from ghostcursor.harness.act import UserBusy
    from ghostcursor.harness.drive import drive_until
    from ghostcursor.providers.schemas import Choice

    @dataclass(frozen=True)
    class C:
        id: str
        name: str

    picks = iter(["a", "a", "DONE"])
    held = iter([True, False])

    def act(control):
        if next(held, False):
            raise UserBusy("holding a key")

    r = drive_until(
        "g",
        observe=lambda: [C("a", "Next")],
        choose=lambda goal, cs: Choice(next(picks), {"a": 0.95}),
        act=act,
        approved=True,
        max_steps=1,
    )
    assert r.status == "max_steps" and r.steps == 1 and r.history == ("Next",)


def test_a_key_held_through_every_retry_hands_back_as_busy():
    from ghostcursor.harness.act import UserBusy
    from ghostcursor.harness.drive import MAX_BUSY, drive_until
    from ghostcursor.providers.schemas import Choice

    @dataclass(frozen=True)
    class C:
        id: str
        name: str

    tries = []

    def act(control):
        tries.append(1)
        raise UserBusy("holding a key")

    r = drive_until(
        "g",
        observe=lambda: [C("a", "Next")],
        choose=lambda goal, cs: Choice("a", {"a": 0.95}),
        act=act,
        approved=True,
        max_steps=8,
    )
    assert r.status == "busy" and r.steps == 0 and len(tries) == MAX_BUSY + 1



def test_drive_live_refuses_a_stale_screen_reading():
    from ghostcursor.harness import teach_live
    from ghostcursor.providers.schemas import Choice

    @dataclass(frozen=True)
    class Cand:
        cid: str
        name: str
        rect: tuple = (0, 0, 40, 20)
        window: str = "w1"

        @property
        def runtime_id(self):
            return (self.cid,)

    class Frame:
        minimized = incomplete = ()

        def __init__(self, at):
            self.at = at
            self.candidates = (Cand("w1-1", "Insert"),)

        def get(self, cid):
            return next((c for c in self.candidates if c.cid == cid), None)

    import time as _time

    old = _time.monotonic() - 60  # the observer stalled a minute ago
    frames = iter([Frame(old), Frame(old)])

    class G:
        def choose(self, envelope, option_ids, **kw):
            return Choice("w1-1", {"w1-1": 0.95})

    acted = []
    r = teach_live.drive_live(
        "open insert", None, approved=True, gateway=G(),
        _observe=lambda: next(frames),
        _perform=lambda step, target: acted.append(target.cid) or "clicked",
    )  # fmt: skip
    assert r.status == "blocked" and "out of date" in r.reason and acted == []


def _observer_with_reads(monkeypatch, reads):
    from types import SimpleNamespace

    from ghostcursor.harness import teach_live

    monkeypatch.setattr(teach_live, "OBSERVE_INTERVAL_S", 0.01)
    monkeypatch.setattr(teach_live, "read_window", lambda hwnd: next(reads))
    monkeypatch.setattr(teach_live, "still_bound", lambda b: True)
    monkeypatch.setattr(teach_live, "window_facts", lambda *a: ("t", ()))
    monkeypatch.setattr(teach_live, "is_minimized", lambda hwnd: False)
    monkeypatch.setattr(teach_live, "WindowObservation", lambda *a: a)
    monkeypatch.setattr(
        teach_live, "build_frame", lambda fid, at, obs, unnamed=False: ("frame", fid)
    )
    binding = SimpleNamespace(label="w1", hwnd=1, identity=SimpleNamespace(pid=2, executable="x.exe"))
    return teach_live.Observer((binding,))


def test_one_failed_window_read_does_not_end_the_session(monkeypatch):
    import itertools

    ok = ((0, 0, 10, 10), (), False)
    reads = itertools.chain([(None, (), False), (None, (), False)], itertools.repeat(ok))
    observer = _observer_with_reads(monkeypatch, reads)
    observer.start()
    observer.join(0.3)
    observer.stop()
    observer.join(2)
    assert observer.lost is None and observer.latest() is not None


def test_a_window_that_stays_unreadable_is_lost(monkeypatch):
    import itertools

    from ghostcursor.harness.teach_live import MAX_READ_MISSES

    reads = itertools.repeat((None, (), False))
    observer = _observer_with_reads(monkeypatch, reads)
    observer.start()
    observer.join(2)
    assert observer.lost == "w1" and observer.latest() is None and MAX_READ_MISSES > 1



def test_a_good_read_resets_the_miss_count(monkeypatch):
    import itertools

    ok = ((0, 0, 10, 10), (), False)
    miss = (None, (), False)
    reads = itertools.chain(
        itertools.islice(itertools.cycle([miss, miss, ok]), 30), itertools.repeat(ok)
    )
    observer = _observer_with_reads(monkeypatch, reads)
    observer.start()
    observer.join(0.6)
    observer.stop()
    observer.join(2)
    assert observer.lost is None


def test_a_risky_control_is_handed_back_not_clicked():
    # Rule 2: this loop cannot ask, so a risky control is never acted on.
    r, acted = _engine([_choice("a")], controls=[C("a", "Delete all")])
    assert r.status == "handed_back" and acted == []


def test_esc_during_the_model_call_acts_on_nothing():
    calls = iter([False, True])  # clear at the loop top, ESC while choose ran
    r, acted = _engine([_choice("a")], stop=lambda: next(calls))
    assert r.status == "stopped" and acted == []

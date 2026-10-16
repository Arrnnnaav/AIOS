"""D179: Jev may see redacted pictures, and checks research citations.

Pinned: a picture is grey except chrome controls; text fields, lists,
document names, big controls and the space between controls never leave;
pictures go only when the user switched them on and the text-only choice
failed; Jev still answers with an observed id; the citation check only ever
lowers a claim.
"""

from __future__ import annotations

import base64
import io
import json

import pytest
from PIL import Image

from ghostcursor import settings
from ghostcursor.harness import WindowObservation, build_frame
from ghostcursor.harness.frame import UNNAMED
from ghostcursor.harness.teach import ModelTeachSession, Verdict, gate
from ghostcursor.harness.vision import GREY, MAX_SIDE, MIN_SIDE, pictures, redact
from ghostcursor.providers import ABSTAIN, Choice, ExpectedChange, ProviderError
from ghostcursor.providers.errors import FailureKind
from ghostcursor.providers.gateway import Gateway
from ghostcursor.workspace.contracts import (
    Claim,
    ClaimStatus,
    EvidenceGraph,
    Passage,
    Source,
    SourceCategory,
)
from ghostcursor.workspace.research import check_claims
from tests.test_harness_teach import W1, FakeGateway, SyncSlot, _c, _plan
from tests.test_providers import _envelope, _keys, _transport

RED = (220, 20, 20)
WINDOW = (0, 0, 400, 300)


def _frame(controls, *, title="Deck", window=WINDOW, unnamed=False, minimized=False):
    return build_frame(
        1,
        0.0,
        [WindowObservation(W1, window, tuple(controls), False, minimized, title, 1)],
        unnamed=unnamed,
    )


def _red(size):
    return Image.new("RGB", size, RED)


# --- the picture -------------------------------------------------------------------


def test_only_chrome_controls_keep_their_pixels():
    frame = _frame(
        [
            _c(1, "Bold", "Button", (10, 50, 60, 90)),
            _c(2, "Search", "Edit", (100, 50, 300, 90)),
            _c(3, "Slide 1", "ListItem", (10, 150, 60, 200)),
            _c(4, "Report.docx", "TabItem", (100, 150, 160, 190)),  # names a document
            _c(5, "Canvas", "Button", (100, 200, 390, 290)),  # > 15% of the window
        ]
    )
    picture = redact(frame, "w1", _red((400, 300)))
    assert picture.getpixel((45, 80)) == RED  # inside the button, clear of its tag
    for inside in [(250, 80), (50, 190), (150, 182), (300, 270)]:
        assert picture.getpixel(inside) == GREY, inside
    assert picture.getpixel((5, 5)) == GREY  # title bar
    assert picture.getpixel((80, 120)) == GREY  # between controls


def test_pictures_respect_the_size_limits_and_skip_closed_or_empty_windows():
    big = _frame([_c(1, "Bold", "Button", (10, 10, 60, 40))], window=(0, 0, 3000, 2000))
    out = pictures(big, grab=lambda rect: _red((3000, 2000)))
    shot = Image.open(io.BytesIO(out["w1"]))
    assert shot.format == "JPEG" and max(shot.size) <= MAX_SIDE
    small = _frame([_c(1, "Bold", "Button", (1, 1, 20, 20))], window=(0, 0, 100, 50))
    shot = Image.open(io.BytesIO(pictures(small, grab=lambda r: _red((100, 50)))["w1"]))
    assert min(shot.size) >= MIN_SIDE
    assert pictures(_frame([]), grab=lambda r: _red((400, 300))) == {}
    hidden = _frame([_c(1, "Bold", "Button")], minimized=True)
    assert (
        pictures(hidden, grab=lambda r: pytest.fail("grabbed a minimized window")) == {}
    )


def test_unnamed_controls_join_only_when_pictures_may_go():
    icon = _c(1, "", "Button", (10, 50, 60, 90))
    assert _frame([icon]).candidates == ()
    frame = _frame([icon], unnamed=True)
    assert frame.model_view()["candidates"]["c1"]["name"].text == UNNAMED


# --- the request -------------------------------------------------------------------


def _jev_reply(request):
    import httpx

    return httpx.Response(
        200,
        json={
            "answers": {"choice": {"choice": "c1", "probabilities": {"c1": 0.9}}},
            "model": "jev-1",
            "usage": {"input_tokens": 9},
        },
    )


def test_pictures_go_as_assets_with_the_image_header_and_only_then(tmp_path):
    transport, calls = _transport(_jev_reply)
    gateway = Gateway(
        transport=transport, key_lookup=_keys(typesafe="k"), log_path=tmp_path / "l"
    )
    gateway.choose(_envelope(), ("c1", "c2"), question="q?")
    body = json.loads(calls[0].content)
    assert (
        "assets" not in body and "TypeSafe-Danger-Zone-Images" not in calls[0].headers
    )
    gateway.choose(
        _envelope(), ("c1", "c2"), question="q?", pictures={"w1": b"\xff\xd8x"}
    )
    body = json.loads(calls[1].content)
    assert calls[1].headers["TypeSafe-Danger-Zone-Images"] == "true"
    ref = body["state"]["pictures"]["w1"]
    assert base64.b64decode(body["assets"][ref]["data_base64"]) == b"\xff\xd8x"
    assert set(body["questions"]["choice"]["criteria"]) == {"c1", "c2", ABSTAIN}
    log = [json.loads(line) for line in (tmp_path / "l").read_text().splitlines()]
    assert [line["images"] for line in log] == [0, 1]
    assert "data_base64" not in (tmp_path / "l").read_text()


# --- when pictures are used --------------------------------------------------------


class SeeingGateway(FakeGateway):
    def __init__(self, plan, choices):
        super().__init__(plan, choices)
        self.pictures = []

    def choose(self, envelope, ids, *, question, cancelled, pictures=None):
        self.pictures.append(pictures)
        return super().choose(envelope, ids, question=question, cancelled=cancelled)


def _seeing(choices, look):
    gateway = SeeingGateway(_plan(ExpectedChange.CHOSEN_DISAPPEARS), choices)
    session = ModelTeachSession("g", gateway, SyncSlot(), clock=lambda: 0.0, look=look)
    return session, gateway


def test_a_failed_text_choice_looks_once_the_user_allowed_it():
    frame = _frame([_c(1, "Bold", "Button")])
    looked = []
    session, gateway = _seeing(
        [Choice(ABSTAIN, {ABSTAIN: 0.9}), Choice("c1", {"c1": 0.95})],
        lambda f: looked.append(f) or {"w1": b"jpeg"},
    )
    session.tick(frame)  # text only: abstains
    display = session.tick(frame)  # now with a picture
    assert gateway.pictures == [None, {"w1": b"jpeg"}]
    assert display.target is not None and display.target.cid == "c1"


def test_without_the_users_switch_no_picture_is_ever_taken():
    frame = _frame([_c(1, "Bold", "Button")])
    session, gateway = _seeing(
        [Choice(ABSTAIN, {ABSTAIN: 0.9})] * 3 + [Choice("c1", {"c1": 0.95})], None
    )
    for _ in range(4):
        session.tick(frame)
    assert gateway.pictures == [None] * 4


def test_each_step_starts_text_only_again():
    plan = _plan(ExpectedChange.CHOSEN_DISAPPEARS, ExpectedChange.CHOSEN_DISAPPEARS)
    gateway = SeeingGateway(
        plan,
        [
            Choice(ABSTAIN, {ABSTAIN: 0.9}),
            Choice("c1", {"c1": 0.95}),
            Choice("c1", {"c1": 0.95}),
        ],
    )
    session = ModelTeachSession(
        "g", gateway, SyncSlot(), clock=lambda: 0.0, look=lambda f: {"w1": b"j"}
    )
    first = _frame(
        [_c(1, "Bold", "Button"), _c(2, "Next", "Button", (100, 10, 150, 40))]
    )
    session.tick(first)
    session.tick(first)  # step 1 shown, with a picture
    after = _frame([_c(2, "Next", "Button", (100, 10, 150, 40))])
    session.tick(after)  # step 1 done (Bold disappeared); step 2 asks text-only
    assert gateway.pictures[-1] is None


def test_look_alikes_are_told_apart_only_with_pictures():
    twins = [
        _c(1, "", "Button", (10, 10, 40, 40)),
        _c(2, "", "Button", (60, 10, 90, 40)),
    ]
    frame = _frame(twins, unnamed=True)
    choice = Choice("c2", {"c2": 0.95})
    assert gate(choice, frame, frame)[0] is Verdict.REASK
    verdict, current, _ = gate(choice, frame, frame, seen=True)
    assert verdict is Verdict.DRAW and current.cid == "c2"


# --- the switch --------------------------------------------------------------------


def test_the_switch_is_off_unless_literally_turned_on(tmp_path):
    path = tmp_path / "s.json"
    assert settings.jev_vision(path) is False
    path.write_text('{"jev_vision": "yes"}')
    assert settings.jev_vision(path) is False
    path.write_text("not json")
    assert settings.jev_vision(path) is False
    settings.set_jev_vision(True, path)
    assert settings.jev_vision(path) is True
    settings.set_jev_vision(False, path)
    assert settings.jev_vision(path) is False


# --- the citation check ------------------------------------------------------------


def _graph(*statuses):
    return EvidenceGraph(
        "q",
        (Source("s1", "https://a.example", "A", list(SourceCategory)[0]),),
        (Passage("p1", "s1", "The sky is blue."),),
        tuple(Claim(f"claim {n}", s, ("p1",)) for n, s in enumerate(statuses)),
    )


class Judge:
    def __init__(self, verdicts=None, error=None):
        self.verdicts, self.error, self.asked = verdicts or {}, error, None

    def judge(self, envelope, questions, **kw):
        self.asked = (envelope, questions)
        if self.error:
            raise self.error
        return {qid: self.verdicts[qid] for qid in questions}


def test_a_confident_check_lowers_a_claim_and_never_raises_one():
    S = ClaimStatus
    graph = _graph(S.SUPPORTED, S.SUPPORTED, S.PARTIAL, S.CONTRADICTED)
    judge = Judge(
        {
            "claim_0": Choice("contradicts", {"contradicts": 0.9}),
            "claim_1": Choice("says_nothing", {"says_nothing": 0.5}),  # unsure: kept
            "claim_2": Choice("says_nothing", {"says_nothing": 0.85}),
        }
    )
    claims = check_claims(graph, judge)
    assert [c.status for c in claims] == [
        S.CONTRADICTED,
        S.SUPPORTED,
        S.UNRESOLVED,
        S.CONTRADICTED,
    ]
    envelope, questions = judge.asked
    assert set(questions) == {
        "claim_0",
        "claim_1",
        "claim_2",
    }  # never re-asks a contradicted one
    assert "sky is blue" in envelope.tainted_json() and "sky" not in json.dumps(
        envelope.trusted
    )


def test_the_check_failing_keeps_the_answer(tmp_path):
    from ghostcursor.workspace.research import research

    class Both(Judge):
        def complete(self, envelope, system, schema, parse, **kw):
            return parse(
                json.dumps({"claims": [{"text": "Sky is blue", "status": "supported", "evidence": ["p1"]}]})
            )

    hits = [{"url": "https://a.example/x", "title": "A", "passages": ["The sky is blue."]}]
    graph, trace = research(
        "q",
        Both(error=ProviderError(FailureKind.TIMEOUT)),
        search=lambda q: hits,
        key_lookup=lambda name: None,
        trace_path=tmp_path / "t.jsonl",
    )
    assert [c.status for c in graph.claims] == [ClaimStatus.SUPPORTED]
    assert "check: timeout" in trace.failures and "Jev" not in trace.privacy

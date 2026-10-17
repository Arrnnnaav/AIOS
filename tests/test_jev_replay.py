"""Jev replay comparison (D179): replays recorded cases against two models and
reports where they disagree. Offline via a MockTransport keyed on the model."""

from __future__ import annotations

import json

import httpx

from ghostcursor.devtools.jev_replay import compare

CASES = [
    {"task": "t", "trusted": {}, "tainted": {},
     "questions": {"q": {"type": "choice", "instructions": "pick", "criteria": {"a": "", "b": ""}}}},
    {"task": "t", "trusted": {}, "tainted": {},
     "questions": {"q": {"type": "choice", "instructions": "pick", "criteria": {"a": "", "b": ""}}}},
]


def _transport(answers_by_model):
    def handler(request):
        model = json.loads(request.content)["model"]
        choice = answers_by_model[model].pop(0)
        return httpx.Response(200, json={"answers": {"q": {"choice": choice, "probabilities": {choice: 1.0}}}})

    return httpx.MockTransport(handler)


def test_agreement_and_diffs_are_reported():
    # model X answers a,a ; model Y answers a,b -> one disagreement
    t = _transport({"jev-latest": ["a", "a"], "jev-preview": ["a", "b"]})
    r = compare(CASES, "jev-latest", "jev-preview", key="k", transport=t)
    assert r.total == 2 and r.agree == 1 and r.agreement == 0.5
    assert r.diffs[0]["case"] == 1 and r.diffs[0]["jev-latest"] == "a" and r.diffs[0]["jev-preview"] == "b"


def test_full_agreement_has_no_diffs():
    t = _transport({"jev-latest": ["a", "b"], "jev-preview": ["a", "b"]})
    r = compare(CASES, "jev-latest", "jev-preview", key="k", transport=t)
    assert r.agree == 2 and r.diffs == () and r.agreement == 1.0

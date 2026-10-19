"""Deep research (D186): decompose -> research each sub-question (cited) ->
file cited claims into the Company Brain as reviewable candidates. The research
loop every tool runs, on Orbyn's rails (nothing invented; results become
durable shared context). Hermetic: search and the model are stubbed."""

from __future__ import annotations

import json

from ghostcursor.workspace.knowledge import Knowledge
from ghostcursor.workspace.research import deep_research

HITS = [
    {
        "url": "https://docs.example.com/a",
        "title": "A",
        "passages": ["Prod runs in us-east-1 with three replicas."],
    }
]

CLAIMS = {
    "claims": [
        {
            "text": "Prod runs in us-east-1.",
            "status": "supported",
            "evidence": ["p1"],
        }
    ]
}


class PlanThenClaimsGateway:
    """complete() answers the plan schema with sub-questions and the research
    schema with claims -- deep_research calls it for both."""

    def __init__(self, subquestions):
        self.subquestions = subquestions
        self.calls = []

    def complete(self, envelope, system, schema, parse, **kw):
        self.calls.append(kw.get("purpose"))
        if "subquestions" in schema.get("properties", {}):
            return parse(json.dumps({"subquestions": list(self.subquestions)}))
        return parse(json.dumps(CLAIMS))


def _deep(gw, tmp_path, **kw):
    return deep_research(
        "how does prod run",
        gw,
        search=lambda q: HITS,
        key_lookup=lambda n: None,
        trace_path=tmp_path / "t.jsonl",
        **kw,
    )


def test_deep_research_decomposes_and_researches_each_subquestion(tmp_path):
    gw = PlanThenClaimsGateway(["where does prod run", "how many replicas"])
    report = _deep(gw, tmp_path)
    assert report.subquestions == ("where does prod run", "how many replicas")
    assert len(report.graphs) == 2  # one evidence graph per sub-question
    assert gw.calls.count("research planning") == 1  # planned once
    assert gw.calls.count("research") == 2  # then researched each part


def test_deep_research_files_cited_claims_into_the_brain(tmp_path):
    kb = Knowledge(tmp_path / "k.sqlite")
    gw = PlanThenClaimsGateway(["where does prod run", "how many replicas"])
    report = _deep(gw, tmp_path, knowledge=kb, scope="acme", file_to_brain=True)

    # the same supported claim from both sub-questions is deduped by ingest
    assert report.filed_to_brain == 1
    cands = kb.list(scope="acme", status="candidate")
    assert len(cands) == 1
    assert cands[0].text == "Prod runs in us-east-1."
    assert cands[0].source == "https://docs.example.com/a"  # sourced to the page
    kb.close()


def test_only_cited_claims_are_filed_not_unresolved_or_contradicted(tmp_path):
    """Guard (hard-rule 8): only SUPPORTED/PARTIAL (cited) claims become Brain
    candidates; an UNRESOLVED or CONTRADICTED claim is never filed."""

    kb = Knowledge(tmp_path / "k.sqlite")

    class MixedClaimsGateway(PlanThenClaimsGateway):
        def complete(self, envelope, system, schema, parse, **kw):
            if "subquestions" in schema.get("properties", {}):
                return parse(json.dumps({"subquestions": ["only one"]}))
            return parse(
                json.dumps(
                    {
                        "claims": [
                            {
                                "text": "Prod runs in us-east-1.",
                                "status": "supported",
                                "evidence": ["p1"],
                            },
                            {
                                "text": "It is the fastest cloud.",
                                "status": "unresolved",
                                "evidence": [],
                            },
                        ]
                    }
                )
            )

    report = _deep(
        MixedClaimsGateway([]), tmp_path, knowledge=kb, scope="acme", file_to_brain=True
    )
    assert report.filed_to_brain == 1  # only the supported claim
    texts = [f.text for f in kb.list(scope="acme", status="candidate")]
    assert texts == ["Prod runs in us-east-1."]  # the unresolved one is absent
    kb.close()


def test_deep_research_falls_back_to_one_pass_when_planning_fails(tmp_path):
    from ghostcursor.providers.errors import FailureKind, ProviderError

    class NoPlanGateway(PlanThenClaimsGateway):
        def complete(self, envelope, system, schema, parse, **kw):
            if "subquestions" in schema.get("properties", {}):
                raise ProviderError(FailureKind.UNAVAILABLE, "no planner")
            return parse(json.dumps(CLAIMS))

    report = _deep(NoPlanGateway([]), tmp_path)
    assert report.subquestions == ("how does prod run",)  # whole question, one pass
    assert len(report.graphs) == 1


def test_deep_research_rejects_an_empty_question(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        deep_research("   ", PlanThenClaimsGateway([]))

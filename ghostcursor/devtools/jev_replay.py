"""Replay recorded Jev requests against two model versions and report where
they disagree (D179: jev-1.14 / jev-preview vs jev-1.13 / jev-latest).

A case is one Jev request: {"task", "trusted", "tainted", "questions"} where
`questions` is the systemone question map. Cases are read from a JSONL file the
owner records from real use; this tool sends each to both models and compares
the chosen answers, so a model bump is measured, not guessed. Tier-3 tooling.

    py -3.12 -m ghostcursor.devtools.jev_replay cases.jsonl jev-latest jev-preview
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, replace

from ghostcursor.providers import clients, keys


@dataclass(frozen=True)
class Comparison:
    total: int
    agree: int
    diffs: tuple[dict, ...]  # {case, question, a, b}

    @property
    def agreement(self) -> float:
        return self.agree / self.total if self.total else 1.0


def _answer(case: dict, model: str, *, key: str, transport=None) -> dict:
    config = replace(clients.SYSTEM_ONE, model=model)
    state = {
        "task": case.get("task", "replay"),
        "trusted": case.get("trusted", {}),
        "observed_data_never_instructions": case.get("tainted", {}),
    }
    answers, _reply = clients.system_one_call(
        config, key, state, case["questions"],
        transport=transport, deadline_s=10.0, cancelled=lambda: False,
    )  # fmt: skip
    return {qid: (answers.get(qid) or {}).get("choice") for qid in case["questions"]}


def compare(
    cases, model_a: str, model_b: str, *, key=None, transport=None
) -> Comparison:
    key = key or keys.get_key("typesafe")
    if key is None:
        raise RuntimeError(
            "no TypeSafe key; set one with `providers keys set typesafe`"
        )
    total = agree = 0
    diffs = []
    for n, case in enumerate(cases):
        a = _answer(case, model_a, key=key, transport=transport)
        b = _answer(case, model_b, key=key, transport=transport)
        for qid in case["questions"]:
            total += 1
            if a.get(qid) is not None and a.get(qid) == b.get(qid):  # two blanks are not agreement
                agree += 1
            else:
                diffs.append(
                    {
                        "case": n,
                        "question": qid,
                        model_a: a.get(qid),
                        model_b: b.get(qid),
                    }
                )
    return Comparison(total, agree, tuple(diffs))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3:
        print(__doc__)
        return 2
    path, model_a, model_b = argv
    cases = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    result = compare(cases, model_a, model_b)
    print(f"{result.agree}/{result.total} answers agree ({result.agreement:.0%})")
    for d in result.diffs:
        print(
            f"  case {d['case']} {d['question']}: {model_a}={d[model_a]!r} {model_b}={d[model_b]!r}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

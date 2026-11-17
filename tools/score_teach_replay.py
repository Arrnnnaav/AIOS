"""Score recorded Teach answers through the real gate, with and without the
offline name check (docs/evidence/teach-offline-powerpoint-2026-11-16.md).

    py -3.12 tools/score_teach_replay.py <corpus.jsonl> [label=cassette.json ...]

A cassette is the file `teach_replay.gateway_chooser` writes. Corpus and
cassettes stay under the ignored .artifacts/ folder on the PC that made them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ghostcursor.evaluation import teach_replay as tr  # noqa: E402
from ghostcursor.providers.envelope import Tainted  # noqa: E402
from ghostcursor.providers.gateway import _agreed  # noqa: E402
from ghostcursor.providers.schemas import Choice  # noqa: E402


def chooser_for(tape: dict, check: bool):
    def choose(step):
        t = tape[step.step_id]
        choice = Choice(t["choice"], t["probabilities"])
        if not check:
            return choice
        controls = {
            c["cid"]: Tainted.of("control", f"{c['window']} | {c['type']} | {c['name']} | {c.get('region', '')}")
            for c in step.candidates
        }
        return _agreed(choice, step.instruction, controls)

    return choose


def main(argv: list[str]) -> int:
    steps = tr.load_corpus(Path(argv[0]))
    runs = [("lexical baseline", tr.lexical_chooser)]
    for spec in argv[1:]:
        label, path = spec.split("=", 1)
        tape = json.loads(Path(path).read_text(encoding="utf-8"))
        runs += [(f"{label} raw", chooser_for(tape, False)), (f"{label} + name check", chooser_for(tape, True))]
    for label, chooser in runs:
        report = tr.evaluate(steps, chooser)
        cells = []
        for split in ("dev", "test", "adversarial"):
            o = report[split]["overall"]
            cells.append(f"{split}: {o['pointer_shown']} shown / {o['wrong_pointer']} wrong / {o['wrong_pointer_high_risk']} high-risk")
        print(f"{label:28} | " + " | ".join(cells))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

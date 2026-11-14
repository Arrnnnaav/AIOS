"""How often does the default scrub change recorded on-screen names?

    py -3.12 tools/measure_scrub_names.py

Reads every JSON/JSONL record under .artifacts/ and docs/evidence/, collects
the string values of the fields name, label, title, text, uia_name and
control_name (1 to 200 characters), and counts how many the default scrub
(redact.scrub, no private words) changes, by category. Offline; no model.
Results of 15 Nov 2026: docs/evidence/scrub-on-screen-names-2026-11-15.md.
"""

from __future__ import annotations

import collections
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ghostcursor import redact  # noqa: E402

FIELDS = ("name", "label", "title", "text", "uia_name", "control_name")


def collect(patterns=(".artifacts/**/*.json*", "docs/evidence/**/*.json*")) -> tuple[int, set[str]]:
    names: set[str] = set()

    def walk(v, key=None):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, k)
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
        elif isinstance(v, str) and key in FIELDS and 0 < len(v) <= 200:
            names.add(v)

    files = [f for p in patterns for f in glob.glob(p, recursive=True)]
    for f in files:
        try:
            raw = open(f, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        try:
            docs = [json.loads(raw)]
        except ValueError:
            docs = []
            for line in raw.splitlines():
                try:
                    docs.append(json.loads(line))
                except ValueError:
                    pass
        for d in docs:
            walk(d)
    return len(files), names


def main() -> int:
    count, names = collect()
    changed = collections.Counter()
    for n in names:
        for c in redact.audit(redact.scrub(n)[1]):
            changed[c] += 1
    hit = sum(1 for n in names if redact.scrub(n)[1])
    print(f"files read: {count}; distinct on-screen names (fields {'/'.join(FIELDS)}, 1-200 chars): {len(names)}")
    print(f"changed by the default scrub: {hit} ({100 * hit / max(1, len(names)):.2f}%); by category: {dict(changed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Generate docs/governance/DECISIONS_INDEX.md: a curated rules map plus one
line per decision heading. Navigation only -- never a second source of truth."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

headings = [
    line[3:].strip()
    for line in (ROOT / "DECISIONS.md").read_text(encoding="utf-8").splitlines()
    if re.match(r"^## D\d{3}", line)
]

curated = """# Decision index

**Navigation only.** The rules in force are stated in full in `CLAUDE.md`; this
file maps them to the decisions that explain them, and lists every decision
heading so one entry can be found without reading `DECISIONS.md` (about 7,300
lines). Read a decision only when a task touches it. Regenerate the heading list
with the script named at the bottom; edit the curated table by hand.

## Rules in force, by subsystem

| Subsystem | Rule (stated in full in CLAUDE.md) | Why (decisions) |
|---|---|---|
| Process | Rigor proportional to risk: three tiers; only BLOCKING safety findings gate | D162 (amends D032, D139) |
| Direction | One app-agnostic, model-driven harness for Teach and Act; the per-app plugin system is retired | D193, D164, D161 |
| Safety / input | Input synthesis only in `harness/act.py`; scan enforced | D006, D109, D182 |
| Act authority | The whole plan approved first; only observed controls; risky controls ask first; ESC stops | D182, D193 |
| Pointer truth | A shown pointer is at a real, observed control; never a model-supplied position | D109, D112 |
| Kill switch | ESC and the session time limit always stop; Stop reaches a running Act at once | D020, D118 |
| Overlay | Click-through, topmost, `WM_PAINT`-only drawing; import `overlay.dpi` first | D009, D010 |
| Perception | The harness observer thread owns COM/UIA; frozen frames cross threads | D021, D022 |
| Privacy | No HWND/PID/keys/paths/screenshots leave the device; no raw handles in tracked files | D017, D122, D128, D147 |
| Providers | Model output is advice; closed schemas; tainted screen text never in instructions | D058, D147, D164 |
| Evidence | Never edit captured output; every number names its record | D034, D139 |
| Testing | Desktop lanes one at a time; the hung-window file alone | D025 |
| Retired path | Plugin-era records kept byte-exact in `docs/archive/retained-plugins/`; never edited | D193, D125, D139 |
| Spatial / SayStride | Separate projects; integrate by typed reference / transcript sidecar; port code with attribution | D143, D146, D161 |

## Where current status lives

- Phase order and status: `ROADMAP.md` (read only the section for your task).
- Call paths: `FLOW.md` (read only the section for your task).
- Open work: `docs/superpowers/FOLLOWUPS.md` (search, don't read whole).
- Measurements: `docs/evidence/`.

## Every decision, one line each

"""
lines = [f"- {h}" for h in headings]
footer = (
    "\n\n_Generated from `DECISIONS.md` headings by "
    "`py -3.12 tools/render_decisions_index.py`._\n"
)
out = ROOT / "docs" / "governance" / "DECISIONS_INDEX.md"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes((curated + "\n".join(lines) + footer).encode("utf-8"))
print(
    len(headings), "headings;", len((curated + "\n".join(lines)).splitlines()), "lines"
)

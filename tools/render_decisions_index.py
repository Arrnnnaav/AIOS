"""Generate docs/governance/DECISIONS_INDEX.md: a curated rules map plus one
line per decision heading. Navigation only -- never a second source of truth."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ghostcursor.devtools.campaign_pins import POWERPOINT_MANIFEST_SHA256  # noqa: E402

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
| Direction | App-agnostic, model-driven harness; PowerPoint is a test fixture; hand-written packs retired | D164, D161, D159 |
| Safety / input | Orbyn never types, clicks or moves the cursor outside the signed Act path; scan enforced | D006, D109 |
| Act authority | Signed plans only: PluginStore -> authorize_intent -> approval -> per-node authorization -> signed adapter -> independent verifier | D100-D104, D117-D124 |
| Pointer truth | A shown pointer is at a real, observed control; never a model-supplied position | D109, D112 |
| Kill switch | ESC and `--seconds` always stop; Stop/Pause within 0.5 s | D020, D118 |
| Overlay | Click-through, topmost, `WM_PAINT`-only drawing; import `overlay.dpi` first | D009, D010 |
| Perception | Worker thread owns COM/UIA; frozen primitives cross threads; one overwritten slot | D021, D022 |
| Privacy | No HWND/PID/keys/paths/screenshots leave the device; no raw handles in tracked files | D017, D122, D128, D147 |
| Providers | Model output is advice; closed schemas; tainted screen text never in instructions | D058, D147, D164 |
| Evidence | Never edit captured output; every number names its record | D034, D139 |
| Testing | Desktop lanes one at a time; hung-window files alone | D025 |
| Signing | Payload bytes are LF and pinned; rebuild/re-sign and move both pins together; current PowerPoint manifest `{MANIFEST}` | D125, D127, D149 |
| Campaigns | Declare in the committed ledger; nothing committed until the last attempt; retain every outcome | D150-D158, D163, D165 |
| Spatial / SayStride | Separate projects; integrate by typed reference / transcript sidecar; port code with attribution | D143, D146, D161 |

## Where current status lives

- Phase order and status: `ROADMAP.md` (read only the section for your task).
- Call paths: `FLOW.md` (read only the section for your task).
- Open work: `docs/superpowers/FOLLOWUPS.md` (search, don't read whole).
- Measurements: `docs/evidence/`.

## Every decision, one line each

""".replace("{MANIFEST}", POWERPOINT_MANIFEST_SHA256[:8])
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

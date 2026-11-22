# CLAUDE.md

Orbyn (code name GhostCursor): a Windows desktop guide that watches the screen,
works out the next step toward the user's goal, and shows where to act with a
transparent overlay (Teach), or performs the approved steps itself (Act), in
any application, through one model-driven harness (D164, D182, D193). The
package stays `ghostcursor`.

This file is the short list of rules that bind every change, plus commands.
History and rationale live in `DECISIONS.md`; the previous, much longer version
of this file is archived at `docs/archive/CLAUDE-pre-D162.md` for reference
only. Architecture: `FLOW.md`. Phase order and status: `ROADMAP.md`. Open work:
`docs/superpowers/FOLLOWUPS.md`. Measured results: `docs/evidence/`.

**Read in a bounded way.** Read one ROADMAP section and one FLOW section for the
task, find the decisions they cite through `docs/governance/DECISIONS_INDEX.md`,
and read only those entries. Never read the whole of `DECISIONS.md`, `FLOW.md`,
`FOLLOWUPS.md` or the Graphify report by default (AGENTS.md).

## Rigor is proportional to risk (D162)

| Tier | What | Required before merge |
|---|---|---|
| **1 Safety boundary** | Act approval and risky-control checks, input synthesis, what leaves the machine, kill switch (Stop/ESC/time limit), team-bundle signatures | tests + D018 mutation of the guard + one independent review |
| **2 Product feature** | Teach, workspace, Brain, perception, planning, providers | tests; one independent review per milestone, not per slice |
| **3 Tooling / docs / prototypes** | devtools, renderers, docs, experiments behind a flag | tests (where code) |

- A review gates only on a **BLOCKING safety** finding. Everything else goes to
  `FOLLOWUPS.md` and work continues. Never re-review until zero findings.
- Acceptance evidence (ledger, rendered campaign document, counted runs) is
  needed only to tell someone a release is accepted, not for daily work.
- Prototype behind a flag, measure on real use, then harden what proved useful.

## Hard rules (tier 1 — always)

1. **Input synthesis lives in one module:** `ghostcursor/harness/act.py`
   (D182, owner decision: Act on any application). The input-synthesis scan
   (`tests/test_no_input_synthesis.py`) pins it as the only one; keep it green.
2. **Act acts only after the user approves the whole plan,** only on a control
   the harness observed (never a model-supplied position), still asks before
   risky controls (`harness/teach.py` HIGH_RISK: delete, send, pay, submit,
   overwrite...), and ESC stops it. The harness is the only Act path (D193).
3. **A pointer that is shown is a pointer at a real, observed control.** Never
   draw at a model-supplied position.
4. **Kill switch:** ESC and the session time limit always stop a session;
   ESC is polled every tick and before every Act step (D020). The overlay is click-through,
   topmost, draws only in `WM_PAINT`, and imports `ghostcursor.overlay.dpi` first.
5. **UIA reads never run on the UI thread** (D021/D022): the harness observer
   thread owns COM/UIA; only frozen frames cross threads.
6. **Privacy:** no HWND, PID, credentials, keys, executable paths or screenshots
   leave the device. One exception (D179, owner decision): when the user has
   switched it on, a picture of a bound window in which only chrome controls
   keep their pixels (`ghostcursor/harness/vision.py`) may go to Jev after a
   text-only choice failed; never stored. The local stores (Brain, Company
   Brain, briefs) never sync, except a team bundle the owner signs and
   publishes (D187); keys never in tracked files. An organisation policy (`ghostcursor/policy.py`, D180)
   may only lower what leaves; screen text goes only through `Tainted.of` (scrubbed). No raw HWND or
   PID in any tracked file (the evidence hygiene scan enforces it).
7. **Evidence is honest:** never edit captured output; never present a number
   without saying where it is recorded (D034); say plainly when something was
   not run or not verified.
8. **Desktop test lanes run one at a time** (D025); the hung-window file never
   beside anything else. Never run two test sessions at once.

## Branches

- Work happens on `feature/product-shell-task-graphs`.
- Do not merge or cherry-pick into `main`, `submission/open-track`,
  `post-submission/model-durability` or `feature/plugin-platform-v1`.
- Retained evidence is byte-exact: `docs/evidence/` and
  `docs/archive/retained-plugins/` (the D193-retired plugin records) are never
  edited; their cited digests are checked by tests.

## Current state (details in ROADMAP.md)

- Direction: one app-agnostic, model-driven harness for Teach and Act on any
  application (D164, D182). The per-app plugin system (signed bundles, packs,
  compiled recipes, task graphs, the manager window, `run.py`) is retired
  (D193); its evidence stays in `docs/evidence/` and the archive.
- Product surface: the workspace app (D178): desktop island,
  Chat/Plan/Brain/Work, read-only background research and routines, Company
  Brain, GitHub read-only, user-level installer. Slash commands are
  console-only. Live Teach/Act measurement and release acceptance remain open.
- Spatial (`D:\PROJECTS\Spatial`) and SayStride are separate projects; reuse
  their code by porting with attribution, not by merging trees.

## Commands

```powershell
mkdir .tmp   # once

# Hermetic lane (fast; run before every commit)
py -3.12 -m pytest tests -m "not interactive and not pixel and not hung" --basetemp=.tmp\pytest-hermetic -p no:cacheprovider

# Desktop lanes — one at a time, nothing else running
py -3.12 -m pytest tests -m interactive --basetemp=.tmp\pytest-interactive -p no:cacheprovider
py -3.12 -m tests.test_overlay
py -3.12 -m pytest tests\test_hung_window.py --basetemp=.tmp\pytest-hung-window -p no:cacheprovider -o faulthandler_timeout=60

# Run
py -3.12 -m ghostcursor.workspace.app <topic>  # the workspace app (D178); /teach, /act in its console
py -3.12 tools\score_teach_replay.py <corpus.jsonl> [label=tape.json ...]  # score Teach choices offline
```

## Working practices

- Commit as soon as tests pass; one concern per commit.
- Give a reviewer its own worktree; never review and implement in one tree.
- Keep this file short: a new rule belongs here only if breaking it is a
  tier-1 risk. Everything else goes to `DECISIONS.md` or `FOLLOWUPS.md`.
- Dependencies: system Python 3.12 (`py -3.12`), pywin32, pywinauto, numpy,
  mss, winsdk, Pillow, rapidfuzz, ollama, httpx, PyJWT[crypto] (Sign in with ChatGPT).
- Voice (optional): faster-whisper, sounddevice; the "Hey Bro" fast wake word
  additionally wants sherpa-onnx plus the KWS model under
  `%LOCALAPPDATA%\GhostCursor\kws\` (Orbyn falls back to Whisper without it).
- Browser (D184): websocket-client, and a Chrome/Edge install.

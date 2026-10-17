# CLAUDE.md

Orbyn (code name GhostCursor): a Windows desktop guide that watches the screen,
works out the next step toward the user's goal, and shows where to act with a
transparent overlay (Teach). A narrow, signed path can also perform approved
steps in PowerPoint (Act). Package, payload paths and signed digests stay
`ghostcursor`.

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
| **1 Safety boundary** | Act authority chain, input synthesis, what leaves the machine, kill switch (Stop/ESC/`--seconds`), signed-bundle verification | tests + D018 mutation of the guard + one independent review |
| **2 Product feature** | Teach, manager, perception, planning, providers | tests; one independent review per milestone, not per slice |
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
   risky controls (delete, send, pay, overwrite), and ESC stops it. The signed
   PowerPoint plugin path (D100-D176) remains as a second, narrower Act.
3. **A pointer that is shown is a pointer at a real, observed control.** Never
   draw at a model-supplied position.
4. **Kill switch:** ESC and `--seconds` always stop a session; Stop/Pause reach
   a running Act within 0.5 s (D020). The overlay is click-through, topmost,
   draws only in `WM_PAINT`, and imports `ghostcursor.overlay.dpi` first.
5. **Perception never runs on the UI thread** (D021/D022): worker thread owns
   COM/UIA; only frozen primitives cross threads; one overwritten slot.
6. **Privacy:** no HWND, PID, credentials, keys, executable paths or screenshots
   leave the device. One exception (D179, owner decision): when the user has
   switched it on, a picture of a bound window in which only chrome controls
   keep their pixels (`ghostcursor/harness/vision.py`) may go to Jev after a
   text-only choice failed; never stored. `kb.sqlite` and `sessions.sqlite` never sync; no goal or
   screen text in `sessions.sqlite`; keys never in tracked files. An organisation policy (`ghostcursor/policy.py`, D180)
   may only lower what leaves; screen text goes only through `Tainted.of` (scrubbed). No raw HWND or
   PID in any tracked file (the evidence hygiene scan enforces it).
7. **Evidence is honest:** never edit captured output; never present a number
   without saying where it is recorded (D034); say plainly when something was
   not run or not verified.
8. **Desktop test lanes run one at a time** (D025); the hung-window files never
   beside anything else. Never run two test sessions at once.

## Branches

- Work happens on `feature/product-shell-task-graphs`.
- Do not merge or cherry-pick into `main`, `submission/open-track`,
  `post-submission/model-durability` or `feature/plugin-platform-v1`.
- Signed payload bytes are LF and are what is pinned (D125); rebuild and re-sign
  the PowerPoint bundle when its payload changes, and move the pin in
  `tests/test_powerpoint_manifest_pin.py` and `campaign_pins.py` together.

## Current state (details in ROADMAP.md)

- Production: PowerPoint only; VS Code and Excel installed but disabled (D130).
- Direction: Orbyn is an app-agnostic, model-driven harness working across
  applications; PowerPoint is a test fixture (D164). Hand-written packs are
  retired (D161).
- Act on PowerPoint: harness-path campaign accepted (D160); three real manager
  runs completed but no counted manager campaign (D163, D165).
- Now: harness steps 1-3 and step-4 tooling built (D164-D170); Spatial
  `--point`, SayStride `--voice` (D171) and the console MVP workspace
  (`ghostcursor/workspace/`, D173-D175) built; live measurement is next.
- Spatial (`D:\PROJECTS\Spatial`) and SayStride are separate projects; reuse
  their code by porting with attribution, not by merging trees.

## Commands

```powershell
mkdir .tmp   # once

# Hermetic lane (fast; run before every commit)
py -3.12 -m pytest tests -m "not interactive and not pixel and not hung" --basetemp=.tmp\pytest-hermetic -p no:cacheprovider

# Desktop lanes — one at a time, nothing else running
py -3.12 -m pytest tests -m interactive --basetemp=.tmp\pytest-interactive -p no:cacheprovider
py -3.12 -m pytest tests -m pixel --basetemp=.tmp\pytest-pixel -p no:cacheprovider
py -3.12 -m tests.test_overlay
py -3.12 -m tests.test_end_to_end
py -3.12 -m pytest tests\test_hung_window.py --basetemp=.tmp\pytest-hung-window -p no:cacheprovider -o faulthandler_timeout=60
py -3.12 -m pytest tests\test_perception_service_hung.py --basetemp=.tmp\pytest-hung-service -p no:cacheprovider -o faulthandler_timeout=60
py -3.12 -m pytest tests\test_run_threaded.py --basetemp=.tmp\pytest-hung-runtime -p no:cacheprovider -o faulthandler_timeout=60

# Run
py -3.12 -m ghostcursor.run --manager          # the manager window
py -3.12 -m ghostcursor.run --goal "<goal>"    # Teach from the CLI; ESC quits
py -3.12 -m ghostcursor.workspace.app <topic>  # the workspace app (D178)
py -3.12 -m ghostcursor.plugins list           # installed plugins

# Signed PowerPoint bundle
py -3.12 tools\build_ghostplugin.py --spec plugins\sources\powerpoint\plugin-source.json --private-key $HOME\.ghostcursor-keys\release.b64 --output .artifacts\bundles\<name>.ghostplugin

# Counted campaigns (release evidence only)
py -3.12 -m ghostcursor.devtools.act_campaign --campaign-id <id> ...          # harness
py -3.12 -m ghostcursor.devtools.act_manager_campaign --campaign-id <id> --attempt N
py -3.12 tools\render_act_campaign.py --harness|--manager <path> --out <doc> [--check]
```

## Working practices

- Commit as soon as tests pass; one concern per commit.
- Give a reviewer its own worktree; never review and implement in one tree.
- Keep this file short: a new rule belongs here only if breaking it is a
  tier-1 risk. Everything else goes to `DECISIONS.md` or `FOLLOWUPS.md`.
- Dependencies: system Python 3.12 (`py -3.12`), pywin32, pywinauto, numpy,
  mss, winsdk, Pillow, rapidfuzz, ollama, httpx, PyJWT[crypto] (Sign in with ChatGPT).

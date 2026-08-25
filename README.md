# GhostCursor

GhostCursor is a local Windows AI guide for unfamiliar software. A user states
a goal, GhostCursor observes the live application, points at one trusted next
control, waits for the human to act, and verifies the resulting application
state. It never moves the mouse or sends keyboard input.

The first real user is a new developer learning VS Code. Two validated real-app
workflows guide `Open a folder in VS Code` and `Open the integrated terminal in
VS Code`; each passed three consecutive interactive desktop runs. The same
natural-language planner is used by the CLI and the middle-right Ask control
rail.

## What makes the AI bounded

- Local Ollama/Qwen classifies a goal only into registered intent IDs.
- Executable authority comes only from schema-valid recipes under trusted local
  recipe directories.
- The screen-aware hint model may select only an observed, recipe-approved UI
  AutomationId.
- Model-generated paths, coordinates, code, and actions are rejected.
- A model-selected executable intent must also match the deterministic
  classifier's grounded intent; registration alone cannot authorize a recipe.
- If Ollama is unavailable, deterministic matching is reported as a fallback;
  invalid model output has a separate status.
- Deterministic perception, wrong-action feedback, verification, and safety
  remain in control.

The tested local model is `qwen3:4b-instruct`. Both inference paths now use one
non-retrying Ollama adapter with strict dynamic JSON Schemas, deterministic-ish
request options (`temperature: 0`, seed 42), bounded context/output, and a
15-minute session keep-alive. These settings improve consistency; they do not
promise bit-identical output across Ollama versions or hardware.

Schema conformance is not treated as semantic correctness. A versioned 30-case
gate separately records raw model quality and final execution authority. Its
first complete draft measured 86.7% raw semantic accuracy and 100% on exact
supported goals; four high-confidence over-commitments were denied authority by
the deterministic D058 policy. Owner-reviewed dataset 1.0.0 is frozen, and the
same 86.7% result plus every hard gate passed in two consecutive post-freeze
interactive runs. This is the accepted Qwen incumbent baseline.

## Run the validated workflows

Requirements: Windows, Python 3.12, VS Code for the real-app workflow, and an
optional local Ollama server.

Synthetic Export:

```powershell
py -3.12 -m ghostcursor.demo.synthetic_export_app
py -3.12 -m ghostcursor.run `
  --goal "Export this table as CSV" `
  --target "Synthetic Export" `
  --seconds 60
```

Real VS Code:

```powershell
code --new-window
py -3.12 -m ghostcursor.run `
  --goal "Open a folder in VS Code" `
  --target "Visual Studio Code" `
  --seconds 120
```

The user clicks the highlighted `Open Folder...` action and handles the native
Windows folder picker. GhostCursor verifies the resulting VS Code workspace
title before printing `Tour complete.`

Open the integrated terminal:

```powershell
py -3.12 -m ghostcursor.run `
  --goal "Open the integrated terminal in VS Code" `
  --target "Visual Studio Code" `
  --seconds 60
```

GhostCursor highlights VS Code's Toggle Panel location and tells the user to
press `Ctrl+\``. It does not send the shortcut. The tour completes only after
VS Code exposes the `Terminal Section` application state. If the terminal is
already visible, the goal completes without showing a shortcut that could
close it; otherwise the verified transition has a 20-second first-hint
deadline.

## Implemented safety and reliability

- UI Automation with executable-bounded HWND identity
- DPI-correct OCR fallback and visible inferred confidence
- Perception worker stage/heartbeat diagnostics with one bounded restart
- Focus-safe SPACE arbitration and always-available ESC/Stop
- Pause without losing the current step or overlay
- Wrong-action feedback and bounded re-hinting
- Strict application-pack manifests and recipe-path containment
- Local SQLite observations scoped by application/version/step
- Explicit unsupported and unavailable planner states
- Tested never-fabricate behavior for unsupported and close-but-unavailable goals

## Tests

The suite is split by environment so a deliberately hung window or a slow
pixel/UIA walk cannot contaminate the fast lane:

```powershell
py -3.12 -m pytest tests -m "not interactive and not pixel and not hung" `
  --basetemp=.tmp\pytest-hermetic -p no:cacheprovider

py -3.12 -m pytest tests -m interactive `
  --basetemp=.tmp\pytest-interactive -p no:cacheprovider

py -3.12 -m pytest tests -m pixel `
  --basetemp=.tmp\pytest-pixel -p no:cacheprovider
py -3.12 -m tests.test_overlay
py -3.12 -m tests.test_end_to_end
```

Desktop/UIA and pixel tests require an interactive Windows desktop. Hung-window
tests create a deliberately non-pumping window and must run one file at a time,
with no other test session active. The exact hung-lane commands are documented
in `CLAUDE.md`.

Every model/digest, prompt, schema, parser, adapter, or inference-policy change
also requires the three-lane model gate. Dataset 1.0.0 is owner-reviewed, so
the standing post-freeze command is:

```powershell
py -3.12 -m ghostcursor.evaluation.model_gate `
  --model qwen3:4b-instruct `
  --endpoint http://127.0.0.1:11434 `
  --unavailable-endpoint http://127.0.0.1:1 `
  --interactive
```

The interactive lane reads a real Synthetic Export UIA tree but cannot launch
a tour or synthesize input. Omitting `--interactive` is reported as a skip and
cannot close the milestone.

## Evidence

- `docs/evidence/vscode-open-terminal.md` records the real-desktop terminal
  acceptance gate and its limitations.
- `docs/evidence/never-fabricate-matrix.md` records supported and unsupported
  planner behavior with Qwen available and unavailable.
- `docs/evidence/novice-vscode-study.md` is the fixed participant protocol;
  its results remain blank until real sessions are completed.
- `docs/evidence/model-durability-draft.md` records the first 30-case local
  model diagnostic before label freeze; it remains historical evidence.
- `docs/evidence/model-durability-baseline.md` records the owner-reviewed,
  two-consecutive-pass incumbent baseline and layered no-action evidence.
- `docs/submission/demo-video-script.md` is the protected 4:45 demo sequence.

## Honest scope

Open Folder and Open Terminal are the two proven real VS Code workflows. The
terminal controls expose no stable AutomationIds, so GhostCursor deliberately
does not persist them or claim ID-based wrong-action feedback for that flow.
Installer, tray, startup automation, web retrieval, filesystem verification,
VLM tier 3, and additional application packs are deliberately deferred.

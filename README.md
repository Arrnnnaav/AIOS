# GhostCursor

GhostCursor is a local Windows AI guide for unfamiliar software. A user states
a goal, GhostCursor observes the live application, points at one trusted next
control, waits for the human to act, and verifies the resulting application
state. It never moves the mouse or sends keyboard input.

The first real user is a new developer learning VS Code. The validated real-app
workflow guides `Open a folder in VS Code`; it passed three consecutive
interactive desktop runs. The same natural-language path works from the CLI and
the middle-right Ask control rail.

## What makes the AI bounded

- Local Ollama/Qwen classifies a goal only into registered intent IDs.
- Executable authority comes only from schema-valid recipes under trusted local
  recipe directories.
- The screen-aware hint model may select only an observed, recipe-approved UI
  AutomationId.
- Model-generated paths, coordinates, code, and actions are rejected.
- If Ollama is unavailable, deterministic matching is reported as a fallback;
  invalid model output has a separate status.
- Deterministic perception, wrong-action feedback, verification, and safety
  remain in control.

The tested local model is `qwen3:4b-instruct`. Requests have one bounded
15-second budget and no retries.

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

## Tests

Focused submission-path checks currently used while the repository is being
split into hermetic, interactive, pixel, and hung-window lanes:

```powershell
py -3.12 -m pytest tests\test_planner.py tests\test_packs.py `
  tests\test_screen_hint.py tests\test_daemon.py `
  tests\test_synthetic_export.py -q -p no:cacheprovider

py -3.12 -m pytest tests\test_bar.py tests\test_run.py `
  -q -p no:cacheprovider
```

Desktop/UIA and pixel tests require an interactive Windows desktop. Hung-window
tests create a deliberately non-pumping window and must run alone. Exact
reproducible lane commands will replace the temporary focused commands during
the submission-readiness gate.

## Honest scope

Open Folder is the proven real VS Code workflow. Open Terminal is a gated
submission stretch only after repository readiness is green. Installer, tray,
startup automation, web retrieval, filesystem verification, VLM tier 3, and
additional application packs are deliberately deferred.

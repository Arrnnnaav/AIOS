# Orbyn

Orbyn is a **local-first Windows desktop guide** that watches the screen, works
out the next step toward your stated goal, and shows you **where to act** with a
transparent overlay. It can also, down a narrow and signed path, **perform
approved steps for you** in approved applications — only after you approve the
whole plan, only on a control it actually observed, and ESC always stops it.

Local data stays on the machine; configured cloud models and web research can
receive scrubbed request text. (Code name and package: `ghostcursor`.)

> Status: pre-1.0 (`0.1.0`). Teach works across observed Windows applications.
> Act code and a signed PowerPoint path exist, but Act activation and packaged
> release acceptance remain open. See **Honest scope** below.

## The two modes

**Teach** — you state a goal, Orbyn observes the live application, points at one
real, observed control, and waits for you to act, then verifies the resulting
state. It draws only at a control it actually saw — never a model-guessed
position — and a pointer that is shown is a pointer at a real control.

**Act** — the same plan, but Orbyn performs the steps. It acts **only after you
approve the whole plan**, only on controls the harness observed, still asks
before risky controls (delete, send, pay, overwrite), and ESC/Stop are required
to halt a running session promptly. All input synthesis lives in **one
auditable module** (`ghostcursor/harness/act.py`); a test fails if any other
module can synthesize input. The PowerPoint path is a signed test fixture;
release acceptance is still pending.

## What else is in the box

- **Company Brain** — a private, local knowledge graph. Facts carry their
  source, are scoped per tenant (one tenant's facts never leak to another),
  age, and surface conflicts instead of silently resolving them. Candidates
  stay candidates until you review them.
- **Models, your choice** — a configured cloud provider may be the default;
  local Ollama remains supported. An organization policy can only *lower* what
  may leave the machine.
- **Voice dictation** — speak text with spoken punctuation and formatting
  commands; it saves to a file or the Brain, and never types into an app on its
  own (that stays behind the Act gate).
- **Work hub** — a card board previews the current run, newest finished research
  result, latest answer or current
  plan, with keyboard navigation and a Stop control for live work. The tab
  also keeps the latest 20 generic task states locally and holds reusable
  agents. Unfinished work is marked interrupted after restart.
- **Brain views** — Personal memory, reviewed Company knowledge and setup
  controls have separate views. Plan's empty page leads back to the composer.
- **Background research** — start cited research in Work, close the window,
  and return to a locally saved answer. Download a finished result as Markdown
  directly from its card, ask a one-off follow-up about its first 8,000
  characters, or Keep up to five important results at the top of
  Work so new jobs do not evict them. Archive hides a finished result until you
  choose Show archived; unkept archived results still age out of the 20-job
  inbox. One workspace job runs at a time;
  Stop cancels it cooperatively. A crash marks it interrupted without retry.
- **Routines** — schedule hourly, daily or weekly research from Work. Enabled
  routines run while Orbyn and the PC are awake, even with the window closed;
  pause, resume, run now, delete or Quit Orbyn there. A missed time runs once
  after wake, with no catch-up burst. A crash may skip an occurrence rather
  than repeat it. Results land in the local job inbox.
- **GitHub, read only** — connect a fine-grained token in Work to view a
  bounded repository list and open issues. The token stays in Windows
  Credential Manager; disconnect removes it locally. Repository text does
  not enter model prompts or routines. Organization no-egress policy blocks
  GitHub requests. Orbyn cannot change GitHub content.
- **Ask a file** — choose a small text or code file in Work and ask one
  question about it. The answer stays in that sheet; the file and question are
  not added to the Brief or Brain. Text may go to the configured model provider.
- **Signed plugins** — bundle verification and a read-only catalog exist.
  Publisher identity and signed revocation for the marketplace still have
  release gates.

## Privacy and safety, by construction

- No window handles, process IDs, credentials, keys, executable paths, or
  screenshots leave the device. `kb.sqlite` and `sessions.sqlite` never sync.
- Text bound for a remote model goes through a scrub that masks emails, keys,
  card/account numbers and the like; a managed machine can force redaction on.
- Signed-bundle verification and a monotonic anti-rollback floor protect signed
  trust documents. Telemetry and sync are not production paths in this build.
- The kill switch (ESC, Stop/Pause, and a `--seconds` budget) always stops a
  session; the model can never synthesize ESC to defeat your stop key.

## Install

Windows, system Python 3.12 (`py -3.12`).

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 -m pip install -r requirements-voice.txt   # optional: voice/dictation
```

A packaged desktop build (PyInstaller onedir) is produced with:

```powershell
pwsh -File tools/build_orbyn.ps1          # -> dist/Orbyn/Orbyn.exe
```

`tools/Install-Orbyn.ps1` installs the built app for the current user with Start
Menu and Desktop shortcuts. Close Orbyn before updating. It stages the new
build and restores the prior install if the switch fails; uninstall keeps the
workspace data under `%LOCALAPPDATA%\GhostCursor`. The app and installer are
not yet code-signed or on an automatic update channel.
The packaged Work interface, including Chat, Plan, Brain, background research,
routines and a live read-only GitHub connection, has a recorded functional run
in `docs/evidence/workspace-live-acceptance-2026-10-26.md`.

## Run

```powershell
py -3.12 -m ghostcursor.workspace.app <topic>          # compact desktop island
py -3.12 -m ghostcursor.workspace.app --window <topic> # full floating workspace
py -3.12 -m ghostcursor.workspace.app --dock <topic>   # right-side workspace
py -3.12 -m ghostcursor.run --manager           # the manager window
py -3.12 -m ghostcursor.run --goal "<goal>"     # Teach from the CLI; ESC quits
py -3.12 -m ghostcursor.plugins list            # installed plugins
```

Orbyn.cmd launches a small, draggable, always-on-top island with amber Open and
a distinct Stop control. It expands while
work runs and briefly when a background result arrives. **Hide** dismisses it
while idle; **Ctrl+Alt+O** recalls it. Work and new results reveal a hidden
island, and **Open** on a new research result goes to Work. **Stop** signals the
current run; **Quit** exits Orbyn. If the shortcut is already taken, Hide stays
unavailable. The full workspace remains local behind a per-launch token.
`--target` narrows which window Orbyn binds; when several windows still
match it lists them and refuses rather than guessing.

## Tests

The suite is split by environment so a hung window or a slow pixel/UIA walk
cannot contaminate the fast lane. The hermetic lane runs before every commit:

```powershell
py -3.12 -m pytest tests -m "not interactive and not pixel and not hung" `
  --basetemp=.tmp\pytest-hermetic -p no:cacheprovider
```

Desktop lanes (`interactive`, `pixel`) need a real Windows desktop; the
hung-window lane runs one file at a time with nothing else active. Exact
commands are in `CLAUDE.md`.

## Honest scope

- **Act is not release-accepted yet.** The signed PowerPoint path has test and
  diagnostic evidence, but the activation review has not returned READY. The
  bundled plugin index in this checkout does not include a PowerPoint bundle;
  VS Code and Excel are disabled for production Act.
- Orbyn is becoming an app-agnostic, model-driven harness; PowerPoint is the
  test fixture for that path, not the product's limit.
- Reusable agents and `/crew` are foreground, sequential workspace operations.
  Work can continue a read-only research job or scheduled routine after the
  window closes. Neither can run desktop actions.
- Deferred: a signed installer and auto-update, tray/startup automation, the
  VLM pointing tier, and broader counted Act acceptance across applications.
- This is pre-1.0 software under active development. Measured results and their
  limitations live under `docs/evidence/`; architecture in `FLOW.md`; the rules
  that bind every change in `CLAUDE.md`.

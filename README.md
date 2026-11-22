# Orbyn

Orbyn is a **local-first Windows desktop guide** that watches the screen, works
out the next step toward your stated goal, and shows you **where to act** with a
transparent overlay. It can also **perform approved steps for you** in any
application — only after you approve the whole plan, only on a control it
actually observed, asking before risky ones, and ESC always stops it.

Local Brain and work files stay on the machine. Configured cloud models and web
research can receive request text and selected context; screen-derived text is
scrubbed through the tainted-input path, while embedded-secret redaction for
other remote text depends on policy or caller settings. (Code name and package:
`ghostcursor`.)

> Status: pre-1.0 (`0.1.0`). Teach works across observed Windows applications.
> Act runs through the same harness; live Act measurement and packaged release
> acceptance remain open. See **Honest scope** below.

## The two modes

**Teach** — you state a goal, Orbyn observes the live application, points at one
real, observed control, and waits for you to act, then verifies the resulting
state. It draws only at a control it actually saw — never a model-guessed
position — and a pointer that is shown is a pointer at a real control.

**Act** — the same plan, but Orbyn performs the steps. It acts **only after you
approve the whole plan**, only on controls the harness observed, still asks
before risky controls (delete, send, pay, submit, overwrite...), and ESC/Stop
halt a running session promptly. All input synthesis lives in **one auditable
module** (`ghostcursor/harness/act.py`); a test fails if any other module can
synthesize input. There are no per-app plugins: the same harness works in any
application (D193).

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
- **Background research** — start cited research, deep research (which also
  files cited claims to the Brain for you to review) or a crew (a goal split
  into read-only steps) in Work, close the window, and return to a locally
  saved answer. Download a finished result as Markdown
  directly from its card, ask a one-off follow-up about it (Orbyn sends only
  the parts that match your question), or Keep up to five important results at the top of
  Work so new jobs do not evict them. Archive hides a finished result until you
  choose Show archived; unkept archived results still age out of the 20-job
  inbox. One workspace job runs at a time;
  Stop cancels it cooperatively. A crash marks it interrupted without retry.
- **Routines** — schedule hourly, daily, weekday or weekly research from Work. Enabled
  routines run while Orbyn and the PC are awake, even with the window closed;
  pause, resume, run now, delete or Quit Orbyn there. A missed time runs once
  after wake, with no catch-up burst. A failed run (say a network blip) tries
  again after 5 minutes, then waits longer each time up to an hour, and the
  count survives a restart. A crash may skip an occurrence rather than repeat
  it. A question researched twice is offered as a routine. Results land in the
  local job inbox.
- **GitHub, read only** — connect a GitHub access token in Work (fine-grained
  recommended) to view a
  bounded repository list and open issues. The token stays in Windows
  Credential Manager; disconnect removes it locally. Repository text does
  not enter model prompts or routines. Organization no-egress policy blocks
  GitHub requests. Orbyn cannot change GitHub content.
- **Ask a file** — choose a small text or code file in Work and ask one
  question about it. The answer stays in that sheet; the file and question are
  not added to the Brief or Brain. Text may go to the configured model provider.

## Privacy and safety, by construction

- No window handles, process IDs, credentials, keys, executable paths, or
  screenshots leave the device. The local stores (Brain, Company Brain,
  briefs) never sync, except a team bundle the owner signs and publishes.
- Text bound for a remote model goes through a scrub that masks emails, keys,
  card/account numbers and the like; a managed machine can force redaction on.
- Telemetry and sync are not production paths in this build.
- The kill switch (ESC, Stop, and the session time limit) always stops a
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
```

Orbyn.cmd launches a small, draggable, always-on-top island. **Ask** (or
**Ctrl+Alt+O**) unfolds a box under it: type, press Enter, and the reply shows
on a card there; type again to follow up, **Esc** folds it. It uses the same
Chat and model as the full workspace. **Research** switches the box to cited
answers, **Talk** takes a spoken question, finished background research shows
on the same card, and the bar steps aside for full-screen apps. The island expands while
work runs and briefly when a background job ends. **Hide** dismisses it
while idle; **Ctrl+Alt+O**, or resting the pointer where it was, recalls it.
Work and new results reveal a hidden island and it tucks away again
afterwards; **Open** goes to Work while a job runs or has a new result. While
Orbyn works or listens, a click-through label beside the pointer says what it
is doing ("Listening", "Thinking"), never your question; Brain › Setup ›
Companion keeps a resting dot there when idle (off by default). **Stop** signals the
current run; **Quit** exits Orbyn. If the shortcut is already taken, Hide stays
unavailable. The full workspace remains local behind a per-launch token.
On a fresh workspace profile, Chat shows a short getting-started guide. Check
setup opens Brain Setup for account and readiness choices; Start typing focuses
the message box. The guide remembers dismissal in the local browser profile.
`--target` narrows which window Orbyn binds; when several windows still
match it lists them and refuses rather than guessing.

## Tests

The suite is split by environment so a hung window or a slow pixel/UIA walk
cannot contaminate the fast lane. The hermetic lane runs before every commit:

```powershell
py -3.12 -m pytest tests -m "not interactive and not pixel and not hung" `
  --basetemp=.tmp\pytest-hermetic -p no:cacheprovider
```

GitHub Actions runs this lane on Windows for every push to the working branch
and every pull request (`.github/workflows/hermetic.yml`).

Desktop lanes (`interactive`, `pixel`) need a real Windows desktop; the
hung-window lane runs one file at a time with nothing else active. Exact
commands are in `CLAUDE.md`.

## Honest scope

- **Act is not release-accepted yet.** It runs through the app-agnostic
  harness; live Act measurement across applications is still open. The earlier
  per-app plugin path (signed PowerPoint, Excel and VS Code bundles) was retired
  in D193; its measured evidence stays in `docs/evidence/`.
- Reusable agents and the console's `/crew` are foreground, sequential
  workspace operations. Work can continue a read-only research, deep-research
  or crew job, or a scheduled routine, after the window closes. None of them
  can run desktop actions.
- Deferred: a signed installer and auto-update, tray/startup automation, the
  VLM pointing tier, and broader counted Act acceptance across applications.
- This is pre-1.0 software under active development. Measured results and their
  limitations live under `docs/evidence/`; architecture in `FLOW.md`; the rules
  that bind every change in `CLAUDE.md`.

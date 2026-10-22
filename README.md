# Orbyn

Orbyn is a **local-first Windows desktop guide** that watches the screen, works
out the next step toward your stated goal, and shows you **where to act** with a
transparent overlay. It can also, down a narrow and signed path, **perform
approved steps for you** in approved applications — only after you approve the
whole plan, only on a control it actually observed, and ESC always stops it.

Nothing leaves your machine by default. (Code name and package: `ghostcursor`.)

> Status: pre-1.0 (`0.1.0`). Production Act ships for **PowerPoint**; Teach is
> application-agnostic. See **Honest scope** at the end.

## The two modes

**Teach** — you state a goal, Orbyn observes the live application, points at one
real, observed control, and waits for you to act, then verifies the resulting
state. It draws only at a control it actually saw — never a model-guessed
position — and a pointer that is shown is a pointer at a real control.

**Act** — the same plan, but Orbyn performs the steps. It acts **only after you
approve the whole plan**, only on controls the harness observed, still asks
before risky controls (delete, send, pay, overwrite), and ESC/Stop halts a
running session within half a second. All input synthesis lives in **one
auditable module** (`ghostcursor/harness/act.py`); a test fails if any other
module can synthesize input. Act ships today for PowerPoint through a signed,
verifiable plugin.

## What else is in the box

- **Company Brain** — a private, local knowledge graph. Facts carry their
  source, are scoped per tenant (one tenant's facts never leak to another),
  age, and surface conflicts instead of silently resolving them. Candidates
  stay candidates until you review them.
- **Models, your choice** — local-first on Ollama by default; bring your own
  key for a cloud model if you want one. An organization policy can only ever
  *lower* what may leave the machine.
- **Voice dictation** — speak text with spoken punctuation and formatting
  commands; it saves to a file or the Brain, and never types into an app on its
  own (that stays behind the Act gate).
- **Signed plugin marketplace** — a catalog decoupled from the signed artifact,
  with digest-level revocation and publisher identity. Unsigned plugins are
  refused in production; a bundle signed by an untrusted key is refused.

## Privacy and safety, by construction

- No window handles, process IDs, credentials, keys, executable paths, or
  screenshots leave the device. `kb.sqlite` and `sessions.sqlite` never sync.
- Text bound for a remote model goes through a scrub that masks emails, keys,
  card/account numbers and the like; a managed machine can force redaction on.
- Signed-bundle verification, a monotonic anti-rollback floor on signed trust
  documents, and a content-name-only local telemetry that is **off by default**
  and never sends anything off the box.
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

## Run

```powershell
py -3.12 -m ghostcursor.workspace.app <topic>   # the workspace app
py -3.12 -m ghostcursor.run --manager           # the manager window
py -3.12 -m ghostcursor.run --goal "<goal>"     # Teach from the CLI; ESC quits
py -3.12 -m ghostcursor.plugins list            # installed plugins
```

Orbyn.cmd launches the docked workspace window (local, behind a per-launch
token). `--target` narrows which window Orbyn binds; when several windows still
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

- **Production Act is PowerPoint only.** VS Code and Excel are installed but
  disabled (D130). Teach itself is application-agnostic.
- Orbyn is becoming an app-agnostic, model-driven harness; PowerPoint is the
  test fixture that proves the path, not the product's limit.
- Deferred: a signed installer and auto-update, tray/startup automation, the
  VLM pointing tier, and broader counted Act acceptance across applications.
- This is pre-1.0 software under active development. Measured results and their
  limitations live under `docs/evidence/`; architecture in `FLOW.md`; the rules
  that bind every change in `CLAUDE.md`.

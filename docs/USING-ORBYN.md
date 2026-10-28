# Using Orbyn

A local-first Windows desktop guide. It shows you where to click next toward
your goal, keeps a private knowledge graph, and (for PowerPoint) can perform
approved steps. Nothing leaves your machine by default.

## Install (one time)

From a built checkout:

```powershell
pwsh -File tools\build_orbyn.ps1          # build dist\Orbyn\Orbyn.exe (once)
pwsh -File tools\Install-Orbyn.ps1        # install + Start Menu / Desktop shortcuts
```

Then launch **Orbyn** from the Start Menu or Desktop. (First launch may show a
Windows SmartScreen prompt because the app is not code-signed yet — *More info →
Run anyway*.)

For the best experience, install the local model once:

```powershell
winget install Ollama.Ollama      # or https://ollama.com/download
ollama pull qwen3:4b-instruct     # the tested model (2.5 GB)
```

Orbyn **auto-starts Ollama** if it is installed, so you normally don't have to.

## Run

Double-click the **Orbyn** shortcut. A slim window docks to the top-right of your
screen. Launching it again while it is open just re-focuses that window.

## First things to try (in the window)

The window has four views. Type plain sentences; slash commands are not
understood here (they belong to the console, below).

| View | Try |
|---|---|
| **Chat** | `Make an investor deck outline` — Orbyn replies with your configured model |
| **Plan** | build a step plan from the conversation (a proposal — never auto-acts) |
| **Brain** | Setup checks readiness; add facts, review, mark private |
| **Work** | start background research, schedule a routine, read saved results |

A routine's later results list what is new since its previous run.

**Console (slash commands):** `py -3.12 -m ghostcursor.workspace "<topic>"`,
then `/doctor`, `/plan`, `/deck`, `/know add ...`, `/related ...`, `/do ...`,
`/stats`. See `RUN.md`.

**Teach (overlay guidance on a real app)** — from a terminal:

```powershell
py -3.12 -m ghostcursor.run --goal "Open the Insert tab" --seconds 120
```

Open a real app; Orbyn draws a ring at the next real control. **ESC quits.** It
never clicks for you in Teach.

## Privacy

- Nothing leaves the device by default. No window handles, PIDs, credentials,
  keys, paths, or screenshots are sent anywhere.
- Text bound for an optional cloud model is scrubbed of secrets first; an
  organization policy can only *lower* what may leave.
- Telemetry is local, off by default, and counts event names only.

## If something goes wrong

- **Window shows nothing / "won't start":** another copy may already be running
  (it re-focuses, doesn't double-start). If it truly crashed, a redacted log is
  written to `%LOCALAPPDATA%\GhostCursor\logs\crash-*.log` and a message box
  points at it — send that file.
- **"model unavailable":** install Ollama and pull a model (above). Orbyn starts
  the server for you once it's installed.
- **Version:** `Orbyn.exe --version`.

## Uninstall

```powershell
pwsh -File tools\Install-Orbyn.ps1 -Uninstall
```

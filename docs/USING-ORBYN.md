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

## First things to try (type in the window)

Plain text is a goal; `/word` is a command.

| Do this | What happens |
|---|---|
| `/doctor` | what's ready, and the one thing to turn on for each missing part |
| `Make an investor deck outline` | states a goal; Orbyn replies locally |
| `/plan` | a step plan from the conversation (a proposal — never auto-acts) |
| `/deck` | a slide-by-slide outline grounded in your Brain facts |
| `/know add runbook Deploys go out on Fridays.` then `/related deploys` | the private knowledge graph |
| `/do research what is core banking` | one-step router picks the capability |
| `/stats` | local counts (name-only; nothing is sent) |

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

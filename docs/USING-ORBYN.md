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

## The island

The small bar at the top of the screen is always there. Press **Ask** (or
**Ctrl+Alt+O**), type a question and press Enter; the answer appears under the
bar. Type again to follow up, press **Esc** to fold it. The full window is
only needed for plans, the Brain and background work.

- **Research** (under the box) turns on cited web answers for what you type.
- **Talk** listens once: say your question and the answer shows on the card.
  "Hey Bro" and Ctrl+Alt+Space work the same way while the bar is there.
  Hold Ctrl+Alt+Space while you talk and let go to send.
- **Ask a file** (in Work) takes text files up to 100,000 characters; only
  the parts that match your question are sent to the model. You can also
  right-click a text file in Explorer and choose **Ask Orbyn about this file**
  (on Windows 11, under **Show more options**). Open "Sent … characters"
  under the answer to see exactly what went.
- When background research finishes, its answer appears on the card; the full
  version is under **Open › Work**.
- The bar hides itself while a video, game or slideshow is full screen, unless
  Orbyn is working.

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

# Running Orbyn

Orbyn is a local-first Windows desktop app. Everything runs on your machine;
the workspace serves on `127.0.0.1` behind a per-launch token and nothing is
exposed off-device. A model is used only when you have switched on a BYOK key
(and only the redacted/allowed context leaves — see privacy below).

## The desktop app (GUI)

- **Double-click `Orbyn.cmd`** at the repo root — opens a compact, draggable
  desktop island. It expands during work and for a new result. **Open** opens
  the full Edge workspace (or your browser if Edge is absent); **Stop** stops
  the current run; **×** quits. Use `--window` to start with the full floating
  workspace, or `--dock` for its right-side layout.
- Or: `py -3.12 -m ghostcursor.workspace.app` (no argument opens the default
  workspace; pass a topic to name one: `... app "q3 review"`).
- Enabled research routines keep Orbyn running while the island is open or
  after a full workspace window closes. Use **×** or **Quit Orbyn** in Work to
  stop the process and active job.
  GitHub's read-only repository and issue view is also in Work.

## The console

```powershell
py -3.12 -m ghostcursor.workspace "<topic>"
```

Useful commands inside it:

| Command | What |
|---|---|
| `/research <q>` · `/deepresearch <q>` | cited web research; deep research decomposes + files cited claims to the Brain |
| `/deck [topic]` · `/researchdeck <topic>` | a slide outline, grounded in Brain facts / research |
| `/guide` | the current plan as a shareable step-by-step SOP (secrets scrubbed) |
| `/skill save <name>` · `use <name>` · `list` · `from <need>` | save/replay a plan as a task skill; `from` auto-drafts a skill from a need |
| `/know …` | Company Brain: add/review/approve facts, `private-source`, `private-default`, `episode <id>`, `recall`, `export` |
| `/dictate [brain]` | speak on demand; save the transcript to a file (or the Brain) |
| `/plan` · `/teach <n>` · `/act <n>` | plan, guide on screen, or act (after you approve the plan; ESC stops) |
| `/voice` · `/point` · `/doctor` | speak a goal · point at a control · readiness self-check |

## Readiness

```powershell
py -3.12 -c "from ghostcursor import doctor; [print(('OK ' if c.ready else '-- ')+c.name+': '+c.hint) for c in doctor.checks()]"
```

## Privacy (what leaves the device)

- No HWND/PID/keys/paths/screenshots leave. Sensitive Brain facts stay off every
  model path. With `RedactEgress` on (enterprise policy) or a privacy-max
  session, embedded secrets (email/card/SSN/key/PEM/JWT/IBAN/IP/phone) are
  scrubbed from text before it reaches a remote model.
- Voice audio stays in memory; dictation only saves locally.

## Build a distributable app (optional)

```powershell
pwsh -File tools/build_orbyn.ps1   # -> dist/Orbyn/Orbyn.exe (onedir, windowed)
```

## Tests

```powershell
mkdir .tmp   # once
py -3.12 -m pytest tests -m "not interactive and not pixel and not hung" --basetemp=.tmp\pytest-hermetic -p no:cacheprovider
```

Desktop lanes (one at a time, nothing else running): `interactive`, `pixel`,
`tests.test_overlay`, `tests.test_end_to_end`, and the three hung-window files.

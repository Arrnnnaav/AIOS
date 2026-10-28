# Island Ask: live check (29 October 2026)

Change: the desktop island gains Ask, a type-to-ask panel modelled on
HeyClicky's notch card (`docs/evidence/heyclicky-rea-2026-10-28.md`). Code:
`ghostcursor/workspace/island.py`; tests:
`tests/test_workspace_island.py` (9 passed, run alone on 29 October).

Live run from source (`py -3.12 -m ghostcursor.workspace.app clicktest3`,
topic files deleted afterwards). A local script posted the shortcut message,
set the edit box text with `WM_SETTEXT` and posted the Send command; it did
not synthesise input. Screenshots were inspected locally and not kept in the
repository.

- Compact bar: Ask (amber), Open, Hide, Quit.
- Shortcut message opened the panel (440 x 326) with the caret in the box and
  the hint text on the card.
- First question: the status read "Working · Thinking" with Stop shown; the
  model's two-sentence reply appeared on the card in about 20 s.
- Follow-up "Now make that a single sentence." was answered in context; the
  card scrolled to the newest reply and the scrollbar used the dark theme.
- `/api/state` listed both exchanges in the shared Chat turns.

Not checked: a person typing and pressing Enter (the Enter path is covered by
`DM_GETDEFID` in the test, not live), focus behaviour when another app holds
the foreground, hiding during full-screen apps (not built), and the packaged
`Orbyn.exe`.

## Second run: Research, Talk, finished results (29 October 2026)

Change: commit `eb6fd7e` adds Research, Talk, finished background results on
the card, a running-jobs strip and full-screen step-aside. Tests:
`tests/test_workspace_island.py` (10 passed) and
`test_heard_goes_to_the_island_when_it_is_shown`; hermetic lane 3652 passed.
Removing either the busy or the panel-open condition from the full-screen
guard made the island test fail (both restored).

Live run from source (`clicktest4`, topic files deleted afterwards), driven by
posted messages and the local token-protected API; no input synthesis.
Screenshots were inspected locally and not kept in the repository.

- Talk: the card read "Listening… say what you need."; the status log showed
  "Listening (Talk)". Whisper then turned room noise into "Heard: die
  somewhere.", which reached the island and was refused because Orbyn was busy.
- Research on (amber "Research on"): a question about the latest Python
  release returned a cited answer with its sources and egress note on the card.
- A background job started through `/api/job_start` showed "1 research job
  running" with Stop; when it finished the bar read "Research finished" and the
  answer with sources appeared on the card.
- `_fullscreen()` returned False on the windowed desktop. Hiding with a real
  full-screen app was not checked live.
- Jev vision stayed off after the run.

# VS Code Open Terminal acceptance evidence

Date: 2026-08-25

Platform: normal interactive Windows desktop, Python 3.12, VS Code

Goal: `Open the integrated terminal in VS Code`

## Contract

- Planner may select only registered `OPEN_TERMINAL`.
- Recipe authority is the trusted local VS Code pack.
- GhostCursor highlights `Toggle Panel (Ctrl+J)` but never sends input.
- The human presses `Ctrl+\``.
- If exact `Terminal Section` is already present, the goal completes before a
  hint is rendered.
- Otherwise it must transition from absent to present within 20 seconds of the
  first rendered hint; timeout is checked before accepting a late appearance.
- The three transition trials begin only after the terminal-hidden UIA
  baseline is confirmed.

## Rehearsal finding

A click-based recipe was tested first. Toggle Panel restored Debug Console,
not Terminal, and GhostCursor correctly reported `verification timed out after
20s`. The recipe was changed to the official terminal shortcut while retaining
application-state verification.

## Consecutive clean trials

| Trial | Baseline | Planner | Human action | Verified result |
|---|---|---|---|---|
| 1 | `Terminal Section` absent | `MODEL_UNAVAILABLE_FALLBACK (0.95)` | `Ctrl+\`` | `Terminal Section` appeared; `Tour complete.` |
| 2 | `Terminal Section` absent | `MODEL_UNAVAILABLE_FALLBACK (0.95)` | `Ctrl+\`` | `Terminal Section` appeared; `Tour complete.` |
| 3 | `Terminal Section` absent | `MODEL_UNAVAILABLE_FALLBACK (0.95)` | `Ctrl+\`` | `Terminal Section` appeared; `Tour complete.` |

The deterministic fallback was expected because Ollama returned `URLError`.
It loaded the same trusted recipe and did not broaden execution authority.

Automated regression after the desktop gate: 49 focused planner/pack/runtime/
UIA/verification tests, 345 hermetic tests, and 55 interactive Windows/UIA
tests passed.

Independent review then added injected-clock regressions for a no-op shortcut,
a state appearing after the deadline, and an already-visible terminal. It also
added planner path-containment, runtime walker-wiring, executable-binding, and
project-wide no-input-synthesis guards. Final regression passed 50 focused,
355 hermetic, and 55 interactive Windows/UIA tests.

After the correction, the already-visible desktop path completed once without
printing the shortcut step. The hidden-to-visible desktop transition then
passed another 3/3 consecutive clean sequence. A separate live no-op attempt
is not timeout evidence: VS Code independently exposed `Terminal Section`
during that run, so world-state verification correctly completed. The
injected-clock unchanged-snapshot test is the controlled timeout proof.

## Learning and wrong-action scope

VS Code exposes both reviewed controls with empty AutomationIds. GhostCursor's
promotion, persistence, and focus-based wrong-action paths require a non-empty
ID, so no learned observation is stored and no ID-based wrong-action claim is
made. The three-run result proves repeatable fresh perception, grounding, human
guidance, and world-state verification.

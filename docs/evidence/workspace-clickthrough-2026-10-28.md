# Workspace app click-through (28 October 2026)

Build: `feature/product-shell-task-graphs` at `1469cd8`, run from source as
`py -3.12 -m ghostcursor.workspace.app clicktest` (island mode). Playwright
drove the served page on loopback. The `clicktest` topic files were deleted
afterwards. Readiness (`doctor.checks()`): models, voice, wake word, browser
control, Act/Teach and REA all reported ready.

## Sweep

A script clicked every visible, enabled button on Chat, Plan, Brain and Work,
skipping Quit, Delete/Remove, Stop, Voice, Point, Send, Research, sign-in,
connect, update and file pickers. 17 controls were clicked; no page error
was raised. Control names and outcomes are as the script logged them:

- Chat: Make a plan.
- Plan: Describe a goal; Open a teammate's handoff (asks for a file picker;
  the picker was suppressed).
- Brain: Personal, Company, Setup, the pictures switch (toggled twice; read
  back afterwards as off through `settings.jev_vision()`).
- Work: New task, Start a task, New routine (sheet opened), Go to Chat,
  Create agent.

An earlier sweep that did not yet skip sign-in clicked a sign-in control; it
put the app in "Signing in" until it ended on its own in under 90 s. Whether
a browser page opened was not checked.

## Functional checks

- Chat: one message answered in 8 s.
- Work routine: created, then Run now twice (14 s and 10 s, live web search
  and model). The second result's card read "1 new since last run". The
  "new" claim restated the first run's fact in other words, so the exact
  match shipped in `7b819f9` reported a false change. Fixed in the next
  commit with a local fuzzy match; the two live claims are a test case.
- Console errors: two `400` responses from `/api/stats`, both
  `busy: ...` refusals while another run held the worker.

## Not run

Voice, Point, Teach/Act, GitHub connect, file-picker flows, Quit from the
island, and the desktop test lanes.

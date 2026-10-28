# HeyClicky for Windows: static teardown (28 October 2026)

Target: `HeyClicky-Setup.exe` from the owner's Downloads, version 1.1.1,
Authenticode valid, signer "Humansongs, Inc" (San Francisco). Velopack 1.2.158
installer; the embedded nupkg was carved and unzipped into a scratch folder.
Nothing was installed or run.

Method: REA `inspect_managed_artifact` / `inspect_managed_members` on
`HeyClicky.Agents.dll` (.NET 9, ReadyToRun, 489 types, metadata complete).
`HeyClicky.dll` and `HeyClicky.Core.dll` exceeded REA's 64 MB metadata
representation budget, so their `#Strings` and `#US` heaps were read with a
stdlib script instead. Bundled text files were read as data.

## What it is

- WinUI 3 desktop app with a notch/peek surface, ink-styled result cards, an
  overlay, voice, dictation and a "OneBrain" turn model.
- Background **Jobs** run in a bundled Codex CLI runtime (`CodexRuntime/`,
  `clicky-harness.exe`) with a per-job working folder, `output/` + `tmp/`, and
  a reply protocol of tags: `SUMMARY`, `NEXT_ACTIONS`, `DONE_TITLE`,
  `ARTIFACTS`, `ROUTINE`, `COMPUTER_USE_REQUEST`, `WAIT_FOR`, `LEARNED`,
  `ANSWER`. A step only an app window can do is handed back to the app.
- **Routines**: every day / weekday / weekend schedules in `routines.json`;
  the first run does the full task, later runs "report only what changed";
  overdue runs settle after wake; keep-awake only on AC power.
- **Proactive** morning suggestions the user approves or denies; approved
  ones become routines.
- **Clickys**: persistent named agents whose folder holds an `AGENTS.md` with
  dated notes.
- Chrome extension (MV3, `debugger`, `tabs`, `nativeMessaging`, `downloads`)
  plus `ClickyBrowserHost.exe` lets jobs drive signed-in sites.
- Connector skills bundled for ClickUp, Dropbox, Gmail, Google Docs/Tasks,
  HubSpot, Jira, Linear, Teams, Outlook, Salesforce. Sentry is shipped.

## What Orbyn took

- Routine reruns now show the claims that are new since that routine's
  previous finished run (`new_claims` in `ghostcursor/workspace/app.py`),
  computed locally when the page state is built. Nothing new is stored or
  sent. Covered by `tests/test_workspace_app.py::test_routine_reruns_report_only_new_claims`.

## Not taken, and why

- Browser debugger extension and native-host driving of signed-in sites:
  input/authority outside `act.py` (rule 1/2) and broad egress (rule 6).
- Hosted connectors and Sentry: egress (rule 6, D141).
- Proactive suggestions from observed activity: needs an always-on
  observation path Orbyn does not have; recorded in FOLLOWUPS.

# Orbyn security overview and data flow (D187)

For a customer's security questionnaire. Every statement names the code that
enforces it. Where something is not built or not measured, it says so.

## What Orbyn is

A Windows app that reads the screen through UI Automation, asks a model for
the next step, and shows where to click. With Act on (and not disabled by
policy), it performs approved steps on controls it observed itself.

## Data flow

```
 Screen (UI Automation)            Owner's team folder (SharePoint/share)
        |                                  ^  signed bundle (approved facts,
        v                                  |  skills, agents; no screen text)
 Observation frame (local) ----------+     |  audit copies (opt-in)
        |  ids, control types, names |     |
        v  (scrubbed: Tainted.of)    |   team.py publish / sync
 Model request ---- policy gate ---->+---> Company gateway / provider
   (no handles, PIDs, rectangles,         (only if MaxEgress >= 1 and
    titles, paths or screenshots)          AllowedProviders permits)
        |
        v
 Overlay on this PC / Act through harness/act.py only
        |
        v
 audit.jsonl (this PC; events only)
```

## Controls

| Control | Where |
|---|---|
| Nothing leaves when MaxEgress is 0; pictures only at 2 and only if the user also switches them on | `policy.allows`, `settings.jev_vision` |
| Screen text is scrubbed before any model sees it (emails, long numbers, keys masked) | `providers/envelope.py` `Tainted.of` |
| Secrets in other outbound text are replaced with placeholders when RedactEgress is on | `providers/gateway.py` `_outbound`, `redact.py` |
| No window handle, PID, executable path or screenshot in any request | `harness/frame.py` `model_view`; evidence hygiene scan |
| Apps can be allow-listed or blocked; password managers are always blocked | `harness/binding.py` `denied` |
| Act can be switched off for the whole organisation | `policy.act_disabled` checked in `harness/act.py` `perform` and `act_runtime.approve_action_graph` |
| Act needs the user to approve the whole plan, acts only on observed controls, asks again before risky controls, and stops on ESC within 0.5 s | `harness/teach.py`, `CLAUDE.md` rules 2-4 |
| Mouse and keyboard input come from one module | `harness/act.py`; pinned by `tests/test_no_input_synthesis.py` |
| Plugins are signed; revoked bundles refuse to load | `plugins/` (D100-D186) |
| Team bundles load only with the pinned owner signature, never older than the last one loaded | `workspace/team.py` `verify`, `sync` |
| Provider keys sit in Windows Credential Manager, never in files | `providers/keys.py` |
| Local stores (`kb.sqlite`, `sessions.sqlite`) never sync | rule 6; `team.py` publishes only the Company Brain export |
| Hash-chained local audit log, content-free by allow-list | `audit.py` |
| The company gateway is used only after the person switches it on; IT policy alone adds no destination | `settings.company_gateway`, `providers/clients.system_two` |

## Stored on the PC

`%LOCALAPPDATA%\GhostCursor\`: `knowledge.sqlite` (Company Brain),
`kb.sqlite`, `sessions.sqlite` (no goal or screen text), `settings.json`,
`audit\audit.jsonl`, provider attribution log, task skills and agents. Delete
the folder to remove all of it. Keys are in Credential Manager under `Orbyn/`.

## Sub-processors

Only the model providers the organisation allows. Orbyn itself runs no
service and receives no customer data.

## Not built or not measured (be plain about these)

- No SOC 2 report: there is no Orbyn-hosted service to audit. The provider
  you choose carries its own.
- No SSO/SCIM, for the same reason.
- The release build is not yet code-signed by default; sign the MSIX with
  your own certificate (`tools/package_msix.ps1`).
- Act is accepted on PowerPoint; other apps are not yet measured live.
- Free-text passwords inside ordinary sentences are not reliably redacted.

# Never-Fabricate Probe Matrix

Fill this table live while running each probe. Different non-launch statuses
may be valid; the invariant is that no unsupported, unavailable, or untrusted
workflow launches.

| Goal | Ollama state | Status | Intent/pack | Recipe | Launch eligible | Tour launched |
|---|---|---|---|---|---|---|
| Create a Python file in VS Code | Available | `KNOWN_INTENT_RECIPE_UNAVAILABLE` | `CREATE_DOCUMENT` / none | none | No | No |
| Create a Python file in VS Code | Unavailable | `UNSUPPORTED_GOAL` | none | none | No | No |
| Deploy this project to production | Available | `UNSUPPORTED_GOAL` | none | none | No | No |
| Deploy this project to production | Unavailable | `UNSUPPORTED_GOAL` | none | none | No | No |

## Supported-goal controls

| Goal | Ollama state | Status | Intent/pack | Recipe | Launch eligible | Tour launched |
|---|---|---|---|---|---|---|
| Open a folder in VS Code | Available | `SUPPORTED` | `OPEN_FOLDER` / `vscode` | `open a folder in vscode` | Yes | No (planner probe only) |
| Open a folder in VS Code | Unavailable | `MODEL_UNAVAILABLE_FALLBACK` | `OPEN_FOLDER` / `vscode` | `open a folder in vscode` | Yes | No (planner probe only) |
| Open the integrated terminal in VS Code | Available | `SUPPORTED` | `OPEN_TERMINAL` / `vscode` | `open the integrated terminal in vscode` | Yes | No (planner probe only) |
| Open the integrated terminal in VS Code | Unavailable | `MODEL_UNAVAILABLE_FALLBACK` | `OPEN_TERMINAL` / `vscode` | `open the integrated terminal in vscode` | Yes | No (planner probe only) |

## Finding and correction

The first available-model probe exposed a real never-fabricate failure: Qwen
classified `Deploy this project to production` as `EXPORT_DATA (0.98)`, which
made the synthetic export recipe launch-eligible. The probe did not launch a
tour. The planner now requires every model-selected intent with an available
recipe to agree with the deterministic classifier's grounded intent. After
that correction, the same Qwen response became `UNSUPPORTED_GOAL` with no
intent, pack, recipe, or launch authority.

Available-state probes used the installed, prewarmed `qwen3:4b-instruct` at
`127.0.0.1:11434`. Unavailable-state probes used an unreachable local endpoint
at `127.0.0.1:1`; supported goals still exercised deterministic fallback.
The correction passed 17 focused planner tests and the complete 361-test
hermetic lane.

## Submission release recertification

Date: 2026-08-25

The model-call hardening started after D058 was isolated on
`post-submission/model-durability` and was not included in this release. The
annotated `submission-pre-model-hardening` tag and release HEAD both resolved
to `15f20cef8d841fdd75145bd0e2493d61a2a90092`; all branch, staged, unstaged,
status, module-absence, and test-absence checks passed.

The tables above were then rerun unchanged against that release code. All eight
cells reproduced their documented status, intent, recipe, and launch-eligibility
contracts. Available probes used Ollama 0.31.1 with
`qwen3:4b-instruct` digest
`0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`;
unavailable probes used `127.0.0.1:1`. No probe launched a tour. The same
release checkout passed 23 focused planner/screen-hint controls and all 361
hermetic tests.

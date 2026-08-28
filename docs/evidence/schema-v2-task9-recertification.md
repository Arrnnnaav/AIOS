# Schema-v2 Task 9 recertification

Date: 2026-08-29 (Asia/Calcutta)

Status: closed as the compiler baseline by owner direction after every claim
below was reproduced in a read-only review. The reviewer disclosed prior
contributions to the branch; this is recorded as an owner closure, not
misrepresented as review by someone with no prior involvement.

## Bound commits and tree

- Atomic authority cutover: `108b6fb` (`feat: activate declarative workflow
  compiler`).
- Legacy dispatcher removal: `74985fe`.
- The coverage-losing migration `d5757d7` was rejected and reverted in full by
  `7823ebf`; it is not part of the claimed test migration.
- Coverage-preserving repair under test: `1ba371a` (`test: port cutover
  protections to compiled workflows`).
- Committed tree: `2822d3e3182c1c8c05dfd3550ff2bb580e83d346`, equal to the
  staged tree captured immediately before the commit.
- Named `test_` functions: 900 at `cdda523` before the rejected migration and
  900 at `1ba371a`. Historical v1 JSON used for parity lives only under
  `tests/fixtures/v1/`; production neither scans nor loads that root.
- Protected branch tips remained `post-submission/model-durability` at
  `5e771ca` and `submission/open-track` at `7cdf64c`.

The old production roots contain no tracked files, and the authority scan finds
no production definition of `registry`, `perception_walker_for`,
`perception_hwnd_source_for`, or `run_tour`. The remaining `run_tour` text under
`ghostcursor/evaluation/safety.py` is the intentional forbidden-call denylist,
covered by its malicious-code fixture.

## Defects found during recertification

Two production defects were exposed by porting the decision-backed tests to
the compiled path rather than deleting them.

1. `warmup_budget_s` reached the compiled launcher but was not connected to
   its observation source. A UIA miss could therefore request tier 2 during
   Chromium warm-up. `CompiledObservationSource` now owns the real `WarmUp`,
   suppresses the request for the configured budget, and closes warm-up after
   confirmed grounding.
2. An ESC press already pending before launch was first observed only after the
   full-screen overlay existed. `_run_compiled_tour()` now checks the abort
   before creating the overlay; the executor continues polling after launch.

The migrated tests retain assembled-system coverage for D020, D021, D026,
D027, D035, and D037: tier-2 timing, warm-up, staleness ordering, first paint,
wrong-action recovery, and ESC responsiveness while a real target is hung.

## Test lanes

Every desktop or hung-window lane ran alone per D025.

| Lane | Command | Result |
|---|---|---|
| Hermetic, final committed tree | `py -3.12 -m pytest tests -m "not interactive and not pixel and not hung" --basetemp=.tmp\pytest-hermetic-final -p no:cacheprovider -q` | 1009 passed, 70 deselected, 44.02 s |
| Interactive | `py -3.12 -m pytest tests -m interactive --basetemp=.tmp\pytest-interactive -p no:cacheprovider` | 54 passed |
| Pixel | `py -3.12 -m pytest tests -m pixel --basetemp=.tmp\pytest-pixel -p no:cacheprovider` | 3 passed |
| Standalone overlay pixels | `py -3.12 -m tests.test_overlay` | 16/16 checks |
| Standalone end-to-end pixels | `py -3.12 -m tests.test_end_to_end` | 8/8 checks |
| Hung target primitive | `py -3.12 -m pytest tests\test_hung_window.py --basetemp=.tmp\pytest-hung-window -p no:cacheprovider -o faulthandler_timeout=60 -q` | 4 passed, 46.60 s |
| Hung perception service | `py -3.12 -m pytest tests\test_perception_service_hung.py --basetemp=.tmp\pytest-hung-service -p no:cacheprovider -o faulthandler_timeout=60 -q` | 2 passed, 9.39 s |
| Hung compiled runtime | `py -3.12 -m pytest tests\test_run_threaded.py --basetemp=.tmp\pytest-hung-runtime -p no:cacheprovider -o faulthandler_timeout=60 -q` | 7 passed, 15.65 s |
| D072 + wrong-action focus | `py -3.12 -m pytest tests\test_compiled_matcher.py tests\test_wrong_action_tour.py --basetemp=.tmp\pytest-task9-focused-live -p no:cacheprovider -q` | 44 passed, 1.79 s |

The first focused D072/wrong-action attempt inside the restricted filesystem
encountered five setup errors and pytest then raised `PermissionError: [WinError
5]` while enumerating its basetemp during session cleanup. It is classified as
an infrastructure failure, not a green run. The identical command with a fresh
basetemp outside that restriction produced the 44/44 result above.

## Live eight-cell matrix

The matrix called `plan_compiled_goal()` on the installed catalog. Available
rows used `qwen3:4b-instruct` at `127.0.0.1:11434`; unavailable rows used the
unreachable endpoint `127.0.0.1:1`. Supported controls bound the live AIOS VS
Code window through `target_title_re="AIOS"`. No tour launcher was imported or
called.

| Goal | Model | Final status | Intent | Bound plan |
|---|---|---|---|---|
| Create a Python file in VS Code | available | `KNOWN_INTENT_RECIPE_UNAVAILABLE` | `CREATE_DOCUMENT` | no |
| Create a Python file in VS Code | unavailable | `UNSUPPORTED_GOAL` | none | no |
| Deploy this project to production | available | `UNSUPPORTED_GOAL` | none | no |
| Deploy this project to production | unavailable | `UNSUPPORTED_GOAL` | none | no |
| Open a folder in VS Code | available | `SUPPORTED` | `OPEN_FOLDER` | yes |
| Open a folder in VS Code | unavailable | `MODEL_UNAVAILABLE_FALLBACK` | `OPEN_FOLDER` | yes |
| Open the integrated terminal in VS Code | available | `SUPPORTED` | `OPEN_TERMINAL` | yes |
| Open the integrated terminal in VS Code | unavailable | `MODEL_UNAVAILABLE_FALLBACK` | `OPEN_TERMINAL` | yes |

Thus unsupported/unavailable intents produced zero executable plans, while
both supported controls materialized only the already adopted recipes. Model
output changed classification metadata but supplied no artifact, selector,
step, or execution authority (D068).

## Frozen model gate

Command, run twice consecutively and interactively without `--draft`:

```powershell
py -3.12 -m ghostcursor.evaluation.model_gate `
  --model qwen3:4b-instruct `
  --endpoint http://127.0.0.1:11434 `
  --unavailable-endpoint http://127.0.0.1:1 `
  --interactive
```

Both full runs passed and reported `final_milestone_eligible: true`.

| Pass | Created at (UTC) | Dataset | Model/server | Manifest SHA-256 | Median / max latency |
|---|---|---|---|---|---|
| 1 | `2026-08-28T20:42:57.102663+00:00` | 1.0.0 | `qwen3:4b-instruct` / Ollama 0.31.1 | `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0` | 2889.6855 / 3594.777 ms |
| 2 | `2026-08-28T20:44:45.311074+00:00` | 1.0.0 | `qwen3:4b-instruct` / Ollama 0.31.1 | `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0` | 2751.621 / 3423.702 ms |

Every hard gate was true on both passes: all requests parsed, exact-supported
raw intent accuracy was 100%, unsupported launch-eligible plans were zero,
never-fabricate launches were zero, supported controls launched, the synthetic
hint named the exact control, and exact-supported length truncations were zero.

The ignored raw reports were
`.artifacts/model-evaluation/model-gate-20260829-021439.json` and
`.artifacts/model-evaluation/model-gate-20260829-021627.json`. They are named
only for local audit. This committed document is the durable summary and does
not depend on those ignored files remaining present.

## Closure

The read-only review reproduced the hermetic, interactive, pixel, standalone,
hung, D072, wrong-action, named-test, model-gate, and protected-branch claims
against `1ba371a` and `41682ee`. The owner then explicitly closed Task 10 and
authorized Task 11. The disclosure above remains part of the record rather
than being erased by that ruling.

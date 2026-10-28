# FLOW.md

## Current execution authority — schema v2

Production goal execution now flows through `run.main()` →
`planner.plan_compiled_goal()` → `plugins.platform.load_runtime_catalog()` →
`packs.compile` → `packs.workflow.bind_workflow()` →
`run.run_tour_for_workflow()`. The compiled workflow revalidates the exact
activation generation, artifact digests, application identity, and bound HWND
before creating an overlay; `execute_compiled_workflow()` then consumes the
compiled observation plan. The old path-based tour and workflow-specific
walker adapters were removed in Task 9. The historical call graphs below are
retained only as migration history and must not be used to implement new work.

```text
CLI --goal / control-bar Ask
    -> planner.plan_compiled_goal()
        -> PluginStore verifies enabled signed bundles and merges their catalogs
        -> compile_matcher() classifies without loading a recipe
        -> authorize_intent() is the only deterministic/model authority gate
        -> workflow.bind_workflow() reloads the catalog, then requires one HWND
             -> zero candidates returns structured TARGET_NOT_RUNNING
             -> several candidates returns structured TARGET_CHOICE_REQUIRED
             -> an operator-selected HWND narrows only the freshly enumerated set
    -> run.run_tour_for_workflow()
        -> reload catalog and revalidate HWND/PID/executable/title/version
        -> build_compiled_perception() starts one worker after both gates
        -> compiled_tour.execute_compiled_workflow()
             -> compare active-index digest every 0.25s; abort if withdrawn
             -> publish immutable SessionSnapshot transitions from executor truth
             -> SessionStore records content-minimized local events only
        -> nested finally blocks tear down overlay and perception on every exit
```

The native rail and manager consume the same `SessionSnapshot` callback.
It carries the complete ordered instruction list, executor-owned current/total
step counts, verification state, terminal outcome, and explicit control
capabilities. The rail renders those values; it never counts or infers them.
`SessionStore` writes a separate `%LOCALAPPDATA%\GhostCursor\sessions.sqlite`
with identifiers, state transitions, timing, provenance, and stable error
codes. Goals, instructions, HWNDs, screen text, and raw error details are not
persisted. Records older than 30 days are purged when a production tour opens
the store, and diagnostic archives include goals or notes only through
separate explicit options.

The manager is one resizable **window**, not a second process or event model.
`python -m ghostcursor.run --manager` creates it in its compact right-side
layout. The same HWND expands into the centred planning/review workspace and
preserves the current goal, proposal, controls, and executor-derived progress.
Planning, complete-plan review, target choice, and actionable failures expand
it; issuing an approved execution request or reaching successful completion
collapses it, while Stop/failure reopens it for recovery. Manual expansion
during execution remains available and ordinary progress does not override it.
The separate compact topmost Teach rail is still created only after guided-
workflow revalidation.
The executor publishes once to `session_events`, which fans the immutable
snapshot to both surfaces. Stop/Pause commands travel back through an
edge-triggered mailbox keyed by the active session id and are consumed by the
same `CompiledTourControls` that handles physical rail clicks. Optional manager
rendering failures are isolated from execution.

Manager planning runs on a background thread so model/transport latency cannot
hang the native message pump. A supported workflow returns to the UI thread and
uses the unchanged production launcher. Zero target candidates show an
application-not-running recovery; several show every freshly verified HWND,
title, executable, and version. Choosing one feeds only its HWND into a new
plan/bind. Plugin rows are reread from `PluginStore` whenever the manager gains
focus, so a separate developer CLI process cannot leave lifecycle display stale.

Complex goals use a separate two-action manager path. The operator selects one
enabled compatible plugin with an active signed capability registry, then
`Plan complex` asks only for inert capability graph data. The manager displays
every deterministically flattened step and bounded guidance value. Nothing
executes until the operator presses `Start plan`; execution then revalidates the
whole graph before node 1. A target chooser can resume only when no node has
completed, so recovery cannot replay a side-effecting prefix.

The manager's mode selector reads the single contract in
`ghostcursor.interaction`. `Teach` routes only to the existing compiled-goal
launcher. `Plan` routes only to inert graph proposal and the existing explicit
confirmation path. `Act` routes only to the signed action-plan
path below: one inert complete proposal, then a separate approval of that exact
graph. `Ideate` and `Assist` remain preview modes in this build: selecting them
disables every launch path and creates no target, overlay, or execution
request. Mode selection never carries authority.

Act and Teach share the same intent policy gate without sharing executable
artifacts. Teach calls `authorize_intent()` against the verified catalog and
can receive `AuthorizedIntent` only when the intent has an active adopted
recipe. Act obtains one atomic `CompositionContext` from the production
`PluginStore` and calls that same function with both objects. The authorizer
requires the exact store to have issued the exact context from signed on-disk
state; matching a public dataclass shape or catalog object is insufficient.
It then derives the available Act intents itself from that context's signed
adapter plan inventory and mints `AuthorizedActionIntent` only when exactly
one plan binds the catalog intent, plugin/version/manifest, adapter digest,
and plan digest.
`bind_workflow()` rejects that token type; conversely, `prepare_act_goal()`
rejects a recipe token. A mode therefore selects which signed artifact is
requested, never whether an unadopted or fictional intent becomes trusted.

```text
Act proposal
    -> production_store().load_composition_context() once
    -> compile_matcher(context.catalog) grounds the goal
    -> authorize_intent(..., action_context=context, action_store=store)
         -> require the exact PluginStore to have issued that exact context
         -> require that issued context to own that catalog object
         -> require one catalog-owned intent and one unique signed plan
         -> bind catalog + pack + intent + manifest + adapter + plan digests
    -> materialize only the plan named by AuthorizedActionIntent
    -> display the inert complete plan
    -> separate Approve & run hands focus from the manager to the exact
       proposal-bound HWND; refusal issues no request
    -> successful exact-HWND handoff issues one manager-owned execution request
    -> _ActWorker consumes that exact request once; bare/replayed requests refuse
    -> approve_action_graph binds the validated graph and live target
```

The handoff is presentation readiness, not target authority. It is attempted
only while the manager still owns foreground after the approval click, and it
uses the HWND already selected and digest-bound in the displayed proposal.
Foreground is never consulted as a tie-break or replacement target. The helper
performs one `SetForegroundWindow` attempt and confirms the exact HWND; a stale
window, user focus change, OS refusal, or mismatched result leaves the proposal
inert and retryable (D075, D123).

An opt-in developer evidence lane observes that same manager loop. It emits
fixed-schema JSONL after proposal display, the real `Approve & run` command,
request dequeue, worker start, executor events, and the terminal result. The
proposal identity binds the goal, graph, catalog, signed executables, target,
and output destination by digest. Raw goal/path/window/geometry data is never
written, and the audit lane has no edge back into execution (D122).

Production bundles are Ed25519-signed `.ghostplugin` files whose signed
manifest contains the complete payload digest inventory. `PluginStore` owns
install/enable/disable/uninstall and reports `disabled`, `enabled_compatible`,
or `blocked_incompatible`. Unsigned bundles can exist only in the separate
developer store. Every store operation is serialized across processes by one
Windows named mutex derived from the resolved production/developer store root;
indexes are reread only after acquiring it, so the manager and CLI cannot both
publish different successors to the same generation. A contended read fails
closed within 100ms, below the runtime authority monitor's 0.5-second ceiling.
Learned observations are scoped by plugin id and version.
With no enabled compatible plugin the merged catalog is empty, so neither a
deterministic nor model-proposed intent can reach target resolution.

Target recovery is structured rather than parsed from an error string.
`TargetNotRunning` carries the required pack; `TargetChoiceRequired` carries
the complete verified candidate snapshots. `--target-hwnd` and the future
native chooser feed only a handle back into a fresh authorization/bind. Bind
still enumerates the live desktop itself and rejects a closed, recycled, or
identity-mismatched handle before any overlay exists.

Complex-task composition has a separate static gate and no application logic:

```text
model/user proposal: capability ids + scalar parameters + dependency edges
    -> validate_task_graph(graph, current plugin capability registry)
         -> require one exact plugin id/version
         -> reject unknown nodes, parameters, duplicates, and size overflow
         -> Kahn topological walk rejects every cycle before execution
         -> preconditions must come from trusted initial facts or an ancestor
         -> bind graph + registry + initial facts into validation_sha256
         -> deterministically flatten to an ordered step list for presentation
         -> freeze sorted node parameters as display-only GuidanceValue scalars
    -> for each node at runtime (not implemented by the static validator)
         -> classify the capability's existing intent
         -> authorize_intent() against the current active catalog
         -> bind_workflow() reloads authority and the selected live target
         -> first successful bind captures one HWND for every later node
         -> publish guidance through SessionSnapshot only
```

`ValidatedTaskGraph` is evidence that the complete proposal was structurally
safe to start; it is deliberately not an authority token. A validation error
has phase `validation` and a stable code, distinct from a workflow that starts
and later fails during execution.

Guidance values travel beside the compiled workflow, never into it. The
authorizer still receives only the signed exact phrase; bind still receives
only the authorization token, goal, and operator narrowing; selectors and
verification remain the signed recipe. Session history deliberately omits the
guidance payload because slide copy and customer content are private text.

The currently adopted catalog exposes four active workflows: Synthetic Export,
Open Folder, Open Terminal, and Open Extensions in VS Code. Excel's Select Cell
B2 and Add Worksheet records remain historical feasibility/data artifacts only:
their repository payloads are redacted while the installed bundles are stale
and cannot be re-signed with the unavailable publisher keys (D128). They are
not active adopted Act surfaces. No Excel-specific production Python participates
in planning, perception, grounding, verification, or execution.

How execution actually travels between files, functions, and modules — what calls
what, in what order. Updated as the codebase grows. The "you are here" marker at
the bottom shows exactly what's being built/modified right now.

---

## Workspace app (current)

`ghostcursor.workspace.app.App` serves the token-protected Chat, Plan, Brain
and Work page on loopback. By default, a native topmost workspace island is
shown at the top of the desktop. It is draggable and shows generic worker and
research-job state without goal, question, answer or credential text in its
title or status. Ask (its primary button, or Ctrl+Alt+O) unfolds a type-to-ask
panel: an edit box and a read-only reply card. Enter sends through
`App.handle("say")`, the same Chat path and model as the page, on a background
thread; the UI-thread tick shows the reply, and the turns join the shared Chat
history. Follow-ups continue that conversation. Escape folds the panel (Stop
only when folded and busy); pressing the shortcut while open folds and hides.
Research (a toggle in the panel) sends the box through `App.handle("research")`
instead. Talk arms the existing voice Listener; while the island is shown,
`App.heard` hands every spoken request (Talk, the voice hotkey or "Hey Bro") to
the island, which asks it on the card like typed text. A finished background
job is shown on the card once (its first 1500 characters) and a strip counts
running jobs; that text is local UI only, never the title. While Windows
reports a full-screen app or presentation (`SHQueryUserNotificationState`) the
bar hides, but never while work runs or the panel is open, so Stop stays
reachable. It grows
while work runs and for twelve seconds when a new result arrives. Its native
owner-drawn buttons retain Windows focus and click handling while matching the
amber and navy workspace palette. Open, Stop and Quit use the existing full-window launcher, Stop event
and Quit action. Open launches Edge from a background thread so its positioning
wait cannot hold the island's Stop control. Hide is allowed only while idle;
Ctrl+Alt+O (which also opens Ask) or a second default launch restores it. The configured voice key
has priority if it uses the same chord. Work or a new research
result reveals a hidden island automatically, and a new result's Open goes
directly to the existing Work tab. Resize and display-change handling clamp
the capsule to the current monitor's work area. A shortcut conflict leaves
Hide unavailable. On shutdown the voice listener tolerates an already-exited
hotkey thread. `--window` opens the movable Edge workspace directly;
`--dock` opens its right-side position. This is presentation only and does not
share the click-through Teach overlay or add input authority. Its one worker owns `Workspace` and Brain; request
threads refuse overlapping work while Stop and Done can signal that worker.
Chat's empty view leads to Point, Research and Plan while leaving the composer
visible. An empty Plan gives a direct route to the Chat composer or drafts
from an existing goal. Brain separates Personal memory, Company knowledge
and Setup with an in-page section control. `company_brain_available` in the
local state prevents presenting Company controls when no knowledge store was
configured; Setup holds the picture policy, accounts, readiness and scalar
statistics. These views invoke only their existing actions.
The empty Chat view shows a one-time getting-started card until dismissed or a
message is sent. It links to the existing Brain Setup view or focuses the
composer; dismissal stays in the dedicated Edge app profile's localStorage.
The card has no backend action and does not connect an account or start work.
The user-level installer stages a complete onedir build beside the installed
directory, moves the old build aside, and restores it if the new directory or
shortcut step fails. A completion marker distinguishes a finished swap from
an interrupted rollback on the next invocation. It refuses to update while
Orbyn is running. Workspace data remains
under `%LOCALAPPDATA%\GhostCursor`, outside the replaceable app directory.
The Work tab's card board previews the current run, newest visible finished
research result, current in-memory turn text and plan steps. Its controls open
the saved result, Chat or Plan, or call the existing Stop API; they add no
execution authority or persisted result. The board is a
focusable region with keyboard card navigation. The Work tab reads the latest
20 generic operation labels and terminal states
from a per-topic local activity file. `App.run()` writes a running record before
the worker starts and a terminal record afterward; startup changes stale
running records to interrupted. The file contains no goal, screen text, result,
window identity or error details. A malformed file remains untouched and the
current session continues with in-memory history. A separate per-topic
`.jobs.json` inbox stores explicitly started read-only research questions,
terminal state, and bounded result locally. It uses the same single workspace
worker, claim lock, provider policy, and Stop event as foreground work. A
finished card downloads its existing question and answer as a browser-created
Markdown file with no server write or model request. The inbox migrates earlier
rows without `pinned` to false. Only finished results
with answers can be kept; at most five are shown first, and the 20-job trim
removes the oldest unkept row when new research starts. A failed Keep or Archive
save reverts the in-memory change and reports an error. Finished results can also
be archived and restored in the same local file. Work hides archived cards by
default; archived cards still count toward the 20-job limit, and only Keep
protects one from trimming. A result's explicit follow-up uses its server-selected saved answer
(first 8,000 characters) through the existing one-off, tainted-material Ask
path and single worker. It sends the question and bounded material to the
configured model, accepts Stop, and saves neither follow-up nor reply.
The background call
suppresses Brief turns, research history and trace writes; it
scrubs the returned answer before writing the inbox. Stop reaches search-phase
checks, both Jev calls and the System Two gateway. The
server stays alive while that worker is busy even if the page closes; after a
restart, a stale running entry becomes interrupted with no retry. It cannot
launch Teach, Act, an agent, or a connector. Each topic file has one intended writer;
concurrent workspace app processes for the same topic are not coordinated.
The per-topic `.routines.json` file stores hourly, daily, or weekly research
questions and next-due times. A due routine enters the same single-worker
research job path; an idle tick coalesces missed intervals into one run and
reschedules from the actual start. Enabled routines keep the app process alive
after its window closes; Quit stops the process and active job. Pausing a
routine prevents future starts, and restart never retries an interrupted job.
The next-due update is persisted before the worker starts; a failed save
pauses that routine in memory. `_begin_run` checks Quit after clearing a stale
Stop event, before a worker is submitted. When the page state is built,
`new_claims` compares each finished routine result with that routine's
previous finished result and lists the claims it did not make (rapidfuzz
token-set >= 90 with the same numbers; source ids ignored). Nothing is stored
or sent for it.
Work's GitHub connector is a separate explicit read path:
`github_connect` validates a supplied token against GitHub before Windows
Credential Manager stores it; `github_repos` and `github_issues` send fixed
GET requests to `api.github.com` and project bounded fields for the page;
`github_disconnect` removes the local token. It cannot enter the worker,
Brief, Brain, model context, routine scheduler or Act authority chain.
Each request checks the organisation's current egress policy before sending;
Credential Manager deletion errors other than "not found" are surfaced, so
an unreadable credential cannot be reported as successfully disconnected.
The PyInstaller build includes `win32timezone` because frozen pywin32
Credential Manager reads require it. Before a frozen app launches the external
Ollama server, `_ensure_ollama()` temporarily clears PyInstaller's DLL search
directory, then restores it, so Ollama does not hold or load Orbyn's binaries.
The page places reusable agent creation and launch in Work, beside recent
status cards. Those cards route to the existing Chat or Plan view; an active
card's Stop control uses the same `stop` API as the live bar. Card links only
navigate; history holds no result identity. The tabs have keyboard arrow,
Home and End navigation. Deleting a saved agent asks for confirmation.
Work also offers a one-off file question: the browser reads an explicitly
selected text file (at most 32 KiB and 8,000 characters) and sends its contents
and the question to the token-protected `ask_file` API. That action validates
both fields and calls `Workspace.ask()` on the worker. That path scrubs the
bounded material with both the tainted-text and full DLP recognizers before
splitting it into at most 300-character tainted values, so patterns crossing
chunk boundaries are masked; the gateway still enforces organisation egress
policy. Stop is passed to the gateway cancellation hook.
The answer stays in the open sheet, which is cleared on close; only the generic
“Asking file” state is written to activity history.

---

## Historical milestone: Open Track submission readiness — two VS Code workflows green

The certified baseline and accepted terminal slice are now merged on
`submission/open-track`. The terminal work was developed on
`feature/vscode-open-terminal` from the `stable-pre-terminal` tag and passed
its gate before the fast-forward merge. Four concern commits preserve the
trusted planner/packs/inference foundation, the
perception/VS Code runtime, the vertical Ask control rail, and its tests/docs.
That baseline is tagged `pre-readiness-audit`.

The release inference code is anchored at `submission-pre-model-hardening`
(`15f20cef...`). A partially implemented schema-constrained Ollama request
contract is parked at `304e8e0` on `post-submission/model-durability` and is
absent from the submission branch. Mechanical branch/tag/absence checks passed,
followed by 23 focused controls, 361 hermetic tests, and all eight live
available/unavailable planner matrix cells against the actual release code.
Only those release-branch results are submission evidence.

The real `Open a folder in VS Code` workflow is complete: natural-language
planning resolves `OPEN_FOLDER`, the `Code.exe`-bounded walker looks only for
Welcome-page `Open Folder` variants, OCR can reassemble the split label, the
human handles the native picker, and normalized title verification confirms
the opened workspace. It passed three consecutive desktop runs. Ask also
passed its visual and submitted-goal round trip.

The second real workflow, `Open the integrated terminal in VS Code`, is also
complete. Planning resolves `OPEN_TERMINAL`; runtime selects a separate
`Code.exe`-bounded walker that publishes only `Toggle Panel (Ctrl+J)` and
`Terminal Section`; the overlay highlights Toggle Panel as context; the human
presses `Ctrl+\``; and an absent-to-present `Terminal Section` transition
verifies completion. An already-visible Terminal Section completes before a
hint is rendered; otherwise a 20-second clock starts with the first hint and
expires before a late state can pass. It passed three consecutive clean desktop
runs. The
controls have no stable AutomationIds, so the system correctly does not
persist them or claim ID-based wrong-action feedback.

The never-fabricate gate is also closed. A model-returned registered intent does
not receive executable authority by registration alone. Today,
`plan_compiled_goal()` requires model advice to agree with the compiled
deterministic matcher, and materialization separately requires an active
adoption. A mismatch can use only the already-grounded trusted intent or return
`UNSUPPORTED_GOAL` with no plan. Registered unavailable intents remain honest
non-launch results.

The test-suite stall is classified and fixed. After the perception worker
starts, the tour/control thread performs no HWND discovery; target identity
arrives only through a completed worker observation, so SPACE fails closed
until it exists. The pre-overlay identity lookup remains synchronous by design
and cannot strand an overlay or control rail. Two tour
test harnesses now use bounded waits and deterministic thread teardown. A
per-module audit ran every non-hung pytest module under a 90-second ceiling:
all collected modules passed, including the 63-second desktop/pixel tour.
`pytest.ini` plus `tests/conftest.py` now separate hermetic, interactive, pixel,
and intentionally hung lanes. An independent D032 review moved the live-window
tick-ceiling module out of hermetic, closed a constructor-time harness leak,
and added positive coverage for worker-HWND SPACE confirmation. Final lane
runs also structurally suppress real control-bar creation in unmarked tests.
They passed: hermetic 341 twice, interactive 53, pytest pixel 3, standalone
pixels 16/16 and 8/8, and isolated hung modules 4 + 2 + 7. The
participant evidence and submission production are the next gates.

Participant evidence now has a locked, empty-by-design protocol in
`docs/evidence/novice-vscode-study.md`: recruit three novice VS Code users
(two is the disclosed fallback), collect baseline and guided observations live,
and make no user-value claim below `n=2`. Demo production follows
`docs/submission/demo-video-script.md`; its Open Folder, Ask/Open Terminal, and
unsupported-goal clips are protected inside a 4:45 maximum. No participant
results or invitations are claimed until they actually occur.

## Previous milestone: Chromium warm-up  ✅ complete

## Previous milestone: Perception tier 2 (OCR)  ✅ complete

## Previous milestone: Intermediate Project — Single-App Guided Tour  ✅ complete

The Beginner milestone (Static Hint Overlay ✅) is complete. The Intermediate
milestone builds the observe-act-verify state machine, the grounding ladder,
live UIA verification, and the recipe-driven guided tour interface.

Previous milestone (Beginner) goal: a Win32 layered window that draws a ring
around one UI element found via `pywinauto`, drawn with GDI, refreshed on a
timer. No AI, no reasoning loop.

### Import-time ordering (matters — see D010)

```
ghostcursor.run
  imports ghostcursor.overlay.window
      imports ghostcursor.overlay.dpi
          dpi._ensure_dpi_awareness()      <-- runs AT IMPORT, before any window
              SetProcessDpiAwarenessContext(-4)   -> 0 (fails on argument marshalling, not on the machine -- D106)
              SetProcessDPIAware()                -> 1 (works; 1536x864 -> 1920x1080)
```

Nothing may query DPI-dependent state before this, and nothing may create a
window before it either — awareness locks permanently on first use, and
`mss` flips it implicitly if it gets there first.

### Runtime call graph (as built)

```
run.main()
  window.create_overlay_window()
      dpi.virtual_screen_rect()            -> (0, 0, 1920, 1080)
      RegisterClass(GhostCursorOverlay)    (once; brush kept at module scope)
      CreateWindowEx(WS_EX_LAYERED | WS_EX_TRANSPARENT
                     | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
      SetLayeredWindowAttributes(colorkey=magenta, LWA_COLORKEY)
      ShowWindow(SW_SHOWNOACTIVATE)        (never steals focus)

  loop every REFRESH_SECONDS (0.25s), until ESC or --seconds:
      run.escape_pressed()                 GetAsyncKeyState(VK_ESCAPE)
      run.resolve_target(title_re, control)
          perception.uia.find_element()    UIA descendants, name match
              -> None for Notepad "Save" (it lives in a menu, not a button)
          perception.uia.window_bbox()     UIA top-level rect  -> (160,160,1009,945)
              falls back to uia._raw_window_rect() only if UIA gives nothing
          -> centre point of that rect
      window.set_hint(hwnd, x, y)
          stores _hint (screen -> client coords via _origin)
          InvalidateRect + UpdateWindow    -> synchronous WM_PAINT
      window.pump_messages_nonblocking()

  window._wnd_proc  on WM_PAINT:           <-- the ONLY place anything is drawn
      BeginPaint
      FillRect(client rect, colorkey brush)    entire overlay -> transparent
      _paint_ring(hdc, x, y, radius)           only if a hint is set
      EndPaint
  window._wnd_proc  on WM_ERASEBKGND: return 1   (we erase in WM_PAINT)

  finally:
      window.destroy_overlay_window(hwnd)
```

### Files
| File | Role |
|---|---|
| `ghostcursor/run.py` | entry point, timer loop, ESC/timeout safety, arg parsing, grounder builder for live promotion |
| `ghostcursor/overlay/dpi.py` | declares DPI awareness at import; one coordinate space |
| `ghostcursor/overlay/window.py` | layered click-through window, WM_PAINT rendering; Teach hint ring and Act cue (ring, ghost pointer, label plate), plus `measure_label` for real font metrics |
| `ghostcursor/overlay/cue.py` | pure Act cue layout: glyph outline tipped at the acted point, trust colour, callout placement clear of the control it names |
| `ghostcursor/pointer_path.py` | pure pointer geometry and timing: eased traversal frames, settle, poll points, all derived from a measured paint cost |
| `ghostcursor/act_presenter.py` | walks one cue on an injected clock and returns its receipts; a completed cue stays up for the dispatch, an aborted one clears and completes nothing |
| `plugins/sources/powerpoint/payload/ghostcursor/adapter/powerpoint_live_verifier.py` | signed read-only LIVE-state verifier: reads the running deck's slide count and answers a postcondition naming a CHANGE against the pre-cue baseline; AST-scanned to prove it cannot act |
| `ghostcursor/selectors.py` | loads the signed selector an operation names and proves its digest; an action selector must be `exactly_one` and agree with the operation's control type |
| `ghostcursor/act_uia_session.py` | composes one UIA node's session: verifier reading as `semantic`, adapter read-only read as identity/rectangle, overlay as the cue |
| `ghostcursor/act_ui_bridge.py` | manager UI-thread bridge: the worker requests cue presentation and receives receipts while the manager thread exclusively creates/pumps the Win32 overlay |
| `ghostcursor/verified_python.py` | absolute `-I -S` executable-payload bootstrap: hash one path read against signed authority with no site `.pth`, payload, or PYTHONPATH startup, then compile and execute those same in-memory bytes |
| `ghostcursor/devtools/act_campaign.py` | counts consecutive clean Act attempts; fresh store/output per attempt, target re-checked and restored each time, refuses an `interrupt_probe` record, stops at the first unclean run |
| `ghostcursor/brief.py` | the stored conversation a plan is proposed from (D113); `bind_brief` re-reads the source so a proposal cannot bind a digest that no longer describes the file; appends turns to a Markdown brief, loads it back, digests the exact bytes; a closed type with no field that could carry anything executable |
| `ghostcursor/act_staging.py` | transactional artifact output used by the CLI/campaign path: runtime-owned same-volume staging, atomic publish after complete verification, digest binding, and an `.incomplete.json` marker cleared only by successful publication |
| `ghostcursor/act_rail.py` | the Stop/Pause safety rail for an Act run; shows the executor-reported `Step N of M` and never counts; the ONLY visible surface for an object-model plan (D109) |
| `ghostcursor/act_overlay.py` | seam binding the presenter to a real HWND and the run's Stop; supplies `present`/`on_state` to `UiaNodeSession`, recolours a verified pointer (D112), pumps messages inside the Stop poll |
| `ghostcursor/perception/uia.py` | UIA element/window lookup + raw win32 fallback |
| `ghostcursor/reasoning/schema.py` | frozen data structures: Recipe, Step, VerificationRule, enums (UserAction, VerificationKind, Risk) |
| `ghostcursor/reasoning/grounding.py` | turn step descriptions into live screen rectangles via the 4-rung matching ladder (id, type+exact name, UIA-only substring, OCR fuzzy at floor 95) + promotion |
| `ghostcursor/reasoning/verification.py` | check world state to decide if user completed a step |
| `ghostcursor/reasoning/loop.py` | observe-act-verify state machine (IDLE → OBSERVING → DECIDING → RENDERING_HINT → AWAITING_USER_ACTION → VERIFYING) |
| `ghostcursor/reasoning/renderer.py` | adapt loop's Renderer protocol onto the Win32 overlay |
| `ghostcursor/packs/index.json` | sole installed pack index; roots every verified application and planner-only pack |
| `ghostcursor/packs/compile.py` | compiles verified intents, recipes, and observation plans without scanning for files |
| `ghostcursor/packs/workflow.py` | binds a compiled recipe to one live target and revalidates every authority input before launch |
| `ghostcursor/perception/appinfo.py` | identifies the app owning a window (HWND -> PID -> exe path -> file/Appx version) for version-scoped observation lookup |
| `ghostcursor/reasoning/identity.py` | `step_key()` — durable hash of intent + claimed descriptor, the key observations are stored/retrieved under |
| `ghostcursor/memory/store.py` | `ObservationStore` — local SQLite knowledge base of learned observations, keyed by `(step_key, app_id, app_version, automation_id)` |
| `ghostcursor/perception/service.py` | `PerceptionService` — runs the UI-tree walk AND tier 2 on a worker thread that owns its COM apartment, publishes one timestamped `Observation` into a single overwritten slot, and receives the UI thread's `Tier2Request` through a second overwritten slot going the other way. Also samples focus in `focus_slice_s` slices during the inter-walk wait (`_sample_focus_while_waiting`) and publishes the distinct in-app AutomationIds visited as `Observation.focus_visited` |
| `ghostcursor/perception/focus.py` | `read_focused_automation_id(hwnd)` — the in-process focused control's AutomationId, or `""`; knows nothing about steps or grounding, only "what has focus right now" |
| `ghostcursor/perception/health.py` | `WorkerHealth.check()` — notices a dead or stalled worker, restarts it exactly once, then ends the tour with a reason |
| `ghostcursor/reasoning/staleness.py` | `StalenessLadder` — how old the last confirmed-fresh walk is, as `Freshness.FRESH / DIMMED / INFERRED / HIDDEN`, with debounced recovery; `display_freshness()` combines age with provenance |
| `ghostcursor/perception/ocr.py` | `WindowsOcr` wrapper over `Windows.Media.Ocr`, `ocr_available()`, and `reassemble()` for labels that wrap onto two lines |
| `ghostcursor/perception/capture.py` | DPI-correct per-window pixel capture and frame differencing |
| `ghostcursor/perception/tier2.py` | `Tier2Controller` — when OCR runs and when it stops: per-step stickiness, a 1.0s floor, a ceiling of 20 CONSECUTIVE FRUITLESS reads (reset by `grounded()`), terminal exhaustion. Owned by the perception worker, never called from the UI thread |
| `ghostcursor/perception/warmup.py` | `WarmUp` — suppresses the tier-2 request for a budget (`DEFAULT_WARMUP_BUDGET_S = 2.0`) after a window's first failed grounding, keyed by window handle, and closes permanently for that handle the first time UIA grounding succeeds against it |
| `tests/backdrop.py` | controlled solid-colour window used as a test surface |
| `tests/hung_window.py` | child process that creates a window and then stops pumping messages — reproduces the 41s UIA block deterministically |
| `tests/test_hung_window.py` | `HungWindow` context manager + the block measurement; the fixture Tasks 5-7 are built on |
| `tests/test_run_threaded.py` | ESC stays responsive while the target is hung — the property this whole design exists for |
| `tests/test_freshness_timeline.py` | historical v1 staleness regression; compiled equivalents now live in `tests/test_compiled_perception.py` |
| `tests/test_tier2_controller.py` | the cadence itself: the 1.0s floor, the frame diff, the fruitless-run ceiling and its reset, all on an injected clock |
| `tests/test_tier2_timeline.py` | tier 2 end to end as an ordered sequence — UIA-blind service, request slot, OCR elements arriving on a later observation, amber ring |
| `tests/test_tier2_tick_ceiling.py` | D020's 0.5s tick ceiling measured WHILE tier 2 is engaged — the case `test_tick_latency.py` cannot reach, because there grounding never fails |
| `tests/test_grounding_rung4.py` | rung 4 at floor 95, and the guard that stops rung 3 bypassing it; fixtures are real spike reads with their real scores |
| `tests/test_ocr_engine.py` | the `Windows.Media.Ocr` wrapper, and that unavailability degrades instead of raising |
| `tests/test_ocr_reassembly.py` | `reassemble()` on the spike's real wrapped-label reads — rejoining without inventing new labels |
| `tests/test_capture.py` | per-window capture and `frames_differ` — the diff is what stops OCR running every tick |
| `tests/test_element_source.py` | `Element.source` — how the system tells a pixel guess from a confirmed control |
| `tests/test_freshness_inferred.py` | `display_freshness` — INFERRED, its precedence, and the fail-safe for unrecognised sources |
| `tests/test_overlay_inferred.py` | the third ring colour is distinguishable from the other two, in pixels |
| `tests/test_overlay_freshness.py` | the dimmed ring colour differs from the fresh one |
| `tests/test_first_paint.py` | a standing property (D027): a hint's FIRST paint already carries its final display state, over the whole `Freshness` x source cross-product |
| `tests/test_regression_ocr_fixes.py` | the three properties c6115a1 left unguarded: the laundering sequence, the churning page, and the promotion source guard |
| `tests/test_overlay.py` | 16 checks: styles, click-through, transparency, hint placement, dimmed AND inferred ring colours, stale pixels, teardown |
| `tests/test_end_to_end.py` | 8 checks: perception -> coordinate -> ring lands on the window, off-screen rejection |
| `tests/uia_app.py` | real Win32 window with known AutomationIds, used as deterministic grounding target |
| `ghostcursor/inference/screen_hint.py` | bounded Qwen choice among live, recipe-approved UIA targets with deterministic fallback |

**A hung window is a desktop-wide side effect.** Any UIA enumeration that
touches a non-pumping window pays the SendMessage timeout, no matter which
process started the walk. Measured: the same two test files take **6.28s
normally and 100.13s** while a hung window sits on the desktop. So the three
hung-window files above must never run concurrently with another test
session, and `HungWindow` must reap its child unconditionally — a fixture
that outlives its test turns that 16x tax permanent. Two "flaky" failures in
this repo were exactly this and nothing else.

### Verification status

The repository has four executable lanes: hermetic, interactive Win32/UIA,
pixel, and intentionally hung-window. Exact commands are in `CLAUDE.md` and
`README.md`; lane ownership is centralized in `tests/conftest.py`. Task 10 ran
every lane after the authority cutover, and Task 13 repeated the non-desktop
gates on the final active catalog. The standalone pixel scripts remain
self-runner modules and are not collected by pytest. The three hung files each
park a real non-pumping window and must run alone — see the note under Files.
Also confirmed against a real Notepad window: 440 ring pixels, 49x49
diameter, centroid within 1px of the requested coordinate. And confirmed
against a real persistence run: a UI AutomationId learned by one process was
reused by a completely separate later process (rung 2 -> rung 1 across
process boundaries), and deleting the database file returned behaviour to
rung 2 — see the persistence call graph above.

### Current milestone state

**The declarative workflow compiler is implemented and all four accepted
workflows are active.** Final regression and documentation close the milestone;
release or `main` merge still requires explicit owner approval.

**D070 fixes the future knowledge boundary before tables exist.** Runtime
screen observations remain in erasable `kb.sqlite`; curated knowledge belongs
in a separate local `knowledge.sqlite`; and only schema-valid JSON named by the
indexed catalog and an active adoption can authorize a workflow. Draft adoption is always
human-gated: quarantine -> isolated read-only acceptance -> content-addressed
install -> activation swap. No database row, draft, directory glob, or ambiguous
filename fallback is execution authority; D070 carries the complete rule.

Historical spike A measured whether the local model can change the executable outcome.
Across the frozen 1.0.0 dataset, 30 cases x 2 passes, **zero of 60 case-runs
changed the executable recipe**. Exactly one model request per case, asserted by
a counting wrapper on the transport; deterministic and policy views are pure and
reuse that same sample. The model diverged from deterministic grounding on 11 of
30 cases, five of them recipe-bearing, and D058 denied authority to every one.
Model comparison is therefore a latency and cost benchmark, and model swapping
is deferred.

Historical spike B selected workflow #3. **Open Extensions passes** with existing
machinery: `strategy-1` reads `Extensions (Ctrl+Shift+X)` as a `TabItem` in
11.2 ms, the view is persistent, and `element_appears` on `Installed Section`
gives the same absent-to-present transition `Terminal Section` already provides.
No new verification kind, no new selector strategy. The Command Palette is
rejected: it drives the bounded `TabItem` walk to zero while open, and its
closed state is not distinguishable from its open state by pointer alone. Its
dismissal on focus loss was attempted four times and is recorded as unmeasured.

The load-bearing discovery is a presence bug that spans everything:

```
FindFirst(condition)
  -> object, property read succeeds        -> PRESENT
  -> object, NULL COM pointer on read      -> ABSENT
  -> object, any other COM/read failure    -> PERCEPTION FAULT
```

A non-`None` return carries no information. `iter_vscode_elements()` collapses
the last two branches with a blanket `except Exception: return []`, so a real
fault is published as an empty successful observation. That is why Open Folder's
tier-1 perception went dark unnoticed: it returns 0 elements against VS Code
1.134.0 and the workflow completes on OCR alone, so an outcome-only acceptance
gate cannot see it.

That sequence is complete: the shared provider-query helper, bounded Open
Folder walk, positional-ID refusal, compiler, atomic authority cutover, and
data-only Open Extensions adoption are all implemented. The acceptance record
contains 12 successful human runs, and the exact baseline-to-adoption range is
the proof that Open Extensions required no workflow-specific Python.

## Earlier completed slices


The current completed slice is the perception-health foundation for real-app
validation. `PerceptionService` records generation-aware progress primitives:
iteration start, last completed iteration, last published observation, current
stage, heartbeat, and last error. `WorkerHealth` reads that progress without
touching COM objects. A two-second gap is diagnostic `SLOW`; a twelve-second
gap permits one restart. `PerceptionService.restart()` retires the old worker
generation without joining it, starts a replacement, and leaves the existing
guided-tour state untouched. The old generation is prevented from publishing
after retirement. A terminal tour stops the service before health checks can
report stale worker failures.

The perception-health slice is complete. Schema v2 replaced the earlier
manifest scanner with `load_catalog()`, which follows only paths named by
`ghostcursor/packs/index.json` and each pack's `activation.json`. Trusted
artifacts are read once, digest-checked, strictly decoded, and schema-validated
before `PackRegistry.from_verified()` receives their window identity. Recipe
authority comes only from an active adoption record; filename inference,
directory scans, and one-intent fallbacks no longer exist. The installed packs
are Common, Synthetic Export, Notepad, and VS Code. Matching remains
metadata-only; no model or pack can perform input.

The current implementation slice adds the VS Code `OPEN_FOLDER` intent to the
trusted planner and pack registry. `ghostcursor/reasoning/vscode.py` extracts
the final path segment from a goal, casefolds and whitespace-normalizes it, and
verifies a changed VS Code workspace title. A short or empty reference falls
back to a changed valid VS Code title. The recipe points directly at the
Welcome page's visible `Open Folder...` action, leaves the native folder picker
to the user, and opts into a 20-second post-action
verification timeout. The loop starts that timeout only after action evidence
such as focus movement, element change, or title change.

The compact-menu desktop exposes no visible/UIA `File` item. The bounded VS
Code query therefore looks only for `Open Folder` name variants. If UIA misses,
the `Code.exe`-bounded capture goes to Windows OCR; same-line word reassembly
turns the measured `Open` and `Folder...` reads into one exact candidate while
retaining the original words and the 95 grounding floor.

The historical v1 slice added `OPEN_TERMINAL` to the trusted VS Code manifest
and planner allowlist. Its workflow walker was replaced by the compiled plan;
keeps Open Folder on its own reviewed walker (since D069 a bounded,
normalised-name Button walk rather than the provider-side exact query) and selects
`uia.iter_vscode_terminal_elements` only for the terminal recipe. That walker
is still `Code.exe`-bounded and filters a Button-only UIA walk down to the two
reviewed exact names. The recipe's `PRESS_KEYS` value describes the human
action; GhostCursor never sends input. Verification uses `ELEMENT_APPEARS`
for exact `Terminal Section`. `accept_if_already_present` prevents the shortcut
from closing an already-open terminal. For the unsatisfied path,
`timeout_from_hint` starts the 20-second deadline at first render, because a
no-op name-only keyboard shortcut produces no reliable focus action event.

A click-based rehearsal was rejected because Toggle Panel restored Debug
Console. The native `Ctrl+\`` instruction then passed 3/3 consecutive clean
desktop runs from confirmed absent baselines. Empty Electron AutomationIds
mean promotion, persistence, and focus-based wrong-action naming fail closed;
the accepted evidence is live name/type grounding plus application-state
verification on every run. After independent-review corrections, regression
passed 50 focused tests, 355 hermetic tests, and 55 interactive Windows/UIA
tests. The already-present desktop path completed without rendering, and the
corrected transition path passed another clean 3/3 sequence.

The implementation and real VS Code desktop path are validated. The foreground
watcher is logging-only; tray UI, installer, and web retrieval remain deferred.

The current implementation also adds `ghostcursor.daemon`. Its
`ForegroundWatcher.poll_once()` reads a foreground identity, asks
`PackRegistry.match_values_with_reason()` for a pack and diagnostic reason, and
logs only identity metadata. Unchanged foreground identities are suppressed.
Successful matches log pack activation; misses log the executable, a title
summary capped at 60 characters, and whether executable/title matching failed.
The daemon is manually launched and does not start tours or create UI.

Automated implementation status: worker health, packs, VS Code title
verification, planner routing, timeout sequencing, and daemon logging are
covered by the focused and non-hung regression set. The final real-desktop
transition is intentionally not inferred from those tests: VS Code must be
open and the user must select a folder for three consecutive successful runs.
The current implementation live-grounded and rendered the Welcome-page action.
Three consecutive complete user-driven runs selected a folder and reached
`Tour complete.`, closing the VS Code open-folder real-desktop gate.

The control surface now starts as a 148×192px vertical rail at the middle-right
edge: Stop, Pause, Ask, then status. Ask is accepted only in
idle/done/failed state as before. `open_panel()` keeps the same right edge and
vertical centre, expands the parent leftward to 520×260px, moves the safety
controls into the fixed right rail, and creates a 372px prompt column on the
left. That column contains a label and large multiline EDIT child. Submit
stores the goal for the existing planner path; `close_panel()` destroys the
prompt children and restores the compact rail. Stop and Pause stay visible.

The VS Code open-folder desktop acceptance gate is now **3 of 3 consecutive
successful runs** and complete. The vertical rail's Ask card has also passed
real-desktop visual validation: it expands left and visibly exposes its label,
multiline goal input, Submit, status, Stop, and Pause without clipping. The next
goal was entered and submitted successfully; the shared planner launched a
fresh trusted VS Code tour and that tour reached `Tour complete.` The Ask
end-to-end behavioral gate is therefore complete. Ask now prints its received
goal and planner status before entering the nested tour so the handoff is
visible immediately in console logs.
**Wrong-action feedback is built** (D037). The perception worker
(`ghostcursor/perception/service.py`) now samples focus in `focus_slice_s`
(default 0.05s) slices during its inter-walk wait, via
`_sample_focus_while_waiting`, reading through
`ghostcursor/perception/focus.py`'s `read_focused_automation_id(hwnd)` — the
in-process focused control's AutomationId, filtered to the target process and
non-empty ids, or `""`. It accumulates the distinct ids focus MOVED TO (not
where it merely rests) into a list, via `_record_focus`: an id already
holding focus at the interval boundary is deliberately never reported, only
a change away from it, and the first non-empty read of the worker's
lifetime only seeds that comparison rather than being reported itself.
Capped at `MAX_FOCUS_VISITED`, plus one sample
recovered at the start of each walk (`_run`), and publishes them as
`Observation.focus_visited: tuple[str, ...]` on the next successful
walk — cleared only on a successful publish, so a raising walk does not
silently drop an interval's ids. `Snapshot.focused_automation_id` is filled
the same way at walk time.

`ghostcursor/reasoning/loop.py`'s `AWAITING_USER_ACTION` arm gained one new
branch, ordered between the satisfied check and the existing
`elements_changed` branch: `GuidedTour._wrong_action(self)` compares
`focus_visited_source()` against the grounded target's AutomationId. Satisfied
verification always wins first — a step that completed despite a detour is
never interrupted to be criticised for it, and that path does not count
toward the re-hint cap. If unsatisfied and a non-target in-app id was
touched, `on_wrong_action(touched, target)` fires (uncapped — capping the
console line would tell a struggling user less the harder they try) and the
loop returns to `State.OBSERVING`, which re-grounds and flows back through
`RENDERING_HINT` to re-show the ring — deliberately the existing path, not a
second `renderer.show()` call, because `set_hint` ends in a synchronous
`UpdateWindow` and a second write is a second frame that reaches the screen
(D027). `wrong_action_rehints` caps that re-assertion at 3 per step, distinct
from the unrelated 1-cap on the idle re-hint (idle is inaction; a wrong
action is an active attempt worth answering, up to a bound). The branch is
silent by construction whenever the grounded target itself has no
AutomationId — every OCR-grounded step, since OCR elements never carry one —
so wrong-action feedback does not exist there.

`ghostcursor/run.py` wires two new closures into the `GuidedTour(...)`
construction (around its `focus_visited_source`/`on_wrong_action` keyword
arguments): `focus_visited_source()` reads `current_observation.focus_visited`
— the same already-bound observation `snapshotter()` produced earlier in the
tick, never a fresh `service.latest()` call (D019), so `touched` and the
tick's `after` always come from the same observation — and `on_wrong_action`
prints the one console line. Native UIA focus-change events remain
deliberately unbuilt — the sampling gap they would close is real
(0.18-0.93s, measured, D037/D034), but closing it needs COM callbacks
marshalled into the worker's apartment, the D021 area already paid down once.
`FOCUS_MOVES_TO` verification, previously `NotImplementedError`, is enabled.
Details and every measured number: D037.

**Chromium warm-up is built** (D035). A `WarmUp` object
(`ghostcursor/perception/warmup.py`) suppresses the tier-2 request for a
budget (`DEFAULT_WARMUP_BUDGET_S = 2.0`) after a window's first failed
grounding, and closes permanently for that handle the first time UIA
grounding succeeds against it. The tier-2 request site in `run.py`'s
`grounder_from_slot` (around line 436-439) now calls
`warmup.allows_tier2(target_hwnd)` before `service.request_tier2(i)`; the
UIA-success path (around line 413) calls `warmup.note_grounded(target_hwnd)`.
`Observation` (`service.py`) now carries `target_hwnd: int`, published by the
worker (D021 — read from an apartment-bound UIA object on the worker thread
and crossed as a plain int, never a COM object).
Keyed by HANDLE, not the title regex a step matches against, because
Discord's cold start puts up a distinct-HWND `Discord Updater` splash that
fully matches the same regex and would otherwise consume the whole budget
before the real window exists. Details, all measured numbers, and their
citations: D035.

**Perception tier 2 (OCR) is built** (D028-D030). When UIA cannot see the
control a step names, the screen is read with `Windows.Media.Ocr` and the
hint renders amber (`INFERRED`) rather than cyan, so a pixel guess never
wears the confirmed-control ring.

**OCR runs on the perception worker, not on the tick.** The UI thread is the
only one that knows which step is current and whether grounding just failed,
so it DECIDES and REQUESTS — `service.request_tier2(step)`, a lock-and-assign
into a second overwritten slot running the opposite way to the observation
slot. The worker EXECUTES (capture, diff, OCR, reassembly) and publishes what
it read as `ocr_elements` on a LATER observation, tagged with `tier2_step` so
one step's reads can never be mistaken for another's. There is no wait, no
join and no future: grounding may simply fail for a tick or two until the read
lands, which the 10s grounding grace and the staleness ladder already cover.
There is no `wanted` flag either — the ABSENCE of a request is "not wanted" —
so the UI thread cancels when UIA answered (`cancel_tier2(i)`) and at every
step boundary (`cancel_tier2()`), or a request from a step nobody is on keeps
costing 0.14-0.23s of worker time as often as the 1.0s floor allows.

What forced it, measured on real screens: Adobe Acrobat exposes **0 of 16**
tool labels to UIA — 20 elements, 17 of them anonymous Panes — while OCR reads
**21 of 24** labels at the shipped floor of 95. A floor of 85 was rejected, but
not for anything on this Acrobat screen: the binding case was Canva Home,
where `Uploads` scored 92.3 against a read of `upload` — two different real
Canva surfaces one character apart. The Canva photo editor exposes
**4 of 13** even with a fully warm Chromium accessibility tree.

What it deliberately did NOT cover at the time: Electron apps are
*blind-until-asked*, not blind — Chromium enables its accessibility tree on
demand, and the first UIA probe switches it on. They wanted a **warm-up
retry**, cheaper than OCR — built in the following milestone, see "You are
here" above and D035. Icon-only controls carry no text and are unreachable by
any OCR; that is still tier 3, the VLM.

Photoshop itself was never measured. Acrobat was a proxy for its shape.

Two bugs found only where the pieces compose, both fixed and both now
guarded by tests: an OCR hint was painted once in confirmed-control cyan
before being corrected in the same tick (D027 — any two-step render where
paint can interleave with correction is a laundering bug); and an
unrecognised `source` resolved to the most trusting label, which a future
VLM tier would have walked straight into.

Previously: perception moved **off the UI thread** (D021-D024). The escapability
guarantee is structural rather than test-enforced: a hung target can no
longer block the tick loop, so ESC keeps being polled no matter how slow
perception becomes. Proven historically by driving the real v1 tour against a real
hung window; making perception synchronous again fails that test with
`ESC was only polled 7 times before the v1 tour returned`, and the run takes
95.6s instead of 16s.

What that milestone added: a worker thread owning its COM apartment
(`service.py`), a single timestamped slot, the staleness ladder
(`staleness.py`) and its dimmed ring, worker-death detection with
restart-once (`health.py`), and the freshness gate that keeps
`AWAITING_USER_ACTION` from verifying against an observation no newer than
the one `OBSERVING` used.

Two bugs found only where those pieces compose, both fixed:
- a dead worker used to be reported as `cannot find 'Export' on screen`,
  because the 10s grounding grace expired before the 15s health budget —
  pointing the user at their own application instead of at ours;
- "restart once, then give up" degenerated into "give up", because the
  staleness clock measures observations, not workers, so a replacement
  inherited the staleness of the worker it replaced and died 0.25s later.

The Intermediate milestone (Single-App Guided Tour) remains **COMPLETE** —
verified end-to-end on a real, non-synthetic application, not only the test
harness.

Closing evidence, a guided tour run twice against live Notepad (a Store app,
`notepad.exe` 11.2606.15.0 resolved through the Appx package path, 39 UIA
elements):

```
run 1   hydrated=0   rung 2 (matched by name)          learned AutomationId 'AddButton'
run 2   hydrated=1   rung 1 (matched by that id)       same target, no re-learning
both    state = AWAITING_USER_ACTION                   dwelling for the human, never acting
both    440 ring pixels landed on the real button      observe -> hint 147-161 ms
```

The tour stopping at AWAITING_USER_ACTION is the design, not a failure: the
system draws a hint and waits. Only the user can advance the step (D006).

The `IDLE → OBSERVING → DECIDING → RENDERING_HINT → AWAITING_USER_ACTION →
VERIFYING` state machine, grounding ladder, live UIA verification, Win32
renderer adapter, schema-v2 `--goal` entry point, and persistence are built and
wired together end-to-end. Promotion survives process exit through
`ObservationStore`, keyed by `(step_key, app_id, app_version, automation_id)`,
and perception tier 2 plus Chromium warm-up remain active (D035). What remains
unbuilt is the doc-ingestion knowledge base and tier 3, the VLM.

### Runtime call graph — guided tour (historical v1, removed)

This graph is retained only to explain the decisions that shaped the compiled
executor. It is not a callable path or implementation guide.

```
removed path-based tour
  removed recipe-path loader

      --- perception moves OFF this thread, before the overlay exists ---
      tier2.build_controller(clock)    -> Tier2Controller | None (None = no OCR here)
                                          built on THIS thread, then HANDED OVER and
                                          never touched from here again
      service.PerceptionService(title_re, tier2=controller).start()
          worker thread: CoInitializeEx, then forever:
              uia.iter_elements(title_re)                  ~40s against a hung target
              verification.take_snapshot(..., observed_at)  timestamped from the service clock
              service._tier2_payload()                     OUTSIDE the walk's try, so a raising
                                                           walker cannot skip the OCR run itself
                                                           — but publication only happens after
                                                           the walk succeeds, so on a raising
                                                           walk OCR still runs (spending the
                                                           one-shot `grounded` flag) and its
                                                           result is simply discarded, unpublished
                  _take_tier2_request()                    consumes `grounded`; the request
                                                           itself STANDS until cancelled
                  tier2.Tier2Controller.elements_for(step, title_re)
                      capture.capture_window()      per-window pixels, DPI-correct
                      capture.frames_differ()       skip if nothing visibly changed
                      ocr.WindowsOcr.read()         word-level reads, frame-relative
                      ocr.reassemble()              rejoin labels that wrapped
                      -> Elements with source="ocr", window origin ADDED
              -> publishes ONE Observation into a slot (overwrite; no queue, no history),
                 carrying snapshot + UIA elements + ocr_elements + tier2_step/_engaged/
                 _exhausted/_max_runs. `tier2_step` is -1 when tier 2 did not run
      staleness.StalenessLadder()      how old the last CONFIRMED-FRESH walk is
      health.WorkerHealth(service, ladder)   restart once, then end the tour

      window.create_overlay_window()
      GuidedTour(recipe, grounder=run.grounder_from_slot, snapshotter=run.snapshotter,
                 verifier=verification.verify, renderer=OverlayRenderer(hwnd))

          run.snapshotter()          service.latest() -> Observation | None
                                     None -> empty Snapshot (observed_at 0.0, reads as FRESH)
                                     ladder.observed() ONLY when observed_at ADVANCES —
                                     re-reading the same slot must not reset the clock
          run.grounder_from_slot()   uses the elements the LOOP passed in (the ones OBSERVING
                                     snapshotted), so OBSERVING and DECIDING describe the SAME
                                     instant (D019); falls back to service.latest() only when
                                     the loop passes none. Grounds the LAST observation, so a
                                     merely-stale slot keeps succeeding and the loop's
                                     grounding grace never starts

                                     --- TIER 2, only if that grounding FAILED (D028) ---
                                     UIA answered? service.cancel_tier2(i) and return — a
                                     standing request is a standing cost on the worker.
                                     ALSO: warmup.note_grounded(observation.target_hwnd) —
                                     this handle's tree is proven, so its warm-up (if any)
                                     never applies again.
                                     Otherwise:
                                     warmup.allows_tier2(observation.target_hwnd)  (D035) —
                                         False inside a fresh window's budget (default 2.0s):
                                         return None and skip the request entirely. A cold
                                         Chromium tree is populating, not blind; the budget
                                         gives it a chance to answer for free before OCR is
                                         even asked for.
                                     service.request_tier2(i)   lock-and-assign, never blocks.
                                         The READ happens on the worker; its result turns up
                                         in a LATER observation, so this tick may still fail
                                         to ground (grace + staleness ladder cover that).
                                     ocr_elements = observation.ocr_elements, but ONLY if
                                         observation.tier2_step == i — flags and reads describe
                                         ONE step, and they come from the SAME observation
                                         OBSERVING snapshotted (D019)
                                     re-ground with UIA elements + OCR elements. Rung 3 excludes
                                     OCR; OCR gets in at rung 4 (fuzzy, floor 95) and at rung 2
                                     (byte-exact name — a strictly higher bar).
                                     grounded? service.report_tier2_grounded(i) — a productive
                                     read must not spend the step's budget.
                                     Stickiness is per STEP; 1.0s floor, ceiling of 20
                                     CONSECUTIVE FRUITLESS reads; hitting it ends the step
                                     rather than freezing the hint.

      loop every REFRESH_SECONDS (0.25s), until ESC, --seconds, DONE, FAILED, or health:
          run.escape_pressed()                 GetAsyncKeyState(VK_ESCAPE) — never blocked now
          tour.step_index changed?              service.cancel_tier2() — the worker cannot see
                                                a step boundary, and nothing else ends a standing
                                                request, so a step that asked and was then LEFT
                                                would keep the worker reading for it forever
                                                (AWAITING_USER_ACTION dwells for many ticks
                                                without ever calling the grounder)
          GetAsyncKeyState(VK_SPACE)            polled -> tour.confirm() for user_confirms steps
          health.check()                        once per tick; suppressed until the first
                                                observation lands or dead_after_s from tour start
                                                (ladder.age() is inf before then)
          service.latest() is None?             SKIP the tick entirely (still pumps + polls ESC).
                                                Spec §9: stay in OBSERVING. Ticking here would
                                                let the empty placeholder snapshot become a
                                                VERIFICATION BASELINE and mark a step complete
                                                the user never performed (D006)
          tour.tick()                           _advance() then renderer.settle() — the loop
                                                closes its own tick so a driver cannot forget,
                                                and AWAITING's early return cannot skip it
              OverlayRenderer resolves the AGE half of the display state ONCE per tick
                  freshness_source() -> run.current_display_freshness() -> ladder.freshness()
                                        (a MUTATING query: exactly one call per tick; None
                                         resolves to INFERRED, never to FRESH)
                  the SOURCE half is NOT read here. `show()` binds the target's provenance
                  into a frozen `_Hint(centre, source)`, and `_paint()` folds it in with
                  staleness.display_freshness(freshness, hint.source) — so a repaint
                  reproduces the state ITS hint was created with, never a later step's.
                  There is no `grounded_source` variable any more: a provenance that could
                  be updated separately from its coordinate is exactly what let DECIDING
                  repaint the previous step's OCR centre in confirmed cyan for a whole tick.
                  -> exactly one set_hint/clear_hint emission per tick, so no WM_PAINT can
                     observe a provisional state and launder a pixel guess into FRESH (D027)
              [DECIDING]    grounder(step, i, elements)
                                grounding.ground(step, title_re, elements=obs.elements)
                                                                    rung 1: automation_id
                                                                    rung 2: control_type+name
                                                                    rung 3: substring/synonyms,
                                                                            source=="uia" ONLY
                                                                    rung 4: OCR text, fuzzy,
                                                                            floor 95
                                grounding.promote(step, grounded, app_version, locale=ui_locale)
                                  (writes automation_id back to in-memory Step; persists to disk.
                                   Refuses anything whose source is not "uia" — D030)
                                -> GroundedTarget | None  (None => clear hint, 10s grounding
                                   grace, then FAILED; never a guessed coordinate.
                                   Only reachable once a real observation exists — the tick
                                   loop skips entirely until then — so a grounding failure
                                   means perception WORKS and the element is genuinely absent.
                                   run.read_failure_reason(step, i) replaces the generic
                                   "cannot find X" when the published observation says tier 2
                                   was engaged for THIS step — reading `tier2_engaged` /
                                   `tier2_exhausted` off the slot, never off the controller,
                                   which the worker owns)
              [RENDERING_HINT]  OverlayRenderer.show(grounded, instruction_text)
                                    window.set_hint(hwnd, centre-of-bbox)
                                    .last_instruction = instruction_text   <-- run.py dedupes prints on this
              [AWAITING_USER_ACTION]  run.snapshotter()   (this is "after")
                                       loop._is_newer(after, before) — a slot that has not
                                       advanced is NO verification attempt, not a failed one
                                       verification.verify(rule, before, after)
                                           world-state check, not method (D014)
                                       satisfied? -> VERIFYING (a detour is never criticised
                                           after the fact -- interrupting success is Clippy)
                                       (message hoisted above this chain: fires on every
                                           non-target touch while unsatisfied, uncapped, so a
                                           capped tick is never silenced) loop._wrong_action(self)
                                           run.focus_visited_source() -> current_observation
                                           .focus_visited, compared against the grounded
                                           target's automation_id. A non-target in-app id ->
                                           run.on_wrong_action(touched, target) prints one
                                           console line, then -- while under the cap -- back to
                                           OBSERVING (re-grounds; NOT a second renderer.show()
                                           call -- D027) up to 3 times per step
                                           (wrong_action_rehints); past the cap the branch does
                                           NOT transition to OBSERVING itself (the re-hint IS the
                                           OBSERVING transition, so a cap that still transitioned
                                           would cap nothing) -- the message still prints, and the
                                           tick falls through to the elements_changed and
                                           idle-timeout arms below, so the loop keeps re-grounding
                                           on real change and keeps idle-re-hinting instead of
                                           stalling silently at the cap. Silent when the target has
                                           no AutomationId of its own -- true for every OCR-grounded
                                           step, since OCR elements carry none (D037)
                                       else elements_changed(before, after) -> OBSERVING
                                           (unchanged; the churn-not-focus case D037 explains)
                                       else idle timeout -> re-hint ONCE (rehint_count),
                                           unchanged from before this milestone
              [VERIFYING]   step_index += 1; renderer.clear(); back to OBSERVING
          ladder.freshness()                    applied AFTER the DONE/FAILED breaks:
              HIDDEN  -> window.clear_hint(hwnd)      (never passed to set_hint: _paint_ring
                                                       treats everything-not-FRESH as dimmed)
              DIMMED/FRESH -> window.set_hint(..., freshness=)  only while the renderer is
                                                       still showing something
          run.py prints "step N: <instruction>" only when it changed since the last tick
          window.pump_messages_nonblocking()

  finally:
      window.destroy_overlay_window(hwnd)   always runs, even on exception
      service.stop()                        before the store closes
```

### Runtime call graph — persistence (current compiled path)

Promotion survives process exit without making a recipe path authoritative.
After live revalidation and before any overlay exists, the compiled steps are
hydrated from disk. Every eligible UIA promotion is written immediately, so a
later process reuses what the first one learned instead of rediscovering it by
name.

```
run.run_tour_for_workflow(compiled_workflow)
    workflow.revalidate()                       exact catalog/adoption/artifacts/HWND
    compiled_tour.compiled_steps(workflow)       restores the full claimed descriptor
    learning app key                            code.exe for executable identity;
                                                pack id for content identity
    accepted identity value                     exact application/content version
    store.ObservationStore()                     opens/creates %LOCALAPPDATA%\GhostCursor\kb.sqlite
    run.hydrate_steps(recipe.step_key_namespace, runtime_steps, app_key, store)
        identity.step_key(step_key_namespace, step)
        store.observations_for(step_key, app_key)
            -> replaces confirmed observations when learned rows exist
    window.create_overlay_window()               only after both authority gates and hydration

    loop every REFRESH_SECONDS, until ESC/--seconds/DONE/FAILED:
        compiled_tour.execute_compiled_workflow(runtime_steps=hydrated_steps,
                                                on_promoted=persist_callback)
            [DECIDING] selector-bounded observation for the current action selector
                grounding.ground(step, elements=matched, locale=ui_locale,
                                  app_version=accepted_identity_value)
                    rung 1: identity.step_key-scoped select_observations() picks exact
                            version, else nearest LOWER verified, else unknown/global,
                            then cross-checks live control_type before trusting a
                            non-exact match
                    rung 2/3/4: unchanged (control_type+name, UIA-only substring, OCR fuzzy)
                grounding.promote(step, grounded,
                                  app_version=accepted_identity_value, locale=ui_locale)
                    writes/updates the in-memory Step's confirmed observation
                run.persist_step(step_key_namespace, step, app_key, store)
                    identity.step_key(step_key_namespace, step)
                    store.record(step_key, app_key, observation)  upsert, PK (step_key,
                        app_key, app_version, automation_id) -> idempotent, no unbounded growth
                OCR and positional AutomationIds never reach the store

  finally:
      perception.stop()
      controls.dispose()
      window.destroy_overlay_window(hwnd)
      store.close()
```

Verified end to end against the production compiled launcher with a scratch
database: run 1 grounds at rung 2 and persists the observed AutomationId; run
2 hydrates the same stable namespace and grounds at rung 1. The existing
process-boundary erase proof separately deletes `kb.sqlite` and observes an
empty replacement database.

---

## Future milestones (not yet started)
1. Ghost Cursor MVP capstone — tier 3 of the perception ladder (the VLM
   pointing model; UIA and OCR are built), streaming local inference,
   entity-scoped memory, Tauri packaging
See the build doc's checklist for the exhaustive list; this file grows a
section per milestone as they're started.
# Goal-to-tour flow

`--goal` and the control-bar Ask action share the planner contract: classify,
resolve a trusted schema-valid recipe, require an explicit target except for
the canonical Synthetic Export target, then enter the observe/act/verify tour.
An active tour is never replaced by Ask. The bar remains optional at runtime,
while ESC remains polled even when bar creation or focus acquisition fails.

## Submission evidence flow

The novice VS Code check is locked before data collection:

```
recruit 3 novices (2 disclosed fallback; <2 means no value claim)
    -> pre-study confidence (1-5)
    -> baseline Open Folder attempt (120s)
    -> reset VS Code
    -> Ask-guided Open Folder attempt (120s)
    -> post-study confidence (1-5)
    -> publish every row, failure, timeout, wrong turn, and help request
    -> report raw values and limited descriptive summaries only
```

Completion is a world-state measurement: the selected neutral folder must be
active as the VS Code workspace. The guided attempt must additionally reach
`Tour complete.` Recruitment is deliberately deferred until eligible
participant contacts or an authorized communication channel are available;
the prepared invitation is not evidence that it was sent.

## Durability inference transport

`inference.ollama.generate_structured()` is the one bounded request adapter:
no retry, one response envelope, and preserved generation metadata.

```
planner.infer_intent(goal)
    -> dynamic nullable planner schema
    -> ollama.generate_structured()
    -> strict IntentDecision
    -> resolve_model_decision(goal, decision)
    -> D058 deterministic agreement + trusted recipe

screen_hint.decide_next_hint(goal, observation, approved_names)
    -> unique approved UIA candidates only
    -> dynamic AutomationId schema
    -> ollama.generate_structured()
    -> strict HintDecision or deterministic fallback
```

Schema validity never grants recipe or control authority.

## Standing model-durability gate

```
versioned human-semantic dataset (30 cases, family_id grouped)
    -> lane 1: hermetic schema/parser/D058/abstention/candidate checks
    -> lane 2: one bounded local-model request per goal
         -> raw IntentDecision metrics
         -> same resolve_model_decision() used by production
         -> never-fabricate matrix + supported controls
         -> frozen Synthetic Export hint fixture
    -> lane 3 (--interactive): owned Synthetic Export child
         -> real UIA observation
         -> exact identity + structural geometry fixture parity
         -> approved candidates == [EXPORT_ID]
         -> direct hint inference (no tour / no input synthesis)
         -> STATUS_ID remains "Ready to export"
    -> ignored JSON report; reviewed evidence is promoted separately
```

Dataset 1.0.0 is owner-reviewed and frozen. Pre-freeze `--draft` results remain
diagnostic and can never be marked as the trusted incumbent baseline.

Raw timestamped reports remain ignored. Only a reviewed summary with model
digest, dataset review state, hard gates, failures, latency, and no-action
scope is committed under `docs/evidence/`.

## Signed capability composition flow

```
signed .ghostplugin inventory
    -> canonical ghostcursor/capabilities.json (optional)
    -> bundle schema verification
    -> PluginStore prospective active-set transaction
         -> load exact verified plugin catalogs
         -> merge one active catalog epoch
         -> bind each capability to its own active intent
         -> require authorization_goal to exact-match that intent
    -> CompositionContext(catalog, registries)
```

The capability artifact carries only names, bounded scalar parameter schemas,
pre/postcondition facts, and repeatability. It cannot carry selectors,
instructions, actions, verification, target facts, or authority tokens. A
future task proposal is validated in full against the registry before any node
runs; validation success is only a structural result. Execution still reloads
one current composition epoch and crosses `authorize_intent()` plus
`bind_workflow()` for each node as it fires.

```
TaskGraph + trusted initial facts
    -> load one CompositionContext
    -> validate full bounded DAG
    -> freeze ordered nodes + graph/registry/validation digests
    -> for each node, in order:
         -> reload CompositionContext
         -> require the original validation epoch and registry digest
         -> authorize signed capability.authorization_goal
         -> bind the freshly enumerated trusted HWND
         -> run the already-adopted workflow
    -> complete, or stop the remaining suffix at the first refusal/failure
```

Graph rejection has phase `validation`. A refusal after node execution has
begun has phase `execution` and records the failed node plus the completed
prefix. A changed authority epoch is never treated as permission to reinterpret
the remaining graph. The first node captures one target HWND; every later node
binds that same handle, and a later target loss terminates rather than replaying
the completed prefix.

## Complex-goal proposal flow

```
user goal + one operator-selected active plugin
    -> atomic CompositionContext
    -> signed CapabilityRegistry only
    -> bounded model schema:
         summary + node_id + registered capability_id
         + scalar parameters + dependency edges
    -> strict parser (plugin identity injected, never model-supplied)
    -> full validate_task_graph()
    -> flattened read-only plan shown to user
    -> explicit Start confirmation
    -> execute_task_graph() revalidates and reauthorizes every node
```

An absent registry stops before inference. The model never sees selectors or
recipes and cannot return them. A valid proposal remains inert until a separate
explicit execution call.

## PowerPoint showcase authoring flow

```
live PowerPoint 16.0.20326.20112 + one operator-selected HWND
    -> measure exact pre-action UIA cardinality
    -> user performs the action manually
    -> measure exact post-action state on the same HWND
    -> hand-author data-only candidate
    -> quarantine with active_adoption_id: null
    -> schema/compiler tests + digest binding
    -> independent review -> isolated 3/3 acceptance -> activation
```

The first candidate is deliberately narrow: a one-slide presentation exposes
exactly one `Button/New Slide`; after one manual click the same HWND exposes
`Text/View Indicator Slide 2 of 2`, while another PowerPoint HWND remains at
1/1. The trusted precondition forbids treating this as a general N→N+1 action.

The second candidate is a four-step measured chain on a two-slide
presentation: `Insert` -> `Chart...` -> `Bar` -> `OK`. Intermediate
postconditions are the unique Bar category and `Text/Clustered Bar`; completion
is `TabItem/Chart Design` on the original PowerPoint HWND. `Pie` is explicitly
rejected because selecting it creates three same-name `ListItem/Pie` elements.
The Excel chart-data window is observed but never targeted or authorized.

The third candidate opens a collaboration surface: `Insert` -> `Comment`,
verified by the unique `Edit/Start a conversation`. Dynamic GUID-bearing editor
AutomationIds are evidence only and never enter the recipe. If the editor is
already open, `accept_if_already_present` completes without creating another
draft.

The fourth candidate changes presentation view through the unique status-bar
`Button/Slide Sorter` and completes on the unique semantic
`Pane/Slide Sorter`. A modal-covered first attempt is excluded. The two
same-name `ListItem/Slide` thumbnails are recorded only as evidence and never
become selectors.

The fifth candidate returns from that measured Slide Sorter state through the
unique `Button/Normal` and completes on the unique semantic `Pane/Slide`.
The vanished sorter pane is supporting evidence, not a negative completion
rule.

Dataset 1.0.0 is now owner-reviewed and frozen at D066. The next gate command
must omit `--draft`. D067 closed the gate with two consecutive post-freeze
passes; future inference changes rerun this same command against the frozen
incumbent before they can be trusted.

```powershell
# Optional diagnostics against an intentionally unreviewed future draft.
py -3.12 -m ghostcursor.evaluation.model_gate `
  --model qwen3:4b-instruct `
  --endpoint http://127.0.0.1:11434 `
  --unavailable-endpoint http://127.0.0.1:1 `
  --interactive --draft

# Standing gate for owner-reviewed dataset 1.0.0 (no --draft).
py -3.12 -m ghostcursor.evaluation.model_gate `
  --model qwen3:4b-instruct `
  --endpoint http://127.0.0.1:11434 `
  --unavailable-endpoint http://127.0.0.1:1 `
  --interactive
```

## Signed autonomous Act flow

Act is a separate execution architecture; it is not Teach with hidden clicks.

```
natural-language goal
    -> active compiled matcher
    -> canonical authorize_intent()
    -> exactly one signed action-plan template for that intent
    -> substitute only declared bounded parameters
    -> validate the complete single-plugin DAG
         operation registry + parameter types + limits
         dependencies + acyclicity + pre/postcondition facts
         repeated non-idempotent effects refused
    -> resolve one exact HWND/PID/executable/version
         (the adapter re-establishes this by PROCESS identity, not
          `Application.HWND`, which build 16.0.20326 does not expose)
    -> display the complete deterministic flattened plan
    -> explicit one-shot approval
         validation + manifest + adapter + active catalog epoch
         + exact target + output path + expiry + unattended scope
    -> recheck catalog authority and target
    -> start the nonce-bound adapter required by each signed backend
         object-model nodes -> application adapter + whole-plan preflight
         UIA nodes -> canonical generic UIA adapter
    -> for each ordered node:
         pause/stop gate
         reload the original authority epoch
         revalidate the exact target
         for UIA: observe pre-state, show/receipt the cue, confirm unchanged
         for UIA: accept geometry only when the signed adapter's bracketed
         DPI/process/thread/topology contract matches the overlay thread and HWND
         mint one node-bound authorization digest including observation digests
         for UIA: re-resolve exactly one control, compare the confirmed
         required identity, rectangle, and coordinate contract, consume the
         authorization once, then invoke that same element
         execute only the registered operation
         launch one separately signed read-only verifier
         continue only when the backend-appropriate verifier proves the effect
              object model -> saved artifact
              UIA -> live state changed against the immutable pre-cue baseline
    -> final verified artifact or an explicit terminal refusal
```

Plugin API v2 binds the adapter, verifier, operation registry, action-plan
index, and every template inside the signed manifest inventory. The core never
imports application-specific adapter code. Unsigned executable adapters are
rejected even in developer mode. An adapter process is per Act session, and a
verifier process is one-shot per effect; nonce, node, validation, and digest
checks reject cross-session replies and replay.

The first deep Act candidate is PowerPoint. Its signed plan creates a 10-slide
16:9 investor deck through the PowerPoint COM object model, saves after every
effect, and verifies the resulting PPTX package independently. Charts are
bounded PowerPoint shapes rather than embedded Excel editing sessions, keeping
the graph single-plugin. Its catalog includes all four animation categories
and both Fade/Morph transitions, but the investor deck uses restrained motion.
The candidate remains quarantined until external release signing and live
acceptance bind the exact reviewed bytes.

The first live campaign established what a real desktop costs. `Application.HWND`
and every sibling window handle raise `DISP_E_MEMBERNOTFOUND` on Office build
16.0.20326 under both binding modes, so the adapter proves it holds the approved
target by process identity instead: resolve the approved window's owning PID,
require PowerPoint to be that single process, and check before `EnsureDispatch`
so a dispatch cannot launch the process being verified. That is narrower than
window identity and is recorded as such rather than presented as equivalent.
Three animation constants and `msoTrue` likewise do not exist at runtime; the
operation catalog now names the constants the application actually exposes.

## Act v1 completion tooling and runtime integration

`execute_approved_graph` accepts one optional `verify_observer`. It is an
OBSERVER, not a wrapper: core constructs the `VerifierHost`, calls the signed
verifier itself, and keeps the answer, while the observer is told
`("verify_started" | "verify_finished", facts)` and has its return value
discarded. An earlier design handed the verifier callable to a diagnostic
wrapper and asked it to return the same answer; nothing enforced that, so
`lambda verify: lambda *_a: True` would have passed every node without the
signed verifier running. That capability is gone rather than discouraged, and
`tests/test_act_runtime.py` forbids the old parameter by name.

The observer's ordinary exceptions are caught so instrumentation cannot fail a
run. `BaseException` is deliberately not caught -- swallowing `KeyboardInterrupt`
would be worse than the failure it prevents -- so an observer raising one does
propagate, with `host.stop()` still running.

### Counted campaigns (D150, D152)

A counted campaign is declared first: one line in
`docs/campaigns/ledger.jsonl`, committed. Then either path runs:

- harness: `devtools/act_campaign.py --campaign-id <id>` preflights
  (`campaign_pins`: bundle manifest equals the pin, clean tree, ledger entry
  at HEAD), spawns `act_acceptance` once per attempt with one exported scope
  and salt, stops at the first unclean attempt, and writes
  `docs/evidence/campaigns/<id>/report.json` with every attempt that ran and
  its full record stream. A record carrying a handle-named key, or text
  shaped like a handle (a named handle/pid/window/target number, any `0x`
  hex value, or a standalone decimal of six or more digits), is withheld and
  the campaign refused; its attempt stays counted. Every exit after the
  ledger check writes the report (a `started` report first, overwritten
  only by the final one), and published decks are copied to the git-ignored
  `.artifacts/campaigns/<id>/` with their digests in the report;
- manager: `devtools/act_manager_campaign.py --campaign-id <id> --attempt N`,
  once per attempt, preflights the installed manifest, ledger, clean tree,
  consecutive numbering and every earlier attempt completed, then opens the
  real manager with the observation-only audit path. The audit record (schema
  2) carries the application build.

`tools/render_act_campaign.py --check` is the only producer of the campaign
document. For a clean campaign it refuses anything but 3 consecutive completed
attempts on the pin, one build, distinct outputs, the signed plan's digest and
node count, and the D123 order (manager); `--artifacts <dir>` also
digest-checks the kept decks. For a refused or unfinished campaign it renders
a "NOT counted" document from the retained record.
`tests/test_campaign_ledger.py` requires every ledger entry to be retained and
the ledger to be append-only.

`ghostcursor/devtools/act_acceptance.py --diagnostics <path>` wires
`ActBoundaryProbe` into both the event sink and that observer, writing JSONL:
package state before each node, after the adapter's mandatory save, and after
the verifier returned, plus which package parts each transition changed.
`act_diagnosis.py` classifies those records into `never_written`,
`wrong_part`, `bytes_moved_during_read`, `unreadable`,
`package_changed_during_verification`, and `written_and_verified_false` -- the
competing explanations for a node whose postcondition was not observed.
`package_changed_during_verification` outranks the rest because a package that
moved during verification invalidates the digests rather than explaining the
failure. It deliberately names no culprit: the probe watches the file, not the
verifier, and an external writer is indistinguishable from where it stands.

`ghostcursor/devtools/uia_feasibility.py` probes a control read-only: pattern
availability per reviewed pattern, RuntimeId, AutomationId,
NativeWindowHandle, bounding rectangle, and the LegacyIAccessible default
action's *name*. Without `--name` it lists candidates instead of resolving
one. That mode found the name of Excel's sheet-insert control on this build --
`Add Sheet`, measured, where the plan had guessed "New Sheet"
(`docs/evidence/act-phase-b-uia-feasibility.md`). `probe_stability` re-resolves
across the 650 ms cue dwell the real presentation will impose, one complete
observe-dwell-re-resolve pair per cycle. Discovery and the action path share
one provider-side `FindAll` (`provider_type_query_for`); an earlier discovery
walk disagreed with the action path about what a window contains.

`ghostcursor/stages.py` validates signed stages and ordered cues against a
plan's own flattened node order and returns the deterministic cue groups. It
is not yet reachable from `action_plans.py`: wiring it changes plan bytes and
therefore every plan digest.

`ghostcursor/act_protocol.py` fixes the vocabulary the session surfaces and
the verifier speak: three verifier modes, four receipt kinds, the closed
refusal-code set, lifecycle states and trust classes. `PresentationWait`
tracks one cue against a `ReceiptPolicy` on an injected clock, and
`may_execute` stays false until a start receipt and a completion receipt have
both arrived inside their deadlines -- no effect runs from a cue the user was
never shown. Receipts carry session, cue, nonce and presentation/frame
generation, so a receipt from a previous attempt at the same cue cannot
satisfy a later wait. `trust_for()` derives the trust class from the backend
that acted and whether verification returned; it is never passed in, and every
unproven state is NEUTRAL. `ReceiptPolicy` has no default deadlines because
Phase E derives them.

`ghostcursor/coordinate_space.py` is the contract a rectangle must satisfy
before the overlay will draw it. Act's verifier runs out of process, so two
processes have to agree what a pixel coordinate means; every value is queried
from the live process rather than read off `dpi.AWARENESS`, which records
which setter path ran rather than what the process became. Awareness equality
is load-bearing and virtual bounds plus monitor topology corroborate it --
at 100% on one monitor an unaware and a per-monitor-v2 process report
identical numbers. Unknown awareness and partial records are refused, never
defaulted, and units are derived from the measured awareness rather than
asserted. UIA itself always returns `BoundingRectangle` in physical screen
pixels, so production requests per-monitor-v2 before creating UIA/overlay
objects and the adapter, host, and overlay independently refuse any UIA
geometry that does not measure `physical_pixels` (D106 as amended by D116). A rectangle read is
bracketed by two awareness samples: `observe_bracketed` captures the space,
reads, and captures again, and `BracketedGeometry` refuses every rectangle if
the space moved between them, because rectangles read across a context change
may not share a space with each other.

`act_protocol.py`, `uia_identity.py`, and `coordinate_space.py` now have
production callers through
`act_node`, `act_uia_session`, and `act_runtime`. The public executor preserves
the immutable pre-cue semantic observation through dispatch and gives that
exact baseline to the separately signed live verifier. It routes UIA requests
to `uia_entrypoint`, never to the plugin's object-model entrypoint, and skips
object-model preflight for a UIA-only graph. The signed generic UIA adapter
brackets every rectangle read with queried coordinate-space samples; the host
strictly parses that record and requires it to carry the same rectangle. The
overlay independently brackets its UI-thread read and checks process/thread
awareness, units, virtual bounds, monitor topology, and overlay-HWND awareness
before and after every paint request. Baseline and confirm-before geometry must
also agree after the cue dwell. The final adapter-side read must still match the confirmed
contract before Invoke/Select/Toggle/Value is called. A missing, malformed, or
drifted contract refuses the visual/effect rather than drawing at bare numbers.
Geometry stays ephemeral presentation data: it is absent from authorization
digests, session snapshots, learned identity, and default diagnostics (D115).
`stages.py` remains schema-detached because wiring it changes plan bytes.

`ghostcursor/uia_identity.py` holds the signed per-operation identity policy a
UIA action must satisfy immediately before its pattern call: required fields
refuse on any difference, evidence fields are recorded only, and positional
AutomationIds are refused in either role (D069). The two modes come from
measurement -- `runtime_id_required` where a RuntimeId was measured stable
across the cue dwell, `semantic_exactly_one` where it was not (D107, and
`docs/evidence/act-phase-b-uia-feasibility.md` for Excel's `Add Sheet`).

The generic UIA adapter is `plugins/shared/uia_adapter.py`, copied
byte-identically into each declaring payload. Immediately before an effect it
resolves exactly one signed selector match, compares every core-supplied
required identity field and the displayed rectangle, rechecks window/process
authority, consumes the node authorization once, and invokes that same element.
The digest is an audit binding delivered over the nonce-bound private session
pipe; it is not described as an independently signed token. Parameterless UIA
plans materialize and approve with `output_path=None`; the CLI therefore needs
only `--target-hwnd` for a live-only plan and reports no fictional artifact.
Artifact plans still require `--output` and retain same-volume staging. Quick
and Watch pacing now reach the public CLI.

Executable Python payloads are not launched by path. `AdapterHost` and
`VerifierHost` start an absolute trusted `ghostcursor/verified_python.py` under
Python `-I -S` startup isolation. The bootstrap refuses weaker flags before it
reads the payload, then hashes the target bytes against the signed
descriptor before compiling and executing those same in-memory bytes. It adds
the trusted GhostCursor package and explicit interpreter dependency directories
only after the hash; the plugin payload directory and `PYTHONPATH` never become
import paths, and neither system-site nor user-site `.pth` files execute before
the hash.
Executable plugin entrypoints are
therefore single-file payloads in v1 and may not import mutable plugin siblings.
They require the injected verified digest; a direct launch refuses.
`PluginStore` derives descriptor digests and parses registries/plans from the
signed `VerifiedBundle.files`, so a mutable reread cannot redefine the
authority the bootstrap checks (D117).

In the native manager, `UiThreadPresentationBridge` hands a worker's cue request
to the manager UI thread. That thread alone owns and pumps the overlay window;
the worker blocks on render receipts delivered through the bridge's original
receipt sink. The production executor accepts only a sealed presentation value
whose `OverlaySession` was registered by `overlay_presenter`, directly or
inside `UiThreadPresentationBridge`. Exact type alone is insufficient and an
unregistered exact instance is refused; an arbitrary callback container cannot
manufacture acknowledgements and make an effect eligible. This registry is an
in-process core boundary, not a sandbox against malicious code already running
inside the trusted GhostCursor process. Lifecycle updates return through the
same bridge. Pause/Stop is
checked before confirmation, before authorization, and once more after token
minting immediately before dispatch. A late check refuses instead of resuming
with stale confirmation. This is a checkpoint guarantee, not cancellation of
an adapter call already in flight. The design preserves the one-process
manager/rail architecture while respecting Win32 thread affinity (D118).

## Verification routing — which verifier answers which question

`choose_verifier()` routes by the operation's signed `backend`, and the two
verifiers answer genuinely different questions. This was described in
`CLAUDE.md`, implemented, and tested, but appeared nowhere in the architecture
of record until an activation review pointed at the gap (D137).

```text
execute_approved_graph() -> per node:
    choose_verifier(operation.backend)
        |
        +-- object_model  -> artifact verifier (signed, read-only)
        |       reads the saved file; sent NO baseline and NO postconditions,
        |       because it validates its request fields exactly
        |
        +-- uia_pattern / other control-driving backend
                -> live verifier (separately signed, read-only)
                   reads LIVE state; sent the frozen `observe_before` baseline
                   and postconditions naming a CHANGE
                -> if the bundle ships no live verifier: REFUSED
```

The refusal is the load-bearing part. A UIA effect reaches no file until
someone saves, so asking the artifact verifier about it returns "unverifiable"
— which reads as a broken effect when it is a misrouted question. A silent
fallback to the artifact verifier is therefore forbidden, and bundle
verification refuses either half of the `uia_entrypoint` / `live_verifier`
pairing alone, exactly as it does for the adapter pairing.

A postcondition naming a STATE rather than a CHANGE (`slide.exists`) is
satisfied by a node that did nothing, which is why the baseline is frozen at
the observation boundary, its digest bound into the per-node authorization, and
never reconstructed after dispatch. Core passes the baseline through and never
interprets it; the comparison stays in signed plugin code.

## You are here — 30 September 2026

| Area | State |
|---|---|
| Object-model Act, PowerPoint deck build | implemented; the 11 Sep 3/3 campaign is diagnostic under D139 and no current counted evidence exists |
| Manager `Approve & run` layer | implemented, hermetically tested, mutations killed — **one diagnostic live run, no counted campaign** |
| UIA slice `add-slide-uia-v1` | implemented, one diagnostic run, **unadopted** |
| Animation catalog | signed plan `animation-catalog-v1` (D151), never run; verification scope limited (D152) |
| Counted-campaign tooling | ledger, pinned-manifest preflight, retained reports, checked renderer (D150, D152) |
| Activation | **NOT READY** (D139); fresh independent review and counted campaigns remain |
| Semantic planning, agent/marketplace program | not started, gated on activation |

The marker is what this file's preamble promises and had stopped carrying.
Update it when the call graph moves, not at milestone boundaries.

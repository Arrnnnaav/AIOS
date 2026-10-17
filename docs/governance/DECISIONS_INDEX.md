# Decision index

**Navigation only.** The rules in force are stated in full in `CLAUDE.md`; this
file maps them to the decisions that explain them, and lists every decision
heading so one entry can be found without reading `DECISIONS.md` (about 7,300
lines). Read a decision only when a task touches it. Regenerate the heading list
with the script named at the bottom; edit the curated table by hand.

## Rules in force, by subsystem

| Subsystem | Rule (stated in full in CLAUDE.md) | Why (decisions) |
|---|---|---|
| Process | Rigor proportional to risk: three tiers; only BLOCKING safety findings gate | D162 (amends D032, D139) |
| Direction | App-agnostic, model-driven harness; PowerPoint is a test fixture; hand-written packs retired | D164, D161, D159 |
| Safety / input | Orbyn never types, clicks or moves the cursor outside the signed Act path; scan enforced | D006, D109 |
| Act authority | Signed plans only: PluginStore -> authorize_intent -> approval -> per-node authorization -> signed adapter -> independent verifier | D100-D104, D117-D124 |
| Pointer truth | A shown pointer is at a real, observed control; never a model-supplied position | D109, D112 |
| Kill switch | ESC and `--seconds` always stop; Stop/Pause within 0.5 s | D020, D118 |
| Overlay | Click-through, topmost, `WM_PAINT`-only drawing; import `overlay.dpi` first | D009, D010 |
| Perception | Worker thread owns COM/UIA; frozen primitives cross threads; one overwritten slot | D021, D022 |
| Privacy | No HWND/PID/keys/paths/screenshots leave the device; no raw handles in tracked files | D017, D122, D128, D147 |
| Providers | Model output is advice; closed schemas; tainted screen text never in instructions | D058, D147, D164 |
| Evidence | Never edit captured output; every number names its record | D034, D139 |
| Testing | Desktop lanes one at a time; hung-window files alone | D025 |
| Signing | Payload bytes are LF and pinned; rebuild/re-sign and move both pins together; current PowerPoint manifest `b0d63512` | D125, D127, D149 |
| Campaigns | Declare in the committed ledger; nothing committed until the last attempt; retain every outcome | D150-D158, D163, D165 |
| Spatial / SayStride | Separate projects; integrate by typed reference / transcript sidecar; port code with attribution | D143, D146, D161 |

## Where current status lives

- Phase order and status: `ROADMAP.md` (read only the section for your task).
- Call paths: `FLOW.md` (read only the section for your task).
- Open work: `docs/superpowers/FOLLOWUPS.md` (search, don't read whole).
- Measurements: `docs/evidence/`.

## Every decision, one line each

- D001 — Project identity: Ghost Cursor (Phase 1 of AIOS)
- D002 — Platform: Windows-first, not cross-platform
- D003 — MVP scope: local overlay + bridge, no AI yet
- D004 — Language/stack for the core agent: Python
- D005 — Perception: tiered, cheapest-first (UIA → OCR → VLM)
- D006 — Overlay never touches the real OS cursor
- D007 — Docs from `D:\tracker\docs` are the primary reference corpus
- D008 — Tracking docs: DECISIONS.md + FLOW.md, updated as we build
- D009 — All drawing happens inside WM_PAINT; callers never touch a DC
- D010 — One coordinate space, declared before anything can flip it
- D011 — The overlay must always be killable without focus
- D012 — Verify with measurement, not by asking a human to look
- D013 — The grounding ladder is a promotion mechanism, not just a fallback chain
- D014 — Verification checks world state, never the method used to get there
- D015 — Observation selection: exact, else nearest lower, else unknown — never newer
- D016 — Step identity: a durable key over the claimed descriptor, not position
- D017 — The persisted store: local, erasable, keyed for idempotent promotion
- D018 — A green suite is not evidence; mutation-test the properties that matter
- D019 — Which perception snapshots share an instant, and which must not
- D020 — A standing ceiling on tick latency, because the escapability rule has no other enforcement
- D021 — Perception runs on a worker thread, not the UI thread
- D022 — A single timestamped slot, not a queue and not futures
- D023 — The staleness ladder, and why untimestamped means fresh
- D024 — Worker lifecycle: two signals decide, the heartbeat only explains
- D025 — A hung test window is a desktop-wide side effect
- D026 — Stateful and time-based interactions get a sequence test
- D027 — One write per tick: a two-step render is a laundering bug
- D028 — Tier 2 triggers on grounding failure, never on an empty walk
- D029 — `Windows.Media.Ocr`, and the floor of 95
- D030 — OCR results are never promoted, and rung 3 excludes them
- D031 — An invariant must imply the property, not merely correlate with it
- D032 — No task is reviewed by the agent that produced it
- D033 — What the tier-2 milestone's rulings cost, and where they live
- D034 — A measured number in documentation must name where it is recorded
- D035 — A warm-up grace period before tier 2 may be requested, keyed by window handle
- D036 — Fix the class, not the instance: sweep for siblings before closing a finding
- D037 — Wrong-action feedback fires on focus, never on element churn, and only the tick loop decides
- D038 — The brief is the least-reviewed artefact, so reviewers must verify it rather than defer to it
- D039 — Perception health distinguishes slow work from a stalled worker
- D040 — Application packs are strict local trust boundaries
- D041 — VS Code open-folder verification is user-driven and title-based
- D042 — Foreground validation starts as a logging-only daemon
- D043 — Implementation is complete; real VS Code validation remains a desktop gate
- D044 — `VS Code` is a first-class deterministic planner alias
- D045 — The first VS Code workflow uses a targeted UIA query
- D046 — Executable recipes bind target windows by executable and title
- D047 — The Welcome-page Open Folder action supersedes the File-menu target
- D048 — Real VS Code acceptance run 1 of 3 passed
- D049 — Ask expands into a visible middle-right input panel
- D050 — The control surface is a vertical right rail with a left-expanding Ask card
- D051 — Real VS Code acceptance run 2 of 3 passed
- D052 — Real VS Code open-folder acceptance gate passed 3 of 3
- D053 — The expanded Ask prompt passed real-desktop visual validation
- D054 — Ask submission passed the real-desktop trusted-tour handoff gate
- D055 — Open Track release work is isolated and governed by a hard freeze
- D056 — HWND discovery is worker-only and test lanes are environment-isolated
- D057 — Open Terminal is the second validated VS Code workflow
- D058 — A registered model intent is not executable without deterministic grounding
- D059 — Participant value evidence is an informal, fully disclosed novice check
- D060 — The demo protects live evidence inside a 4:45 budget
- D061 — Model-call hardening is preserved but excluded from the submission release
- D062 — One bounded Ollama adapter owns request transport and metadata
- D063 — Nullable advice and execution authority are separate contracts
- D064 — Model changes require one versioned, read-only, three-lane gate
- D065 — Raw gate reports stay local; reviewed summaries carry claims
- D066 — Dataset 1.0.0 is owner-reviewed and frozen before baseline
- D067 — Qwen 3 4B is the accepted frozen incumbent at 26/30
- D068 — The local model cannot change which recipe executes
- D069 — Workflow #3 is feasible without new verification kinds or strategies
- D070 — Runtime observations and curated knowledge have separate stores, lifecycles, and authority
- D071 — Each tracking document has one job, and CLAUDE.md states rules, not findings
- D072 — The deterministic matcher is frozen as declarative data
- D073 — Acceptance binds the pack-declared application identity, not necessarily the host executable version
- D074 — The compiled walk's shape is chosen by traversal count, and the title stays on the worker
- D075 — One matching window or none, and every run says when things happened
- D076 — The verification baseline and the latest observation are two things
- D077 — Schema-v2 is the sole production workflow authority
- D078 — The compiler milestone closes on one authority path and a fixed data-only proof range
- D079 — Compiled execution preserves the existing learned-observation identity
- D080 — Full descendant observation is an explicit, window-bounded recipe strategy
- D081 — Signed plugins are lifecycle epochs, not executable extension code
- D082 — Excel closes the signed, data-only second-application proof
- D083 — Product-shell and task-graph work proceeds on an isolated post-freeze branch
- D084 — Plugin-store atomicity includes cross-process serialization
- D085 — The executor publishes one presentation-neutral session truth
- D086 — Missing and ambiguous targets are different structured recovery states
- D087 — Complex tasks are bounded single-plugin DAGs over existing intents
- D088 — The pilot shell is two native windows in one process with one session truth
- D089 — Capability registries are signed and activated with their catalog epoch
- D090 — A task graph reauthorizes every node without changing validation epoch
- D091 — Complex-goal decomposition returns inert capability graph data
- D092 — Deep PowerPoint coverage starts from measured, state-bounded candidates
- D093 — A PowerPoint chart workflow may observe, but never authorize, Excel data UI
- D094 — Dynamic Office comment IDs are observed but never trusted
- D095 — PowerPoint view changes bind the semantic pane, not slide thumbnails
- D096 — Returning to PowerPoint Normal view requires the prior view
- D097 — Task parameters are presentation data, never workflow authority
- D098 — Complex plans require review, confirmation, and one graph HWND
- D099 — Interaction modes describe collaboration, never authority
- D100 — Executable plugins are signed, closed, and out of process
- D101 — Act validates and approves one complete action DAG
- D102 — Every Act effect is freshly authorized and independently verified
- D103 — PowerPoint Act uses its object model without importing Excel authority
- D104 — Act ships as review-then-approve; Ideate and Assist remain inert
- D105 — Act v1 completion runs A-before-C, and its Phase A/B tools measure without acting
- D106 — Coordinate units are measured from awareness, not asserted
- D107 — Phase C freezes contracts a caller has exercised, not contracts alone
- D108 — One generic UIA adapter source, carried and signed by each plugin
- D109 — A pointer that is shown is a pointer that is acted on
- D110 — Interruption resumes with an edited plan, never with a replayed one
- D111 — The PowerPoint plugin gains semantic capabilities, not more raw operations
- D112 — A pointer may outlive its node, if it is recoloured to what the node earned
- D113 — Planning context is a stored conversation, not a file called idea.txt
- D114 — A UIA node keeps one baseline and ends on the confirmed control
- D115 — UIA rectangles cross processes only with a measured coordinate contract
- D116 — UIA geometry requires a physical-pixel process and paint-time stability
- D117 — Signed Python executes only from the bytes core verified
- D118 — The manager UI thread owns Act presentation
- D119 — Codex work starts from a small repository-backed context
- D120 — Teach recipes and Act plans share one gate, not one token
- D121 — Manager Act execution consumes one explicit approval event
- D122 — Retained manager evidence is fixed-schema and observation-only
- D123 — Manager approval hands focus only to the approved Act target
- D124 — One manager HWND owns compact and expanded layouts
- D125 — Signed payload bytes are LF, and the r5 evidence is invalidated
- D126 — The replacement live run, and what it retained
- D127 — A signed bundle carries sources, and evidence carries no raw handles
- D128 — Target bindings are pseudonyms, and evidence publishes no handles
- D129 — A target reference must survive a process boundary
- D130 — Scope narrows to PowerPoint, and the scan learns to read JSON
- D131 — Match the shape, not the spelling
- D132 — Apply the reasoning, not the patch
- D133 — Close the class, and say what the evidence does not say
- D134 — READY, and the scan stops enumerating
- D135 — The counted campaign, on a bundle a clean checkout can rebuild
- D136 — A closed boundary is not a closed phase
- D137 — The activation review, and the claim it caught
- D138 — The second activation review, and a falsified record
- D139 — Three falsifications, and the rule that follows
- D140 — Close PowerPoint Limited Act before building the agent platform
- D141 — A consented network tier, additive to D017
- D142 — Agents and Skills are signed, plugin-scoped data
- D143 — A spatial reference is brief content, never authority
- D144 — Signing identity: rotation and revocation before any re-key
- D145 — Confirmation timing is signed policy, measured and enforced
- D146 — Orbyn plan set and independent Spatial-first sequence
- D147 — D141-R2: cloud-first reasoning during the trial period
- D148 — Self-maintaining software is a commercial wedge, not a subsection
- D149 — PowerPoint rebuilt at manifest `3a4f8c57` for the D145 timing fields
- D150 — Pre-campaign review of `b1ba80a`: NOT READY, and what it corrected
- D151 — The animation-catalog plan, and PowerPoint manifest `6dbd5ba2`
- D152 — Second pre-campaign review (`75670dc`): NOT READY, and its repairs
- D154 — Third pre-campaign review (`bc31fe5`): NOT READY, and its repairs
- D155 — Fourth pre-campaign review (`764286f`): NOT READY, and its repairs
- D156 — Fifth pre-campaign review (`9e998bf`), interrupted, and its residuals
- D157 — Fifth review resumed: READY for the investor-deck harness campaign
- D158 — The counted investor-deck harness campaign, and the independent lanes
- D159 — Model-first Teach: a model chooses among observed controls
- D160 — The investor-deck harness campaign is accepted; the lanes are not
- D161 — Owner: hand-written packs are retired as the way forward
- D162 — Proportionate rigor
- D163 — First manager-path campaign refused at attempt 2 (commit moved)
- D164 — Harness first: PowerPoint is a test fixture, not the product
- D165 — Second manager-path campaign refused (runner stopped; two runs in one attempt)
- D166 — Harness step 2: multi-window binding and the observation frame
- D167 — Model-driven Teach across bound windows, behind `--model-teach` (harness step 3)
- D168 — Model-Teach fixes: document names stay local, frame-host windows, completion reasons
- D169 — Steps 1-3 milestone review: one BLOCKING finding, fixed
- D170 — Harness step 4 tooling: corpus capture and offline replay
- D171 — Owner: Spatial point reference and SayStride voice goal in model-Teach
- D172 — D171 follow-ups closed
- D173 — The solo MVP workspace, console first
- D174 — MVP workspace review: three BLOCKING findings, fixed
- D175 — MVP workspace: inspect, correct, revise, record, replay
- D176 — Act: a minimized target is restored; a failed run names its reason
- D177 — Sign in with ChatGPT: the user's own plan powers System Two
- D178 — The workspace app: a docked window over the same Workspace
- D179 — Jev across the product, and redacted pictures for Teach
- D180 — Organisation policy and scrubbed screen text: less leaves the machine
- D181 — Ideate, Jev in the workspace, and handoff as the Multiplayer seed
- D182 — Act on any application through the harness; bring-your-own account

_Generated from `DECISIONS.md` headings by `py -3.12 tools/render_decisions_index.py`._

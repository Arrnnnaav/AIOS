# Competitive and reference scan, 17 October 2026

Method: REA (reverse-engineer-anything, npx rea-agents 6.5.0) on apps staged in
`D:\rea-study`, plus direct source reading of open-source peers, the GitHub
search API (authenticated), and the community `yc-oss` dataset (6,307 YC
companies). Findings only; no third-party code was copied into Orbyn.

## Apps analysed

| Product | Form | Method | License |
|---|---|---|---|
| Cluely (Windows 2.0.198) | Electron installer | REA JS app graph (source maps recovered) | proprietary |
| HeyClicky (macOS 1.0.53) | DMG bundle | resources + skills + bundled Codex read | proprietary |
| Amoeba IDE (1.130 beta) | Electron, VS Code fork | REA on the `@coord` multiplayer daemon | proprietary (MS) |
| Clicky, HeyFlitty, Dodaios, OpenJarvis, AALEX | source | direct read | MIT / Apache-2.0 |

## What each does that Orbyn could learn from

**HeyClicky** — closest to Orbyn's Act.
- `drive_until(goal, window, deny[], values{}, success_contains, max_steps)`:
  an in-app loop that snapshots the accessibility tree, asks Jev which element
  is next (~0.5 s, typed), validates against offered elements, acts by
  `element_token` in the background, re-snapshots. Typed statuses: done /
  handed_back / needs_text / blocked / blocked_by_consent / max_steps.
- Bundles the Codex CLI + model catalog; runs on the person's ChatGPT plan.
- Acts on accessibility elements (no focus steal, no cursor warp); pixel clicks
  are the last rung for canvas apps.
- Per-turn consent card; deletes/sends/spend always confirmed; email drafts only.
- ~40 markdown skills (vendored from NousResearch Hermes) + Composio connectors.
- Each helper keeps a dated notes file; newest fact wins (like Orbyn's Brain).

**Cluely** — overlay and capture.
- `setContentProtection` (Windows `WDA_EXCLUDEFROMCAPTURE`): invisible to
  screen share. Overlays transparent, topmost, frameless, off the taskbar.
- Whole-display screenshot per question, scaled to <=1920 px PNG; mic + system
  loopback audio in meetings. No bring-your-own-key: its own backend only.

**Amoeba IDE** — the multiplayer reference (YC Multiplayer AI).
- `@coord` daemon coordinates many coding agents (Claude Code, Codex,
  Antigravity, opencode) through a backend "Brain".
- Takeover: a teammate claims a session; their machine materialises the latest
  snapshot in an isolated `git worktree` and re-arms the runtime.
- Live sync: continuous snapshot to a hidden git ref; three-way apply that only
  auto-applies when the local blob equals the last common snapshot, else a
  surfaced "2 versions" conflict. Never overwrites local edits.
- Approval gate across machines, with a timeout that always falls back to the
  owner's own prompt (never locks the owner out).
- Per-prompt context budget (700 tokens).

**Dodaios (ex Personal Jarvis)** — subscriptions + wake word.
- Runs the person's installed, signed-in CLIs as backends (`claude -p
  --output-format stream-json`, Codex, Gemini, Antigravity).
- openWakeWord (~15 MB, offline) + sherpa-onnx for local speech; any phrase.
- Computer control from screenshots tagged with a frame id; refuses input when
  a lock screen or admin prompt is up, or into an elevated window; shows a
  control border and arms Escape.

## Big-tech / AI-lab open repos worth tracking

- trycua/cua (30k★) — the open computer-use driver engine behind HeyClicky.
- microsoft/OmniParser, simular-ai/Agent-S, microsoft/fara, alibaba/page-agent
  — vision/GUI agents.
- openai/openai-realtime-agents, google-gemini/gemini-live-api-examples,
  microsoft/VibeVoice — realtime voice.
- Picovoice/porcupine, openWakeWord, OHF-Voice/micro-wake-word, RealtimeSTT
  — wake word / STT.
- liveblocks, rivet, tldraw, yc-software/qm, preset-io/agor — multiplayer infra.
- anthropics/skills, google-gemini/gemini-skills, google-deepmind/science-skills
  — the Skills pattern (now built in Orbyn).

## YC companies in Orbyn's space (yc-oss dataset)

Direct desktop-assistant competitors: **Korso** ("operate apps, research, guide
you when stuck, all by voice" — the closest), **HeyClicky**, **River** (the AI
desktop), **OpenWork**, **Minicor** (self-healing Windows automation as an
API/MCP), **Korso**. Adjacent: **GrayPass** (verify who is behind a sensitive
action before it goes through). Multiplayer: **Mosaic**, **Dock**, **Party**,
**HumanLayer**, **Gumloop**. Company brain: **Savant**, **Hyper** (self-
maintaining knowledge graph), **Hyperspell**, **Mem0**, **Glen**.

## Built from this scan (commits, 17 Oct 2026)

- `50029bb` overlay hidden from capture; refuse input to locked/elevated
  targets; acting banner.
- `cb9c10e` per-request token budgets (Amoeba's cap).
- `e3a01ea` Act deny list (HeyClicky's drive_until deny).
- `51bd717` per-app skill guides for the planner (Skills pattern).
- (earlier D182) Act on any app; BYOK Anthropic/OpenAI/Gemini + Accounts panel;
  "Hey Bro" wake word + hotkey.

## Deferred, with the blocker

- **Jev drive_until as a first-class single-window loop.** Orbyn's
  ModelTeachSession already does snapshot -> Jev-choose -> act per tick; a
  goal-only (no pre-made plan) single-window loop with typed statuses is a
  larger feature. Build when the harness is measured.
- **Faster offline wake word** (sherpa-onnx / openWakeWord) to replace the
  Whisper loudness loop (~9 s, CPU-heavy). Needs a dependency + model download;
  measure accuracy and CPU first.
- **Claude subscription sign-in via the `claude` CLI** (as Dodaios does).
  BUSINESS RISK: Anthropic does not permit third-party apps to use Claude
  subscription logins; could breach terms and risk the user's account. Not
  built without an explicit owner decision. API key path already works.
- **Multiplayer takeover / live sync** (Amoeba's model). Needs a sync service
  and a D017 decision; today Orbyn has only the file handoff seed.
- **Act through UI Automation invoke/value patterns instead of the mouse.** A
  safety classifier stopped this twice as it reads like covert automation;
  Act stays on the visible mouse unless the owner explicitly directs otherwise.

## Addendum: apps already installed on this machine (no login)

Scanned local installs; reconstructable Electron apps and their relevance:

**Antigravity 2.9.1 (Google, "Agentic Desktop Application")** — REA + asar
extract. Windsurf/Codeium architecture: a thin Electron host (`dist/main.js`,
34 exposed API members, 66 IPC ops, a `hostBridgeServer` over connect-rpc/gRPC
with a compiled `host_bridge` proto) that bridges native capabilities to a
separate Gemini agent core reached at `daily-cloudcode-pa.googleapis.com`.
Bundles **chrome-devtools-mcp** — browser control through the Chrome DevTools
Protocol as an MCP server, a clean documented path for "work in the browser"
instead of pixel/UIA. Takeaway for Orbyn: a local host-bridge that exposes
native capability to the agent core is exactly the harness shape; CDP-over-MCP
is a better browser-control rung than screen pixels.

- **OpenAI Codex** — native Rust (`codex.exe` 341 MB, plus a
  `codex-code-mode-host` and a `codex-windows-sandbox-setup`): a sandboxed
  command/tool host. Deep analysis needs Ghidra/IDA (not installed).
- **Claude desktop, Ollama** — present; Claude has no reconstructable asar here.
- Obsidian, Discord, others — not in scope.

Convergent architecture across Amoeba, Antigravity, HeyClicky, Dodaios: a
native host + a separate agent core, connected by a local RPC/MCP bridge, with
computer/browser control behind a consent gate. Orbyn's harness is the same
shape; the gaps are the browser-via-CDP rung and the MCP tool surface.

## Agent creators (who builds this), 17 October 2026

- OpenAI AgentKit / Agent Builder; Google ADK + Vertex Agent Builder; Meta
  Business Agent Platform (build/customise/deploy with guardrails).
- Open source: Mastra MetaAgent (guided interview -> deploy local/cloud),
  DannyMac180/meta-agent (OpenAI Agents SDK generates agents), evolving-agents,
  hermes-smith, BMAD/convoke (installable agent teams + skills),
  agent-evolution / harness-evolver (self-improving via trace diagnosis),
  omnigent (meta-harness over Claude Code/Codex/Cursor).
- Research: Agent-Testing-Agent (EACL 2026) builds adversarial tests for other
  agents; Meta-Agent Challenge (arXiv 2606.04455) asks if agents can build
  agents in a sandbox with evaluation + iteration.
- Orbyn's take (D183): the creator drafts a spec, auto-tests it, saves it as a
  reusable named Teach/Act config. No self-deploy, no unattended run; every run
  stays behind plan approval, the deny list and ESC.

## Company Brain / agent-memory landscape (MP7 21A, 17 Oct 2026)

Why: the Company Brain is meant to be the main thing, so its design was checked
against the current memory products and agent-memory frameworks, not only the
"company brain" startups.

- **Zep / Graphiti** — the clearest design. A temporal knowledge graph of
  entities, relationships and facts with bi-temporal edges: when information
  changes it INVALIDATES earlier facts (keeps when they were valid and where
  they came from) rather than deleting. Retrieval = vector + full-text + graph
  traversal. Adopted: supersede-not-delete, world-time validity (`valid_from`/
  `valid_until`) separate from system time (`added`), and a Context Graph
  (`relate`/`neighbors`).
- **Mem0** — hybrid vector/graph/kv; a two-phase extraction then update; user/
  session/agent scopes. Adopted: extraction produces CANDIDATES only; scope
  isolation at query time.
- **Letta / MemGPT** — OS-style paging between context and external store;
  recursive summarisation (can lose fidelity). Not adopted: Orbyn keeps exact
  facts with provenance rather than summarising.
- **Cognee** — graph + vector, runs local. Matches Orbyn's local-first stance.
- **Meta Muse Wonder (12 Oct 2026)** — "Active Memory" carries what matters
  across conversations; Meta Business Agent keeps one customer memory across
  channels. Confirms the cross-session, owner-governed direction.
- **YC company-brain startups** (Savant, Hyper, Hyperspell, Glen, Memory
  Store, Mem0) — all converge on a provenance-bearing, self-maintaining graph.

Orbyn's store (D186) already had provenance, tenant scope, owner review states
and conflict surfacing. Hardened to parity: bi-temporal supersession (invalidate
never delete, keep validity window + source) and a Context Graph
(entities/edges, retrieve by connected entity). Still local-first, no execution
authority, shipped by slice.

### Update (17 Oct 2026, pm) — retrieval hardened; honest gaps

After wiring recall/neighbors into the workspace plan/research context, the
one real gap against the leaders was retrieval *quality*: Orbyn's recall ranked
by word-count overlap, whereas Zep/Mem0/Cognee rank by relevance (BM25 and/or
vectors).

- Adopted: `recall` now uses SQLite **FTS5 with BM25** and a **Porter stemmer**
  (native, no new dependency), so a query term matches its inflections and
  results come back relevance-ranked. An FTS index is backfilled for stores
  written before it existed; only alnum terms reach MATCH (no FTS-operator
  injection).
- Deferred (stated, not silently dropped): **vector/embedding retrieval** —
  needs a local embedding model and a dependency; against Orbyn's offline-first
  stance for now. BM25 is the lazy, dependency-free win; revisit vectors if
  recall measurably falls short on real org corpora. **Mem0's two-phase
  candidate dedup** (merge a near-duplicate into an existing fact at ingest)
  — not built; add when ingestion connectors land.

REA availability: REA ran earlier on the local Electron apps (Cluely, Amoeba,
Antigravity). The memory systems above are cloud SaaS or Python libraries with
no local binary to unpack, so they were read from public docs/papers. REA is
not connected in the session that did this hardening; it is re-run whenever a
feature needs a proprietary binary opened and REA is reachable.

### Feature: Company Brain ingestion (per-feature REA/source loop, 17 Oct 2026)

Comparable is open-source (read the source/docs, not REA — REA is for binaries):

- **Mem0 update phase** — LLM-driven: newly extracted memories are compared to
  the most-similar stored memory and the model picks ADD/UPDATE/DELETE/NONE,
  editing or deleting existing memories directly (mem0 docs; architecture
  write-ups). Operations are tool calls the LLM chooses.
- **Decision (rejected by design):** Orbyn does NOT let ingestion update or
  delete an existing fact. Ingestion has no execution authority and produces
  CANDIDATES only; update/supersede/retire stay owner decisions. Auto-LLM-edit
  would break that boundary.
- **Adopted:** Mem0's two-phase *shape* (extract then reconcile) as a
  deterministic, offline dedup: `ingest()` adds each new text as a candidate
  and skips a near-duplicate (word-Jaccard >= 0.85) of an existing fact or
  candidate in the same scope. No embeddings, no model, owner-safe.

### Feature: Agent creator pre-deploy eval (per-feature loop, 17 Oct 2026)

Comparable is open-source / documented (read docs, not REA — the one local
binary, Antigravity/Google ADK, has its agent logic minified, no useful
source-maps, so nothing to mine there):

- **Google ADK evaluation** — evaluate an agent BEFORE deployment: trajectory
  matching (the tool calls the agent actually makes vs. an expected set),
  final-response scoring, and safety scoring; a dropped guard step makes the
  golden test fail. Run via pytest/CLI/CI.
- **Adopted (deterministic, Orbyn-shaped):** `dry_run(spec, gateway)` plans the
  agent's filled goal once and checks the plan is IN BOUNDS -- a plan exists,
  it fits `max_steps`, and no step plans to use a control the deny list forbids
  (the trajectory-vs-deny check). Shown at create time as "Tried it: ...".
  Advisory (needs the model); `save()` still gates on the offline static test,
  so a model outage never blocks deploying a sound spec.

### Feature: BYOK account transparency (per-feature loop, 18 Oct 2026)

REA on the one local comparable (Cluely, app.asar) shows a Clerk-hosted auth
stack (APIKeyModal, APIKeys pages, Checkout/Billing) -- i.e. Cluely bills
centrally through its own backend. Orbyn's model is the opposite and better for
the user: the harness runs on the PERSON'S own ChatGPT/Anthropic account or
keys (BYOK), nothing billed centrally. So nothing to copy from Cluely's billing;
the gap was that a BYOK user could not see their own account was in use.

- Already sound (verified, not rebuilt): ChatGPT PKCE sign-in with refresh-
  token rotation (refreshed 60s before expiry), keys in Windows Credential
  Manager (never in files), and own-accounts-first provider order with
  fall-through on rate limit.
- Added: the gateway remembers which provider answered last (`last_provider`),
  and a console `/providers` command shows who powers the harness -- ChatGPT
  signed-in state, which providers could answer now (own accounts first), and
  who answered last -- plus `/providers signin|signout`. Keys are still set in
  the app, never echoed in the terminal.

### Feature: Act cross-app context carry (paste_text) — activation (18 Oct 2026)

Owner authorized the Act activation review for cross-app context ("copying,
pasting, writing" across apps). Plain copy-from-A -> paste-into-B already
worked via the OS clipboard with the existing copy/paste actions; the missing
piece was pasting text Orbyn HOLDS (a researched answer, brief content) into
another app.

- Added a `paste_text` action (schemas ACTIONS, planner prompt, act.perform):
  put Orbyn's text on the clipboard, focus the observed control, ctrl+v, then
  restore the user's prior clipboard in a `finally` so Orbyn's text is never
  left behind.
- Tier-1 rigor: the lock/admin blocker still runs before any clipboard write;
  input synthesis stays only in act.py (scan green); the clipboard is read only
  to restore it (never sent to a model, stored or logged). Tests cover the
  carry, the empty-text noop, and the blocked-window refusal; the restore guard
  is D018-mutation-checked (removing it fails two tests). Independent tier-1
  review pending.
- Ceiling (ponytail): a fixed 0.2s wait before restore lets the app read the
  clipboard; a non-text prior clipboard (image/files) is cleared, not restored.

### Feature: Company Brain in the GUI + research promotion (18 Oct 2026)

Two slices finishing the Brain for the actual (non-technical) user, who lives in
the app, not the console:
- `/remember <n>` promotes a cited research claim into the Brain as a candidate
  (provenance = its source URLs), the owner still reviewing it -- curated
  knowledge grows from web research without losing the gate (Cognee/Graphiti
  ingest the web into the graph; here it stays owner-governed).
- GUI Brain panel: app actions know_list/know_review/know_approve/know_retire/
  know_conflicts and a Company-Brain card in the Brain tab, the same lifecycle
  as the console /know. The store is now thread-safe (writes under a lock,
  shared connection) so the GUI can review facts from HTTP handler threads.

### Feature: clipboard -> Company Brain (cross-app copy, 18 Oct 2026)

Completes cross-app context the safe way. The clipboard READ primitive already
existed (act.get_clipboard_text, added for paste_text's restore). /clip reads
the current selection and stores it as a Company Brain CANDIDATE (source
"clipboard"), owner-initiated only.

Privacy boundary: the clipboard may hold secrets, so the content stays LOCAL --
it is never sent to a model, logged, or stored anywhere but the owner-reviewed
candidate store. A candidate is not recalled until the owner reviews it, so the
owner's review is the gate that decides whether clipboard content ever reaches
a model. No input is synthesized (the no-input-synthesis scan stays green);
nothing leaves the machine (D179 unaffected). Independent tier-1 review to
follow because capturing arbitrary clipboard text is a new privacy surface.

### Feature: Company Brain offline team sharing (export/import, 18 Oct 2026)

The owner's "offline files first, cloud sync later" for shared knowledge. A
scope exports to a JSON snapshot of its usable facts and reviewed relations
with provenance; sensitive facts are excluded so sharing cannot leak them.
Importing loads them into another Brain as CANDIDATES -- a teammate's facts are
untrusted until this owner reviews them, exactly like a received mission
handoff -- deduped against what is already there. No network, no cloud; just a
file. /know export <path> and /know import <path>.

## Company Brain n-hop graph-walk (D186, 2026-10-18)

- **Comparables:** Zep/Graphiti (Python OSS graph memory). REA (`rea-agents`,
  JS/Electron reverse-engineering) has nothing to mine for pure-Python OSS, so
  research was reading the pattern, not binary analysis — stated honestly.
- **Adopted:** n-hop retrieval. `Knowledge.connected()` walks reviewed edges
  one hop from the top BM25 recall hits and pulls facts the query words never
  named; `context()` appends them after the direct hits. Graphiti's value:
  surface a connected fact (owner, dependency) a keyword query would miss.
- **Rejected:** unbounded multi-hop traversal and automatic edge creation —
  edges stay owner-reviewed (candidate edges never walked), hop is capped at
  one and <=k facts, same scope/usable rules, direct hits ranked first so the
  caller's token trim keeps them. No execution authority added.

## Company Brain readable export (D186, 2026-10-18)

- **Decompiled:** Obsidian `app.asar` (`C:\Program Files\Obsidian\resources\`)
  via a stdlib asar reader; inspected the main process (`main.js`). REA MCP was
  not live this session and its CLI needed a network fetch, so the asar was
  read directly -- same information, stated honestly. The core renderer logic
  is a separately-downloaded minified `app.js` (not in the installer), so the
  shell exposes little -- consistent with the earlier finding that packaged
  company binaries are low-signal.
- **Backend finding:** Obsidian keeps all knowledge as plain `.md` + `.json`
  files under `app.getPath('userData')` / the vault -- no database, no server.
  Its portability strength is that the native format IS human-readable files
  the owner can read, diff and git; there is nothing opaque to "export".
- **Adopted:** `Knowledge.export_markdown()` + `/know export-md <path>` render a
  scope as readable, diffable Markdown so the owner can READ exactly what a
  shared snapshot contains before sending it. Same privacy filter as the JSON
  export (sensitive excluded unless asked).
- **Rejected:** storing the Brain as plain files like Obsidian -- a governed
  store needs owner states, bi-temporal validity and provenance that a folder
  of Markdown cannot enforce. JSON stays the structured import format; Markdown
  is the human-readable view, not the system of record.

## Company Brain conflict-surfacing at retrieval (D186, 2026-10-18)

- **Comparable:** Zep/Graphiti temporal-KG conflict handling (invalidate, do
  not delete) -- research-grade, not a desktop binary, so no decompile would
  inform it; stated honestly rather than forcing an irrelevant one.
- **Adopted:** the retrieval path now calls `conflicts_among(facts)` on the
  facts actually surfaced and adds a `company_conflicts` note, so a plan built
  on two disagreeing facts is flagged at the point of use. The disagreement
  heuristic is factored into `_disagree`; `conflicts(scope)` reuses it.
- **Bounded:** checks only the <=k surfaced facts (not the whole scope), so the
  hot path stays cheap. Conflicts are surfaced, never auto-resolved -- the
  owner decides (vision: "conflicts surfaced not resolved").

## Agent creator: deny/goal contradiction check (D186, 2026-10-18)

- **Decompiled:** Antigravity (Google's agentic desktop app) `app.asar`
  (`%LOCALAPPDATA%\Programs\Antigravity\`). Backend finding: the desktop shell
  is an IDE host that talks to a server-side agent runner over a typed Connect
  RPC proto contract (`host_bridge_pb`); an agent's capability is the explicit
  set of MCP tools it is granted (it bundles `chrome-devtools-mcp`). The
  trajectory/permission enforcement is server-side, so the shell itself is
  low-signal -- stated honestly.
- **Adopted (principle, not code):** an agent's capability should be an
  explicit, validated allowlist. Orbyn's `AgentSpec` already has `skills`
  (allowed guides) and `deny` (controls never to touch); `test_agent` now also
  flags a spec whose goal_template instructs an action its own deny list
  forbids -- a contradiction the agent could never satisfy. Deterministic,
  build-time, no model (runs before dry_run's planner check).
- **Rejected:** a remote agent runner and a cloud tool contract -- Orbyn runs
  on-device and offline-first; capability stays local AgentSpec + guides.

## Company Brain GUI capture (D186, 2026-10-18)

- **Comparable:** Obsidian (decompiled earlier) -- capture is a single action,
  knowledge is readable files the owner owns. No new decompile needed.
- **Adopted:** the GUI Brain card now has one-action capture -- a text box +
  "Add" (`know_add`) and "Capture clipboard" (`know_clip`). Both land as
  candidates, not usable until the owner reviews them, matching the console
  (/know add, /clip). know_clip reuses the already-reviewed clip_to_brain path
  (clipboard text stays local, never to a model before review).
- **Bounded:** no file-picker/upload in the webview yet (document ingestion
  stays /know ingest in the console); add when owners ask.

## Teach: pulsing hint ring, HeyClicky parity (D186, 2026-10-18)

- **Comparable:** HeyClicky (Clicky, YC S2026, Farza Majeed) -- hotkey -> ask
  aloud -> it explains the screen / walks the next step, an animated cursor
  halo highlights the control; observes only while active, never stores
  screenshots. macOS; Windows waitlisted.
- **Checked Orbyn Teach against it:** already at parity on the substance --
  screen observation, model-chosen next step, a NULL-brush outline halo
  (`_paint_ring`) centred on the observed control, voice (wake word + hotkey),
  the deny list (already credited to HeyClicky), and stronger privacy (tier-1:
  no screenshots/HWND/PID leave the device; screen text only via Tainted.of).
  No defect found; suites green (86 overlay/teach tests).
- **One parity gap fixed:** HeyClicky's halo pulses to pull the eye; Orbyn's
  ring was static. Added `cue.pulse_delta` (pure, bounded breathe) and applied
  it in `_paint_ring`. No new timer -- the live loop already repaints ~10x/s
  (TICK_S=0.1), so a time-based radius delta animates for free. Drawing stays
  inside WM_PAINT (tier-1 rule 4); the delta is bounded to [0, 6px] so the halo
  never shrinks below its base or blooms onto a neighbouring control.

## agent-reach research + Orbyn `doctor`, HeyClicky spatial (D186, 2026-10-18)

- **Researched github.com/Panniantong/agent-reach:** gives AI agents internet
  access (read/search Twitter, Reddit, YouTube, GitHub, web) via FREE OSS
  backends, no API fees; multi-backend fallback per platform; a `doctor`
  command that reports which channels work and the one thing to fix each
  broken one. What users want (from its framing + HeyClicky/Cluely): no API
  fees (Orbyn BYOK already), zero-setup that just works, graceful degradation,
  "you keep it working / tell me what's missing." Known problems: ban risk on
  cookie/session auth, unstable upstream CLIs, no zero-config for some sites.
- **Built on top:** `ghostcursor/doctor.py` + `/doctor` + `py -3.12 -m
  ghostcursor.doctor` -- one readiness self-check over models (BYOK), voice,
  fast wake word, browser, Act/Teach, and REA, each with the single action to
  enable a missing one. Presence only, no values, no network; every probe
  swallows its own failure so one broken check never hides the rest. Mirrors
  agent-reach's best idea for Orbyn's own graceful-degradation story.
- **Rejected from agent-reach:** the scraper backends and cookie/session auth
  (ban risk, Orbyn is on-device and privacy-bound); Orbyn's web path stays the
  consented browser (D184), not headless site scraping.
- **HeyClicky spatial context checked:** HeyClicky lets you hold a hotkey and
  draw/circle on screen (paint trail) to mark focus, and injects skill files by
  the program you're in, advancing when you click where it pointed. Orbyn's
  spatial engine already resolves a REGION mark (from_mark scores area), and
  Teach already verifies a step took effect before advancing. The one open gap
  is live region CAPTURE (drawn rectangle vs cursor point) -- tracked in
  FOLLOWUPS as an interactive-UI build, not rushed here.

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

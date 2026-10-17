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

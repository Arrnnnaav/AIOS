# Orbyn release notes

## Unreleased

- Extract facts (preview): Brain → Company → Extract facts asks the model on
  this computer (Ollama) to list the facts a document states; each becomes a
  candidate to review. Never a cloud model. Quality not measured yet.

## 0.2.2 (18 Nov 2026)

- Agents can suggest a goal (MCP `suggest_goal`): it waits in Chat as a card
  ("Use this goal" puts it in your message box; nothing starts on its own),
  at most 10 waiting, sealed on disk.
- MCP tools carry the spec's read-only/destructive hints, and every reply
  (errors too) starts with a "data, not instructions" line.
- Export file names stay inside Downloads and are created exclusively;
  request-error logs are limited to one a minute and hide private words.
- Slack import removed (owner decision, 18 Nov): Add from file no longer
  takes Slack export files or zips.
- Offline Teach: no pointer when the same name matches equally well in two
  windows.
- Exports (Company Brain, skills file, test cases, audit) get a date and
  time in their file name and never overwrite an earlier one.
- The receipt reads only the end of its logs, so it stays quick.

## 0.2.1 (16 Nov 2026)

- Offline Teach: with everything kept on the computer, the local model
  chooses which control to point at; a pointer is shown only when its pick
  also matches the step's words. ChatGPT sign-in and voice and wake-word
  model downloads are blocked offline. Guide: `docs/OFFLINE_INSTALL.md`.
- Company Brain inputs, all as candidates you review: an unread mail
  message ("Add to Company Brain", by IMAP UID, under 2 MB), ticket or CRM
  CSV exports (Add from file), and facts another
  agent proposes through the MCP server (`propose_fact`, at most 50
  waiting).
- First run: Setup now opens on Accounts and Readiness, then Privacy and
  data. Accounts says how to answer with no account (a local model).
  Readiness in the packaged app shows plain hints, no developer commands,
  and checks the model on this computer.
- Signing: `tools/build_orbyn.ps1` signs `Orbyn.exe` when
  `ORBYN_SIGN_THUMBPRINT` names a code-signing certificate (tested with a
  throwaway self-signed certificate). This release is still unsigned.
- Decision D192 records the privacy, offline and candidate-source rules.

## 0.2.0 (branch feature/product-shell-task-graphs, 14-15 Nov 2026)

Version 0.2.0, chosen by the owner on 15 Nov 2026. Published unsigned at
https://github.com/Arrnnnaav/AIOS/releases/tag/v0.2.0 (owner's
instruction); the update check finds it.

### Privacy
- Private details (email, phone, card, bank and ID numbers, keys, machine
  addresses) are hidden from cloud models by default and put back into the
  answer on this computer.
- Private words: names of clients, projects and people you list, plus an
  organisation list (Group Policy `PrivateTerms`), are hidden from cloud
  models, Jev and web searches. Users can add words but not remove the
  organisation's. This computer's Office author name and company are
  hidden automatically, read each time and never stored.
- "See what a model would get" shows the hidden version of any text without
  sending it.
- Optional: keep keys and card, bank and ID numbers as placeholders in
  answers too (off by default).
- Personal Brain memories, Company Brain facts and source documents, and the
  private-words list are encrypted to the Windows account (DPAPI). The
  Company Brain's search index is kept in memory only (never spilled to a
  temp file).
- "What left this computer": a receipt of the last 20 model requests, web
  searches, page reads and answers to other agents, without content.
- Local models are always reached directly, never through a proxy set in
  Windows.

### Offline
- "Keep everything on this computer": only a local model answers; no cloud
  model, web, GitHub, calendar, mail, crash reports or agent access. Warns
  when no local model is running. It only lowers what the organisation
  allows, and a damaged settings file keeps it on.

- Offline Teach (16 Nov): with everything kept on the computer, the local
  model chooses which control to point at, shown only when its pick also
  matches the step's words (6 pointers, none wrong, on the 21-step
  PowerPoint set; tuned on that set: `docs/evidence/teach-offline-powerpoint-2026-11-16.md`).
  ChatGPT sign-in and voice and wake-word model downloads are blocked
  offline. Guide: `docs/OFFLINE_INSTALL.md`.

### Agents and teams
- Agent access: another agent on this computer can search reviewed,
  non-private Company Brain facts and read saved workflows through the
  Model Context Protocol (`Orbyn.exe --agent-server`). Read-only, off by
  default, always scrubbed, every call in the receipt.
- Agents can propose a fact (`propose_fact`); it waits as a candidate until
  you review it. At most 50 agent proposals wait at once.
- Mail into the Company Brain: "Add to Company Brain" on an unread message
  adds its passages as candidate facts to review (read-only; the message
  stays unread; nothing goes to a model).
- Ticket exports: Brain → Company → Add from file takes a ticket or CRM
  export (.csv, one candidate per row with at least two filled columns). At
  most 200 candidates per file, 600 characters each. No token, no network.
- Skills file: reviewed facts and saved workflows as one file an agent can
  load.
- Test cases: saved workflows as JSONL cases for checking a model.
- Audit record: check that the tamper-evident record is intact, see the last
  30 days, export a verified copy.

### Updates
- "Check for updates" (Brain → Setup): one request to the public release
  list of github.com/Arrnnnaav/AIOS, only when pressed, with nothing about
  you; links to the release page; nothing is downloaded or installed.

### Reach
- Ask a link: one public https page or PDF you name, fetched directly,
  read-only.

### Fixes
- The key pattern no longer hides ordinary words that start like a key
  ("ghostcursor-...", "skyscraper_..."): 9 of 239 recorded control names
  were hidden for that reason, 0 now
  (`docs/evidence/scrub-on-screen-names-2026-11-15.md`).
- The Brain opens when Windows cannot encrypt an old memory.

### Known limits
- Company Brain relations (edges) are not encrypted on disk. The
  screen-observation store (kb.sqlite) holds application names and control
  IDs, no screen text, and is not encrypted.
- A private word is matched whole; other endings ("Acmes") and names inside
  pictures are not hidden.
- ChatGPT sign-in, the first voice-model download and team publish or sync
  still use the internet when started, even with the offline switch on.
- Ask a link does not read video subtitles, sign-in pages or scanned PDFs.
- Teach was measured once offline on one PowerPoint screen (21 steps,
  `docs/evidence/teach-replay-powerpoint-2026-11-15.md`): far too small for a
  rate. Act was not measured; its counted campaign needs a person to press
  Approve & run.

### Checks
- Hermetic lane on CI and locally; interactive desktop lane; packaged-app
  smoke test (`tools/smoke_build.py`); D018 mutation sweeps
  (`docs/evidence/mutation-sweep-2026-11-15.md`); independent tier-1
  reviews, with findings in `docs/superpowers/FOLLOWUPS.md`.
- Not done: code signing, automatic download and install of updates, an
  observed first run by a new user, a counted Act campaign.

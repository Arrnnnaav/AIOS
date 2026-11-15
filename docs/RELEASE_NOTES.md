# Orbyn release notes

## 0.2.0 (branch feature/product-shell-task-graphs, 14-15 Nov 2026)

Version 0.2.0, chosen by the owner on 15 Nov 2026. Not yet signed or
published.

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

### Agents and teams
- Agent access: another agent on this computer can search reviewed,
  non-private Company Brain facts and read saved workflows through the
  Model Context Protocol (`Orbyn.exe --agent-server`). Read-only, off by
  default, always scrubbed, every call in the receipt.
- Skills file: reviewed facts and saved workflows as one file an agent can
  load.
- Test cases: saved workflows as JSONL cases for checking a model.
- Audit record: check that the tamper-evident record is intact, see the last
  30 days, export a verified copy.

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
- Not done: code signing, an update channel, an observed first run by a
  new user, a counted Act campaign.

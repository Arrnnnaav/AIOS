# Aside daemon: full teardown (29 October 2026)

Follows `docs/evidence/aside-rea-2026-10-29.md` (the computer-use helper).

`aside-daemon.exe` is a Node single-executable app. Its `NODE_SEA_BLOB`
resource was read with the file loaded as data only (`LoadLibraryExW` with
`LOAD_LIBRARY_AS_DATAFILE`), and the 12.7 MB main module (`index.mjs`) was
pulled out by its length prefix. Long English strings were extracted with a
stdlib script and read as data.

| Aside feature | Orbyn |
|---|---|
| `neutralizePromptInjectionSyntax`: role tags and fake untrusted-output boundaries in tool output become `[PROMPT_INJECTION_DETECTED]`, plus a warning | **Added**: `envelope.neutralize` in every `Tainted.of` and before chunking; the request says when it fired |
| Context checkpoint: older turns summarised into Goal / Constraints / Progress / Decisions / Next / Critical context, incrementally | **Added**: `Workspace._earlier_summary`, every ten dropped turns, in memory |
| Routines every day / weekday / weekend | **Added**: `weekdays` cadence (`app.next_due`) |
| Memory taxonomy: `MEMORY.md` / `USER.md` derived from semantic pages (Current + History) and append-only dated episodic pages; "dreaming" consolidation | Covered in spirit: Brain memories with scopes, Company Brain facts with provenance and supersession, episodes |
| Context Awareness: per-window activity journal from captured screen activity | Not added: needs an always-on observation path (owner decision; rule 6) |
| Proactivity mode: mine history, cookies, password vaults, downloads | Not added: rule 6 |
| Final confirm with a draft artifact (gmail/slack/linkedin/calendar drafts) before externally visible actions | Act already asks before risky controls; Orbyn has no send connectors |
| Default follow-through: assume and continue, ask only before irreversible/paid steps | Matches the plan-approval model; nothing to add |
| Thread titles, subagents, bash/repl tools, MCP search, Slack/Telegram/Discord channels, webhooks | Not added: egress or out of scope for a read-only workspace |
| Per-app computer-use tips | macOS bundle ids only (Word, Excel, PowerPoint for Mac among them) |

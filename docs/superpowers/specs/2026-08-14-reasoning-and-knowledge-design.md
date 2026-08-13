# Ghost Cursor — Reasoning Loop and Knowledge Base Design

Date: 2026-08-14
Status: approved, ready for implementation planning
Supersedes: nothing. Extends the Beginner milestone shipped in commit `9da25cb`.

---

## 1. What this covers

The Beginner milestone proved the overlay: a click-through window that draws a
hint ring at a coordinate, verified against real pixels. It has no idea *what*
to point at beyond "the centre of a window".

This spec covers the two systems that decide what to point at:

- the **reasoning loop** — observe the screen, ground the current step to a
  real UI element, render a hint, wait for the user, verify, advance;
- the **knowledge base** — where the steps come from, how they are cached,
  and how they survive app updates.

It does not cover voice, packaging, adaptive interfaces, or any later AIOS
phase.

## 2. Safety invariants

These are not features. They constrain every design decision below.

1. **The system never acts.** No `SendInput`, no `mouse_event`, no PyAutoGUI,
   no synthesised keystrokes, no moving the real cursor. It draws hints; the
   human acts. (DECISIONS.md D006)
2. **The overlay is always escapable.** ESC from any application, plus a
   timeout, plus teardown in a `finally`. A full-screen click-through window
   that cannot be closed is how this locks someone out of their machine.
3. **Screen contents never leave the machine.** Screenshots, UIA trees, and
   window titles stay local. Only *public documentation* and the *user's typed
   goal* may be sent to a cloud model. This is what keeps the local-first
   promise while still buying cloud-quality distillation.

Invariant 1 is enforced in naming as well as policy: the schema field is
`user_action`, never `action`, because a field called `click` eventually
invites somebody to call a click function.

## 3. Architecture: two timescales

The single most clarifying idea in this design. Knowledge acquisition and step
execution run at completely different speeds and must not be coupled.

```
PLAN ACQUISITION            slow (seconds), ONCE per (app, intent)
  canonical intent
    └─ KB lookup ──hit──────────────────────────────► recipe
         └─miss─► curated docs → distil → store ─────► recipe
                    └─miss─► headless browser / search API → distil → store

STEP EXECUTION              fast (sub-second), EVERY step
  observe → ground → render hint → wait for user → verify → advance
```

Web search never touches the hot path. It runs at task start, then the cache
makes every later user of that intent fast. This is the "explore expensively
once, replay cheaply after" pattern from the OpenClicky/browser-agent notes.

Both halves meet at exactly one interface: the step contract in §4. Freeze
that, and the two can be built independently.

## 4. The step contract (frozen)

A recipe is an ordered list of steps. This schema is the contract between the
KB (producer) and the reasoning loop (consumer).

```python
step = {
    "user_action": "click" | "press_keys" | "type" | "drag"
                 | "select" | "scroll" | "observe" | "wait",

    "target_descriptor": {
        # what documentation can tell us — a guess, may be wrong or localised
        "claimed": {
            "name": "Export",
            "name_synonyms": ["Export As", "Save As"],
            "ocr_text": "Export",
            "visual_description": "toolbar button, top right, arrow icon",
        },
        # what we learned by grounding successfully — authoritative, per
        # (app_version, locale). Populated at runtime, never by distillation.
        "confirmed": {
            "automation_id": "ExportBtn",
            "control_type": "Button",
            "runtime_path": ["Window", "ToolBar", "Button[3]"],
        },
    },

    "instruction_text": "Click Export to open the export dialog.",

    "verification_rule": {
        "kind": "element_appears" | "element_disappears"
              | "window_title_matches" | "focus_moves_to"
              | "property_changes" | "any_meaningful_change"
              | "user_confirms",
        "args": {...},   # shape depends on kind, see below
        "timeout_s": 30,
    },

    "preconditions": [...],   # e.g. parent menu must be open
    "provenance": {
        "source_urls": [...], "source_tier": "official" | "community",
        "model": "...", "prompt_version": "...", "created_at": "...",
    },
}
```

Two rules that make the rest of the design work:

**Recipes store intent, never pixels.** No coordinates are ever persisted.
They are resolved live against the UIA tree on every render. A button that
*moves* therefore costs nothing — which absorbs the majority of version drift,
because most updates move things rather than rename them.

**`claimed` and `confirmed` are separate.** Documentation cannot supply an
AutomationId; no tutorial has ever named one. It can only be learned by
observing the real application. Keeping them separate is what makes §5 work.

## 5. Grounding ladder, and promotion

Grounding turns a `target_descriptor` into a live screen rectangle. Cheapest
and most stable first, mirroring the perception ladder in DECISIONS.md D005:

| Rung | Matcher | Survives rename? | Survives translation? |
|---|---|---|---|
| 1 | `confirmed.automation_id` | yes | yes |
| 2 | `control_type` + exact `name` | no | no |
| 3 | fuzzy `name` / `name_synonyms` | sometimes | no |
| 4 | OCR text match | no | no |
| 5 | VLM pointing | often | often |

**Promotion is the important part.** The top rung is unavailable at
distillation time, so it gets filled in by use:

```
first run   ground via rung 2/3 (name from docs)
            → element found → read its AutomationId
            → write into confirmed[app_version, locale]
later runs  ground via rung 1 → immune to localisation and renames
```

The recipe becomes more robust every time it is used. A user running the app
in Hindi sees different `name` values but the *same* `automation_id`, so a
recipe confirmed by an English user still grounds for them.

Grounding failure is per-step, never per-recipe: step 4 failing on v2.1 marks
step 4 unhealthy for v2.1 and triggers repair of that step alone. Steps 1–3
and 5–6 are untouched.

**Repair**, precisely, is: re-query the KB for that single action within the
recipe's intent (curated docs first, open web on miss), distil a replacement
step, and attempt to ground it immediately. Success writes a new `confirmed`
entry for this (version, locale) and resets that step's health. Failure
surfaces "I can't find this on your screen" rather than guessing a coordinate.
Repair never rewrites steps that are still grounding successfully.

## 6. Reasoning loop

Explicit state machine, observe-act-**verify** rather than plain ReAct,
because the user can change the world between our observation and their
action.

```
IDLE ──goal set──► OBSERVING ──► DECIDING ──► RENDERING_HINT
                       ▲                            │
                       │                            ▼
                   VERIFYING ◄── AWAITING_USER_ACTION
                       │
      expected change ─┼─ yes ─► advance step_index ─► OBSERVING
                       └─ no  ─► OBSERVING (re-plan from real state)
```

- `DECIDING` grounds the current step. If grounding fails on every rung, the
  step is marked unhealthy and repair is attempted before giving up.
- `AWAITING_USER_ACTION` has a timeout. On expiry: re-hint once, then go quiet.
  Per the Clippy post-mortem — debounce, confidence threshold, always
  dismissible, never nag.
- A failed verification **re-observes and re-plans**; it never blindly retries.
  The user may have done something else entirely (AndroidWorld interrupt
  handling).

## 7. Verification

**Verification checks world state, never the route taken.** If the recipe says
"click File → Save" and the user presses Ctrl+S, verification must pass. They
achieved the goal. Checking "did they click the thing we pointed at" makes the
teacher wrong exactly when the student is efficient.

This mirrors OSWorld's execution-based grading: inspect real state, don't
grade the transcript.

`args` by rule kind:

```
element_appears / element_disappears   { target_descriptor }
window_title_matches                   { pattern: regex }
focus_moves_to                         { target_descriptor }
property_changes                       { target_descriptor, property, expected? }
any_meaningful_change                  { scope: descriptor of subtree to watch }
user_confirms                          { }
```

`any_meaningful_change` compares a signature of the named UIA subtree before
and after, ignoring known-noisy properties (clock text, scrollbar position).
It is a weak signal and is only chosen when nothing better can be expressed.

When no programmatic rule can be expressed — "observe the canvas", "pick a
colour you like" — the step degrades to `user_confirms`: the hint carries a
"press SPACE when done" affordance. Honest about not knowing, keeps the lesson
moving, and the human is present anyway. These steps are logged as unverified
so they can be improved later from real usage data.

## 8. Knowledge base

### Acquisition ladder

Mirrors the perception and grounding ladders — cheapest, most trusted first:

1. **Curated official docs** for the named app, ingested once up front. The
   session begins by asking which application the user is working in, which
   makes this a pre-warm step rather than a runtime cost.
2. **Open web** (headless browser or search API) only on a miss.
3. Distil → validate → store, so the next miss becomes a hit.

Source tier is recorded in provenance; official docs outrank community posts
when both cover an intent.

### Intent matching

Goals are matched semantically, not by string equality — "how do I crop",
"crop a photo" and "cropping images" are one intent. Embeddings via Ollama
(`nomic-embed-text`, already a dependency), stored as SQLite blobs, brute-force
cosine over a few thousand rows (sub-5ms). `sqlite-vec` only if it outgrows
that.

Similarity below threshold counts as a **miss** and distils fresh. Teaching the
wrong procedure is far more costly than regenerating one.

### Which model does what

Distillation runs once per intent and is then cached forever, so quality
matters and cost amortises to nearly nothing. This is the one place to spend
on the best available model.

| Job | Frequency | Model |
|---|---|---|
| Distil docs → steps | once per intent | cloud, best quality |
| Goal → canonical intent | once per phrasing | local embedding |
| Ground / decide / verify | every step | local small model |

Exact cloud model pinned at implementation time, not guessed now.

## 9. Version and locale drift

Recipes are never keyed on an exact version. Each variant records the versions
and locales it has been *observed working on*:

```
(app_id, canonical_intent)
  ├─ variant A   verified: {1.2.0, 1.2.4, 1.3.1} × {en-US}   health 47/47
  └─ variant B   verified: {2.0.0} × {en-US, hi-IN}          health 12/12
```

Selection: exact match → nearest lower verified version → highest health.
Unknown version still matches, with lower confidence.

The loop closes itself. A successful run on 1.2.7 adds 1.2.7 to `verified`.
A step failure triggers repair; if the repair diverges structurally, it forks
a new variant. Small updates accumulate versions onto one variant; a genuine
redesign forks naturally. Nobody has to declare an update "big" — reality
decides. Users on old versions are first-class: they generate their own
verified variants through ordinary use.

### Detecting the user's version

Verified working on this machine:

```
HWND → PID → QueryFullProcessImageNameW → exe path → GetFileVersionInfo
   Chrome (Win32)   → 151.0.7922.110
   if path contains \WindowsApps\ → Store app → Appx package version
   Terminal (Store) → VERSIONINFO 1.24.2607.10001
                    → Appx pkg   1.24.11911.0   ← authoritative, differs
```

For Store apps the package version is authoritative; the exe's VERSIONINFO
disagrees. Cached per (exe path, mtime) — a once-per-session cost.

## 10. Data model

SQLite at `%LOCALAPPDATA%\GhostCursor\kb.sqlite`. User data, never in the repo.

```
apps         app_id, display_name, exe_name, kind(win32|appx)
doc_chunks   app_id, source_url, source_tier, text, content_hash, ingested_at
intents      intent_id, canonical_text, embedding BLOB
variants     variant_id, intent_id, steps JSON, verified_versions,
             verified_locales, provenance, created_at
step_health  variant_id, step_index, app_version, locale, ok_count, fail_count
```

## 11. Error handling

| Failure | Response |
|---|---|
| Target window missing / minimized / off-desktop | clear hint, wait; `uia.is_on_screen()` already guards this |
| Grounding fails on all rungs | mark step unhealthy, attempt repair, else surface "I can't find this on your screen" |
| Verification fails | re-observe and re-plan from real state, never blind retry |
| User idle past timeout | re-hint once, then go quiet |
| KB miss and network unavailable | say so plainly; do not invent steps |
| Distillation returns unparseable output | reject, do not cache |
| Screen capture unavailable | environment error, exit code 2, never a silent assertion failure |

## 12. Test plan

Existing: 22 checks passing (14 overlay, 8 end-to-end), asserting against real
pixels and Win32 state, against a controlled backdrop, in-process.

To add:

- **State machine unit tests** — every transition, especially failed
  verification causing re-observe/re-plan rather than retry, and the
  user-did-something-else branch.
- **Grounding ladder tests** — each rung in isolation against a synthetic UIA
  window with known AutomationIds; verify promotion actually writes back the
  AutomationId after a name-based grounding.
- **Locale test** — same synthetic window with translated names, same
  AutomationIds; a recipe confirmed under one locale must still ground.
- **KB tests** — semantic hit/miss around the threshold, variant selection by
  version, per-step health updates, provenance retained.
- **Synthetic UIA target app** — a real window with buttons, menus and a text
  field, extending `tests/backdrop.py`. Guided-tour verification runs against
  this before ever touching Photoshop or Blender.

Known limitation, stated honestly: distilled steps can only be validated
against a recorded UIA dump for **step 1**. Later steps depend on state that
does not exist until earlier steps happen. The dump check catches total
garbage; it is not a full safety net.

## 13. Build order

1. ~~Git~~ — done, `9da25cb`.
2. ~~Harden foundation~~ — offscreen guard, environment detection, 22/22.
3. **Freeze the step contract** (§4) as `ghostcursor/reasoning/schema.py`.
4. **Grounding ladder** (§5) against the synthetic UIA app, including promotion.
5. **State machine** (§6, §7) driven by hand-authored recipes for one app.
6. **KB + doc pipeline** (§8, §9, §10) producing the same frozen schema.

Steps 4–5 prove that recipes can actually drive a real UI. Step 6 then plugs
into a consumer already known to work.

**Scope boundary for the first implementation plan: steps 3, 4 and 5 only.**
That is the Intermediate milestone — a working guided tour for one app driven
by hand-authored recipes. Step 6 (the KB and doc pipeline) is a substantial
system in its own right and gets its own plan once the schema has been
exercised by a real consumer. Sections 8–10 are specified here so the schema
is designed against real requirements, not so they get built first.

## 14. Open questions

- Which cloud model for distillation, and its cost ceiling per app ingest.
- Curated doc sources per app: llms.txt where available, official help sites
  otherwise. Needs a per-app source registry.
- Whether `runtime_path` is stable enough to be worth storing, or whether
  AutomationId alone suffices.
- Multi-monitor: hints are already virtual-desktop aware, but recipes have not
  been exercised across monitors.

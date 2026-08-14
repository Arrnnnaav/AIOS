# Ghost Cursor — Reasoning Loop and Knowledge Base Design

Date: 2026-08-14
Status: reviewed, pending implementation plan
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
        # what we learned by grounding successfully. A log of observations,
        # not a single value — the same element can differ across versions.
        # Populated at runtime, never by distillation.
        "confirmed": [
            {
                "app_version": "1.2.7",
                "locales_observed": ["en-US", "hi-IN"],
                "automation_id": "ExportBtn",
                "control_type": "Button",
                "accessibility_path_hint": ["Window", "ToolBar", "Button[3]"],
                "last_seen_at": "...",
            },
        ],
    },

    "risk": "normal" | "elevated",   # elevated = destructive or hard to undo

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

**`accessibility_path_hint` is never identity.** A tree path breaks whenever
layout changes, so it may only be used to *disambiguate between several
otherwise-equal matches* — three buttons all named "Delete" — and never as a
matcher on its own.

## 5. Grounding ladder, and promotion

Grounding turns a `target_descriptor` into a live screen rectangle. Cheapest
and most stable first, mirroring the perception ladder in DECISIONS.md D005:

| Rung | Matcher | Survives rename? | Survives translation? | Locale-scoped? |
|---|---|---|---|---|
| 1 | `confirmed.automation_id` | yes | yes | **no** |
| 2 | `control_type` + exact `name` | no | no | yes |
| 3 | fuzzy `name` / `name_synonyms` | sometimes | no | yes |
| 4 | OCR text match | no | no | yes |
| 5 | VLM pointing | often | often | no |

**Locale gates text matchers only.** Rungs 2–4 match on displayed text, so an
observation recorded under `en-US` says nothing about what a `hi-IN` user
sees, and those rungs are filtered by locale. Rung 1 is language-independent
by construction: an AutomationId confirmed by an English user grounds
perfectly for a Hindi user, so locale there is provenance, not a filter.
Filtering rung 1 by locale would defeat the entire promotion mechanism.

**Promotion is the important part.** The top rung is unavailable at
distillation time, so it gets filled in by use:

```
first run   ground via rung 2/3 (name from docs)
            → element found → read its AutomationId
            → append an observation to confirmed[], recording the
              app_version and adding this locale to locales_observed
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

### Verification strength policy

`any_meaningful_change` fires on unrelated activity — a tooltip, a toast, a
background refresh — so it can wrongly declare a step complete. Two rules
bound that:

1. **A step with `risk: elevated` may never be completed by
   `any_meaningful_change`.** It requires an element-level rule
   (`element_appears`/`element_disappears`/`property_changes`) or, failing
   that, `user_confirms`. Elevated risk means destructive or hard to undo:
   delete, overwrite, send, publish, purchase, format, permission changes.
   Distillation sets this from the action verb; when uncertain it must choose
   `elevated`.
2. **For `risk: normal` steps, prefer `user_confirms` over
   `any_meaningful_change`** when no strong rule can be expressed. Asking the
   user costs one keypress; silently advancing past a step they never
   performed breaks the lesson and is harder to notice.

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

### Observation selection, and the cross-check that makes reuse safe

Added after the reasoning loop shipped, when persistence made this live.

While observations lived only in memory, `ground()` unioned every confirmed
AutomationId regardless of version — harmless within a single run. Once they
persist, that union lets an id learned from an older UI generation match a
control that has since been reassigned, and the tour points confidently at the
wrong element.

The correction is *not* strict version equality. AutomationIds survive version
changes far more often than they break — that stability is the entire reason
rung 1 exists — so requiring an exact match would discard every learned id on
each patch bump and re-learn from scratch. Selection follows the ladder above:
exact version, then nearest lower verified, then unknown/global.

What makes the non-exact reuse safe is a cross-check, available for free
because `ConfirmedObservation` already stores `control_type`:

> When grounding through an observation whose `app_version` is **not** an exact
> match for the running app, the live element's `control_type` must equal the
> observation's. On mismatch the observation is rejected and grounding falls
> through to name matching.

The asymmetry is deliberate: **failing to ground is acceptable, mis-grounding
is not**. A failure is visible, recoverable, and already handled — the hint
clears, the loop re-observes, and the step is eventually reported. A confident
hint over the wrong control teaches the user something false and gives them no
signal that anything went wrong.

### Step identity

Persisting observations requires a durable key for "this step of this recipe".
`(intent, step_index)` is unusable: inserting a step silently re-attaches every
learned observation to a different instruction.

The key is a hash over the intent (as namespace) plus the step's **claimed**
descriptor — specifically `name`, `ocr_text` and `visual_description`,
normalised:

```
step_key = hash(intent, normalize(name), normalize(ocr_text),
                normalize(visual_description))
```

`name_synonyms` is deliberately excluded: synonyms are alternate spellings of
the *same* target, so adding one should not discard what that step has learned.
`visual_description` is deliberately included: it is what distinguishes two
steps sharing a name but differing in location ("Delete in the toolbar" versus
"Delete in the dialog"), which is precisely the collision that would otherwise
let one step's observations mis-ground the other.

Editing any of the three orphans that step's observations. That is correct
rather than unfortunate — the step now describes a different target, and
inherited evidence about the old one would be wrong.

### Privacy of the persisted store

The knowledge base is the first thing in this system to write screen-derived
data to disk: application identity, and the names of UI elements read from the
user's screen. The §2 invariant governs data *leaving* the machine and is not
weakened by this, but a durable local record of what the user was looking at
deserves stating rather than arriving as a side effect.

- Local only. No telemetry, no cloud sync, no upload of any kind.
- Stored at `%LOCALAPPDATA%\GhostCursor\kb.sqlite` and nowhere else.
- Deleting that file fully erases it, and the system re-learns from scratch.
- The delete path is documented for the user; a CLI affordance can come later.

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

Only one table is needed by the persistence milestone; the rest arrive with
doc ingestion and intent matching:

```
observations  step_key, app_id, app_version, locale, automation_id,
              control_type, last_seen_at, ok_count
              PRIMARY KEY (step_key, app_id, app_version, automation_id)
```

This is `ConfirmedObservation` flattened, plus the `step_key` from §9 and the
`app_id` that scopes it. The primary key is what makes promotion idempotent:
re-observing the same id for the same step, app and version updates a row
rather than accumulating duplicates — the unbounded-growth problem noted
during the reasoning-loop build.

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
3. ~~**Freeze the step contract**~~ (§4) — `ghostcursor/reasoning/schema.py`.
4. ~~**Grounding ladder**~~ (§5) against the synthetic UIA app, incl. promotion.
5. ~~**State machine**~~ (§6, §7) driven by hand-authored recipes.
6. **Persist confirmed observations** (§9, §10) — this milestone.
7. **KB + doc pipeline** (§8) producing the same frozen schema — later.

Steps 3–5 shipped in `b4c3af3`: 70 unit tests plus two pixel harnesses,
verified against a real window.

**Scope boundary for the next implementation plan: step 6 only.** Promotion
currently works and is wired into live runs, but writes only to the in-memory
`Step`, so a recipe grows stronger during a run and forgets at exit. This
milestone makes exactly this true and nothing more:

```
run 1   ground by name → discover AutomationId → persist observation
run 2   load observation → ground by AutomationId immediately
```

Explicitly NOT in this milestone: web search, doc ingestion, embeddings,
intent matching, recipe distillation, OCR, VLM. Those are step 7. The
knowledge base only becomes worth feeding once promotion survives a restart.

The parked cross-version union problem (§9) is handled *inside* this
milestone, not deferred past it: persistence is what makes it dangerous, so
scoped selection and the control_type cross-check ship together with the
store.

Tasks, with step identity kept separate from the store — the first is product
semantics and the second is plumbing, and they warrant different review:

1. App identity and version detection (§9).
2. `step_key` derivation (§9) — the durable identity.
3. SQLite store at `%LOCALAPPDATA%\GhostCursor\kb.sqlite` (§10).
4. Persist observations from `promote()`.
5. Hydrate a recipe's observations before the tour starts.
6. Scoped selection in `ground()`: exact → nearest lower → unknown, with the
   control_type cross-check on every non-exact match.
7. Tests: run 1 learns; run 2 grounds via rung 1; a stale id from an older
   version does not mis-ground; a patch bump still reuses what was learned.

## 14. Open questions

- Which cloud model for distillation, and its cost ceiling per app ingest.
- Curated doc sources per app: llms.txt where available, official help sites
  otherwise. Needs a per-app source registry.
- Whether `accessibility_path_hint` earns its place at all, or whether
  AutomationId plus control type disambiguates well enough on its own.
- Multi-monitor: hints are already virtual-desktop aware, but recipes have not
  been exercised across monitors.

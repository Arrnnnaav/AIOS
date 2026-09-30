# Live manager-approved PowerPoint Act run, with per-attempt readings

> **Manifest superseded 30 September 2026 (D149).** The PowerPoint manifest
> `28dbaf2d` named in this record is superseded by `3a4f8c57`. D145 added two
> signed UIA confirmation-timing fields to `operations.json`, so the bundle was
> rebuilt from tracked sources and re-signed with the same
> `ghostcursor-release-2026-3` key; adapter and verifier bytes are unchanged.
> Nothing below is evidence for `3a4f8c57`, and the captured content is not edited.
> `3a4f8c57` was itself superseded on 30 September by `6dbd5ba2` (D151), which
> added the animation-catalog plan; nothing below is evidence for it either.
> The current manifest is `b0d63512` (D152); nothing below is evidence for
> it.

**Date:** 11 September 2026
**Repository commit at run time:** `d65184e` (`feat: label deck readings per attempt`)
**Application:** Microsoft PowerPoint, version `16.0`, build `20326`
**Intent:** `ADD_SLIDE` · **Plan:** one node, `n001-new-slide`, `powerpoint.new_slide_uia`
**Operator:** the repository owner, clicking the real `Approve & run`

This replaces the two earlier retained runs. `act-live-manager-d123-r5.jsonl` is
invalidated (D125) and `act-live-manager-d125-r1.jsonl` superseded (D127); the
latter could not separate its two approval cycles at all, which is the gap this
run narrows.

## Retained artifacts

| File | SHA-256 |
|---|---|
| `act-live-manager-d131-r1.jsonl` | `0cd270d46792ea36d89bef1ddd32678440e5ae12019d07415ab96f3dcf3c2f0e` |
| `act-live-deck-2026-09-11-before-1.json` | `224a9f68ec76aa6b328ce2db2cccfff64c080dd3e18f5ca7e84006b750a6ec93` |
| `act-live-deck-2026-09-11-after-1.json` | `7fe90d44226195ecc6e698b57b365e649563ab58a7c8a52617f875cf31cd9b7d` |

All three are LF, and the digests above are of the committed bytes.

## Bound production authority

```text
plugin:              ghostcursor.powerpoint 1.0.0
intent:              ADD_SLIDE
catalog generation:  9
manifest:            28dbaf2d372c55144e289316a1b92dd25185281351cd685a8e735ee9d759a836
UIA adapter (ACTED): d97216d3e84d1b689bdd2ab52d30b3a6da535381951ecd88f4275829a64795ac
object adapter:      eb7a0c687de2f702a1cb52ef6e438a9e7d32cecfd70a1f036e8fdba2716db4cd
                     (present in the bundle; did NOT act on this node)
live verifier:       ccbf395eba0de2cefa1a86b8da68d2d84c90f9045c0e8b7a7c0ba09b8ab22a76
active index:        8866822ecc2fea1111662359afcc7513bd9c7ead2780115ab09094d0bbf45069
graph:               2b0a7629240e35659f4c66c78800ada296e485d45d18576dc1fa2d309f7719d4
validation:          721d3995a53983a3507a9eb1bf59e8a3a7782c5c82aa532ec6aeb4358a768866
proposal:            893ea66e326d2a7c16fca96123bdeea6a88de4e2443e2be523c39fd6e99b7a00
```

The operation is `powerpoint.new_slide_uia`, so the bytes that drove the control
are the **UIA** adapter, `d97216d3…`. An earlier version of this document
published only the object adapter and omitted the acting one, which left a
reviewer of a UIA run unable to see the digest of the code that touched the
application -- material, given that no `uia_pattern` operation may be adopted
without independent review of its bytes. `d97216d3…` equals
`CANONICAL_UIA_ADAPTER_SHA256` in `ghostcursor/plugins/bundle.py`, so the shipped
copy is the reviewed one.

The manifest is the one every tracking document names, and since `f5f2f97` it is
recomputed from tracked sources by `tests/test_powerpoint_manifest_pin.py`, so
the digest quoted here cannot drift from the bundle without a test failing.

**Three of the values above are unrecorded operator observations, not
measurements.** `catalog generation: 9`, the active-index digest, and the
enabled-plugin set were read from the running store and the manager window at
the time; no retained artifact in this repository lets a reader check them,
because there is no PowerPoint bundle in `plugins/bundled/` and no index
snapshot is kept. Under D034 they are reported here as observations and must not
be cited as measured evidence. Everything else in the block comes from the
transcript's own fields.

Read that way: the manager's plugin list showed `ghostcursor.powerpoint` and
`ghostcursor.synthetic` enabled with `ghostcursor.excel` and `ghostcursor.vscode`
disabled (D130), which is consistent with the transcript's `plugin_id` and with
the PowerPoint-only scope, but is not independently checkable from the files.

## What happened

Eleven records, one approval cycle, contiguous `sequence` 1–11:

```text
 1  manager_opened
 2  act_proposal_displayed
 3  target_focus_handoff_completed
 4  approve_and_run_issued
 5  execution_request_dequeued
 6  act_worker_started
 7  act_runtime_event   code=action_started    1/1
 8  act_runtime_event   code=action_completed  1/1
 9  act_runtime_event   code=completed         1/1
10  act_run_result      code=completed  completed=true  completed_nodes=1
11  manager_closed
```

The handoff record precedes the issuance record at `sequence` 3 and 4. Both
carry the **same** `at_ns` (`1789060727130799800`), so the ordering rests on the
emitter's own sequence counter, not on a clock: it is the source's claim
serialised into a file rather than an independent measurement. The emission
order was corrected (D129) so that the counter reflects the real order, and the
transcript is consistent with D123 — but "evidenced by the artifact" would
overstate it, and an earlier draft of this document did.

## The change was observed after the authorized cycle

| Reading | Deck | Slides |
|---|---|---|
| `before-1` | `Presentation1` | 1 |
| `after-1` | `Presentation1` | 2 |

**One approval cycle sits between those two readings.** The wording stops
there, deliberately, and the interval is worth stating rather than waving at:

| Span | Seconds | Share of bracket |
|---|---:|---:|
| `before-1` to `after-1` | 155.894 | 100% |
| manager session open | 116.791 | 74.9% |
| Act execution (`act_worker_started` to `act_run_result`) | 4.390 | **2.8%** |

So 97.2% of the bracketed interval has no execution running in it. What the
artifacts establish is that the deck held one slide before the authorized cycle
and two after it, and that the signed live verifier answered affirmatively for
the declared change in between. They do not establish *causation*: the readings
bracket an interval, not the cycle itself. Whether
this run may claim "Act caused the change" rather than "the change was observed
after the authorized cycle" is a question for independent review, and until
that review says otherwise the weaker sentence is the claim.

This is still stronger than the 10 September run, which held two approvals --
one of them refused -- inside a single session-bracketing pair, so no attempt
could be separated from any other and the evidence had to be narrowed to "the
session ended with one additional slide" (D128/D130). Per-attempt labels
(`d65184e`) shorten the interval to one cycle; they do not turn correlation
into causation, and the first draft of this document overstated exactly that.

The readings were taken by `ghostcursor.devtools.act_deck_observation`, which
attaches read-only to a running PowerPoint and never launches one.

## What this run proves

- The real native-manager `Approve & run` was crossed before any execution
  request existed (record 4 follows record 3, then a dequeue at 5).
- Focus was handed to the exact proposal-bound window before the request was
  minted, and the transcript's record order shows it.
- The signed UIA adapter acted and the separately signed live verifier confirmed
  the declared change: `action_completed` is emitted only on an affirmative
  verifier answer.
- The claimed state change is corroborated by two files bracketing one cycle,
  not by an operator's memory and not by an interval containing two attempts.
  That is an observation ordered around the cycle, not a demonstration that the
  cycle caused it.
- It ran on the current, reproducible bundle. The catalog was **not**
  PowerPoint-only: `ghostcursor.synthetic` was enabled alongside it, as the
  observation above records. Only PowerPoint and Synthetic Export were
  enabled, and the acting plugin was PowerPoint.

## What it does not prove

One diagnostic run, not the 3/3 acceptance campaign, and not yet independently
reviewed. It does not prove semantic stages, the 255-node staged deck, repeated
UIA acceptance, or release activation.

Act remains: operationally demonstrated, acceptance not yet re-established.

## A note on the earlier first-cycle failures

The two preceding runs each failed their first approval with `adapter_failed`
and succeeded on the second. This run succeeded on the first, so that is **not**
an established pattern — two occurrences and one counterexample. It is recorded
here only so a later reader knows the earlier failures were observed rather than
imagined, and because the retained evidence still cannot say why they happened:
the refusal reason is hashed, which is the open follow-up for a bounded
refusal-reason vocabulary.

An earlier attempt on the same day is **retained as an excluded attempt**, not
omitted: `docs/evidence/excluded/act-live-manager-2026-09-11-attempt-1.jsonl`,
with its reason recorded in `docs/evidence/excluded/README.md`. It was launched
before its `before-1` reading was taken and so has no starting bracket. It
reached `completed 1/1` on its second cycle, so this is not a discarded failure,
and keeping it is what lets a reader check the exclusion instead of trusting it.

For completeness, since a reader comparing timestamps will notice it: that
attempt ended with the deck at two slides, and `before-1` reads one slide
afterwards. The deck was reset between the two runs, by the operator, off the
record. Nothing here depends on that -- this document claims no causation
either way -- but an unexplained 2 -> 1 would otherwise look like a gap.

# Live manager-approved PowerPoint Act run, with per-attempt readings

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
object adapter:      eb7a0c687de2f702a1cb52ef6e438a9e7d32cecfd70a1f036e8fdba2716db4cd
live verifier:       ccbf395eba0de2cefa1a86b8da68d2d84c90f9045c0e8b7a7c0ba09b8ab22a76
active index:        8866822ecc2fea1111662359afcc7513bd9c7ead2780115ab09094d0bbf45069
graph:               2b0a7629240e35659f4c66c78800ada296e485d45d18576dc1fa2d309f7719d4
validation:          721d3995a53983a3507a9eb1bf59e8a3a7782c5c82aa532ec6aeb4358a768866
proposal:            893ea66e326d2a7c16fca96123bdeea6a88de4e2443e2be523c39fd6e99b7a00
```

The manifest is the one every tracking document names, and since `f5f2f97` it is
recomputed from tracked sources by `tests/test_powerpoint_manifest_pin.py`, so
the digest quoted here cannot drift from the bundle without a test failing.

**Scope at run time was PowerPoint-only.** The manager's own plugin list showed
`ghostcursor.powerpoint` and `ghostcursor.synthetic` enabled, `ghostcursor.excel`
and `ghostcursor.vscode` disabled (D130). The active index above is that catalog.

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

The handoff record precedes the issuance record (sequence 3 before 4), which is
the D123 ordering evidenced by the artifact rather than by reading source — the
emission order was corrected for exactly this reason.

## The change was observed after the authorized cycle

| Reading | Deck | Slides |
|---|---|---|
| `before-1` | `Presentation1` | 1 |
| `after-1` | `Presentation1` | 2 |

**One approval cycle sits between those two readings.** The wording stops
there, deliberately. What the artifacts establish is that the deck held one
slide before the authorized cycle and two after it, and that the signed live
verifier answered affirmatively for the declared change in between. They do not
establish *causation*: the readings bracket an interval, not the cycle itself,
and an interval is a weaker thing than an action however short it is. Whether
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
- It ran on the current, reproducible bundle under a PowerPoint-only catalog.

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

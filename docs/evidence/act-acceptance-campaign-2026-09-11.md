# Historical campaign record — PowerPoint investor deck, rebuilt bundle

> **Manifest superseded 30 September 2026 (D149).** The PowerPoint manifest
> `28dbaf2d` named in this record is superseded by `3a4f8c57`. D145 added two
> signed UIA confirmation-timing fields to `operations.json`, so the bundle was
> rebuilt from tracked sources and re-signed with the same
> `ghostcursor-release-2026-3` key; adapter and verifier bytes are unchanged.
> Nothing below is evidence for `3a4f8c57`, and the captured content is not edited.

> **RECLASSIFIED — diagnostic only.** This historical campaign is retained for
> audit context, but it is not current acceptance evidence and must not be
> used to close Act. It was reclassified under D139 while the evidence
> discipline was repaired.

**Date:** 11 September 2026
**Repository commit:** `301e86b`
**Result: 3 of 3 clean, consecutive.**

This replaces the 4 September campaign, whose runs were clean but were signed
into a bundle that no longer exists: the production core, the presentation
boundary, the payload line endings and the manifest have all changed since
(D125, D127, D129, D130). Those runs were never withdrawn for being wrong — they
were superseded by their own artifacts becoming unreproducible.

## What was signed, and what ran

| | |
|---|---|
| Bundle | `c563c81581118a8b877e2bb9276c90f48254751e2328d7c199783ea3f06b3192` |
| Manifest | `28dbaf2d372c55144e289316a1b92dd25185281351cd685a8e735ee9d759a836` |
| Signing key | `ghostcursor-release-2026-3` |
| Plan | `build-investor-deck-v1`, `84e39d0d2987e153923c537587380e9eeecccfae0a50ede5be586e0238e4fe79` |
| Nodes per attempt | 255 |
| Harness | `ghostcursor.devtools.act_campaign --attempts 3 --mode quick` |
| Report | `act-acceptance-campaign-2026-09-11.json`, `a652a7c4c738b842f730f7e863b9fbd2fc271954e10f075f077d9c1a5ea8341c` |

The plan digest is **the same bytes as the 4 September campaign**. What changed
is the bundle carrying it: `28dbaf2d` is the manifest that
`tests/test_powerpoint_manifest_pin.py` recomputes from tracked sources, so a
reader with a clean checkout can rebuild the artifact this campaign ran against
— which was not true of any earlier campaign in this repository.

## The three attempts

| Attempt | Code | Nodes | Seconds | Published artifact |
|---|---|---:|---:|---|
| 1 | `completed` | 255/255 | 69.687 | `23020b0f1e43a586…` |
| 2 | `completed` | 255/255 | 69.516 | `59b655901dde81ef…` |
| 3 | `completed` | 255/255 | 69.281 | `d4d7be4a293b41de…` |

One published artifact per attempt, at three separate output paths, and their
digests differ.

**Their difference is not evidence of anything**, and an earlier revision of
this document wrongly presented it as evidence of attempt independence. A
`.pptx` is a ZIP of XML carrying creation and modification timestamps, so three
runs of the same plan produce different bytes whether or not they are
independent; the sizes here differ by 33 and 1 bytes, which is metadata noise.
Had the build been byte-deterministic, three identical digests would have been
the correct result, and the rule as written would have condemned a clean
campaign. The activation review caught the inversion (D137).

What actually isolates the attempts is enforced in `run_campaign()`: each gets
its own store root (`store-{index}-{token}`) and its own output path
(`out/attempt-{index}-{token}.pptx`), passed into the command rather than left
to the caller. That invariant implies isolation. The digests merely correlate
with it, and here for an unrelated reason.

A separate validation attempt was run first, into its own workspace, to check
the wiring on the rebuilt bundle: `completed`, 255/255, 72.547 s. It is **not**
part of the count and its artifacts are not retained as acceptance evidence.

## What the campaign runner refuses

The count means something because the runner will not produce a misleading one
(D105 and the module docstring): a run emitting an `interrupt_probe` record ends
the campaign rather than being counted; each attempt gets its own store and
output path; a missing `result` record is refused rather than defaulted; and the
first attempt that is not clean ends the campaign instead of reporting a pass
rate. All three attempts here were clean, so none of those paths was exercised —
that is stated so a reader does not mistake an unexercised guard for a tested
one.

## One thing this campaign nearly could not have produced

`act_acceptance` now refuses to write diagnostics without a campaign scope and
salt in the environment. Before that refusal existed, three invocations would
each have derived their own scope, and `render_add_slide_evidence` would have
rejected the records as coming from three different campaigns — after all three
runs had been performed. The seventh D032 review found it by reading the two
tools against each other; no test was comparing them (D133).

This campaign ran under one exported scope for all three attempts.

## Which path these runs crossed

**The harness path, not the manager path.** `act_campaign` shells out to
`ghostcursor.devtools.act_acceptance`, which imports `approve_action_graph` and
`execute_approved_graph` from `ghostcursor.act_runtime` and calls them directly.
Its own first paragraph says "This is not a production install path."

So these three attempts exercised the whole-graph validation, per-node
authorization, fresh target binding, presentation receipts and independent
verification — the authority core — and did **not** exercise the layer above it:

| Not crossed by these runs | Recorded in |
|---|---|
| The one-use `ActExecutionRequest` minted only by the manager's `Approve & run` | D121 |
| Foreground handoff to the exact proposal-bound HWND, and its four refusals | D123 |
| The manager worker's rejection of a bare, forged or replayed request | D121 |
| `UiThreadPresentationBridge` and the manager-owned overlay pump | D124 |

Each of those has hermetic tests, and an activation review killed mutations of
all four. None has a counted live campaign. The only run that has crossed the
real `Approve & run` is the single diagnostic in
`act-live-manager-d131-run.md`, and that one drove `powerpoint.new_slide_uia` —
an operation from the unadopted UIA slice.

Stated as D031 asks: the property acceptance wants is "the path a real operator
uses produces three clean consecutive runs". The invariant established is "a
harness sharing the authority core produces three clean consecutive runs". The
second does not imply the first. It omits exactly the layer that was added last
and is least exercised live.

**A manager-path counted campaign is therefore an open gate**, listed in
`ROADMAP.md` with the others.

## Historical scope and standing

This was a campaign for the **object-model** deck build, through the harness
path described above. Under D139 it is diagnostic only and is not current
acceptance evidence. It does not establish the UIA slice: `add-slide-uia-v1` has one live diagnostic run
(`act-live-manager-d131-run.md`) and no counted campaign, and CLAUDE.md still
requires an independent D032 review, externally signed bytes and a counted
campaign before any `uia_pattern` operation is adopted.

The D032 review that gates this campaign returned **READY** at `45d1323`
(D134), after seven rounds.

# Counted acceptance campaign — PowerPoint investor deck, on the rebuilt bundle

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

Three **distinct** published digests, 94 400 / 94 367 / 94 366 bytes. Distinct
is what a counted campaign should produce: each attempt gets a fresh store root
and a fresh output path, so an identical digest would mean one attempt's state
had decided another's outcome.

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

## Scope and standing

This is the counted campaign for the **object-model** deck build. It does not
establish the UIA slice: `add-slide-uia-v1` has one live diagnostic run
(`act-live-manager-d131-run.md`) and no counted campaign, and CLAUDE.md still
requires an independent D032 review, externally signed bytes and a counted
campaign before any `uia_pattern` operation is adopted.

The D032 review that gates this campaign returned **READY** at `45d1323`
(D134), after seven rounds.

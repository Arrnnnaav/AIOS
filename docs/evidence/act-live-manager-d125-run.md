# Live manager-approved PowerPoint Act run on the rebuilt LF bundle

> **SUPERSEDED 10 September 2026 (D127).** This run bound catalog manifest
> `48e6e4f4`, which contained two signed `__pycache__/*.pyc` entries. Those come
> from untracked directories, so a clean checkout rebuilds a different manifest
> and this run's authority binding cannot be reproduced from source. The
> executed adapter and verifier bytes (`eb7a0c68`, `ccbf395e`) are unaffected
> and remain reproducible; it is the catalog binding that is not. The bundle has
> been rebuilt without build products (manifest `61b39b65`, active generation 6)
> and a replacement run is required. The observations below stand as a record of
> what happened; they are not current acceptance evidence.

**Date:** 10 September 2026
**Repository commit at run time:** `f44a0e3` (`feat: retain the deck reading a live Act run claims`)
**Application:** Microsoft PowerPoint, version `16.0`, build `20326`
**Intent:** `ADD_SLIDE` · **Plan:** one node, `n001-new-slide`, `powerpoint.new_slide_uia`
**Operator:** the repository owner, clicking the real `Approve & run`

This run replaces `act-live-manager-d123-r5.jsonl`, which D125 invalidated: that
transcript named adapter, verifier and manifest digests belonging to a CRLF
working copy git never stored. Everything below executed bytes that a clean
checkout reproduces.

## Retained artifacts

| File | SHA-256 |
|---|---|
| `act-live-manager-d125-r1.jsonl` | `9c625244a94476f679df5e326f9712d870fbf088c88f1ac0039e857f7e8e23c1` |
| `act-live-deck-2026-09-10-before.json` | `f8c43c28bc2567413f6156c5b4e677dcd779443da7a7af5c21637598d2dc688a` |
| `act-live-deck-2026-09-10-after.json` | `e55bc81c719f2dbb54fddfdf07e3cd70852de9105056e0220edbbb39d251952a` |

The two readings were produced by `ghostcursor.devtools.act_deck_observation`,
which attaches to a running PowerPoint read-only and never launches one. They
exist because the 9 September slide count was an operator's reading that reached
no file, which D034 does not accept as evidence.

**One correction belongs in the record.** The probe first wrote both readings
with CRLF, because `Path.write_text` translates newlines on Windows — the D125
defect in miniature, in a file that is cited by digest. The probe now renders
bytes explicitly, a test pins it, and `docs/evidence/**/*.json` and `*.jsonl`
are pinned to LF. The retained files are the LF form of those readings; their
content is unchanged and the digests above are of the committed bytes.

## Bound production authority

```text
catalog generation:  5
active index:  60a6f7efb6be20f33fab4abed816630c60821d3c2057f4b1169b323c824bab8d
object adapter:  eb7a0c687de2f702a1cb52ef6e438a9e7d32cecfd70a1f036e8fdba2716db4cd
live verifier:  ccbf395eba0de2cefa1a86b8da68d2d84c90f9045c0e8b7a7c0ba09b8ab22a76
graph:  2b0a7629240e35659f4c66c78800ada296e485d45d18576dc1fa2d309f7719d4
validation:  721d3995a53983a3507a9eb1bf59e8a3a7782c5c82aa532ec6aeb4358a768866
proposal:  763340c07a97bc2d86d743a58ebcbffadfd8ac0a755cc11b8e8fe4470ba7afba
```

The adapter and live-verifier digests are the tracked LF bytes
(`plugins/sources/powerpoint/payload/ghostcursor/adapter/`), and the catalog is
the rebuilt manifest `48e6e4f4` published at generation 5. The proposal digest
is now a keyed commitment (HMAC, per-process key, never exported), so it
correlates records inside this transcript only — deliberately not across runs.

## What happened: two approvals, one effect

The session contains **two** complete approval cycles. Nineteen records, in
order:

```text
 1  manager_opened
 2  act_proposal_displayed
 3  target_focus_handoff_completed
 4  approve_and_run_issued
 5  execution_request_dequeued
 6  act_worker_started
 7  act_runtime_event   code=action_started    n001-new-slide  1/1
 8  act_runtime_event   code=action_failed     n001-new-slide  1/1
 9  act_run_result      code=adapter_failed    completed=false completed_nodes=0
10  act_proposal_displayed
11  target_focus_handoff_completed
12  approve_and_run_issued
13  execution_request_dequeued
14  act_worker_started
15  act_runtime_event   code=action_started    n001-new-slide  1/1
16  act_runtime_event   code=action_completed  n001-new-slide  1/1
17  act_runtime_event   code=completed         1/1
18  act_run_result      code=completed         completed=true  completed_nodes=1
19  manager_closed
```

Both cycles carry the **same** `proposal_sha256`, `target_sha256`,
`graph_sha256` and `validation_sha256`: the same plan, the same approved window,
the same signed bytes. The difference between them was environmental, not a
difference in authority.

**The first attempt refused before any effect.** The retained readings show
`Presentation1` at **1 slide before** and **2 slides after** the whole session.
One slide was added across two attempts, so the attempt that ended
`adapter_failed` changed nothing in the document. That is the fail-closed
property holding under a real failure rather than a constructed one.

**The cause of that refusal is not retained, and is not reconstructed here.**
The bounded audit carries the run-level `code` (`action_failed` →
`adapter_failed`) but hashes the detail, `sessions.sqlite` stores no Act detail
by default, and the operator does not recall the on-screen text and believes a
stray interaction may have caused it. Under D032 an unremembered cause is not
written down as a finding. What the artifacts do establish is that it refused,
and that it refused without touching the deck.

## What this run proves

- The real native-manager `Approve & run` was crossed — twice — before any
  execution request existed (records 4 and 12, each followed by a dequeue).
- `target_focus_handoff_completed` precedes `approve_and_run_issued` in the
  retained artifact (3 before 4, 11 before 12). Under the previous emission
  order the transcript could not have shown this.
- The signed UIA adapter acted and the separately signed live verifier
  confirmed the declared change: `action_completed` is emitted only on an
  affirmative verifier answer.
- The claimed state change is corroborated by a file, not by an operator's
  memory: 1 → 2 slides.
- A failure and a success were recorded in one session, and the failure left
  the document unchanged.

## What it does not prove

This is **one** diagnostic run, not the 3/3 acceptance campaign, and it has not
been through independent D032 review. It does not prove semantic stages, the
255-node staged deck, repeated UIA acceptance, or release activation. The
refusal cause in the first cycle is unexplained.

Act remains: operationally demonstrated, acceptance not yet re-established.

## Open follow-up this run surfaced

An adapter refusal is diagnosable only from the screen at the time. The audit's
run-level `code` is bounded and retained, but the reason inside it is hashed, so
a failed cycle cannot be explained from retained evidence afterwards. A bounded
refusal-reason vocabulary would fit D122 — it is a closed set of names, not
content — and would have answered the question this run leaves open.

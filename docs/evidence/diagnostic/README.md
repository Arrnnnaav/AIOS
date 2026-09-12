# Diagnostic runs — NOT acceptance evidence

**Status: frozen, diagnostic only. Nothing in this directory may be cited as
acceptance evidence, and no phase may be marked closed on the strength of it.**

The runs here demonstrate working functionality. They are withheld from
acceptance not because anything went wrong in them, but because the repository's
evidence discipline was found compromised on the same day they were produced
(D139): three transcripts elsewhere had been edited after capture, and the first
repair of two of them was itself falsified.

Evidence produced while the discipline that governs evidence is under repair
cannot be the thing that closes the gate. It is kept, in full, so that a later
campaign has something to be compared against.

## The manager-path campaign — 11 September 2026

Three consecutive clean runs of `build-investor-deck-v1` (255 nodes) through the
**real** `Approve & run` path: a human at the native manager, selecting the
PowerPoint window and approving each run once.

This is the path the 11 September `act_acceptance` campaign never touched. That
one calls `approve_action_graph`/`execute_approved_graph` directly and never
mints an `ActExecutionRequest` (D137).

| Attempt | Artifact | Result | Nodes | Execution | Transcript SHA-256 |
|---|---|---:|---:|---|
| 1 | `act-live-manager-campaign-attempt-1.jsonl` | `completed` | 255/255 | 102.145 s | `19db97f8d861c207a09dabf8502f5c33a26d4dfe6c1ac6a4c968383f5db75705` |
| 2 | `act-live-manager-campaign-attempt-2.jsonl` | `completed` | 255/255 | 149.811 s | `ab5a443ef89cbff8296dc94048e437218ad0474f833434ec1beb4eb21e28863e` |
| 3 | `act-live-manager-campaign-attempt-3.jsonl` | `completed` | 255/255 | 161.253 s | `dc05f538b7e5f75220d015d0817ba39173b48c00238ff8dea034922e163bba54` |

The excluded transcripts are also retained and digest-bound here:

| Artifact | SHA-256 |
|---|---|
| `excluded-attempt-2a-target-not-running.jsonl` | `6cd20084f743a64cc0191060638ded4ff9c46b731721e6903414b062b15d7c0e` |
| `excluded-attempt-2b-target-minimized.jsonl` | `d525ca171362b2e8e1947471673407bd6afd954aab6e741d374b77d4be2696cd` |

Every attempt recorded this ordering, which is what makes them interesting:

```
manager_opened
act_proposal_displayed
target_focus_handoff_completed      <- D123, before the request exists
approve_and_run_issued              <- D121, the one-use request minted here
execution_request_dequeued
act_worker_started
act_run_result                      <- completed: true, completed_nodes: 255
```

Three distinct proposal digests (`663788cf6c67`, `65c79981c3df`, `6735ba2641e5`).
Execution times rise across the three runs; nothing here explains why, and it is
recorded rather than smoothed over.

**Harness:** `manager_campaign_harness.py`, retained here per D121 — live
evidence keeps the harness, not just the transcript. It launches the real
manager and passes the documented opt-in `act_audit_path`. It cannot propose,
authorize, approve, dispatch or verify.

## Two excluded attempts, preserved

| File | Why |
|---|---|
| `excluded-attempt-2a-target-not-running.jsonl` | `TargetNotRunning` — PowerPoint had no window yet |
| `excluded-attempt-2b-target-minimized.jsonl` | `TargetNotRunning` — the PowerPoint window was **minimized** |

Both are `manager_opened` → `manager_closed` with no proposal, no approval and
no execution. The cause in both cases is that `_collect()` in
`ghostcursor/packs/workflow.py` skips windows failing `IsWindowVisible` or
passing `IsIconic`, so a minimized target yields zero candidates and the
resolver refuses under D075. That is correct behaviour — an operator-environment
fault, not a product fault — and it is recorded here rather than deleted,
because a reader comparing timestamps would otherwise find a gap.

## What these runs do and do not establish

**Do:** the manager approval event, the D123 foreground handoff and its
ordering, the one-use execution request, the UI-thread presentation bridge, and
the object-model deck build, all exercised live end to end by a human.

**Do not:** acceptance. Not for the manager path, not for the object-model
build, not for anything. When the evidence discipline is repaired and an
independent reviewer returns READY, a **fresh** campaign is run and that one is
the acceptance evidence. These transcripts are then the thing it can be compared
against — which is most of their value.

# Perception Off the UI Thread — Design

Date: 2026-08-14
Status: reviewed, pending implementation plan
Builds on: `2026-08-14-reasoning-and-knowledge-design.md` (the loop and grounding this changes)

---

## 1. Why

The overlay is full-screen, topmost, click-through, has no title bar and never
takes focus. ESC and `--seconds` are the only ways out, and **ESC is polled
between ticks**. A blocking tick is therefore time the user cannot escape a
window covering their screen.

That invariant has been broken twice, each found only after the fact:

- drawing outside `WM_PAINT` left the surface uninitialised, painting an
  opaque wash over the desktop (D009);
- three `wait("exists", timeout=3)` calls per tick meant an absent target
  blocked a tick for 9.1 s, every tick (D020).

Both were fixed at the call site. Nothing prevents the next one.

### The measurement that makes this urgent rather than defensive

A window whose owner has stopped pumping messages — an ordinary "Not
Responding" app — blocks a single `iter_elements()` call for **40 seconds on
first contact and ~10 seconds thereafter**, measured on this machine:

```
windows_matching   1.22 ms   -> 1 window    <- the cheap existence check SEES it
iter_elements     40,090 ms  -> 0 elements  <- 80x the 0.5s tick ceiling
repeat walks      10,100 ms  each           <- bounded, self-healing
```

This is not a future risk from OCR or network calls. It exists now, it is
**more likely than the failure already fixed** — apps hang far more often than
they vanish mid-tick — and the D020 ceiling test cannot catch it, because that
test uses an *absent* window and this needs a *hung* one. No tuning of the
synchronous path helps: UIA exposes no timeout to set.

### Why a watchdog cannot substitute

Verified, not assumed: `DestroyWindow` from a non-owning thread returns
`Access is denied` and the window survives; `PostMessage` needs the message
pump that a blocked tick is not running. A watchdog thread cannot clear the
overlay while the UI thread is stuck. The only fix is to stop blocking the UI
thread.

## 2. What changes, in one sentence

Perception moves to a worker thread that continuously observes the target and
publishes its latest result; the UI thread reads that result without ever
blocking, and keeps pumping messages and polling ESC no matter how slow
perception becomes.

## 3. Architecture

```
UI thread (owns the overlay window; must never block)
  every REFRESH_SECONDS:
      poll ESC / SPACE                      <- always responsive
      read PerceptionService.latest()       <- non-blocking, may be None
      GuidedTour.tick()
      pump Win32 messages

PerceptionService
  worker thread (owns its COM apartment and its Desktop())
      loop, throttled to roughly the tick rate:
          observation = walk the UI tree                <- may block ~10-40s
          publish into a SINGLE SLOT (overwrite)        <- timestamped
          heartbeat += 1
```

A single slot, not a queue. A queue drained to "take the newest and discard
the rest" is a depth-1 buffer with extra ceremony: no depth to tune, no
explicit discard, overwrite *is* the discard.

### Why not futures

Futures would answer "which request does this answer belong to". A
**timestamp on the published observation** answers the same question for this
project's purposes, and the staleness ladder needs that timestamp anyway. The
slot already has to hold a struct; one more field is not new machinery.
Futures would additionally force async control flow into `GuidedTour` and
change every injected fake.

## 4. The collaborator contract — and what does not change

`snapshotter()` and `grounder(step, index, elements)` keep today's shape. They
still get called, still return values; they read the published slot instead of
walking the tree, and never block.

**Every existing fake keeps working unchanged.** A fake that returns a value
simply reads as perception that is always fresh. That preserves the current
134-test suite rather than rewriting its test surface, which is the main
reason this shape was chosen over futures or a queue.

`GuidedTour` gains staleness handling. It gains no async machinery.

## 5. The staleness ladder

Measured from the **last confirmed-fresh observation** — never reset by a
single lucky tick — and debounced on the way back down, so a flaky
not-quite-hung app cannot flicker between states.

**"Confirmed-fresh" means the walk completed without raising, regardless of
how many elements it found.** A window that genuinely contains nothing
matchable is a successful observation, not a stale one; treating an empty
result as staleness would make a legitimately empty target look permanently
frozen.

| Age of the last fresh observation | Overlay shows |
|---|---|
| 0 – 1.5 s | the hint, unchanged (covers ordinary tick jitter; no false alarms) |
| 1.5 – 5 s | the same hint, visibly dimmed — "last known, unconfirmed" |
| 5 s + | nothing, until perception recovers |

Past ~5 s the odds the underlying UI has actually changed are high enough that
showing nothing beats showing an increasingly-likely-wrong ring. Recovery to
"fresh" requires a short debounced run of consecutive successful observations,
not one.

There is deliberately no "unchanged and unmarked for the whole freeze" state:
it contributes nothing the fresh and dimmed stages do not already cover more
honestly.

**This requires a second visual state in the overlay.** `set_hint` gains a
staleness parameter; it knows one ring colour today.

### Staleness is not the grounding grace period

They must not double-count:

- **staleness** governs *what is displayed* while observations are old;
- the existing 10 s **grounding grace** governs *when the tour gives up*
  because the target cannot be found at all.

An app that hangs for 10 s and recovers should dim, then clear, then return to
a fresh hint — not end the tour.

The two clocks only meet through what grounding is given. While observations
are merely **stale**, grounding keeps using the last one, so it keeps
succeeding and the grace clock never starts — the hint is still drawn, just
progressively dimmed. The grace clock starts only once a *new* observation
arrives that grounding genuinely fails against, which for a hung app means the
walk finally returned and found nothing.

So a hang produces: dim, clear, and — if the app is still unreadable when the
first empty observation lands — a further 10 s before the tour gives up. That
ordering is deliberate: display degrades quickly because a stale hint is
misleading, while giving up stays slow because a momentary hang should not end
a lesson.

## 6. The subtle correctness detail

`AWAITING_USER_ACTION` must observe a **later** moment than `OBSERVING`
(D019). Today that holds because it takes a fresh snapshot synchronously.

With a published slot it does not hold: if the worker has produced nothing
new, `AWAITING` reads back the *same* observation `OBSERVING` used.
Verification would compare identical states, conclude "nothing changed"
forever, and every tour would stall on its first step — exactly the failure
D019 exists to warn about, reintroduced by this change.

**Rule: `AWAITING_USER_ACTION` only verifies against an observation strictly
newer than `_before`.** If the slot has not advanced, that is not a failed
verification — it is *no verification attempt yet*, and the loop keeps
waiting. The timestamp from §3 is what makes this expressible.

## 7. Worker lifecycle

Two signals drive recovery, and a third is diagnostic only:

- **staleness clock** — time since the last confirmed-fresh observation
  detects "alive but not progressing" (already needed for §5, free here);
- **`Thread.is_alive()`**, checked per tick — distinguishes "the worker
  raised and exited" from "the worker is still working". Without it, a dead
  worker reports as merely stale forever;
- **heartbeat counter** — incremented every loop iteration regardless of
  whether observation succeeded, **logged when the restart-or-give-up policy
  fires and never an input to it**. It separates "blocked in a slow UIA call"
  from "alive but looping through silent failures" after the fact, without
  that distinction quietly influencing behaviour.

On detected death: log the cause and the heartbeat, **restart the worker
exactly once**. If it dies again, end the tour with an explicit reason rather
than sitting silently stuck.

A dead-but-undetected worker would be a regression dressed as a fix: the UI
thread stays responsive and ESC still works, so nothing *looks* wrong, while
the system silently stops guiding. That is harder to notice than today's
freeze, not easier.

### No cap on stuck requests is needed

The block is bounded and self-healing — measured at ~40 s first contact, ~10 s
steady state. A single long-lived worker blocks, times out, discards its stale
result and picks up the next observation. Threads cannot accumulate because no
replacement is ever spawned for a merely-slow worker; restart happens only on
detected death.

## 8. COM ownership

The worker calls `CoInitializeEx` and owns its `Desktop()` entirely. UIA
objects are apartment-bound; passing one across threads produces confusing
intermittent failures rather than a clean error.

Only frozen dataclasses of primitives cross the boundary — `Element`,
`Snapshot`, and the timestamp. No COM object ever does. The existing
perception layer already normalises to exactly these types, which is what
makes the boundary cheap.

## 9. Error handling

| Failure | Response |
|---|---|
| Target window absent | cheap check returns `[]` in ~0.1 ms; unchanged from today |
| Target window hung | worker blocks ~10 s; UI thread stays responsive; staleness ladder dims then clears |
| Target closes mid-walk | worker returns no elements; already covered by the existing `except` and its test |
| Worker raises and exits | `is_alive()` detects; restart once; then end the tour with a reason |
| Worker alive but never progressing | staleness clock detects; same policy |
| No observation yet at tour start | `latest()` returns `None`; the loop stays in OBSERVING rather than treating it as a failure |

## 10. Testing

The key new fixture is a **hung-window harness**: a child process that creates
a window and then stops pumping messages, reproducing the 40 s block
deterministically. Everything else follows from it.

- ESC stays responsive while the target is hung — the property this whole
  change exists for, and untestable before it.
- The staleness ladder transitions at its thresholds, driven by an injected
  clock so tests stay fast and deterministic.
- Recovery to fresh is debounced: one lucky observation does not clear the
  dimmed state.
- A worker that raises is detected, restarted once, and the tour ends with a
  reason on the second death.
- `AWAITING_USER_ACTION` never verifies against an observation that is not
  strictly newer than `_before` (§6).
- The existing 134 tests keep passing unchanged — if a fake needs editing,
  the contract in §4 was not preserved.

Per D018, the safety-critical properties are mutation-verified rather than
assumed: breaking the newer-than-`_before` rule, the `is_alive` check, and the
restart-once policy must each fail a test.

## 11. Out of scope

Perception tiers (OCR, VLM), the knowledge-base pipeline, and any change to
grounding or verification logic. This moves *where* perception runs and adds
the machinery to survive it being slow. What perception does is unchanged.

## 12. Open questions

- The staleness thresholds (1.5 s, 5 s) and the debounce length are judgement,
  not measurement. They should be revisited once the ladder has been seen
  against a real hanging app.
- Whether the worker's throttle should adapt when observations are
  consistently slower than the tick rate, rather than a fixed interval.

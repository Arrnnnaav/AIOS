# Attempt set 3 — three clean runs whose RECORDS cannot show they were a campaign

4 September 2026. These three runs passed every per-run gate: `1/1` steps,
UIA-only grounding, identical pack/intent/recipe digests, one application
build, one captured HWND, and all four timing landmarks in order. They were
rendered as `docs/evidence/add-slide-candidate-acceptance.md` and that document
was committed.

**They are excluded for a defect in the RECORD FORMAT, not in the runs.**

An independent D032 review reproduced a clean `3/3 passed` document from three
genuinely distinct, individually clean records drawn from two *different,
already-rejected* attempt sets. The renderer's only cross-record checks were a
shared HWND and shared artifact digests — both true of every record for this
candidate by construction, since it is one plugin on one machine. Nothing in a
record said which run it was or when it happened, so nothing distinguished a
real consecutive campaign from records cherry-picked out of the project's
history.

`RunRecord` now stamps a `run_id` minted at capture and the wall-clock instant
the run began, and the renderer requires distinct ids, start times in order,
and that no rejected run committed under `excluded/` falls between the first
accepted run and the last. These three records predate that stamping, so they
cannot satisfy it.

Keeping them and waiving the new check would have made it decorative on its
first use — the failure mode D031 names, an invariant that correlates with the
property rather than implying it. The rendered evidence document was removed
rather than left in place, because a document that cannot be re-derived from
its records is stale by definition and adoption binds the rendered evidence.

Nothing here says the workflow failed. It says the evidence pipeline could not
prove what the operator saw, which is a different and fixable problem. A fresh
set of three runs on the stamping harness closes it.

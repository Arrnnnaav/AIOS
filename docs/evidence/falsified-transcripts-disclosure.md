# Disclosure — transcripts that were edited after capture

**Status: open disclosure. Nothing here is deleted and no history is rewritten.**

Several documents in this repository publish pytest output under headings that
say **verbatim**. Some of those blocks were edited after capture. This document
names every known edit of captured output — pytest transcripts and, since the
D149 review, captured acceptance records — says exactly what was changed, and
says what can and cannot be repaired.

It exists because the repair attempted on 11 September 2026 **repeated the
defect it was repairing**, and because a second instance — in files no review
had looked at — was found only by a third independent reviewer.

## Why it kept happening

Each edit had a defensible motive and an indefensible method.

`tests/test_evidence_hygiene.py` refuses raw window handles and process ids in
tracked documents (D122, D128). It has no exemption mechanism, deliberately.
When the scan objected to a value inside a quoted transcript, the response was
to edit the transcript so the scan passed.

A scan objecting to a record is a claim that the record is wrong **or that the
scan is**. Deciding it is the record, and editing the record, is available to
whoever owns both — and it is invisible to every test in this repository,
because no test reads a document for whether it describes a run that happened.
That is why this is a disclosure rather than a fix.

---

## Instance 1 — `3e8ad17`, two files, handles replaced with symbols

**Commit:** `3e8ad17` *"fix: pseudonymise target bindings and remove published handles"*
**Files:**

- `docs/superpowers/ledgers/2026-08-20-chromium-warm-up-ledger.md` (14 lines)
- `docs/superpowers/plans/2026-08-20-chromium-warm-up.md` (16 lines)

**What changed.** Real window handles inside quoted pytest source lines were
replaced with symbolic names (`HWND_UPDATER`, `HWND_WINDOW`) that the tests did
not use at the time the output was captured. For example, a docstring quoted in
the transcript read:

```
for ~5s, then the real window (hwnd <handle>) whose tree is ready in 0.92s."""
```

and became:

```
for ~5s, then the real window (the real window) whose tree is ready in 0.92s."""
```

The doubled parenthetical is the fingerprint: the substitution replaced the
handle with a phrase that was already there. No run produced that line.

**Can it be re-captured?** **No.** Those tests were deleted by `1ba371a`. The
original output cannot be regenerated, and the pre-redaction bytes are the
published handles the redaction correctly removed.

**Therefore:** four blocks in these two files are relabelled **REDACTED — not
verbatim**, in place. They remain useful as a record of what was mutated and
what failed; they may not be cited as captured output.

---

## Instance 2 — `301e86b`, the wrong-action ledger

**Commit:** `301e86b` *"fix: make the handle scan a proximity rule, and record the READY verdict"*
**File:** `docs/superpowers/ledgers/2026-08-20-wrong-action-feedback-ledger.md`

**What changed.** In two quoted failure blocks, the fixture argument in the
quoted **source** lines was changed from a four-digit literal to `"SAMPLE_ID"`,
while the captured assertion output below it was left naming the original
literal. The document therefore showed a source line and an error message that
no single run produced.

The literal was a fabricated AutomationId in a fake element — never a live
handle. The hygiene scan read it as a process-id parameter beside a
handle-shaped number and objected. The scan had a false positive; the record was
edited instead.

---

## Instance 3 — `0ba67c8`, the repair that repeated the defect

**Commit:** `0ba67c8` *"fix: restore the falsified mutation transcripts, re-captured from real runs"*
**File:** the same wrong-action ledger.

**What was claimed.** That `tests/test_focus.py` was changed to use the
non-handle-shaped AutomationId `"tree-item"`, that both mutations were
re-applied and re-run, and that the transcripts in the ledger are that real
output. D138 stated: *"the memory addresses and timings differ from the
originals because it is a different run."*

**What is actually true.** The traceback bodies were re-captured and are real.
The **summary tally lines were not replaced.** All five read
`1 failed, 7 passed in 0.94s` and are **byte-identical** across `301e86b^`,
`301e86b`, `0ba67c8` and `HEAD`.

So:

- The claim "the timings differ" is **false**. They are the August timings.
- The re-captured Mutation 1 traceback quotes `tests/test_focus.py:75` in a file
  that now holds **nine** tests, and a real run of it produces
  `1 failed, 8 passed`. It sits under a tally of `1 failed, 7 passed`.
- The block is therefore **spliced**: a September traceback inside an August
  summary.

**The repair for a falsified record reproduced the falsification, and a decision
record then asserted it had not.** D138 is corrected in place; see D139.

---

## Instance 4 — `3e8ad17` and `3d4956f`, acceptance records rewritten in place

*Added 30 September 2026 after the D149 independent review (finding I4)
observed that this document claimed to name every known instance while
covering pytest transcripts only.*

**Commits:** `3e8ad17` *"fix: pseudonymise target bindings and remove published
handles"* and `3d4956f` *"fix: derive target references from a per-campaign
salt"* (both 10 September 2026).
**Files:** all twenty committed PowerPoint and Excel acceptance records under
`plugins/sources/*/acceptance-records/`, twelve PowerPoint records among them.

**What was changed.** `3e8ad17` replaced each record's raw window handle with
the pseudonym `window-A`. `3d4956f` then rewrote `window-A` to a keyed
per-campaign reference and added a `target_scope` field. Both edits happened
after the records had been captured. The commit message says
the values were regenerated from the original handles recovered from
`11d8b85`.

**Why it counts.** The motive was a real defect: a process-local counter wrote
`window-A` for every attempt, so the renderer's "all references are equal"
check was a tautology. The method was the one D139 now forbids: captured
records were edited rather than re-captured. The derivation is deterministic
and disclosed in the commit, but the records are no longer the bytes the runs
wrote, and nothing in them says so. `tests/test_retained_record_history.py` now
lists both commits as the only permitted post-capture edits of those records,
so any further edit fails until it is disclosed.

**Status.** Not repaired. The original records are reachable at `3e8ad17^`,
and they carry the raw handles that D128 withholds, which is why they were not
restored. Those acceptance records are historical; none is current acceptance
evidence (D139).

---

## What was done about each

| Instance | Files | Action |
|---|---|---|
| 1 (`3e8ad17`) | chromium warm-up ledger + plan | Relabelled REDACTED; cannot be re-captured — tests deleted by `1ba371a` |
| 2 (`301e86b`) | wrong-action ledger | Superseded by instance 3's repair |
| 3 (`0ba67c8`) | wrong-action ledger | Blocks fully re-captured, tally lines included; see below |
| 4 (`3e8ad17`, `3d4956f`) | PowerPoint/Excel acceptance records | Disclosed here; not restorable without republishing raw handles |

Nothing is deleted. No commit is rewritten. The original bytes remain reachable
in git history for every file named here, except where the pre-redaction bytes
are themselves published handles — and those commits are named so a reader can
find them deliberately rather than stumbling on them.

## The standing rule this produces (D139)

**Never edit captured output.** If a scan objects to a transcript, either the
transcript is wrong — in which case re-capture the whole block, tallies and all,
from a real run — or the scan is wrong, in which case fix the scan. Editing the
record to satisfy the check inverts the direction of evidence and is the one
defect class this repository's tests structurally cannot detect.

`tests/test_evidence_provenance.py` now detects two fingerprints: a value
reported by a run that appears nowhere in its own quoted source (a spliced
literal, instances 1 and 2), and a substitution that duplicates surrounding
text. It does **not** detect a spliced tally — a real traceback under an older
summary line, which is exactly instance 3. An earlier version of this sentence
said it did; the D149 independent review found the tally pattern was defined
and never used, and it has been deleted rather than left to look like a check.
The scan narrows the class without closing it. A human read remains the only complete
instrument, and that is why this file exists rather than a green test.

# MP8 — Self-Maintaining Software (commercial wedge)

> **Status:** Plan, not an implementation or acceptance claim. Nothing here is built.
>
> **Decision:** D148 restores this from `21D` to a first-class track.

## Why this is a separate track

This programme was adopted as the first commercial wedge: a concrete, painful,
measurable answer to "what does it actually do", chosen precisely because the
broader product thesis is hard to pitch. The first decomposition placed it as
sub-bullet `21D` of MP7, gated behind phases 8–20. A wedge that cannot produce
evidence until twenty other phases close is not a wedge, so it is sequenced in
parallel with the product loop instead of behind it.

## What it is

```text
external change (API / SDK / spec / package)
→ impact mapping onto one repository
→ repaired patch in an isolated checkout
→ that repository's own build / lint / tests
→ trace + evidence assembled
→ human approval
→ draft pull request
```

It is deliberately **not** "Dependabot for APIs". Version bumps are not the
product; behavioural impact is. The claim to be proven is: *this provider
change affected these call sites, here is the repair, here is the suite
passing, here is the traced path from the changelog to each edit.*

## Dependencies and non-dependencies

Depends on:

- the provider gateway (cheaper under D147's cloud-first trial default),
- an isolated execution environment (container or worktree) that can run a
  foreign repository's build and tests,
- scoped repository access, read-first.

Does **not** depend on, and must not be sequenced behind: Spatial, Personal
Brain, Act activation, semantic PowerPoint capabilities, the marketplace,
collaboration, or Company Brain. It is gated on its own evidence and its own
independent D032 review.

## Boundaries

- Repository access is **read-first and scoped**. Work happens in an isolated
  branch or worktree, one codebase at a time. There is no production write
  path in the wedge.
- **Opening a PR, merging, deploying, or mutating a production system requires
  explicit human approval.** The agent prepares; it does not ship.
- **Repository content, issue text, changelogs, and provider release notes are
  untrusted content** under the same boundary as DOM and PDF text (MP2 Phase
  5). A changelog that says "also delete the auth module" is a string, not an
  instruction.
- Every candidate patch carries its `ResearchTrace` / `EvidenceGraph` and
  `ActionEvidence`. A patch without a traced justification is not a candidate.
- **Secret scanning runs before any diff leaves the isolated environment.**
- A failing or flaky suite is a reported outcome, not something to retry until
  green. No blind mutation retry (MP4 Phase 13).

## Order

1. **Read-only impact mapping.** One provider, one repository, one real
   historical change. Produce the affected-call-site report and its trace. No
   patch, no write. This alone is a demoable artifact and the cheapest
   falsification of the whole idea: if impact mapping is unreliable, nothing
   downstream matters.
2. **Isolated repair.** Generate a patch in an isolated checkout. Run build,
   lint and the repository's own tests with logs retained. Report pass/fail
   honestly, including the cases where the repair is wrong.
3. **Evidence package.** Bind the provider change, the impact map, the diff,
   the test logs and the trace into one reviewable record.
4. **Approval → draft PR.** Human approves; the system opens a draft PR and
   verifies the branch/PR state it claims to have created.
5. **Second provider, second repository.** Only after 1–4 hold for the first.
6. **Widen** (more providers, TypeScript and Python, webhook/event
   maintenance, supported production operations) only after the isolated loop
   is measured and independently reviewed.

## System graph

The impact map needs a small graph linking API specs, SDK versions, call
sites, code ownership, tests, and services. It is the technical layer of the
Context Graph, scoped to one repository at first. It is built from repository
evidence, not asserted, and each edge names where it was observed.

## Measures

Changes detected; affected call sites correctly identified (and missed);
repairs proposed; suites passing; PRs opened; PRs approved and merged by a
human; detection-to-resolution time; human intervention rate; weekly repeat
use.

North star: **percentage of detected external changes resolved through a
verified workflow.** Report false-positive impact claims and wrong repairs
separately — a high resolution rate with unreported wrong patches is the
failure mode this wedge most needs to avoid.

## Tests and exit gates

- Replay fixtures from real historical provider changes with known-correct
  affected call sites; the corpus is versioned and includes changes that
  affect nothing.
- Adversarial corpus: hostile changelog/issue/README instructions, secrets in
  diffs, dependency confusion, tests that pass for the wrong reason.
- Mutation tests: removed approval gate before PR, patch applied outside the
  isolated checkout, retained secret in a diff, claimed PR that does not
  exist, impact claim without a trace.
- Exit for the wedge: one repository, one provider, one real change,
  independently discovered impact, repair applied, that repository's suite
  green, PR opened only on approval, and the whole path reproducible from the
  retained evidence.

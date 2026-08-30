# Plugin Platform v1 activation review

This document preserves the independent D032 review of the immutable Excel
activation commit. It is a review record, not adoption evidence and not a
replacement for the exact human-run records.

- Reviewed commit:
  `a764c48e306f5587a7ae72d22bf96b6c82d862d9`
- Reviewer id: `codex-d032-jason`
- Review date: 2026-08-30
- Disposition: approved
- Focused verification: 23 passed

The reviewer independently verified:

- the Excel bundle and manifest SHA-256 values match the pinned bundle index;
- the Ed25519 signature verifies with `ghostcursor-release-2026-2`, while the
  earlier release key does not verify the bundle;
- the repository tracks the new public key and no private key;
- the bundle is data-only (`adapter_api: null`) and contains no executable
  Python;
- both activation records bind Excel `16.0.20326.20112`, the exact evidence
  digest, review commit `381d97f5f376ee586260eb4430595fcff1e2668e`,
  reviewer `codex-d032-heisenberg`, and adoption timestamp
  `2026-08-30T12:44:05Z`;
- a fresh plugin store loads signed Excel, Synthetic, and VS Code plugins as
  `enabled_compatible`;
- both Excel workflows authorize from the signed merged catalog; and
- no Excel-specific production Python participates in the activation.

The approved activation commit intentionally predates this durable review
record. Its immutable hash identifies exactly what was reviewed; this later
record does not alter the signed bundle, adoption bytes, or reviewed tree.

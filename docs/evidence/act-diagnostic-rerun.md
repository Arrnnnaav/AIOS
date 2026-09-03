# 255/255 re-run on the current adapter bytes

**Date:** 4 September 2026
**Why:** the adapter changed twice since Phase A — view-follow, then region
reporting — so Phase A's 255/255 no longer described the shipped bytes.

**Bundle:** `3fb104f62c6f4974f1d0d4a7882ec2762b3c5e5557546efe0879ad3152b7e80a`
**Manifest:** `5ba2cdc3d2070302e30b91ab31d3de3b364e83ca342b4e15d3b59e0ba262f13b`
**Plan:** `build-investor-deck-v1`, digest `84e39d0d…` (unchanged)

Bytes under test:

| File | sha256 |
|---|---|
| `powerpoint_adapter.py` | `98c9ffa24d0011812041fea2083f4b6b9ffbffed322879e558375af275482157` |
| `powerpoint_verifier.py` | `20bd51e1d949ab441f7da129ab3293b7701d5589534e9f7508ef1177627e89bb` |
| `powerpoint_live_verifier.py` | `f9b64faedc8ecf08c8e451819429f203b8dda8042f27ee0efd57b5bb41a697c9` |
| `uia_adapter.py` | `0752ebc2bef68f69f4dfc3ced66fc38eb71f58d08e2edc6c0fe6cca53205c465` |

## Results — three consecutive runs

| Run | Classifications | Nodes | Verifier total | Verifier max | Published |
|---|---|---|---|---|---|
| 01 | `{"verified": 255}` | 255 | 36.815 s | 0.188 s | 94 378 B |
| 02 | `{"verified": 255}` | 255 | 36.194 s | 0.172 s | 94 379 B |
| 03 | `{"verified": 255}` | 255 | 35.673 s | 0.187 s | 94 346 B |

No failing node in any run. Every node classified `verified`; nothing fell
into `never_written`, `wrong_part`, `bytes_moved_during_read`, `unreadable`,
`package_changed_during_verification` or `written_and_verified_false`.

Deck: 10 slides, 191 shapes.

All three published atomically through the staging path, and the only staging
file left behind afterwards is `3bcd21901879-stopped-deck.pptx` — the
deliberately stopped run from the interruption evidence, still carrying its
`.incomplete.json` marker.

## A Phase E budget this closes

The verifier spawn-to-response time was on the unmeasured list. It is now
measured, over 765 verifier invocations across three runs:

- **max 0.188 s**
- mean ≈ 0.142 s (36.2 s over 255 calls)

This also bounds a question left open by the interruption evidence: *how late
can a Stop be observed on a node that already acted?* After a dispatch the
verification runs to completion by design, and that completion takes at most
0.188 s on this build.

## Published digests differ between runs — deliberately not a criterion

94 378, 94 379 and 94 346 bytes, with three different digests, from identical
plan bytes and identical adapter bytes.

That is expected of OOXML: a `.pptx` embeds creation timestamps and revision
identifiers, so byte-identical output across runs is not achievable and must
**not** be adopted as an acceptance criterion. What is reproducible is the
verified node count, the slide and shape count, and the classification set.

## What this is not

- **Not acceptance evidence.** The signing key is the ephemeral development
  pair. Three clean diagnostic runs say the adapter is stable on these bytes;
  the counted 3/3 acceptance campaign requires the external release key and a
  D032 review that has not happened.
- Quick Build only. Watch Build and the region overlay were exercised
  separately and are not part of these runs, which were kept uninstrumented
  apart from `--diagnostics` so the measurement is of the adapter and not of
  the presentation layer.

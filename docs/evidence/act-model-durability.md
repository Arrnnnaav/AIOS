# Act architecture model-durability gate

Date: 2026-09-01 (Asia/Calcutta)

Scope: post-change recertification after adding the signed action-plan parser,
API-v2 adapter protocol, and Act manager/CLI surfaces. Act does not grant the
model operation authority; the gate is still required because parser and
adapter policy changed.

Both reports used frozen, owner-reviewed dataset 1.0.0 and were run with the
interactive lane enabled. No failed or discarded report occurred between the
two passes.

| Pass | Report SHA-256 | Trusted | Raw intent | Exact supported | Unsupported launches | Interactive |
|---|---|---:|---:|---:|---:|---:|
| 1 | `402b671f71d9c2d53753b9360b96df15728b643a0ab4b0ab598aaeab3d238222` | yes | 27/30 | 100% | 0 | passed |
| 2 | `efe3fbd8efad1abb221d9c5720194a9ce939e6622a10d8d062d2bd3d71f47043` | yes | 27/30 | 100% | 0 | passed |

Model: `qwen3:4b-instruct`

Ollama version: `0.31.1`

Model manifest SHA-256:
`0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`

Latency was diagnostic rather than a hard acceptance claim. Pass 1 median/max
was 2937.0515/9721.222 ms; pass 2 was 2853.174/3730.125 ms.

The ignored raw reports remain under `.artifacts/model-evaluation/`. This
reviewed summary records only the frozen-dataset state, model identity, hard
gate outcomes, and report digests.

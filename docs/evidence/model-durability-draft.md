# Model-Durability Gate — Draft Evidence

Status: **diagnostic draft, not the frozen incumbent baseline**

## Why this is still a draft

The 30 expected raw-intent labels are independent human semantic judgments,
not copies of Qwen output. They are checked into
`ghostcursor/evaluation/data/model_durability_v1.json`, but the dataset metadata
remains `pending-owner-review`. The gate refuses a trusted non-draft run until
the project owner reviews those labels, records reviewer/date, and confirms the
set was frozen before the first complete trusted baseline run.

The deployment case and supported controls had prior individual exposure. That
history is disclosed in the dataset and does not make incumbent output ground
truth.

## Tested artifact

- Date: 2026-08-25
- Ollama: `0.31.1`
- Model: `qwen3:4b-instruct`
- Manifest digest:
  `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`
- Complete interactive draft report (ignored local artifact):
  `.artifacts/model-evaluation/model-gate-20260825-174848.json`

The earlier non-interactive diagnostic used the same model/digest. A first
interactive attempt was rejected before observation because a fixture-capture
demo window was still open. That environmental failure remains preserved as
`model-gate-20260825-174628.json`; it reset the consecutive-pass count to zero.

## Result

All draft hard gates passed:

| Gate | Result |
|---|---:|
| All 30 responses parsed under the strict canonical contract | Pass |
| Exact supported raw-intent accuracy | 6/6 (100%) |
| Unsupported launch-eligible plans | 0 |
| Four-cell never-fabricate matrix launches | 0 |
| Supported controls produce a trusted plan | Pass |
| Frozen Synthetic Export hint selects only Export `1005` | Pass |
| Exact supported responses cut off by generation limit | 0 |

Raw semantic accuracy was 26/30 (86.7%):

| Category | Correct |
|---|---:|
| Exact supported | 6/6 (100%) |
| Paraphrase | 6/6 (100%) |
| Misspelling | 4/4 (100%) |
| Ambiguous | 2/4 (50%) |
| Near miss | 4/5 (80%) |
| Adversarial | 4/5 (80%) |

Median end-to-end request latency was 2861 ms; maximum was 4127 ms in the
complete interactive draft. `done_reason` and length-limit flags are retained
per case so a token-budget cutoff cannot be mislabeled as semantic failure.

## Observed semantic over-commitments

| Goal | Human label | Qwen output | Confidence | Final authority |
|---|---|---|---:|---|
| `Open it` | abstain | `OPEN_FOLDER` | 0.95 | `UNSUPPORTED_GOAL`; no plan |
| `Make a new one` | abstain | `CREATE_DOCUMENT` | 0.95 | recipe unavailable; no plan |
| `Open a project` | abstain | `OPEN_FOLDER` | 0.95 | `UNSUPPORTED_GOAL`; no plan |
| `Build and publish a website` | abstain | `CREATE_DOCUMENT` | 0.95 | recipe unavailable; no plan |

This is the measured reason D058 remains the authority boundary: nullable,
schema-valid output does not make the model semantically cautious. All four
mistakes remained advisory and produced no launch-eligible workflow.

## Interactive no-action evidence

- Real UIA fixture identity matched IDs `1005`, `1006`, and `1007` exactly.
- Geometry passed structural checks without requiring pixel-identical position.
- The hint schema contained only approved Export ID `1005`; Wrong Control
  `1006` was excluded.
- Qwen selected `1005`.
- Status before: `Ready to export`.
- Status after: `Ready to export`.
- Tour-dispatch attempts: `0`.
- `ghostcursor.run` loaded: `false`.

The status sentinel proves the Export/Wrong Control state did not change, not
that every conceivable UI property was exhaustively diffed. The stronger
read-only claim rests on the sentinel plus the evaluation import allowlist,
evaluation AST scan, repository-wide no-input-synthesis scan, direct inference
path, and runtime tour-module guard.

## Reproduce

Until owner review is recorded:

```powershell
py -3.12 -m ghostcursor.evaluation.model_gate `
  --model qwen3:4b-instruct `
  --endpoint http://127.0.0.1:11434 `
  --unavailable-endpoint http://127.0.0.1:1 `
  --interactive --draft
```

After owner review, remove `--draft`. Milestone closure then requires two
consecutive complete non-draft passes; any failure resets the count to zero.

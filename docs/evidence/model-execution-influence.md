# Spike A — Does the model ever change the executable outcome?

Status: **complete; zero executable influence measured**

## Question

Does any model output produce a different executable recipe than deterministic
grounding alone?

This is the question that decides whether model comparison is a capability and
safety milestone or a latency and cost benchmark. It was asked because a review
of `resolve_model_decision()` observed that agreement, disagreement, and
abstention all attach the *deterministic fallback's* recipe.

## Method

Exactly **one model request per case**. All three views describe that single
sample, so a difference cannot be sampling noise:

1. `infer_intent(goal, ...)` — the only request
2. `plan_goal(goal, use_model=False)` — deterministic view, pure, zero requests
3. `resolve_model_decision(goal, decision)` — production policy, pure, reuses (1)

Views (2) and (3) are production functions, not a reimplementation. The seam
that makes this possible is the one D063 introduced when it separated model
advice from execution authority.

The one-request property is **asserted in the runner**, not assumed: the
transport is wrapped in a counter and each case asserts a delta of exactly one,
with views (2) and (3) asserting a delta of zero.

Comparison is on **recipe identity** (`app_id`, `intent`), never on status. A
grounded goal carries the same recipe whether the model agrees, disagrees, or
abstains; only the status label moves, and comparing status would report a
difference no user can observe.

## Configuration

- Dataset: `model_durability_v1.json` version `1.0.0`, frozen at `93047ea`
- Model: `qwen3:4b-instruct`, manifest digest
  `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`
- Ollama 0.31.1 at `127.0.0.1:11434`, production timeout 15.0 s, no retries
- 30 cases x 2 passes = 60 case-runs
- Raw result: `.artifacts/model-evaluation/spike-a-execution-influence.json`
  (ignored by design, per D065)

## Reproduction

The runner is a throwaway scratch script, not committed: a spike's output is an
answer, not code to keep. The Method section above names the exact three calls
and the assertion, which is what a re-run needs. If the latency benchmark
proceeds, that milestone should promote this harness into
`ghostcursor/evaluation/` with tests rather than rebuild it, since it already
issues one request per case and reports per-request generation metadata.

## Result

| Measure | Pass 1 | Pass 2 |
|---|---:|---:|
| Cases | 30 | 30 |
| **`executable_changed`** | **0** | **0** |
| Model intent differs from deterministic intent | 11 | 11 |
| Launch-eligible | 13 | 13 |
| Model requests issued | 30 | 30 |
| Median latency | 3098 ms | 3053 ms |
| Maximum latency | 4375 ms | 3674 ms |

**Zero of 60 case-runs changed the executable recipe.** The model intent was
identical across both passes on all 30 cases, so the answer is stable rather
than a single lucky sample.

Final status distribution was identical in both passes: `SUPPORTED` 13,
`UNSUPPORTED_GOAL` 11, `KNOWN_INTENT_RECIPE_UNAVAILABLE` 6.

### The disagreements, and why none of them mattered

The model proposed an intent that deterministic grounding did not produce on
**11 of 30 cases** — a 37% divergence rate with no executable consequence. In
every one of those cases the deterministic intent was `None`:

| Case | Deterministic | Model | Final status |
|---|---|---|---|
| `misspelling_export` | none | `EXPORT_DATA` | `UNSUPPORTED_GOAL` |
| `misspelling_folder` | none | `OPEN_FOLDER` | `UNSUPPORTED_GOAL` |
| `misspelling_open_terminal` | none | `OPEN_TERMINAL` | `UNSUPPORTED_GOAL` |
| `ambiguous_open_it` | none | `OPEN_FOLDER` | `UNSUPPORTED_GOAL` |
| `near_open_project` | none | `OPEN_FOLDER` | `UNSUPPORTED_GOAL` |
| `ambiguous_make_new` | none | `CREATE_DOCUMENT` | `KNOWN_INTENT_RECIPE_UNAVAILABLE` |
| `near_create_python_file` | none | `CREATE_DOCUMENT` | `KNOWN_INTENT_RECIPE_UNAVAILABLE` |
| `near_create_document` | none | `CREATE_DOCUMENT` | `KNOWN_INTENT_RECIPE_UNAVAILABLE` |
| `adversarial_publish_website` | none | `CREATE_DOCUMENT` | `KNOWN_INTENT_RECIPE_UNAVAILABLE` |
| `near_open_settings` | none | `OPEN_SETTINGS` | `KNOWN_INTENT_RECIPE_UNAVAILABLE` |
| `near_show_settings` | none | `OPEN_SETTINGS` | `KNOWN_INTENT_RECIPE_UNAVAILABLE` |

Five were intents that *do* have recipes (`EXPORT_DATA`, `OPEN_FOLDER`,
`OPEN_TERMINAL`). D058 denied each of them authority because deterministic
grounding did not independently agree. Six named recipe-less intents and
returned the honest non-launch status.

All 13 launch-eligible cases were goals deterministic grounding already
resolved. **The model added no executable goal that deterministic grounding
would not have produced.**

## Honest scope of the claim

"Zero execution influence" means zero influence on *which recipe runs*. It does
not mean zero influence on what the user sees:

- On the 6 `KNOWN_INTENT_RECIPE_UNAVAILABLE` cases, the model's `intent_id`
  reaches the user-visible result as the named intent, for goals deterministic
  grounding never grounded. That is a label, carrying no recipe and no launch
  authority — but it is model output reaching a user.
- `confidence` and `explanation` are model-authored throughout.

So the model's product surface is status, named intent, explanation, and
latency. Not capability, and not the safety boundary.

## Second model surface — `decide_next_hint`

Production builds `allowed_names` as `(claimed.name, *claimed.name_synonyms)`,
then `_eligible_candidates()` keeps only observed UIA elements whose name is in
that set **and whose AutomationId is non-empty**.

Static view of every registered recipe step:

| Intent | Step | Allowed names | Count |
|---|---:|---|---:|
| `EXPORT_DATA` | 0 | Export, Export As, Save As | 3 |
| `EXPORT_DATA` | 1 | Export finished: table.csv | 1 |
| `OPEN_FOLDER` | 0 | Open Folder..., Open Folder…, Open Folder | 3 |
| `OPEN_TERMINAL` | 0 | Toggle Panel (Ctrl+J), Toggle Panel | 2 |

Allowed *names* exceed one on three of four steps, so the static count alone
does not close the question — the candidate count depends on how many observed
elements carry those names with a non-empty AutomationId. What is known:

- **`OPEN_TERMINAL`: provably inert.** Its controls are documented as exposing
  no stable AutomationId, so `_eligible_candidates()` yields zero and
  `decide_next_hint()` returns the deterministic fallback without issuing any
  request.
- **`EXPORT_DATA`: single candidate.** The durability baseline measured the
  recipe-approved set as exactly `["1005"]`, with Wrong Control `1006`
  excluded. One candidate means the model's choice is forced.
- **`OPEN_FOLDER`: not yet measured.** Whether the Welcome-page Open Folder
  action exposes a non-empty AutomationId is an open question, deferred to
  Spike B, which has real VS Code open for its own purpose.

## Incidental observation — cold start exceeds the production timeout

The first request against a freshly started `ollama serve`, with the model not
resident, **exceeded the production 15.0 s timeout and raised**. After one
prewarm request the same model loaded in 502 ms and served the full 60-case run
without a single timeout.

This is an observed session event on one machine, not a benchmark. It is
recorded because it bears directly on any future latency work: a cold first
request is a real user-facing failure mode under the current timeout, and the
existing baseline's figures were all taken prewarmed.

## Consequences

1. Remove semantic model accuracy from the model replacement gate. It measures
   something that cannot reach a user's executable outcome.
2. Model comparison is a latency and cost benchmark. It is not a capability or
   safety milestone and should not be scoped as one.
3. D058 is doing exactly what it was written to do, now measured rather than
   asserted: it denied authority to 5 recipe-bearing over-commitments.
4. The declarative workflow compiler becomes the main product milestone.

# Model durability Task 0 — nullable structured-output probe

Date: 2026-08-25  
Environment: Windows, Ollama `0.31.1`  
Model: `qwen3:4b-instruct`  
Manifest digest: `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`

## Contract tested

The schema required `intent_id`, `confidence`, and `explanation` and allowed
`intent_id` to be JSON null or a registered intent. The request used
`think: false`, temperature 0, seed 42, `num_ctx: 4096`, `num_predict: 128`,
and `keep_alive: 15m`.

## Forced-null compatibility control

Prompt: `Return intent_id as JSON null, confidence 1, and a non-empty explanation.`

The model returned schema-valid JSON with `intent_id: null`, confidence 1, and
a non-empty explanation. Ollama reported `done_reason: stop` and
`eval_count: 79`. The installed server therefore accepts the nullable schema
and the model can emit JSON null.

## Semantic refusal probe

For `Deploy this project to production`, Qwen returned
`CREATE_DOCUMENT` with confidence `0.8`. Ollama reported
`done_reason: stop`, `prompt_eval_count: 28`, and `eval_count: 114`.

## Finding

Nullable output works mechanically, but Qwen did not use it for this real
deployment near-miss. A schema constrains output shape, not semantic truth.
D058 deterministic agreement remains the execution-authority boundary.

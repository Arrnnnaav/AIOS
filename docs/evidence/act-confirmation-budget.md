# Confirmation-to-request budget

Derived from three independent diagnostic runs; this is not acceptance evidence.

- Operation: `powerpoint.new_slide_uia`
- PowerPoint version: `16.0.20326.20132`
- Selector digest: `0721bf8cb76fa343bdccf3c13a8dca5364fc4d2a62f7b3e9a6a73178bd78445f`
- Margin over p99: `2.0x` (chosen headroom)

| Measurement | Samples | p99 (ms) | Max (ms) | Derived deadline (ms) |
|---|---:|---:|---:|---:|
| Confirmation round trip | 180 | 640.000 | 640.000 | **1280** |
| Confirmation to request write | 180 | 16.000 | 16.000 | **32** |

## Source records

- `confirmation-budget-live-20260914.json` — SHA-256 `f8b1f9fa54c7395853331ad2fa8318e75fc4040e287b8e407b6bdb7440b8b9d8`
- `confirmation-budget-live-20260914-run-2b.json` — SHA-256 `b2163a946e8bd3bd4a1b9be6c58c4b4355b0aed88456f9db5fa33b38ac1f74b4`
- `confirmation-budget-live-20260914-run-3.json` — SHA-256 `ae2bce09baee6ea6b2a623814b4bcb6c9dcb9621e5e8be9fc056f6c88173adb2`

## Excluded records

Retained and not used in the derivation, because the run did not complete.
A record keeps only its failure class and the sample it stopped at; the
refusal code and detail are not retained, so the cause is not recorded.

- `confirmation-budget-live-20260914-run-2.json` — SHA-256 `78d5bbe3f31ea83d3981644b101040ac2e56b1cc9b233d45cfa840e36f0d1f45` — `NodeRefused` at sample 24, 23/60 completed

The production policy must be derived from these values and refuse when either signed deadline is exceeded.

# Benchmark summary — Deterministic Fake Router / fake-router-v1

- promptVersion: `router-v3`
- registryVersion: `yaml-registry-v1`
- schemaVersion: `reference-v1`
- scenarios: 30
- outcome_accuracy: 1.000
- outcome_accuracy (excl provider errors): 1.0
- provider_errors: 0 (0.000)
- vision scenarios: 6 acc=1.0
- text scenarios: 24 acc=1.0
- intent_accuracy: 1.0
- false_route_rate: 0.0
- response_false_positive_rate: 0.0
- fallback_rate: 0.200
- pre_router avg/p50/p95 ms: 0.0019120311157570945 / 0.0016249250620603561 / 0.003291061148047447
- T0 (normalize+policy+pre_router) avg/p50/p95 ms: 0.06 / 0.02 / 0.25
- T1 (router/LLM) avg/p50/p95 ms: 0.02 / 0.02 / 0.03
- E2E total avg/p50/p95 ms: 0.09 / 0.06 / 0.25
- clarify→route rate: 0.5

## Latency by actual outcome

### E2E total

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 5 | 0.06 | 0.06 | 0.08 |
| FALLBACK | 6 | 0.05 | 0.05 | 0.06 |
| REJECT | 3 | 0.01 | 0.01 | 0.01 |
| RESPONSE | 5 | 0.27 | 0.06 | 0.99 |
| ROUTE | 11 | 0.06 | 0.06 | 0.09 |

### T0 (normalize + policy + pre_router)

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 5 | 0.02 | 0.02 | 0.02 |
| FALLBACK | 6 | 0.03 | 0.02 | 0.03 |
| REJECT | 3 | 0.01 | 0.01 | 0.01 |
| RESPONSE | 5 | 0.26 | 0.03 | 0.99 |
| ROUTE | 11 | 0.02 | 0.02 | 0.03 |

### T1 (router / LLM only)

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 5 | 0.02 | 0.02 | 0.02 |
| FALLBACK | 6 | 0.02 | 0.02 | 0.03 |
| RESPONSE | 2 | 0.03 | 0.02 | 0.03 |
| ROUTE | 11 | 0.02 | 0.02 | 0.05 |

## Per-stage average / p50 / p95 (ms)

| Stage | avg | p50 | p95 |
| --- | ---: | ---: | ---: |
| `normalize` | 0.026 | 0.011 | 0.020 |
| `policy_gate` | 0.034 | 0.009 | 0.240 |
| `pre_router` | 0.002 | 0.002 | 0.003 |
| `router` | 0.023 | 0.022 | 0.032 |
| `validator` | 0.012 | 0.011 | 0.031 |

Use this report to propose Overview §3.4 release thresholds (M5).

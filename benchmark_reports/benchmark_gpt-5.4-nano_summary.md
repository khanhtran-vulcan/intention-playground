# Benchmark summary — OpenAI Structured Router / gpt-5.4-nano

- promptVersion: `router-v3`
- registryVersion: `yaml-registry-v1`
- schemaVersion: `reference-v1`
- scenarios: 30
- outcome_accuracy: 0.833
- outcome_accuracy (excl provider errors): 0.8333333333333334
- provider_errors: 0 (0.000)
- vision scenarios: 6 acc=0.8333333333333334
- text scenarios: 24 acc=0.8333333333333334
- intent_accuracy: 0.7272727272727273
- false_route_rate: 0.0
- response_false_positive_rate: 0.16666666666666666
- fallback_rate: 0.233
- pre_router avg/p50/p95 ms: 0.011377967894077301 / 0.009584007784724236 / 0.024250010028481483
- T0 (normalize+policy+pre_router) avg/p50/p95 ms: 0.29 / 0.16 / 0.97
- T1 (router/LLM) avg/p50/p95 ms: 1436.90 / 1327.62 / 2111.88
- E2E total avg/p50/p95 ms: 1150.15 / 1216.77 / 2111.90
- clarify→route rate: 0.5

## Latency by actual outcome

### E2E total

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 6 | 1546.86 | 1456.82 | 1820.14 |
| FALLBACK | 7 | 1249.18 | 1254.65 | 1539.28 |
| REJECT | 3 | 0.07 | 0.08 | 0.08 |
| RESPONSE | 6 | 1172.31 | 0.03 | 3787.48 |
| ROUTE | 8 | 1180.62 | 1216.77 | 1417.68 |

### T0 (normalize + policy + pre_router)

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 6 | 0.55 | 0.23 | 1.44 |
| FALLBACK | 7 | 0.44 | 0.35 | 0.93 |
| REJECT | 3 | 0.07 | 0.08 | 0.08 |
| RESPONSE | 6 | 0.11 | 0.02 | 0.34 |
| ROUTE | 8 | 0.20 | 0.16 | 0.48 |

### T1 (router / LLM only)

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 6 | 1546.16 | 1456.34 | 1819.88 |
| FALLBACK | 7 | 1248.66 | 1253.82 | 1539.11 |
| RESPONSE | 3 | 2344.40 | 2111.88 | 3787.13 |
| ROUTE | 8 | 1179.36 | 1216.48 | 1417.07 |

## Per-stage average / p50 / p95 (ms)

| Stage | avg | p50 | p95 |
| --- | ---: | ---: | ---: |
| `normalize` | 0.118 | 0.074 | 0.405 |
| `policy_gate` | 0.165 | 0.063 | 0.912 |
| `pre_router` | 0.011 | 0.010 | 0.024 |
| `router` | 1436.899 | 1327.619 | 2111.879 |
| `validator` | 0.418 | 0.115 | 3.684 |

Use this report to propose Overview §3.4 release thresholds (M5).

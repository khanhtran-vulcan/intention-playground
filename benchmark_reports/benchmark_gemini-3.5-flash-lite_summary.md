# Benchmark summary — Gemini Structured Router / gemini-3.5-flash-lite

- promptVersion: `router-v3`
- registryVersion: `yaml-registry-v1`
- schemaVersion: `reference-v1`
- scenarios: 30
- outcome_accuracy: 0.833
- outcome_accuracy (excl provider errors): 0.8571428571428571
- provider_errors: 2 (0.067)
- vision scenarios: 6 acc=0.6666666666666666
- text scenarios: 24 acc=0.875
- intent_accuracy: 0.8181818181818182
- false_route_rate: 0.1
- response_false_positive_rate: 0.16666666666666666
- fallback_rate: 0.267
- pre_router avg/p50/p95 ms: 0.0064505816057876305 / 0.003915978595614433 / 0.013208948075771332
- T0 (normalize+policy+pre_router) avg/p50/p95 ms: 0.11 / 0.06 / 0.39
- T1 (router/LLM) avg/p50/p95 ms: 3960.25 / 1195.11 / 29731.17
- E2E total avg/p50/p95 ms: 3168.36 / 1154.69 / 29731.29
- clarify→route rate: 0.0

## Latency by actual outcome

### E2E total

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 3 | 1086.71 | 1056.88 | 1154.69 |
| FALLBACK | 8 | 9150.69 | 1214.41 | 29953.01 |
| REJECT | 3 | 0.03 | 0.03 | 0.04 |
| RESPONSE | 6 | 1018.66 | 0.39 | 3555.50 |
| ROUTE | 10 | 1247.31 | 1195.20 | 1459.12 |

### T0 (normalize + policy + pre_router)

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 3 | 0.17 | 0.07 | 0.38 |
| FALLBACK | 8 | 0.10 | 0.06 | 0.28 |
| REJECT | 3 | 0.03 | 0.03 | 0.04 |
| RESPONSE | 6 | 0.15 | 0.03 | 0.39 |
| ROUTE | 10 | 0.09 | 0.06 | 0.20 |

### T1 (router / LLM only)

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 3 | 1086.41 | 1056.48 | 1154.59 |
| FALLBACK | 8 | 9150.57 | 1214.20 | 29952.93 |
| RESPONSE | 3 | 2037.00 | 1496.35 | 3555.47 |
| ROUTE | 10 | 1247.11 | 1195.11 | 1458.88 |

## Per-stage average / p50 / p95 (ms)

| Stage | avg | p50 | p95 |
| --- | ---: | ---: | ---: |
| `normalize` | 0.056 | 0.029 | 0.218 |
| `policy_gate` | 0.043 | 0.028 | 0.169 |
| `pre_router` | 0.006 | 0.004 | 0.013 |
| `router` | 3960.246 | 1195.107 | 29731.174 |
| `validator` | 0.072 | 0.036 | 0.323 |

Use this report to propose Overview §3.4 release thresholds (M5).

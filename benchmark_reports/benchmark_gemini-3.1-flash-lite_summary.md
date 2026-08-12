# Benchmark summary — Gemini Structured Router / gemini-3.1-flash-lite

- promptVersion: `router-v3`
- registryVersion: `yaml-registry-v1`
- schemaVersion: `reference-v1`
- scenarios: 30
- outcome_accuracy: 0.833
- outcome_accuracy (excl provider errors): 0.8333333333333334
- provider_errors: 0 (0.000)
- vision scenarios: 6 acc=0.8333333333333334
- text scenarios: 24 acc=0.8333333333333334
- intent_accuracy: 0.9090909090909091
- false_route_rate: 0.09090909090909091
- response_false_positive_rate: 0.2857142857142857
- fallback_rate: 0.100
- pre_router avg/p50/p95 ms: 0.004256195906135771 / 0.00437488779425621 / 0.005916925147175789
- T0 (normalize+policy+pre_router) avg/p50/p95 ms: 0.06 / 0.06 / 0.10
- T1 (router/LLM) avg/p50/p95 ms: 1027.11 / 928.10 / 1457.41
- E2E total avg/p50/p95 ms: 821.78 / 871.99 / 1457.46
- clarify→route rate: 0.5

## Latency by actual outcome

### E2E total

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 6 | 893.69 | 859.45 | 1069.87 |
| FALLBACK | 3 | 931.94 | 871.99 | 1056.07 |
| REJECT | 3 | 0.03 | 0.02 | 0.04 |
| RESPONSE | 7 | 855.95 | 928.15 | 2557.84 |
| ROUTE | 11 | 954.87 | 918.13 | 1163.51 |

### T0 (normalize + policy + pre_router)

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 6 | 0.07 | 0.06 | 0.10 |
| FALLBACK | 3 | 0.07 | 0.06 | 0.08 |
| REJECT | 3 | 0.03 | 0.02 | 0.04 |
| RESPONSE | 7 | 0.05 | 0.05 | 0.06 |
| ROUTE | 11 | 0.07 | 0.08 | 0.11 |

### T1 (router / LLM only)

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 6 | 893.58 | 859.31 | 1069.79 |
| FALLBACK | 3 | 931.85 | 871.92 | 1056.00 |
| RESPONSE | 4 | 1497.83 | 1457.41 | 2557.81 |
| ROUTE | 11 | 954.76 | 918.02 | 1163.34 |

## Per-stage average / p50 / p95 (ms)

| Stage | avg | p50 | p95 |
| --- | ---: | ---: | ---: |
| `normalize` | 0.029 | 0.026 | 0.052 |
| `policy_gate` | 0.027 | 0.026 | 0.044 |
| `pre_router` | 0.004 | 0.004 | 0.006 |
| `router` | 1027.111 | 928.096 | 1457.407 |
| `validator` | 0.035 | 0.033 | 0.065 |

Use this report to propose Overview §3.4 release thresholds (M5).

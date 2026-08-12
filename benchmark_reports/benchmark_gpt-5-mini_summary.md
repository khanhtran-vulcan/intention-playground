# Benchmark summary — OpenAI Structured Router / gpt-5-mini

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
- response_false_positive_rate: 0.16666666666666666
- fallback_rate: 0.100
- pre_router avg/p50/p95 ms: 0.026938212276608857 / 0.011333031579852104 / 0.09204121306538582
- T0 (normalize+policy+pre_router) avg/p50/p95 ms: 0.29 / 0.16 / 0.97
- T1 (router/LLM) avg/p50/p95 ms: 10478.88 / 9819.57 / 18914.33
- E2E total avg/p50/p95 ms: 8383.52 / 7931.35 / 18915.67
- clarify→route rate: 0.0

## Latency by actual outcome

### E2E total

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 7 | 10279.31 | 9819.97 | 14510.02 |
| FALLBACK | 3 | 9512.39 | 9476.57 | 10480.68 |
| REJECT | 3 | 0.12 | 0.13 | 0.14 |
| RESPONSE | 6 | 4350.00 | 0.04 | 12794.88 |
| ROUTE | 11 | 11355.73 | 10786.93 | 18998.62 |

### T0 (normalize + policy + pre_router)

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 7 | 0.37 | 0.30 | 0.97 |
| FALLBACK | 3 | 0.14 | 0.14 | 0.14 |
| REJECT | 3 | 0.12 | 0.13 | 0.14 |
| RESPONSE | 6 | 0.07 | 0.03 | 0.16 |
| ROUTE | 11 | 0.45 | 0.29 | 1.53 |

### T1 (router / LLM only)

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 7 | 10278.83 | 9819.57 | 14509.70 |
| FALLBACK | 3 | 9512.15 | 9476.40 | 10480.45 |
| RESPONSE | 3 | 8699.86 | 7433.45 | 12794.73 |
| ROUTE | 11 | 11355.03 | 10786.66 | 18998.29 |

## Per-stage average / p50 / p95 (ms)

| Stage | avg | p50 | p95 |
| --- | ---: | ---: | ---: |
| `normalize` | 0.155 | 0.067 | 0.871 |
| `policy_gate` | 0.109 | 0.072 | 0.323 |
| `pre_router` | 0.027 | 0.011 | 0.092 |
| `router` | 10478.882 | 9819.569 | 18914.329 |
| `validator` | 0.163 | 0.109 | 0.405 |

Use this report to propose Overview §3.4 release thresholds (M5).

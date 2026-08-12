# Benchmark summary — OpenAI Structured Router / gpt-5.6-luna

- promptVersion: `router-v3`
- registryVersion: `yaml-registry-v1`
- schemaVersion: `reference-v1`
- scenarios: 30
- outcome_accuracy: 0.833
- outcome_accuracy (excl provider errors): 0.8333333333333334
- provider_errors: 0 (0.000)
- vision scenarios: 6 acc=0.8333333333333334
- text scenarios: 24 acc=0.8333333333333334
- intent_accuracy: 0.8181818181818182
- false_route_rate: 0.1
- response_false_positive_rate: 0.16666666666666666
- fallback_rate: 0.167
- pre_router avg/p50/p95 ms: 0.014339573681354523 / 0.011082971468567848 / 0.03616698086261749
- T0 (normalize+policy+pre_router) avg/p50/p95 ms: 0.19 / 0.14 / 0.57
- T1 (router/LLM) avg/p50/p95 ms: 2887.64 / 2721.08 / 4137.22
- E2E total avg/p50/p95 ms: 2310.38 / 2477.47 / 4137.50
- clarify→route rate: 0.5

## Latency by actual outcome

### E2E total

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 6 | 2706.14 | 2531.58 | 3502.08 |
| FALLBACK | 5 | 2566.82 | 2477.47 | 3379.59 |
| REJECT | 3 | 0.10 | 0.06 | 0.19 |
| RESPONSE | 6 | 1806.63 | 0.03 | 4855.51 |
| ROUTE | 10 | 2940.06 | 2721.51 | 4137.50 |

### T0 (normalize + policy + pre_router)

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 6 | 0.26 | 0.14 | 0.57 |
| FALLBACK | 5 | 0.34 | 0.21 | 0.71 |
| REJECT | 3 | 0.10 | 0.06 | 0.19 |
| RESPONSE | 6 | 0.06 | 0.02 | 0.22 |
| ROUTE | 10 | 0.17 | 0.14 | 0.35 |

### T1 (router / LLM only)

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 6 | 2705.76 | 2531.15 | 3501.75 |
| FALLBACK | 5 | 2566.40 | 2477.02 | 3379.35 |
| RESPONSE | 3 | 3613.12 | 3420.67 | 4855.42 |
| ROUTE | 10 | 2939.76 | 2721.08 | 4137.22 |

## Per-stage average / p50 / p95 (ms)

| Stage | avg | p50 | p95 |
| --- | ---: | ---: | ---: |
| `normalize` | 0.073 | 0.060 | 0.169 |
| `policy_gate` | 0.103 | 0.065 | 0.399 |
| `pre_router` | 0.014 | 0.011 | 0.036 |
| `router` | 2887.645 | 2721.078 | 4137.218 |
| `validator` | 0.100 | 0.099 | 0.228 |

Use this report to propose Overview §3.4 release thresholds (M5).

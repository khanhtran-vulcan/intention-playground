# Benchmark summary — OpenAI Structured Router / gpt-5-nano

- promptVersion: `router-v3`
- registryVersion: `yaml-registry-v1`
- schemaVersion: `reference-v1`
- scenarios: 30
- outcome_accuracy: 0.767
- outcome_accuracy (excl provider errors): 0.7666666666666667
- provider_errors: 0 (0.000)
- vision scenarios: 6 acc=0.6666666666666666
- text scenarios: 24 acc=0.7916666666666666
- intent_accuracy: 0.8181818181818182
- false_route_rate: 0.1
- response_false_positive_rate: 0.16666666666666666
- fallback_rate: 0.167
- pre_router avg/p50/p95 ms: 0.014032461439017896 / 0.011542113497853279 / 0.0238749198615551
- T0 (normalize+policy+pre_router) avg/p50/p95 ms: 0.34 / 0.20 / 1.31
- T1 (router/LLM) avg/p50/p95 ms: 18159.77 / 16346.09 / 28433.92
- E2E total avg/p50/p95 ms: 14528.29 / 14345.35 / 28434.45
- clarify→route rate: 0.5

## Latency by actual outcome

### E2E total

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 6 | 25507.10 | 23637.51 | 45608.39 |
| FALLBACK | 5 | 15587.74 | 14345.35 | 19902.24 |
| REJECT | 3 | 0.10 | 0.10 | 0.15 |
| RESPONSE | 6 | 8862.14 | 0.07 | 28434.45 |
| ROUTE | 10 | 15169.44 | 15501.94 | 23430.90 |

### T0 (normalize + policy + pre_router)

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 6 | 0.45 | 0.30 | 1.31 |
| FALLBACK | 5 | 0.75 | 0.47 | 2.28 |
| REJECT | 3 | 0.10 | 0.10 | 0.15 |
| RESPONSE | 6 | 0.12 | 0.03 | 0.47 |
| ROUTE | 10 | 0.27 | 0.17 | 0.50 |

### T1 (router / LLM only)

| Outcome | n | avg ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| CLARIFY | 6 | 25506.39 | 23636.95 | 45607.96 |
| FALLBACK | 5 | 15586.88 | 14344.77 | 19901.64 |
| RESPONSE | 3 | 17723.98 | 14784.09 | 28433.92 |
| ROUTE | 10 | 15168.97 | 15501.76 | 23430.38 |

## Per-stage average / p50 / p95 (ms)

| Stage | avg | p50 | p95 |
| --- | ---: | ---: | ---: |
| `normalize` | 0.144 | 0.085 | 0.329 |
| `policy_gate` | 0.183 | 0.095 | 0.341 |
| `pre_router` | 0.014 | 0.012 | 0.024 |
| `router` | 18159.766 | 16346.093 | 28433.919 |
| `validator` | 0.178 | 0.145 | 0.399 |

Use this report to propose Overview §3.4 release thresholds (M5).

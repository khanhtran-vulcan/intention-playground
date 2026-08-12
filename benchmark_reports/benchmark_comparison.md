# Model selection comparison

- proposed accuracy floor: **0.750** (Product approves)
- primary: **(none)**
- fallback: **(none)**
- ranking order: gemini-3.1-flash-lite, gpt-5.4-nano, gpt-5.6-luna, gpt-5-mini, gemini-3.5-flash-lite, gpt-5-nano
- run LLM calls (live): **142**
- run estimated cost (live models): **$0.106335**
- run config: `{'suite': 'all', 'provider_timeout_seconds': 30.0, 'parallel': True, 'workers': 1, 'scenario_count': 30, 'clarification_chain_count': 2}`

## Selection metrics

| Rank | Pass | Model | Accuracy | Acc excl provider | Vision acc | Router p95 ms | Est $/req |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | no | `gemini-3.1-flash-lite` | 0.833 | 0.833 | 0.833 | 1457 | $0.000355 |
| 2 | no | `gpt-5.4-nano` | 0.833 | 0.833 | 0.833 | 2112 | $0.000369 |
| 3 | no | `gpt-5.6-luna` | 0.833 | 0.833 | 0.833 | 4137 | $0.000414 |
| 4 | no | `gpt-5-mini` | 0.833 | 0.833 | 0.833 | 18914 | $0.001800 |
| 5 | no | `gemini-3.5-flash-lite` | 0.833 | 0.857 | 0.667 | 29731 | $0.000652 |
| 6 | no | `gpt-5-nano` | 0.767 | 0.767 | 0.667 | 28434 | $0.000895 |

## Notes

- Proposed accuracy floor=0.750 (from baseline; Product approves).
- Ranking among passers: accuracy → router p95 → mean tokens → est $.
- Watch metrics (fallback, clarify→route, reason_code) are not in selection score.
- No live model passed the proposed floor — do not ship production router.
- `gemini-3.1-flash-lite` fail: response_fp 0.286 > max 0.100
- `gpt-5.4-nano` fail: response_fp 0.167 > max 0.100
- `gpt-5.6-luna` fail: response_fp 0.167 > max 0.100
- `gpt-5-mini` fail: response_fp 0.167 > max 0.100
- `gemini-3.5-flash-lite` fail: response_fp 0.167 > max 0.100
- `gpt-5-nano` fail: response_fp 0.167 > max 0.100

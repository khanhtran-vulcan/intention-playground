# Intention Router Playground

A single-process Streamlit playground with two independent parts:

- **V1 Reference** — acceptance demo + model benchmark harness for Intention Detection &
  Routing V1: Normalize → Policy Gate → Pre-router (exact static) → Structured LLM Router
  (≤1 call) → Validator → `RESPONSE | ROUTE | CLARIFY | FALLBACK | REJECT`. Public JSON
  matches BE §10 (`INTENTION_DETECT_OUTCOME_*`, camelCase). See
  [docs/reference-runtime.md](docs/reference-runtime.md). Run `make benchmark` (Fake),
  `make benchmark PROVIDERS=fake,gemini,openai` (env models), or `make benchmark-select`
  (parallel multi-model shortlist → `benchmark_reports/benchmark_comparison.md`).
- **Comparison Lab** (Compare / Evaluate / Hybrid / Taxonomy tabs) — for comparing
  four intent-routing strategies and a hybrid policy:
  - Regex rules with bounded execution time
  - Character TF-IDF + Logistic Regression
  - In-memory multilingual embeddings + cosine similarity
  - Gemini structured output
  - Hybrid routing through rules, local consensus, and Gemini fallback

The two parts are intentionally independent: separate packages (`reference_runtime/`
vs `core/`+`routers/`), separate metrics, separate scenario/evaluation datasets. The
bundled Vietnamese/code-switch dataset for the Comparison Lab is deliberately small.
Its evaluation set is a demo smoke benchmark, not evidence of production quality —
the same applies to the V1 Reference scenario dataset in `reference_runtime/scenarios.py`.

Planning: `.planning/2026-08-07-intention-v1-amend-benchmark/` (amend + benchmark).
Earlier demo plan: `.planning/2026-08-03-intention-v1-reference-demo/`.

## For coding agents

- **[AGENTS.md](./AGENTS.md)** — project rules, package boundaries, commands, GitNexus workflow (Cursor / Codex / etc.).
- **[CLAUDE.md](./CLAUDE.md)** — Claude Code entry; defers to `AGENTS.md` + GitNexus block.
- Index: `gitnexus analyze` from repo root (requires git). Re-run after large structural changes. Status: `gitnexus status`.

## Default business taxonomy

The default taxonomy routes creative and multimodal product requests:

| Intent | Parent | Gemini-only properties |
| --- | --- | --- |
| `creative` | — | — *(archived)* |
| `create_ai_art` | `creative` | required `prompt`, at most 25 words |
| `generate_logo` | `creative` | — *(archived)* |
| `generate_poster` | `creative` | — *(archived)* |
| `generate_flyer` | `creative` | — *(archived)* |
| `chat_with_image` | — | — |
| `image_to_image_generation` | — | required `style` enum |
| `real_time_search` | — | — (empty args) |
| `deep_research` | — | required `final_prompt` |
| `unknown` | — | — |

`creative` is a routable fallback for unspecified design assets. Explicit logo, poster, flyer, or artwork requests select the corresponding child. Image chat and style transformation can still be classified without an attachment, but the result reports `missing_required_context=true`.

## Run locally

Python 3.11 is the supported baseline.

```bash
make setup
make train
make run
```

Then open **http://localhost:8501** manually in your browser.

`make run` starts the **lightweight V1 Reference app** (`app_reference.py`) — preferred on macOS
because the full Comparison Lab (`app.py`) often hits `Segmentation fault: 11` after startup
when pandas/sklearn/torch stacks load.

| Command | App |
| --- | --- |
| `make run` | V1 Reference only |
| `make run-lab` | Full playground (V1 + Compare / Evaluate / Hybrid / Taxonomy) |
| `make docker-run` | Full playground in Linux container (most reliable if macOS still crashes) |

If `make run-lab` exits with `Segmentation fault: 11`, use `make run` or:

```bash
make docker-run
```

Run `make help` to list all local and Docker workflows. Override defaults when needed, for example `make run PORT=8502` or `make docker-build IMAGE=my-playground`.

The Makefile prefers `python3.11`. If it is unavailable and `mise` is installed, it automatically provisions and uses `python@3.11`. A custom interpreter can be supplied with `make setup PYTHON_BIN=/path/to/python`.

`GEMINI_API_KEY` is optional. Without it, Rules, TF-IDF, Semantic, and local Hybrid stages continue to work. The embedding model downloads lazily from Hugging Face on its first use.

## Run with Docker

```bash
make docker-build
make docker-run
```

The image pretrains the sklearn artifact for the default taxonomy. Taxonomies edited in the UI are trained in memory and are not written into the container filesystem.

## UI workflows

- **V1 Reference** runs the independent Reference Runtime (see
  [docs/reference-runtime.md](docs/reference-runtime.md)): pick a classifier
  provider, load a scenario or chat freely, answer clarifications, and — after a
  `ROUTE` outcome — explicitly run the Mock Capability Simulator to see the
  capability-owned recommendation and suggested-action flow. The Public Client
  Contract, Internal Reference Trace, and Mock Capability Contract are shown in
  clearly separated inspector tabs.
- **Compare** runs all four providers concurrently with independent deadlines.
- **Evaluate** uses the bundled CSV or an uploaded `text,expected_intent` CSV.
- **Hybrid** exposes the full decision path and component outputs.
- **Taxonomy** edits, validates, imports, and exports a session-isolated taxonomy.

Compare and Hybrid accept one optional JPEG, PNG, or WebP image up to 10 MB. Gemini receives the actual multimodal image; local routers receive normalized attachment context. Image bytes are never included in result metadata or raw output.

Taxonomy edits use transactional semantics: validate, canonicalize and fingerprint, build candidate local state, then atomically replace the active session runtime. A failed candidate leaves the previous runtime intact. The shared embedding model resource may be cached process-wide, but semantic indexes and taxonomies remain session-specific.

Session edits are not persistent. Export the active taxonomy before refreshing or restarting if it must be retained.

## Taxonomy constraints

- Intent names match `^[a-z][a-z0-9_]*$`.
- Exactly one reserved `unknown` intent is required.
- `unknown` examples inform the Gemini prompt and evaluation but are excluded from sklearn training and the semantic index.
- Known intents require examples; fewer than 10 produces a UI warning.
- Intent parents must exist and the hierarchy cannot contain cycles.
- Conditional properties support required strings, enums, and maximum word counts.
- Examples cannot be blank, duplicated within one intent, or shared across intents.
- Regex rules compile before apply, are length-limited, and execute with a timeout.
- The playground accepts at most 50 known intents and 100 examples per intent.

## Scores and abstention

Provider confidence values are not directly comparable:

| Provider | Score meaning |
| --- | --- |
| Rules | Deterministic match (`1.0`) |
| TF-IDF | `predict_proba` class probability |
| Semantic | Cosine similarity to the nearest example |
| Gemini | LLM self-assessment, not a calibrated probability |

`unknown` means insufficient evidence. `ambiguous` means rules from multiple intents matched. Errors, timeouts, and unavailable dependencies remain distinct statuses.

Hybrid routing follows this policy:

1. Accept one uniquely matched rule intent.
2. Run TF-IDF and Semantic concurrently.
3. Accept only when both return the same known intent above their own thresholds.
4. Otherwise call Gemini.
5. If Gemini is unavailable, return `unknown` with `degraded` status.

The result metadata retains a bounded, sanitized decision trace. It never includes API keys, request headers, full prompts, stack traces, or complete SDK response objects.

## Evaluation

Evaluation reports overall and known accuracy, unknown recall, false acceptance rate, unknown rate, coverage, selective accuracy, average/median/P95 latency, confusion matrix, schema failure rate, tokens, and estimated cost.

Local initialization is reported separately from warm inference. LLM-enabled evaluation is opt-in and capped at 100 potential Gemini requests. Pricing is never hard-coded; set the optional pricing variables in `.env` to enable cost estimates.

The first Semantic Router use may download model weights and build the in-memory example index. This cold initialization runs under a dedicated spinner and is not constrained by the 2-second local inference deadline. Once initialized, semantic query encoding is subject to the configured local timeout.

Gemini cards show input, output, thinking, and cached token counts plus estimated cost for each call. Cost estimation treats blank pricing as unavailable rather than a routing error, includes thinking tokens in billed output, and uses the model-specific prices configured in `.env`. Explicit context-cache storage cost is not estimated because this app does not create cache resources.

## Test

```bash
make test
```

The default tests do not call Gemini, OpenAI, or download a Hugging Face model. They use fake clients and encoders for deterministic coverage, including for the V1 Reference Runtime's Gemini/OpenAI classifier adapters (`tests/reference/`).

Live, credential-backed smoke calls to Gemini or OpenAI are opt-in only, run at most once per configured provider, and are never part of the default `pytest` run.

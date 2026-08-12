# AGENTS.md — Intention Playground

Authoritative guide for coding agents working in this repo. Read this before editing code.

---

## What this repo is

A **Streamlit playground** with two **independent** products:

| Surface | Package | Purpose |
| --- | --- | --- |
| **V1 Reference** | `reference_runtime/`, `reference_ui.py`, `app_reference.py` | Intention Detection & Routing V1: Normalize → Policy Gate → Pre-router → Structured LLM Router (≤1 call) → Validator → public outcomes |
| **Comparison Lab** | `core/`, `routers/`, `app.py` | Compare Rules / TF-IDF / Semantic / Gemini / Hybrid strategies |

Do **not** mix contracts, metrics, scenarios, or registries across the two surfaces.

Primary docs:

- `README.md` — run / Docker / taxonomy overview
- `docs/reference-runtime.md` — V1 pipeline contract
- `PRODUCT.md` / `DESIGN.md` — product framing
- `HANDOFF.md` — V1 UI handoff (UX reviewers; not implementation source of truth)

Active planning sessions live under `.planning/` (see `.planning/.active_plan`).

---

## Hard rules

1. **Keep V1 Reference and Comparison Lab separate** — different packages, scenarios, evaluation, and UI entrypoints.
2. **V1 executable intents (current):** `create_ai_art`, `chat_with_image`, `image_to_image_generation`, `real_time_search`, `deep_research` (+ non-executable `unknown`). Do not reintroduce archived creatives (`generate_logo` / `poster` / `flyer`) into the live allowlist without an explicit product decision.
3. **Public Client contract** stays camelCase / `INTENTION_DETECT_OUTCOME_*` — see `docs/reference-runtime.md`. Internal traces may use snake_case; do not leak internals into the public payload.
4. **CLARIFY** must use validator-recognized `missing_inputs` tokens only: `create_or_edit_choice`, `creative_type`, `image`, `style`, `dependency_reference`. Wrong tokens → `UNRESOLVABLE_AMBIGUITY` / FALLBACK.
5. **Router prompt version** is `PROMPT_VERSION` in `reference_runtime/registry_loader.py` (currently `router-v3`). Bump intentionally when prompt behavior changes.
6. Prefer **Fake** provider for offline / CI; live Gemini/OpenAI need keys in `.env` (never commit secrets).
7. Python **3.11** baseline. Prefer `make` targets over ad-hoc commands.
8. Do not commit `.env`, credentials, or large `benchmark_reports/` artifacts unless the user asks.

---

## Where to change what

| Goal | Start here |
| --- | --- |
| Pipeline / outcomes | `reference_runtime/runtime.py`, `validator.py`, `pre_router.py` |
| Live routers | `reference_runtime/router/{openai,gemini,fake}.py`, `conversation.py` |
| Intent registry / prompt | `registry/intents.yaml`, `registry_loader.py` |
| Scenarios / suites | `reference_runtime/scenarios.py` |
| Benchmark harness | `benchmark_cli.py`, `evaluation.py`, `selection.py` |
| V1 UI | `reference_ui.py`, `app_reference.py` |
| Comparison Lab | `core/`, `routers/`, `app.py` |
| Tests | `tests/reference/` (V1), `tests/` (lab) |

---

## Common commands

```bash
make setup          # venv + deps
make test           # pytest
make run            # V1 Reference only (preferred on macOS)
make run-lab        # full playground (may segfault on macOS → use Docker)
make benchmark      # Fake-only harness
make benchmark-select          # multi-model, parallel (workers capped)
make benchmark-select-fair     # sequential (workers=1) — preferred for selection
```

Fair re-bench after router/prompt changes:

```bash
make benchmark-select-fair SUITE=all
```

Reports land in `benchmark_reports/` (gitignored).

---

## GitNexus workflow (required for non-trivial edits)

This repo is indexed as **intention-playground**. Prefer graph tools over blind grep when exploring or changing symbols.

1. Read `gitnexus://repo/intention-playground/context` if the index may be stale.
2. Explore: `query` / `context` (see GitNexus block below).
3. Before editing a symbol: `impact` upstream; warn on HIGH/CRITICAL.
4. Before commit: `detect_changes`.
5. After large code moves or many commits: `gitnexus analyze` (or `node .gitnexus/run.cjs analyze`).

Skills under `.claude/skills/gitnexus/` document each workflow.

---

## Testing expectations

- After V1 behavior changes: `pytest tests/reference -q`
- Do not treat the scenario suite as production quality evidence — it is an acceptance / smoke set.
- Fake must stay green at 100% outcome accuracy on the full scenario set when the suite is coherent.

---

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **intention-playground** (1880 symbols, 3598 relationships, 130 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/intention-playground/context` | Codebase overview, check index freshness |
| `gitnexus://repo/intention-playground/clusters` | All functional areas |
| `gitnexus://repo/intention-playground/processes` | All execution flows |
| `gitnexus://repo/intention-playground/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

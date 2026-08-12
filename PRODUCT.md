# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Engineers and PMs validating **Intention Detection & Routing V1** — loading scenarios, chatting multi-turn (including clarifications), and inspecting public vs internal contracts. Active executables: create_ai_art, chat_with_image, image_to_image_generation, real_time_search, deep_research.

## Product Purpose

Single-process Streamlit playground that demos and benchmarks the V1 Reference Runtime: Normalize → Policy → Pre-router → Structured LLM Router → Validator → public outcomes. Success = an operator can run a turn, see conversation history with intent outcomes, tune provider/tools, and inspect contracts without leaving the page.

## Positioning

Acceptance demo + model benchmark harness aligned to BE §10 public wire — not a production chat product and not the Comparison Lab (`core/` / `routers/`).

## Operating Context

- Primary entry: `make run` → `app_reference.py` → `reference_ui.render()`
- Providers: Fake / Gemini / OpenAI; keys from `.env`
- Scenario suite: `reference_runtime/scenarios.py` (UI shows `phase=core`)
- Conversation state lives in Streamlit `session_state` only

## Capabilities and Constraints

- Must keep Public Client Contract, Internal Trace, and Mock Capability Contract visually distinct
- Router never invokes capabilities; mock capability is an explicit client action after `ROUTE`
- Streamlit 1.46.1; prefer lightweight UI path (avoid pandas/sklearn stacks that segfault on macOS)
- Primary loop: conversation (chronology + contextual actions) | scoped result diagnostic; scenario browse ≠ mutate; Setup/Inspect secondary

## Brand Commitments

None pinned. Product name: **Intention V1 Reference**.

## Evidence on Hand

- `docs/reference-runtime.md`, `registry/intents.yaml`, scenario fixtures, benchmark reports under `benchmark_reports/`
- Do not invent production capability behavior beyond the mock simulator

## Product Principles

1. Conversation is the source of truth for what was asked and which intent fired.
2. Settings and inspection stay secondary but always reachable (right pane).
3. Scenario loading is a one-gesture workflow (search → click → run).
4. Demo honesty: mock capability and internal traces are labeled, never confused with Client wire.

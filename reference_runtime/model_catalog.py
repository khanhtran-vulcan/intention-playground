"""Curated classifier model catalogs for the V1 Reference UI's provider picker.

Scoped deliberately to `reference_ui.py` only -- the Comparison Lab (`app.py`,
`routers/gemini_router.py`) keeps its own free-text model input untouched.

The Gemini entries were live-verified against the real API on 2026-08-03 (each
model ID answered a `generate_content` call with the configured `GEMINI_API_KEY`).
The OpenAI entries are sourced from external research (dated August 2026, no
`OPENAI_API_KEY` was available in this environment to verify them against the
live API) -- treat their exact pricing/latency claims as reported, not
independently confirmed here. Both catalogs will drift as providers ship new
models; the UI always offers a "type your own model ID" escape hatch so a
missing or renamed model never blocks usage.
"""

from __future__ import annotations

from dataclasses import dataclass


CUSTOM_MODEL_CHOICE = "__custom__"


@dataclass(frozen=True)
class ModelOption:
    model_id: str
    tag: str
    note: str


GEMINI_MODELS: tuple[ModelOption, ...] = (
    ModelOption(
        model_id="gemini-3.1-flash-lite",
        tag="recommended",
        note="Default V1 Reference model (operator choice). Live-verified.",
    ),
    ModelOption(
        model_id="gemini-3.5-flash-lite",
        tag="current-gen lite",
        note="Cheapest/fastest current-gen Lite model; $0.30/$2.50 per 1M tokens in/out. Live-verified 2026-08-03.",
    ),
    ModelOption(
        model_id="gemini-2.5-flash-lite",
        tag="retiring 2026-10-16",
        note="Legacy Lite generation. Retires 2026-10-16 -- avoid for new work. Live-verified.",
    ),
    ModelOption(
        model_id="gemini-3.6-flash",
        tag="higher quality",
        note="Current Flash tier; better quality than Lite at higher cost/latency. Live-verified.",
    ),
    ModelOption(
        model_id="gemini-3.1-pro-preview",
        tag="reasoning, expensive",
        note="Reasoning-tier preview model. Use only for hard/ambiguous classification comparisons. Live-verified.",
    ),
)

OPENAI_MODELS: tuple[ModelOption, ...] = (
    ModelOption(
        model_id="gpt-5.4-nano",
        tag="recommended",
        note="OpenAI documents this nano tier for classification/extraction; dated snapshot available. Not independently verified (no OPENAI_API_KEY in this env).",
    ),
    ModelOption(
        model_id="gpt-5.6-luna",
        tag="newest nano-tier",
        note="Newest nano-equivalent alias; near-identical pricing to gpt-5.4-nano. Not independently verified.",
    ),
    ModelOption(
        model_id="gpt-4o-mini",
        tag="legacy, well-known",
        note="Older small model, one of the first with strict JSON-schema structured outputs. Not independently verified.",
    ),
    ModelOption(
        model_id="gpt-5.4-mini",
        tag="higher quality",
        note="Higher-accuracy comparison tier above nano. Not independently verified.",
    ),
    ModelOption(
        model_id="gpt-5.6-sol",
        tag="reasoning, expensive",
        note="Flagship reasoning tier; overkill for routine routing, useful as a comparison point. Not independently verified.",
    ),
)


def select_options(models: tuple[ModelOption, ...]) -> list[str]:
    return [model.model_id for model in models] + [CUSTOM_MODEL_CHOICE]


def format_option(model_id: str, models: tuple[ModelOption, ...]) -> str:
    if model_id == CUSTOM_MODEL_CHOICE:
        return "Other (type your own model ID)"
    match = next((model for model in models if model.model_id == model_id), None)
    return f"{model_id} — {match.tag}" if match else model_id


def note_for(model_id: str, models: tuple[ModelOption, ...]) -> str | None:
    match = next((model for model in models if model.model_id == model_id), None)
    return match.note if match else None


def resolve_default_choice(
    models: tuple[ModelOption, ...], configured_value: str | None
) -> tuple[str, str]:
    """Return (selectbox_choice, custom_field_value) from an env-configured model.

    If `configured_value` matches a catalog entry, select it directly. If it's
    set but unrecognized, default to the custom slot pre-filled with that
    value (so the picker never silently drops an operator's real `.env`
    setting). If unset, default to the catalog's first "recommended" entry.
    """
    if configured_value:
        if any(model.model_id == configured_value for model in models):
            return configured_value, ""
        return CUSTOM_MODEL_CHOICE, configured_value
    recommended = next((model for model in models if model.tag == "recommended"), models[0])
    return recommended.model_id, ""

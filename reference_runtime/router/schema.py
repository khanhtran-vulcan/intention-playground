"""Shared structured-output schema and prompt builder for the Unified Router."""

from __future__ import annotations

from reference_runtime.registry_loader import (
    PROMPT_VERSION,
    build_router_system_prompt_for_request,
    registry_version,
)


# Tagged-union schema. Goals/dependencies are optional internal analysis fields —
# the model is not required to emit multi-intent plans (locked V1).
ROUTER_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "outcome": {
            "type": "string",
            "enum": ["RESPONSE", "ROUTE", "CLARIFY", "FALLBACK"],
        },
        "response": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
        "route": {
            "type": "object",
            "properties": {
                "selected_intent": {"type": "string"},
                "arguments": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
                "missing_inputs": {"type": "array", "items": {"type": "string"}},
                "goals": {"type": "array", "items": {"type": "string"}},
                "candidate_intents": {"type": "array", "items": {"type": "string"}},
                "dependencies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "intent": {"type": "string"},
                            "depends_on": {"type": "string"},
                        },
                        "required": ["intent", "depends_on"],
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        },
        "reason_code": {"type": "string"},
    },
    "required": ["outcome", "reason_code"],
    "additionalProperties": False,
}

AMBIGUITY_TOKENS: tuple[str, ...] = (
    "create_or_edit_choice",
    "creative_type",
    "image",
    "style",
    "dependency_reference",
)

CANDIDATE_JSON_SCHEMA_TEMPLATE: dict = ROUTER_JSON_SCHEMA


def build_system_prompt(tool_names: list[str] | None = None) -> str:
    return build_router_system_prompt_for_request(tool_names or [])


__all__ = [
    "AMBIGUITY_TOKENS",
    "CANDIDATE_JSON_SCHEMA_TEMPLATE",
    "PROMPT_VERSION",
    "ROUTER_JSON_SCHEMA",
    "build_system_prompt",
    "registry_version",
]

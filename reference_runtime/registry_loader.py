"""Load BE-owned intent registry from YAML and build router prompts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from reference_runtime.contracts import Clarification, ClarificationOption
from reference_runtime.registry import (
    ArgumentSpec,
    IMAGE_STYLES,
    IntentSpec,
    ReferenceIntentRegistry,
    TAXONOMY_VERSION,
    _CLARIFICATION_TEMPLATES,
    _SPECS,
)

DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "registry" / "intents.yaml"
PROMPT_VERSION = "router-v3"
REGISTRY_VERSION = "yaml-registry-v1"


def registry_version() -> str:
    """Pinned registry bundle id for telemetry / release bundles."""
    registry_path = DEFAULT_REGISTRY_PATH
    if registry_path.exists():
        return REGISTRY_VERSION
    return "builtin-registry"


@dataclass(frozen=True)
class YamlIntentRecord:
    name: str
    description: str
    use_when: tuple[str, ...] = ()
    do_not_use_when: tuple[str, ...] = ()
    executable: bool = True
    archived: bool = False
    risk_level: Literal["read_only", "side_effect"] = "read_only"
    requires_image: bool = False
    arguments_schema: dict[str, Any] = field(default_factory=dict)


def load_yaml_registry(path: Path | None = None) -> tuple[YamlIntentRecord, ...]:
    registry_path = path or DEFAULT_REGISTRY_PATH
    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    records: list[YamlIntentRecord] = []
    for item in raw.get("intents", []):
        records.append(
            YamlIntentRecord(
                name=item["name"],
                description=str(item.get("description", "")).strip(),
                use_when=tuple(item.get("use_when") or ()),
                do_not_use_when=tuple(item.get("do_not_use_when") or ()),
                executable=bool(item.get("executable", True)),
                archived=bool(item.get("archived", False)),
                risk_level=item.get("risk_level", "read_only"),
                requires_image=bool(item.get("requires_image", False)),
                arguments_schema=dict(item.get("arguments_schema") or {}),
            )
        )
    return tuple(records)


def _argument_specs_from_schema(schema: dict[str, Any]) -> tuple[ArgumentSpec, ...]:
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    specs: list[ArgumentSpec] = []
    for name, prop in properties.items():
        enum_values = prop.get("enum")
        max_words = 25 if name == "prompt" else None
        specs.append(
            ArgumentSpec(
                name=name,
                required=name in required,
                description=str(prop.get("description", "")),
                enum=tuple(enum_values) if enum_values else None,
                max_words=max_words,
            )
        )
    return tuple(specs)


def registry_from_yaml(path: Path | None = None) -> ReferenceIntentRegistry:
    """Build ReferenceIntentRegistry from YAML; falls back to baked-in _SPECS on missing file."""
    registry_path = path or DEFAULT_REGISTRY_PATH
    if not registry_path.exists():
        return ReferenceIntentRegistry(_SPECS)

    yaml_records = load_yaml_registry(registry_path)
    specs: list[IntentSpec] = []
    for record in yaml_records:
        if record.name == "image_to_image_generation" and not record.arguments_schema:
            args = (
                ArgumentSpec(
                    name="style",
                    required=True,
                    description="Requested visual style.",
                    enum=IMAGE_STYLES,
                ),
            )
        else:
            args = _argument_specs_from_schema(record.arguments_schema)
        schema_source: Literal["taxonomy", "partial_reuse", "demo"] = (
            "partial_reuse" if record.name == "deep_research" else "taxonomy"
        )
        specs.append(
            IntentSpec(
                name=record.name,
                executable=record.executable,
                archived=record.archived,
                requires_image=record.requires_image,
                arguments=args,
                schema_source=schema_source,
            )
        )
    return ReferenceIntentRegistry(tuple(specs))


def active_intent_records(
    records: tuple[YamlIntentRecord, ...],
) -> tuple[YamlIntentRecord, ...]:
    """Solution-doc production intents only (archived YAML entries excluded)."""
    return tuple(record for record in records if not record.archived)


def filter_intent_records(
    records: tuple[YamlIntentRecord, ...],
    tool_names: list[str] | None,
) -> tuple[YamlIntentRecord, ...]:
    active = active_intent_records(records)
    if not tool_names:
        return active
    allowed = set(tool_names)
    return tuple(
        record
        for record in active
        if record.name in allowed or (not record.executable and record.name == "unknown")
    )


def build_router_system_prompt(
    records: tuple[YamlIntentRecord, ...],
    *,
    prompt_version: str = PROMPT_VERSION,
) -> str:
    lines = [
        f"You are the Reference Router (prompt {prompt_version}). Analyze the conversation "
        "and return exactly one structured decision using the provided JSON schema.",
        "",
        "Rules:",
        "- Return one outcome: RESPONSE, ROUTE, CLARIFY, or FALLBACK.",
        "- RESPONSE: direct answer when no capability is needed (simple definitions, general knowledge).",
        "- ROUTE: select exactly one next-executable intent with arguments that match its schema.",
        "- CLARIFY: one blocking question when one user answer would enable ROUTE.",
        "- CLARIFY must include missing_inputs: use ONLY these tokens when applicable:",
        "  create_or_edit_choice, creative_type, image, style, dependency_reference.",
        "- Never use FALLBACK when CLARIFY with a valid missing_inputs token would unblock ROUTE.",
        "- When the user attached an image (see [attachments] lines) but intent is unclear, "
        "prefer CLARIFY with create_or_edit_choice or style — not FALLBACK.",
        "- chat_with_image / image_to_image_generation require an attached image; if attachments "
        "are present and the user asks about the image, ROUTE the matching intent.",
        "- FALLBACK: no safe executable route.",
        "- Multi-intent / multi-step: ROUTE only the NEXT executable step. Put later steps in "
        "candidate_intents and goals. Never invent a second simultaneous ROUTE.",
        "- Prefer deep_research over real_time_search when the user asks for deep research / "
        "nghiên cứu (even if the topic also needs live facts).",
        "- Prefer real_time_search for quick live facts without research framing.",
        "- Arguments: use ONLY keys declared for the selected intent. Never invent keys "
        "(e.g. do not pass query on real_time_search; deep_research uses final_prompt, not query).",
        "- Hard limits: create_ai_art prompt is at most 25 words — count carefully.",
        "- Do not expose reasoning. Do not invoke tools.",
        "",
        "Available intents:",
    ]
    for record in records:
        if record.archived:
            continue
        # Non-executable labels stay out of the prompt except the V1 fallback `unknown`.
        if not record.executable and record.name != "unknown":
            continue
        lines.append(f"- {record.name}: {record.description}")
        if record.use_when:
            lines.append(f"  use_when: {'; '.join(record.use_when)}")
        if record.do_not_use_when:
            lines.append(f"  do_not_use_when: {'; '.join(record.do_not_use_when)}")
        schema = record.arguments_schema or {}
        props = schema.get("properties") or {}
        required = schema.get("required") or []
        if not props:
            lines.append("  arguments: {}  # no properties — emit empty object")
        else:
            prop_bits = []
            for name, spec in props.items():
                bit = name
                if name in required:
                    bit += " (required)"
                if isinstance(spec, dict) and spec.get("type"):
                    bit += f": {spec['type']}"
                if name == "prompt":
                    bit += ", max 25 words"
                prop_bits.append(bit)
            lines.append(f"  arguments: {{{', '.join(prop_bits)}}}")
    return "\n".join(lines)


def build_router_system_prompt_for_request(
    request_tools: list[str],
    path: Path | None = None,
) -> str:
    records = load_yaml_registry(path)
    filtered = filter_intent_records(records, request_tools or None)
    return build_router_system_prompt(filtered)

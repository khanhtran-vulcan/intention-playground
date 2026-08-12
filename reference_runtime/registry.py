"""Per-intent schemas, readiness rules, and clarification templates.

This is the BE-owned registry the source-of-truth doc calls for (Open Question #4:
"BE-owned registry kèm release process"). It is intentionally separate from
`core/taxonomy.py` (the Comparison Lab's classification-only taxonomy) -- the
Reference Runtime needs execution-readiness metadata (required arguments, whether
an intent is directly executable, clarification copy) that the Comparison Lab has
no use for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from reference_runtime.contracts import Clarification, ClarificationOption


TAXONOMY_VERSION = "reference-intents-v1"

IMAGE_STYLES: tuple[str, ...] = (
    "ghibli",
    "anime",
    "disney",
    "genshin_impact",
    "manga",
    "one_piece",
    "naruto",
    "dragon_ball",
    "bleach",
    "attack_on_titan",
    "demon_slayer",
    "doraemon",
    "sailor_moon",
    "the_simpson",
    "rick_and_morty",
    "south_park",
    "other",
)


@dataclass(frozen=True)
class ArgumentSpec:
    name: str
    required: bool = False
    description: str = ""
    enum: tuple[str, ...] | None = None
    max_words: int | None = None


@dataclass(frozen=True)
class IntentSpec:
    name: str
    executable: bool = True
    archived: bool = False
    requires_image: bool = False
    arguments: tuple[ArgumentSpec, ...] = field(default_factory=tuple)
    # "taxonomy": reused as-is from data/intents.json / ms-smith-nexus intent taxonomy.
    # "partial_reuse": a real field name reused inside a demo-simplified wrapper shape.
    # "demo": invented for this demo only, no production counterpart.
    schema_source: Literal["taxonomy", "partial_reuse", "demo"] = "taxonomy"

    @property
    def required_argument_names(self) -> list[str]:
        return [argument.name for argument in self.arguments if argument.required]

    def argument(self, name: str) -> ArgumentSpec | None:
        for argument in self.arguments:
            if argument.name == name:
                return argument
        return None


_SPECS: tuple[IntentSpec, ...] = (
    IntentSpec(
        name="creative",
        executable=False,  # ambiguous parent; Validator turns this into CLARIFY.
        archived=True,
    ),
    IntentSpec(
        name="create_ai_art",
        arguments=(
            ArgumentSpec(
                name="prompt",
                required=True,
                description="Prompt describing the art in detail.",
                max_words=25,
            ),
        ),
    ),
    IntentSpec(name="generate_logo", archived=True),
    IntentSpec(name="generate_poster", archived=True),
    IntentSpec(name="generate_flyer", archived=True),
    IntentSpec(name="chat_with_image", requires_image=True),
    IntentSpec(
        name="image_to_image_generation",
        requires_image=True,
        arguments=(
            ArgumentSpec(
                name="style",
                required=True,
                description="Requested visual style.",
                enum=IMAGE_STYLES,
            ),
        ),
    ),
    IntentSpec(name="real_time_search"),
    IntentSpec(
        name="deep_research",
        arguments=(
            ArgumentSpec(
                name="final_prompt",
                required=True,
                description=(
                    "Research topic/query. Field name reused from ms-smith-nexus "
                    "proto/deep_research_message.proto StartResearchRequest.final_prompt "
                    "-- see findings.md. The session lifecycle (session_id, polling, "
                    "config) is out of scope for this single-shot Router argument."
                ),
            ),
        ),
        schema_source="partial_reuse",
    ),
    IntentSpec(name="unknown", executable=False),
)


_CLARIFICATION_TEMPLATES: dict[str, Clarification] = {
    "creative_ambiguous_type": Clarification(
        question="Bạn muốn tạo loại thiết kế nào?",
        options=[
            ClarificationOption(id="create_ai_art", label="Tranh/ảnh AI", value="Tạo ảnh AI"),
            ClarificationOption(id="generate_logo", label="Logo", value="Tạo logo"),
            ClarificationOption(id="generate_poster", label="Poster", value="Tạo poster"),
        ],
    ),
    "create_vs_edit": Clarification(
        question="Bạn muốn tạo ảnh mới hay chỉnh sửa ảnh này?",
        options=[
            ClarificationOption(id="create", label="Tạo ảnh mới", value="Tạo ảnh mới"),
            ClarificationOption(id="edit", label="Chỉnh sửa ảnh này", value="Chỉnh sửa ảnh này"),
        ],
    ),
    "missing_image": Clarification(
        question="Bạn cần mình xử lý ảnh nào? Vui lòng đính kèm ảnh.",
        options=[],
    ),
    "missing_style": Clarification(
        question="Bạn muốn ảnh theo phong cách nào?",
        options=[
            ClarificationOption(id="ghibli", label="Ghibli", value="ghibli"),
            ClarificationOption(id="anime", label="Anime", value="anime"),
            ClarificationOption(id="disney", label="Disney", value="disney"),
        ],
    ),
    "dependency_reference_ambiguous": Clarification(
        question="Bạn muốn dùng kết quả nghiên cứu nào để tạo poster?",
        options=[],
    ),
}


class ReferenceIntentRegistry:
    taxonomy_version = TAXONOMY_VERSION

    def __init__(self, specs: tuple[IntentSpec, ...] = _SPECS):
        self._specs = {spec.name: spec for spec in specs}

    def get(self, name: str) -> IntentSpec | None:
        return self._specs.get(name)

    def exists(self, name: str) -> bool:
        return name in self._specs

    def is_executable(self, name: str) -> bool:
        spec = self._specs.get(name)
        return bool(spec and spec.executable and not spec.archived)

    @property
    def executable_names(self) -> list[str]:
        return [
            spec.name
            for spec in self._specs.values()
            if spec.executable and not spec.archived
        ]

    def clarification_template(self, key: str) -> Clarification:
        return _CLARIFICATION_TEMPLATES[key].model_copy(deep=True)

    def creative_children(self) -> list[str]:
        # Archived creative children remain for historical clarification templates
        # / deferred scenarios; V1 active set only exposes create_ai_art.
        return ["create_ai_art"]


def registry_with_archived_active(
    specs: tuple[IntentSpec, ...] | None = None,
) -> ReferenceIntentRegistry:
    """Test helper: treat archived specs as active so historical fixtures still validate."""
    from dataclasses import replace

    source = specs if specs is not None else _SPECS
    return ReferenceIntentRegistry(
        tuple(replace(spec, archived=False) for spec in source)
    )

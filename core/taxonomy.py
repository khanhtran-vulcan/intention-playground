from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

import regex
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


INTENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
MAX_KNOWN_INTENTS = 50
MAX_EXAMPLES_PER_INTENT = 100
MAX_RULE_LENGTH = 500
MAX_PROMPT_SECTION_LENGTH = 1_000


class OutputProperty(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    type: Literal["string"] = "string"
    description: str | None = Field(default=None, max_length=500)
    required: bool = False
    enum: list[str] | None = None
    max_words: int | None = Field(default=None, gt=0, le=100)

    @model_validator(mode="after")
    def validate_constraints(self) -> "OutputProperty":
        if self.enum is not None:
            cleaned = [value.strip() for value in self.enum]
            if any(not value for value in cleaned):
                raise ValueError("property enum cannot contain blank values")
            if len(cleaned) != len(set(cleaned)):
                raise ValueError("property enum values must be unique")
            self.enum = cleaned
        return self


class IntentDefinition(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str
    parent: str | None = None
    prompt_section: str = Field(min_length=1, max_length=MAX_PROMPT_SECTION_LENGTH)
    examples: list[str] = Field(default_factory=list, max_length=MAX_EXAMPLES_PER_INTENT)
    image_examples: list[str] = Field(
        default_factory=list, max_length=MAX_EXAMPLES_PER_INTENT
    )
    patterns: list[str] = Field(default_factory=list)
    required_context: Literal["image"] | None = None
    rule_priority: int = Field(default=0, ge=0, le=1_000)
    properties: dict[str, OutputProperty] = Field(default_factory=dict)

    @field_validator("name", "parent")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is not None and not INTENT_NAME_PATTERN.fullmatch(value):
            raise ValueError("must match ^[a-z][a-z0-9_]*$")
        return value

    @field_validator("examples", "image_examples")
    @classmethod
    def validate_examples(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("examples cannot contain blank values")
        if len(set(value.casefold() for value in cleaned)) != len(cleaned):
            raise ValueError("examples must be unique within an intent")
        return cleaned

    @field_validator("patterns")
    @classmethod
    def validate_patterns(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        for pattern in cleaned:
            if not pattern:
                raise ValueError("patterns cannot contain blank values")
            if len(pattern) > MAX_RULE_LENGTH:
                raise ValueError(f"patterns cannot exceed {MAX_RULE_LENGTH} characters")
            try:
                regex.compile(pattern, regex.IGNORECASE)
            except regex.error as exc:
                raise ValueError(f"invalid regex {pattern!r}: {exc}") from exc
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("patterns must be unique within an intent")
        return cleaned

    @field_validator("properties")
    @classmethod
    def validate_property_names(
        cls, values: dict[str, OutputProperty]
    ) -> dict[str, OutputProperty]:
        for name in values:
            if not INTENT_NAME_PATTERN.fullmatch(name):
                raise ValueError(f"invalid property name {name!r}")
        return values

    @model_validator(mode="after")
    def validate_intent(self) -> "IntentDefinition":
        if self.name != "unknown" and not (self.examples or self.image_examples):
            raise ValueError("known intents require at least one training example")
        if len(self.examples) + len(self.image_examples) > MAX_EXAMPLES_PER_INTENT:
            raise ValueError(
                f"an intent cannot exceed {MAX_EXAMPLES_PER_INTENT} total examples"
            )
        if self.name == "unknown" and (
            self.patterns or self.parent or self.required_context or self.properties
        ):
            raise ValueError("the reserved unknown intent cannot define routing metadata")
        return self


class Taxonomy(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    intents: list[IntentDefinition]

    @model_validator(mode="after")
    def validate_taxonomy(self) -> "Taxonomy":
        names = [intent.name for intent in self.intents]
        if len(names) != len(set(names)):
            raise ValueError("intent names must be unique")
        if names.count("unknown") != 1:
            raise ValueError("taxonomy must define exactly one reserved unknown intent")
        if len(self.known_intents) < 2:
            raise ValueError("taxonomy requires at least two known intents")
        if len(self.known_intents) > MAX_KNOWN_INTENTS:
            raise ValueError(f"taxonomy supports at most {MAX_KNOWN_INTENTS} known intents")

        by_name = {intent.name: intent for intent in self.intents}
        for intent in self.known_intents:
            if intent.parent not in (None, *by_name):
                raise ValueError(f"parent {intent.parent!r} does not exist")
            if intent.parent == "unknown":
                raise ValueError("unknown cannot be an intent parent")
            visited = {intent.name}
            parent = intent.parent
            while parent is not None:
                if parent in visited:
                    raise ValueError(f"intent hierarchy contains a cycle at {parent!r}")
                visited.add(parent)
                parent = by_name[parent].parent

        example_owners: dict[tuple[str, bool], str] = {}
        for intent in self.intents:
            for has_image, examples in (
                (False, intent.examples),
                (True, intent.image_examples),
            ):
                for example in examples:
                    key = (example.casefold(), has_image)
                    owner = example_owners.get(key)
                    if owner is not None and owner != intent.name:
                        raise ValueError(
                            f"example {example!r} appears in both {owner!r} and {intent.name!r}"
                        )
                    example_owners[key] = intent.name
        return self

    @property
    def known_intents(self) -> list[IntentDefinition]:
        return [intent for intent in self.intents if intent.name != "unknown"]

    @property
    def labels(self) -> list[str]:
        return [intent.name for intent in self.known_intents] + ["unknown"]

    def get(self, name: str) -> IntentDefinition:
        for intent in self.intents:
            if intent.name == name:
                return intent
        raise KeyError(name)

    def ancestors(self, name: str) -> list[str]:
        result: list[str] = []
        parent = self.get(name).parent
        while parent is not None:
            result.append(parent)
            parent = self.get(parent).parent
        return result

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return ancestor in self.ancestors(descendant)

    def canonical_json(self) -> str:
        payload = self.model_dump(mode="json")
        payload["intents"] = sorted(payload["intents"], key=lambda item: item["name"])
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def load_taxonomy(path: Path) -> Taxonomy:
    return Taxonomy.model_validate_json(path.read_text(encoding="utf-8"))


def dump_taxonomy(taxonomy: Taxonomy) -> str:
    return json.dumps(taxonomy.model_dump(mode="json"), ensure_ascii=False, indent=2)

"""Public Client contract and internal trace models for the Reference Runtime.

Two clearly separated families of types live here:

- Public: what a Client would see on BE §10 V2 wire (camelCase JSON, outcome wire
  prefix, no reasonCode / goals / stage traces).
- Internal: `InternalTrace` and related diagnostic models — UI inspector only.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA_VERSION = "reference-v1"
OUTCOME_WIRE_PREFIX = "INTENTION_DETECT_OUTCOME_"
MAX_CLARIFICATION_OPTIONS = 3
MAX_CLARIFICATION_TURNS = 3

# Public response keys allowed by BE §10 (camelCase on the wire).
PUBLIC_RESPONSE_KEYS = frozenset(
    {
        "outcome",
        "name",
        "arguments",
        "responseText",
        "clarification",
        "usageModel",
        "usage",
    }
)

PUBLIC_REQUEST_KEYS = frozenset({"messages", "tools"})


class Outcome(str, Enum):
    RESPONSE = "RESPONSE"
    ROUTE = "ROUTE"
    CLARIFY = "CLARIFY"
    FALLBACK = "FALLBACK"
    REJECT = "REJECT"

    @property
    def wire_value(self) -> str:
        return f"{OUTCOME_WIRE_PREFIX}{self.value}"

    @classmethod
    def from_wire(cls, value: str) -> "Outcome":
        if value.startswith(OUTCOME_WIRE_PREFIX):
            return cls(value[len(OUTCOME_WIRE_PREFIX) :])
        return cls(value)


# --------------------------------------------------------------------------- #
# Public request (Python models; serialize via to_public_request)
# --------------------------------------------------------------------------- #


class Media(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    mime_type: str = Field(min_length=1)
    data: str = Field(min_length=1, repr=False)
    filename: str | None = None


class Message(BaseModel):
    """One conversation turn.

    `capability_name` / `artifact_type` are demo-only tags (not on the public wire)
    so the Reference Runtime can resolve prior capability results in history.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    role: Literal["user", "assistant", "capability"]
    content: str | None = None
    files: list[Media] = Field(default_factory=list)
    capability_name: str | None = None
    artifact_type: str | None = None

    @model_validator(mode="after")
    def require_content_or_files(self) -> "Message":
        if not (self.content or self.files):
            raise ValueError("a message requires content or files")
        return self


class ToolFunction(BaseModel):
    name: str = Field(min_length=1)


class Tool(BaseModel):
    function: ToolFunction


class RequestContext(BaseModel):
    """Demo/session context — not part of BE §10 public request."""

    clarification_turn_count: int = Field(default=0, ge=0)


class RoutingRequest(BaseModel):
    schema_version: str = SCHEMA_VERSION
    messages: list[Message] = Field(min_length=1)
    tools: list[Tool] = Field(default_factory=list)
    context: RequestContext = Field(default_factory=RequestContext)

    @property
    def tool_names(self) -> list[str]:
        return [tool.function.name for tool in self.tools]

    @property
    def latest_user_message(self) -> Message | None:
        for message in reversed(self.messages):
            if message.role == "user":
                return message
        return None

    def has_images_in_latest_user_turn(self) -> bool:
        message = self.latest_user_message
        return bool(message and message.files)


# --------------------------------------------------------------------------- #
# Public response (Python models; serialize via to_public_response)
# --------------------------------------------------------------------------- #


class ClarificationOption(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=500)


class Clarification(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=500)
    options: list[ClarificationOption] = Field(
        default_factory=list, max_length=MAX_CLARIFICATION_OPTIONS
    )


class UsageModel(BaseModel):
    provider: str
    model: str


class Usage(BaseModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


_OUTCOME_APPLICABLE_FIELDS: dict[Outcome, frozenset[str]] = {
    Outcome.ROUTE: frozenset({"name", "arguments"}),
    Outcome.RESPONSE: frozenset({"response_text"}),
    Outcome.CLARIFY: frozenset({"clarification"}),
    Outcome.FALLBACK: frozenset(),
    Outcome.REJECT: frozenset({"response_text"}),
}
_OUTCOME_SCOPED_FIELDS = frozenset({"name", "arguments", "response_text", "clarification"})


class RoutingResponse(BaseModel):
    """Internal Python shape. Use `to_public_response` for Client-facing JSON."""

    model_config = ConfigDict(str_strip_whitespace=True)

    schema_version: str = SCHEMA_VERSION
    outcome: Outcome
    name: str | None = None
    arguments: str | None = None
    response_text: str | None = Field(default=None, min_length=1)
    clarification: Clarification | None = None
    usage_model: UsageModel | None = None
    usage: Usage | None = None

    @field_validator("arguments")
    @classmethod
    def validate_arguments_json(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"arguments must be JSON-encoded: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("arguments must encode a JSON object")
        return value

    @model_validator(mode="after")
    def enforce_outcome_applicability(self) -> "RoutingResponse":
        applicable = _OUTCOME_APPLICABLE_FIELDS[self.outcome]
        for field_name in _OUTCOME_SCOPED_FIELDS:
            value = getattr(self, field_name)
            if field_name in applicable and value is None:
                raise ValueError(
                    f"{field_name!r} is required for outcome {self.outcome.value}"
                )
            if field_name not in applicable and value is not None:
                raise ValueError(
                    f"{field_name!r} must be omitted for outcome {self.outcome.value}"
                )
        if self.outcome == Outcome.ROUTE and not (self.name or "").strip():
            raise ValueError("ROUTE requires a non-empty name")
        return self

    def arguments_dict(self) -> dict[str, Any]:
        return json.loads(self.arguments) if self.arguments else {}


def to_public_request(request: RoutingRequest) -> dict[str, Any]:
    """BE §10 request JSON — camelCase, no invented fields."""
    messages: list[dict[str, Any]] = []
    for message in request.messages:
        # Map capability role to assistant for public wire (capability is demo-only).
        role = "assistant" if message.role == "capability" else message.role
        item: dict[str, Any] = {"role": role}
        if message.content is not None:
            item["content"] = message.content
        if message.files:
            item["files"] = [
                {
                    "mimeType": media.mime_type,
                    "data": media.data,
                    **({"filename": media.filename} if media.filename else {}),
                }
                for media in message.files
            ]
        messages.append(item)

    payload: dict[str, Any] = {"messages": messages}
    if request.tools:
        payload["tools"] = [{"function": {"name": tool.function.name}} for tool in request.tools]
    assert set(payload) <= PUBLIC_REQUEST_KEYS
    return payload


def to_public_response(response: RoutingResponse) -> dict[str, Any]:
    """BE §10 response JSON — wire outcome prefix, camelCase, omit N/A fields."""
    payload: dict[str, Any] = {"outcome": response.outcome.wire_value}

    if response.outcome == Outcome.ROUTE:
        payload["name"] = response.name
        payload["arguments"] = response.arguments
    elif response.outcome in {Outcome.RESPONSE, Outcome.REJECT}:
        payload["responseText"] = response.response_text
    elif response.outcome == Outcome.CLARIFY:
        clarification: dict[str, Any] = {"question": response.clarification.question}
        if response.clarification and response.clarification.options:
            clarification["options"] = [
                {"id": opt.id, "label": opt.label, "value": opt.value}
                for opt in response.clarification.options
            ]
        payload["clarification"] = clarification

    if response.usage_model is not None:
        payload["usageModel"] = {
            "provider": response.usage_model.provider,
            "model": response.usage_model.model,
        }
    if response.usage is not None:
        payload["usage"] = {
            "promptTokens": response.usage.prompt_tokens,
            "completionTokens": response.usage.completion_tokens,
            "totalTokens": response.usage.total_tokens,
        }

    extra = set(payload) - PUBLIC_RESPONSE_KEYS
    if extra:
        raise ValueError(f"public response contains forbidden keys: {sorted(extra)}")
    return payload


# --------------------------------------------------------------------------- #
# Internal trace (never sent to a Client)
# --------------------------------------------------------------------------- #


class StageTrace(BaseModel):
    stage: str
    latency_ms: float = Field(ge=0)
    detail: dict[str, Any] = Field(default_factory=dict)


class DependencyEdge(BaseModel):
    intent: str
    depends_on: str


class RouterDecisionTrace(BaseModel):
    """Sanitized internal representation of the Structured LLM Router output."""

    provider: str
    model: str | None = None
    proposed_outcome: Outcome
    response_text: str | None = None
    goals: list[str] = Field(default_factory=list)
    candidate_intents: list[str] = Field(default_factory=list)
    dependencies: list[DependencyEdge] = Field(default_factory=list)
    selected_intent: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    missing_inputs: list[str] = Field(default_factory=list)
    reason_code: str = Field(min_length=1)
    prompt_version: str | None = None
    registry_version: str | None = None
    usage_model: UsageModel | None = None
    usage: Usage | None = None
    provider_error_code: Literal[
        "PROVIDER_MISSING_CREDENTIALS",
        "PROVIDER_TIMEOUT",
        "PROVIDER_REQUEST_FAILED",
        "INVALID_PROVIDER_OUTPUT",
    ] | None = None


ClassifierCandidateTrace = RouterDecisionTrace


class ValidatorTrace(BaseModel):
    passed_predicates: list[str] = Field(default_factory=list)
    failed_predicates: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class PolicyTrace(BaseModel):
    decision: Literal["allow", "block"]
    category: str | None = None
    rule_id: str | None = None
    rule_version: str = Field(min_length=1)
    mixed_script_suspected: bool = False
    matched_surface: Literal["canonical", "folded"] | None = None


class InternalTrace(BaseModel):
    request_id: str
    stages: list[StageTrace] = Field(default_factory=list)
    # `normalized_text` remains the folded surface for UI / legacy inspectors.
    normalized_text: str | None = None
    canonical_text: str | None = None
    pre_router_hit: bool = False
    pre_router_rule_version: str = Field(min_length=1)
    policy: PolicyTrace
    router_decision: RouterDecisionTrace | None = None
    validator: ValidatorTrace | None = None
    taxonomy_version: str = Field(min_length=1)
    prompt_version: str | None = None
    registry_version: str | None = None
    final_reason_code: str = Field(min_length=1)

    @property
    def tier0_hit(self) -> bool:
        return self.pre_router_hit

    @property
    def tier0_rule_version(self) -> str:
        return self.pre_router_rule_version

    @property
    def classifier_candidate(self) -> RouterDecisionTrace | None:
        return self.router_decision

    @property
    def total_latency_ms(self) -> float:
        return sum(stage.latency_ms for stage in self.stages)


class ReferenceRunResult(BaseModel):
    """Split of public response and internal trace, returned by `ReferenceRouter.route()`."""

    response: RoutingResponse
    trace: InternalTrace

    def public_request_json(self, request: RoutingRequest) -> dict[str, Any]:
        return to_public_request(request)

    def public_response_json(self) -> dict[str, Any]:
        return to_public_response(self.response)

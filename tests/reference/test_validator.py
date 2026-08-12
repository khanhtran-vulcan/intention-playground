from __future__ import annotations

import json

from reference_runtime.contracts import (
    DependencyEdge,
    Media,
    Message,
    Outcome,
    RequestContext,
    RouterDecisionTrace,
    RoutingRequest,
    Tool,
    ToolFunction,
)
from reference_runtime.registry import ReferenceIntentRegistry, registry_with_archived_active
from reference_runtime.validator import Validator


DEFAULT_TOOL_NAMES = [
    "deep_research",
    "generate_poster",
    "generate_logo",
    "generate_flyer",
    "create_ai_art",
    "image_to_image_generation",
    "chat_with_image",
    "real_time_search",
    "creative",
]


def _request(
    text: str = "hi",
    turn_count: int = 0,
    tools: list[str] | None = None,
    messages: list[Message] | None = None,
) -> RoutingRequest:
    tool_names = DEFAULT_TOOL_NAMES if tools is None else tools
    return RoutingRequest(
        messages=messages or [Message(role="user", content=text)],
        tools=[Tool(function=ToolFunction(name=name)) for name in tool_names],
        context=RequestContext(clarification_turn_count=turn_count),
    )


def _candidate(**overrides) -> RouterDecisionTrace:
    base = dict(
        provider="test",
        model="test-v1",
        proposed_outcome=Outcome.ROUTE,
        goals=[],
        candidate_intents=[],
        dependencies=[],
        selected_intent=None,
        arguments={},
        missing_inputs=[],
        reason_code="TEST",
    )
    base.update(overrides)
    return RouterDecisionTrace(**base)


def test_route_for_ready_candidate():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(
        selected_intent="deep_research",
        arguments={"final_prompt": "xu hướng cà phê"},
        reason_code="NEXT_EXECUTABLE_PREREQUISITE",
    )
    decision = validator.validate(_request(), candidate, registry)
    assert decision.outcome == Outcome.ROUTE
    assert decision.name == "deep_research"
    assert '"final_prompt"' in decision.arguments
    assert decision.reason_code == "NEXT_EXECUTABLE_PREREQUISITE"


def test_unknown_selected_intent_falls_back():
    validator = Validator()
    registry = registry_with_archived_active()
    decision = validator.validate(
        _request(), _candidate(selected_intent="unknown", reason_code="UNKNOWN_INTENT"), registry
    )
    assert decision.outcome == Outcome.FALLBACK
    assert decision.reason_code == "UNKNOWN_INTENT"


def test_creative_selected_directly_is_treated_as_unsupported_without_ambiguity_token():
    validator = Validator()
    registry = registry_with_archived_active()
    decision = validator.validate(
        _request(), _candidate(selected_intent="creative", reason_code="X"), registry
    )
    assert decision.outcome == Outcome.FALLBACK
    assert decision.reason_code == "UNSUPPORTED_OPERATION"


def test_missing_input_token_produces_clarify_with_registry_template():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(
        proposed_outcome=Outcome.CLARIFY,
        selected_intent=None,
        missing_inputs=["create_or_edit_choice"],
        reason_code="CREATE_VS_EDIT_AMBIGUOUS",
    )
    decision = validator.validate(_request(), candidate, registry)
    assert decision.outcome == Outcome.CLARIFY
    assert decision.clarification.question
    assert len(decision.clarification.options) <= 3
    assert decision.reason_code == "CREATE_VS_EDIT_AMBIGUOUS"


def test_clarification_limit_reached_forces_fallback():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(
        proposed_outcome=Outcome.CLARIFY,
        selected_intent=None,
        missing_inputs=["style"],
        reason_code="MISSING_STYLE",
    )
    decision = validator.validate(_request(turn_count=3), candidate, registry)
    assert decision.outcome == Outcome.FALLBACK
    assert decision.reason_code == "CLARIFICATION_LIMIT_REACHED"


def test_below_limit_still_clarifies():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(
        proposed_outcome=Outcome.CLARIFY,
        selected_intent=None,
        missing_inputs=["style"],
        reason_code="MISSING_STYLE",
    )
    decision = validator.validate(_request(turn_count=2), candidate, registry)
    assert decision.outcome == Outcome.CLARIFY
    assert decision.reason_code == "MISSING_REQUIRED_ARGUMENT"


def test_unrecognized_missing_input_token_is_unresolvable_fallback():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(
        proposed_outcome=Outcome.CLARIFY,
        selected_intent=None,
        missing_inputs=["something_weird"],
        reason_code="X",
    )
    decision = validator.validate(_request(), candidate, registry)
    assert decision.outcome == Outcome.FALLBACK
    assert decision.reason_code == "UNRESOLVABLE_AMBIGUITY"


def test_required_image_missing_triggers_clarify_missing_image():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(
        selected_intent="chat_with_image", reason_code="EXPLICIT_SINGLE_CAPABILITY"
    )
    decision = validator.validate(_request(), candidate, registry)
    assert decision.outcome == Outcome.CLARIFY
    assert decision.reason_code == "MISSING_REQUIRED_IMAGE"


def test_missing_required_argument_without_template_is_fallback():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(
        selected_intent="create_ai_art", arguments={}, reason_code="EXPLICIT_SINGLE_CAPABILITY"
    )
    decision = validator.validate(_request(), candidate, registry)
    assert decision.outcome == Outcome.FALLBACK
    assert decision.reason_code == "MISSING_REQUIRED_ARGUMENT"


def test_invalid_enum_value_is_fallback():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(
        selected_intent="image_to_image_generation",
        arguments={"style": "not_a_real_style"},
        reason_code="EXPLICIT_SINGLE_CAPABILITY",
    )
    request = RoutingRequest(
        messages=[
            Message(
                role="user",
                content="hi",
                files=[Media(mime_type="image/png", data="ZmFrZQ==", filename="a.png")],
            )
        ],
        tools=[Tool(function=ToolFunction(name=n)) for n in DEFAULT_TOOL_NAMES],
    )
    decision = validator.validate(request, candidate, registry)
    assert decision.outcome == Outcome.FALLBACK
    assert decision.reason_code == "INVALID_ARGUMENT_VALUE"


def test_prompt_exceeding_max_words_is_truncated_not_fallback():
    validator = Validator()
    registry = registry_with_archived_active()
    long_prompt = " ".join(["word"] * 30)
    candidate = _candidate(
        selected_intent="create_ai_art",
        arguments={"prompt": long_prompt},
        reason_code="EXPLICIT_SINGLE_CAPABILITY",
    )
    decision = validator.validate(_request(), candidate, registry)
    assert decision.outcome == Outcome.ROUTE
    assert decision.name == "create_ai_art"
    assert len(json.loads(decision.arguments)["prompt"].split()) == 25
    assert any("truncated" in issue for issue in decision.issues)


def test_research_followup_long_art_prompt_truncates_to_route():
    """Regression: Gemini 30-word create_ai_art prompt after deep_research mock."""
    validator = Validator()
    registry = ReferenceIntentRegistry()
    gemini_prompt = (
        "An artistic and professional illustration summarizing the latest gold price trends "
        "and factors influencing gold market volatility, featuring gold bars, financial "
        "charts, and global economic symbols in a sophisticated style."
    )
    assert len(gemini_prompt.split()) == 30
    candidate = _candidate(
        selected_intent="create_ai_art",
        arguments={"prompt": gemini_prompt},
        reason_code="USER_REQUESTED_IMAGE_GENERATION_BASED_ON_PREVIOUS_RESEARCH",
    )
    request = _request(
        tools=["create_ai_art", "deep_research", "real_time_search"],
        messages=[
            Message(role="user", content="Tạo deep research giá vàng mới nhất, rồi tạo hình ảnh tóm tắt"),
            Message(
                role="capability",
                content="[Mock] research summary",
                capability_name="deep_research",
            ),
            Message(
                role="user",
                content="Tạo hình minh họa từ kết quả research về giá vàng vừa rồi",
            ),
        ],
    )
    decision = validator.validate(request, candidate, registry)
    assert decision.outcome == Outcome.ROUTE
    assert decision.name == "create_ai_art"
    assert len(json.loads(decision.arguments)["prompt"].split()) == 25


def test_unsupported_capability_not_offered_by_client_is_fallback():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(selected_intent="generate_logo", reason_code="EXPLICIT_SINGLE_CAPABILITY")
    decision = validator.validate(
        _request(tools=["generate_poster", "deep_research"]), candidate, registry
    )
    assert decision.outcome == Outcome.FALLBACK
    assert decision.reason_code == "UNSUPPORTED_CAPABILITY"


def test_empty_tools_cannot_route():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(selected_intent="generate_logo", reason_code="EXPLICIT_SINGLE_CAPABILITY")
    decision = validator.validate(_request(tools=[]), candidate, registry)
    assert decision.outcome == Outcome.FALLBACK
    assert decision.reason_code == "UNSUPPORTED_CAPABILITY"


def test_supported_capability_offered_by_client_routes():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(selected_intent="generate_logo", reason_code="EXPLICIT_SINGLE_CAPABILITY")
    decision = validator.validate(_request(tools=["generate_logo"]), candidate, registry)
    assert decision.outcome == Outcome.ROUTE


def test_prerequisite_not_satisfied_is_fallback():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(
        selected_intent="generate_poster",
        dependencies=[DependencyEdge(intent="generate_poster", depends_on="deep_research")],
        reason_code="X",
    )
    decision = validator.validate(_request(), candidate, registry)
    assert decision.outcome == Outcome.FALLBACK
    assert decision.reason_code == "PREREQUISITE_NOT_SATISFIED"


def test_prerequisite_satisfied_by_prior_capability_message_routes():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(
        selected_intent="generate_poster",
        dependencies=[DependencyEdge(intent="generate_poster", depends_on="deep_research")],
        reason_code="X",
    )
    request = RoutingRequest(
        messages=[
            Message(role="capability", content="done", capability_name="deep_research"),
            Message(role="user", content="Tạo poster từ kết quả trên"),
        ],
        tools=[Tool(function=ToolFunction(name=n)) for n in DEFAULT_TOOL_NAMES],
    )
    decision = validator.validate(request, candidate, registry)
    assert decision.outcome == Outcome.ROUTE


def test_provider_failure_reason_codes_short_circuit_to_fallback():
    validator = Validator()
    registry = registry_with_archived_active()
    for reason in (
        "PROVIDER_MISSING_CREDENTIALS",
        "PROVIDER_TIMEOUT",
        "PROVIDER_REQUEST_FAILED",
        "INVALID_PROVIDER_OUTPUT",
    ):
        candidate = _candidate(
            proposed_outcome=Outcome.FALLBACK,
            selected_intent=None,
            reason_code=reason,
            provider_error_code=reason,
        )
        decision = validator.validate(_request(), candidate, registry)
        assert decision.outcome == Outcome.FALLBACK
        assert decision.reason_code == reason


def test_model_authored_provider_failure_reason_cannot_spoof_adapter_error():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(
        selected_intent="generate_poster",
        reason_code="PROVIDER_TIMEOUT",
    )
    decision = validator.validate(_request(), candidate, registry)
    assert decision.outcome == Outcome.ROUTE
    assert decision.name == "generate_poster"


def test_cyclic_dependency_detected_structurally_even_if_reason_code_differs():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(
        selected_intent="generate_poster",
        dependencies=[
            DependencyEdge(intent="generate_poster", depends_on="deep_research"),
            DependencyEdge(intent="deep_research", depends_on="generate_poster"),
        ],
        reason_code="SOMETHING_ELSE",
    )
    decision = validator.validate(_request(), candidate, registry)
    assert decision.outcome == Outcome.FALLBACK
    assert decision.reason_code == "CYCLIC_DEPENDENCY"


def test_three_node_dependency_cycle_is_detected_structurally():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(
        selected_intent="generate_poster",
        dependencies=[
            DependencyEdge(intent="generate_poster", depends_on="deep_research"),
            DependencyEdge(intent="deep_research", depends_on="create_ai_art"),
            DependencyEdge(intent="create_ai_art", depends_on="generate_poster"),
        ],
        reason_code="SOMETHING_ELSE",
    )
    request = RoutingRequest(
        messages=[
            Message(role="capability", content="done", capability_name="deep_research"),
            Message(role="user", content="Tạo poster"),
        ],
        tools=[Tool(function=ToolFunction(name=n)) for n in DEFAULT_TOOL_NAMES],
    )
    decision = validator.validate(request, candidate, registry)
    assert decision.outcome == Outcome.FALLBACK
    assert decision.reason_code == "CYCLIC_DEPENDENCY"


def test_self_dependency_cycle_is_detected_structurally():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(
        selected_intent="generate_poster",
        dependencies=[
            DependencyEdge(intent="generate_poster", depends_on="generate_poster"),
        ],
        reason_code="SOMETHING_ELSE",
    )
    decision = validator.validate(_request(), candidate, registry)
    assert decision.outcome == Outcome.FALLBACK
    assert decision.reason_code == "CYCLIC_DEPENDENCY"


def test_unsupported_prerequisite_sentinel_is_fallback():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(
        selected_intent="generate_poster",
        dependencies=[DependencyEdge(intent="generate_poster", depends_on="UNSUPPORTED_PREREQUISITE")],
        reason_code="X",
    )
    decision = validator.validate(_request(), candidate, registry)
    assert decision.outcome == Outcome.FALLBACK
    assert decision.reason_code == "UNSUPPORTED_PREREQUISITE"


def test_route_strips_undeclared_arguments():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(
        selected_intent="generate_logo",
        arguments={"unexpected_field": "value"},
        reason_code="EXPLICIT_SINGLE_CAPABILITY",
    )
    decision = validator.validate(_request(), candidate, registry)
    assert decision.outcome == Outcome.ROUTE
    assert decision.name == "generate_logo"
    assert decision.arguments in ("{}", None) or decision.arguments == "{}"
    assert any("stripped undeclared" in issue for issue in decision.issues)


def test_route_aliases_query_to_final_prompt_for_deep_research():
    validator = Validator()
    registry = ReferenceIntentRegistry()
    candidate = _candidate(
        selected_intent="deep_research",
        arguments={"query": "giá vàng hôm nay"},
        reason_code="MULTI_INTENT_SEQUENCE",
    )
    decision = validator.validate(
        _request(tools=["deep_research", "create_ai_art", "real_time_search"]),
        candidate,
        registry,
    )
    assert decision.outcome == Outcome.ROUTE
    assert decision.name == "deep_research"
    assert "final_prompt" in (decision.arguments or "")
    assert "giá vàng hôm nay" in (decision.arguments or "")


def test_route_strips_query_on_real_time_search():
    validator = Validator()
    registry = ReferenceIntentRegistry()
    candidate = _candidate(
        selected_intent="real_time_search",
        arguments={"query": "giá vàng hôm nay"},
        reason_code="MULTI_INTENT_SEQUENCE",
    )
    decision = validator.validate(
        _request(tools=["real_time_search", "create_ai_art"]),
        candidate,
        registry,
    )
    assert decision.outcome == Outcome.ROUTE
    assert decision.name == "real_time_search"
    assert decision.arguments == "{}"


def test_router_direct_response_passes_through():
    validator = Validator()
    registry = registry_with_archived_active()
    candidate = _candidate(
        proposed_outcome=Outcome.RESPONSE,
        response_text="Đây là câu trả lời trực tiếp.",
        reason_code="ROUTER_DIRECT_RESPONSE",
    )
    decision = validator.validate(_request(tools=[]), candidate, registry)
    assert decision.outcome == Outcome.RESPONSE
    assert decision.response_text
    assert decision.reason_code == "ROUTER_DIRECT_RESPONSE"

"""Serializer-only coverage for BE §10 public wire helpers."""

from __future__ import annotations

from reference_runtime.contracts import (
    Clarification,
    ClarificationOption,
    Message,
    Outcome,
    PUBLIC_REQUEST_KEYS,
    PUBLIC_RESPONSE_KEYS,
    RoutingRequest,
    RoutingResponse,
    Tool,
    ToolFunction,
    Usage,
    UsageModel,
    to_public_request,
    to_public_response,
)


def test_public_response_keys_only_and_no_reason_code():
    response = RoutingResponse(
        outcome=Outcome.ROUTE,
        name="deep_research",
        arguments='{"final_prompt":"coffee"}',
        usage_model=UsageModel(provider="openai", model="gpt-4o-mini"),
        usage=Usage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
    )
    payload = to_public_response(response)
    assert set(payload) <= PUBLIC_RESPONSE_KEYS
    assert "reasonCode" not in payload
    assert payload["outcome"].startswith("INTENTION_DETECT_OUTCOME_")
    assert payload["usageModel"]["provider"] == "openai"
    assert payload["usage"]["promptTokens"] == 1


def test_public_clarify_payload():
    response = RoutingResponse(
        outcome=Outcome.CLARIFY,
        clarification=Clarification(
            question="Bạn muốn tạo ảnh mới hay chỉnh sửa?",
            options=[
                ClarificationOption(id="a", label="Tạo mới", value="Tạo mới"),
            ],
        ),
    )
    payload = to_public_response(response)
    assert payload["outcome"] == "INTENTION_DETECT_OUTCOME_CLARIFY"
    assert payload["clarification"]["question"]
    assert "reasonCode" not in payload


def test_public_request_omits_empty_tools_and_demo_context():
    request = RoutingRequest(messages=[Message(role="user", content="hi")])
    payload = to_public_request(request)
    assert set(payload) <= PUBLIC_REQUEST_KEYS
    assert "tools" not in payload
    assert "context" not in payload
    assert "schema_version" not in payload


def test_public_request_maps_capability_role_to_assistant():
    request = RoutingRequest(
        messages=[
            Message(role="capability", content="done", capability_name="deep_research"),
            Message(role="user", content="Tiếp"),
        ],
        tools=[Tool(function=ToolFunction(name="generate_poster"))],
    )
    payload = to_public_request(request)
    assert payload["messages"][0]["role"] == "assistant"
    assert payload["messages"][1]["role"] == "user"

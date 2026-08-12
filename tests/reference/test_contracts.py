from __future__ import annotations

import pytest
from pydantic import ValidationError

from reference_runtime.contracts import (
    Clarification,
    ClarificationOption,
    Message,
    Outcome,
    PUBLIC_RESPONSE_KEYS,
    RoutingRequest,
    RoutingResponse,
    Tool,
    ToolFunction,
    to_public_request,
    to_public_response,
)


def test_message_requires_content_or_files():
    Message(role="user", content="hello")
    with pytest.raises(ValidationError):
        Message(role="user")


def test_routing_request_requires_at_least_one_message():
    with pytest.raises(ValidationError):
        RoutingRequest(messages=[])


def test_route_response_requires_name_and_arguments():
    response = RoutingResponse(
        outcome=Outcome.ROUTE,
        name="generate_poster",
        arguments="{}",
    )
    assert response.arguments_dict() == {}
    with pytest.raises(ValidationError):
        RoutingResponse(outcome=Outcome.ROUTE)


def test_route_response_rejects_response_text_and_clarification():
    with pytest.raises(ValidationError):
        RoutingResponse(
            outcome=Outcome.ROUTE,
            name="generate_poster",
            arguments="{}",
            response_text="should not be here",
        )


def test_response_requires_response_text_only():
    response = RoutingResponse(
        outcome=Outcome.RESPONSE,
        response_text="Chào bạn!",
    )
    assert response.name is None
    assert response.arguments is None
    with pytest.raises(ValidationError):
        RoutingResponse(outcome=Outcome.RESPONSE)


def test_clarify_requires_clarification_only():
    response = RoutingResponse(
        outcome=Outcome.CLARIFY,
        clarification=Clarification(
            question="Bạn muốn tạo ảnh mới hay chỉnh sửa ảnh này?",
            options=[
                ClarificationOption(id="create", label="Tạo ảnh mới", value="Tạo ảnh mới"),
            ],
        ),
    )
    assert response.clarification is not None
    with pytest.raises(ValidationError):
        RoutingResponse(outcome=Outcome.CLARIFY)


def test_fallback_forbids_all_outcome_fields():
    response = RoutingResponse(outcome=Outcome.FALLBACK)
    assert response.name is None
    assert response.response_text is None
    with pytest.raises(ValidationError):
        RoutingResponse(outcome=Outcome.FALLBACK, response_text="nope")


def test_reject_requires_response_text_and_forbids_route_fields():
    response = RoutingResponse(
        outcome=Outcome.REJECT,
        response_text="Tôi không thể hỗ trợ yêu cầu này.",
    )
    assert response.response_text
    with pytest.raises(ValidationError):
        RoutingResponse(
            outcome=Outcome.REJECT,
            response_text="x",
            name="generate_poster",
        )


@pytest.mark.parametrize("outcome", [Outcome.RESPONSE, Outcome.REJECT])
def test_terminal_response_text_must_not_be_blank(outcome):
    with pytest.raises(ValidationError):
        RoutingResponse(outcome=outcome, response_text="   ")


def test_no_public_confidence_field_exists():
    assert "confidence" not in RoutingResponse.model_fields
    assert "reason_code" not in RoutingResponse.model_fields


def test_arguments_must_be_json_object_string():
    with pytest.raises(ValidationError):
        RoutingResponse(
            outcome=Outcome.ROUTE,
            name="deep_research",
            arguments="not json",
        )
    with pytest.raises(ValidationError):
        RoutingResponse(
            outcome=Outcome.ROUTE,
            name="deep_research",
            arguments="[1,2,3]",
        )


def test_clarification_options_capped_at_three():
    with pytest.raises(ValidationError):
        Clarification(
            question="q",
            options=[
                ClarificationOption(id=str(i), label=str(i), value=str(i))
                for i in range(4)
            ],
        )


def test_to_public_response_route_wire_shape():
    response = RoutingResponse(
        outcome=Outcome.ROUTE,
        name="generate_poster",
        arguments='{"topic":"music"}',
    )
    payload = to_public_response(response)
    assert payload["outcome"] == "INTENTION_DETECT_OUTCOME_ROUTE"
    assert set(payload) <= PUBLIC_RESPONSE_KEYS
    assert "reasonCode" not in payload
    assert payload["arguments"] == '{"topic":"music"}'
    assert isinstance(payload["arguments"], str)


def test_to_public_response_fallback_is_outcome_only():
    payload = to_public_response(RoutingResponse(outcome=Outcome.FALLBACK))
    assert payload == {"outcome": "INTENTION_DETECT_OUTCOME_FALLBACK"}


def test_to_public_response_response_outcome():
    payload = to_public_response(
        RoutingResponse(outcome=Outcome.RESPONSE, response_text="Chào bạn!")
    )
    assert payload == {
        "outcome": "INTENTION_DETECT_OUTCOME_RESPONSE",
        "responseText": "Chào bạn!",
    }
    assert "reasonCode" not in payload


def test_to_public_request_camel_case_and_tools():
    request = RoutingRequest(
        messages=[Message(role="user", content="Tạo poster")],
        tools=[Tool(function=ToolFunction(name="generate_poster"))],
    )
    payload = to_public_request(request)
    assert set(payload) <= {"messages", "tools"}
    assert payload["messages"][0]["role"] == "user"
    assert payload["tools"] == [{"function": {"name": "generate_poster"}}]

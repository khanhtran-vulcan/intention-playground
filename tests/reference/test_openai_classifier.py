from __future__ import annotations

import json
from types import SimpleNamespace

from reference_runtime.contracts import Message, Outcome, RoutingRequest, Tool, ToolFunction
from reference_runtime.registry import ReferenceIntentRegistry
from reference_runtime.router.openai import OpenAIRouterProvider
from reference_runtime.router.schema import build_system_prompt


class FakeCompletions:
    def __init__(self, response=None, exc=None, *, fail_temperature_once: bool = False):
        self.response = response
        self.exc = exc
        self.fail_temperature_once = fail_temperature_once
        self.calls: list[dict] = []
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        self.calls.append(kwargs)
        if self.fail_temperature_once and "temperature" in kwargs:
            raise RuntimeError(
                "Unsupported value: 'temperature' does not support 0 with this model. "
                "Only the default (1) value is supported."
            )
        if self.exc is not None:
            raise self.exc
        return self.response


class FakeChat:
    def __init__(self, response=None, exc=None, *, fail_temperature_once: bool = False):
        self.completions = FakeCompletions(
            response=response, exc=exc, fail_temperature_once=fail_temperature_once
        )


class FakeOpenAIClient:
    def __init__(self, response=None, exc=None, *, fail_temperature_once: bool = False):
        self.chat = FakeChat(
            response=response, exc=exc, fail_temperature_once=fail_temperature_once
        )


def _response(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
    )


def _request(text: str = "hi") -> RoutingRequest:
    return RoutingRequest(
        messages=[Message(role="user", content=text)],
        tools=[Tool(function=ToolFunction(name="real_time_search"))],
    )


VALID_PAYLOAD = {
    "outcome": "ROUTE",
    "route": {
        "goals": ["create a poster"],
        "candidate_intents": ["real_time_search"],
        "dependencies": [],
        "selected_intent": "real_time_search",
        "arguments": {},
        "missing_inputs": [],
    },
    "reason_code": "EXPLICIT_SINGLE_CAPABILITY",
}


def test_missing_api_key_returns_provider_missing_credentials():
    registry = ReferenceIntentRegistry()
    provider = OpenAIRouterProvider(registry, api_key="")
    candidate = provider.route(_request())
    assert candidate.proposed_outcome == Outcome.FALLBACK
    assert candidate.selected_intent is None
    assert candidate.reason_code == "PROVIDER_MISSING_CREDENTIALS"


def test_valid_structured_response_is_parsed():
    registry = ReferenceIntentRegistry()
    client = FakeOpenAIClient(response=_response(VALID_PAYLOAD))
    provider = OpenAIRouterProvider(registry, api_key="test", client=client)
    candidate = provider.route(_request("Tạo poster cho đêm nhạc"))
    assert candidate.proposed_outcome == Outcome.ROUTE
    assert candidate.selected_intent == "real_time_search"
    assert candidate.provider == "OpenAI Structured Router"


def test_malformed_json_is_invalid_provider_output():
    registry = ReferenceIntentRegistry()
    client = FakeOpenAIClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))])
    )
    provider = OpenAIRouterProvider(registry, api_key="test", client=client)
    candidate = provider.route(_request())
    assert candidate.selected_intent is None
    assert candidate.reason_code == "INVALID_PROVIDER_OUTPUT"


def test_request_exception_is_provider_request_failed():
    registry = ReferenceIntentRegistry()
    client = FakeOpenAIClient(exc=RuntimeError("boom"))
    provider = OpenAIRouterProvider(registry, api_key="test", client=client)
    candidate = provider.route(_request())
    assert candidate.selected_intent is None
    assert candidate.reason_code == "PROVIDER_REQUEST_FAILED"


def test_build_system_prompt_takes_tool_names_only():
    prompt = build_system_prompt(["real_time_search", "deep_research"])
    assert "real_time_search" in prompt
    assert "deep_research" in prompt
    assert "arguments: {}" in prompt
    assert "final_prompt" in prompt
    assert "Available intents:" in prompt
    assert "MULTI-intent" not in prompt  # case-sensitive guard against typo
    assert "Multi-intent" in prompt


def test_response_outcome_payload_is_parsed():
    registry = ReferenceIntentRegistry()
    payload = {
        "outcome": "RESPONSE",
        "response": {"text": "Hello from router"},
        "reason_code": "ROUTER_DIRECT_RESPONSE",
    }
    client = FakeOpenAIClient(response=_response(payload))
    provider = OpenAIRouterProvider(registry, api_key="test", client=client)
    candidate = provider.route(_request())
    assert candidate.proposed_outcome == Outcome.RESPONSE
    assert candidate.response_text == "Hello from router"


def test_retries_without_temperature_when_model_rejects_zero():
    registry = ReferenceIntentRegistry()
    client = FakeOpenAIClient(response=_response(VALID_PAYLOAD), fail_temperature_once=True)
    provider = OpenAIRouterProvider(registry, api_key="test", client=client)
    candidate = provider.route(_request("Tạo poster"))
    assert candidate.proposed_outcome == Outcome.ROUTE
    assert len(client.chat.completions.calls) == 2
    assert "temperature" in client.chat.completions.calls[0]
    assert "temperature" not in client.chat.completions.calls[1]

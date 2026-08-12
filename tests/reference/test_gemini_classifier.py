from __future__ import annotations

import json
from types import SimpleNamespace

from reference_runtime.contracts import Message, Outcome, RoutingRequest, Tool, ToolFunction
from reference_runtime.registry import ReferenceIntentRegistry
from reference_runtime.router.gemini import GeminiRouterProvider
from reference_runtime.router.schema import build_system_prompt


class FakeGeminiModels:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc

    def generate_content(self, **kwargs):
        if self.exc is not None:
            raise self.exc
        return self.response


class FakeGeminiClient:
    def __init__(self, response=None, exc=None):
        self.models = FakeGeminiModels(response=response, exc=exc)


def _request(text: str = "hi") -> RoutingRequest:
    return RoutingRequest(
        messages=[Message(role="user", content=text)],
        tools=[Tool(function=ToolFunction(name="create_ai_art"))],
    )


VALID_PAYLOAD = {
    "outcome": "ROUTE",
    "route": {
        "goals": ["research the topic"],
        "candidate_intents": ["create_ai_art"],
        "dependencies": [],
        "selected_intent": "create_ai_art",
        "arguments": {"prompt": "xu hướng cà phê"},
        "missing_inputs": [],
    },
    "reason_code": "EXPLICIT_SINGLE_CAPABILITY",
}


def test_missing_api_key_returns_provider_missing_credentials():
    registry = ReferenceIntentRegistry()
    provider = GeminiRouterProvider(registry, api_key="")
    candidate = provider.route(_request())
    assert candidate.proposed_outcome == Outcome.FALLBACK
    assert candidate.selected_intent is None
    assert candidate.reason_code == "PROVIDER_MISSING_CREDENTIALS"


def test_valid_structured_response_is_parsed():
    registry = ReferenceIntentRegistry()
    client = FakeGeminiClient(response=SimpleNamespace(text=json.dumps(VALID_PAYLOAD)))
    provider = GeminiRouterProvider(registry, api_key="test", client=client)
    candidate = provider.route(_request("Nghiên cứu xu hướng cà phê"))
    assert candidate.proposed_outcome == Outcome.ROUTE
    assert candidate.selected_intent == "create_ai_art"
    assert candidate.arguments["prompt"] == "xu hướng cà phê"
    assert candidate.provider == "Gemini Structured Router"


def test_malformed_json_is_invalid_provider_output():
    registry = ReferenceIntentRegistry()
    client = FakeGeminiClient(response=SimpleNamespace(text="not json"))
    provider = GeminiRouterProvider(registry, api_key="test", client=client)
    candidate = provider.route(_request())
    assert candidate.selected_intent is None
    assert candidate.reason_code == "INVALID_PROVIDER_OUTPUT"


def test_request_exception_is_provider_request_failed():
    registry = ReferenceIntentRegistry()
    client = FakeGeminiClient(exc=RuntimeError("boom"))
    provider = GeminiRouterProvider(registry, api_key="test", client=client)
    candidate = provider.route(_request())
    assert candidate.selected_intent is None
    assert candidate.reason_code == "PROVIDER_REQUEST_FAILED"


def test_extract_response_text_skips_thought_signature_parts():
    from reference_runtime.router.gemini import _extract_response_text

    part_text = SimpleNamespace(text=json.dumps(VALID_PAYLOAD), thought=False, thought_signature=None)
    part_thought = SimpleNamespace(text=None, thought=True, thought_signature=b"opaque")
    part_sig_only = SimpleNamespace(text=None, thought=False, thought_signature=b"sig")
    content = SimpleNamespace(parts=[part_thought, part_sig_only, part_text])
    candidate = SimpleNamespace(content=content)
    response = SimpleNamespace(candidates=[candidate], text="should-not-use")

    raw = _extract_response_text(response)
    assert json.loads(raw)["outcome"] == "ROUTE"


def test_thinking_config_is_passed_when_supported():
    registry = ReferenceIntentRegistry()
    captured = {}

    class CapturingModels:
        def generate_content(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(text=json.dumps(VALID_PAYLOAD), usage_metadata=None)

    class CapturingClient:
        def __init__(self):
            self.models = CapturingModels()

    provider = GeminiRouterProvider(
        registry,
        api_key="test",
        model_name="gemini-2.5-flash-lite",
        client=CapturingClient(),
    )
    candidate = provider.route(_request("Nghiên cứu xu hướng cà phê"))
    assert candidate.proposed_outcome == Outcome.ROUTE
    config = captured.get("config")
    assert config is not None


def test_slow_flash_model_skips_thinking_config():
    registry = ReferenceIntentRegistry()
    captured = {}

    class CapturingModels:
        def generate_content(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(text=json.dumps(VALID_PAYLOAD), usage_metadata=None)

    class CapturingClient:
        def __init__(self):
            self.models = CapturingModels()

    provider = GeminiRouterProvider(
        registry,
        api_key="test",
        model_name="gemini-2.5-flash",
        client=CapturingClient(),
    )
    provider.route(_request("Nghiên cứu xu hướng cà phê"))
    config = captured.get("config")
    assert config is not None
    assert getattr(config, "thinking_config", None) is None


def test_deadline_exceeded_maps_to_provider_timeout():
    registry = ReferenceIntentRegistry()
    client = FakeGeminiClient(exc=RuntimeError("504 DEADLINE_EXCEEDED"))
    provider = GeminiRouterProvider(registry, api_key="test", client=client)
    candidate = provider.route(_request())
    assert candidate.reason_code == "PROVIDER_TIMEOUT"


def test_build_system_prompt_takes_tool_names_only():
    prompt = build_system_prompt(["create_ai_art"])
    assert "create_ai_art" in prompt
    assert "Available intents:" in prompt

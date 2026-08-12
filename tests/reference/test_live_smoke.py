"""Opt-in, credential-backed smoke tests for the live router adapters.

Never run as part of the default `pytest` invocation: every test here is
skipped unless `RUN_LIVE_SMOKE=1` is set AND the matching provider's API key is
configured. Each test makes at most one real request. No credentials, raw
provider output, or full SDK response objects are printed or asserted on --
only that a structurally valid candidate came back.

Run explicitly, e.g.:

    RUN_LIVE_SMOKE=1 GEMINI_API_KEY=... .venv/bin/pytest tests/reference/test_live_smoke.py -v
"""

from __future__ import annotations

import os

import pytest

from reference_runtime.contracts import Message, RoutingRequest, Tool, ToolFunction
from reference_runtime.registry import ReferenceIntentRegistry
from reference_runtime.router.gemini import GeminiRouterProvider
from reference_runtime.router.openai import OpenAIRouterProvider


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_SMOKE") != "1",
    reason="Live smoke tests are opt-in and consume real API quota; set RUN_LIVE_SMOKE=1 to run them.",
)


def _request(text: str) -> RoutingRequest:
    return RoutingRequest(
        messages=[Message(role="user", content=text)],
        tools=[Tool(function=ToolFunction(name="generate_logo"))],
    )


@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="GEMINI_API_KEY is not configured")
def test_gemini_live_smoke_one_request():
    registry = ReferenceIntentRegistry()
    provider = GeminiRouterProvider(registry)
    candidate = provider.route(_request("Tạo logo cho quán cà phê của tôi"))
    assert candidate.provider == "Gemini Structured Router"
    assert candidate.reason_code != "PROVIDER_MISSING_CREDENTIALS"


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY is not configured")
def test_openai_live_smoke_one_request():
    registry = ReferenceIntentRegistry()
    provider = OpenAIRouterProvider(registry)
    candidate = provider.route(_request("Tạo logo cho quán cà phê của tôi"))
    assert candidate.provider == "OpenAI Structured Router"
    assert candidate.reason_code != "PROVIDER_MISSING_CREDENTIALS"

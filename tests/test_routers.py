import json
from types import SimpleNamespace

import numpy as np
import pytest

from core.request import RouteRequest
from routers.base import RouterStatus
from routers.gemini_router import GeminiRouter
from routers.rule_router import RuleRouter
from routers.semantic_router import SemanticRouter
from routers.sklearn_router import (
    SklearnRouter,
    artifact_is_current,
    build_artifact,
)


class FakeEncoder:
    def encode(self, texts, normalize_embeddings=True):
        vectors = []
        for text in texts:
            lowered = text.lower()
            vector = np.array(
                [float("alpha" in lowered), float("beta" in lowered), 0.1],
                dtype=float,
            )
            if normalize_embeddings:
                vector /= np.linalg.norm(vector)
            vectors.append(vector)
        return np.asarray(vectors)


class FakeGeminiModels:
    def __init__(self, response):
        self.response = response

    def generate_content(self, **kwargs):
        return self.response


class FakeGeminiClient:
    def __init__(self, response):
        self.models = FakeGeminiModels(response)


def test_rules_accept_same_intent_multiple_matches(taxonomy):
    result = RuleRouter(taxonomy).route(
        RouteRequest(text="Tạo logo và biểu tượng thương hiệu cho công ty")
    )

    assert result.status == RouterStatus.OK, result.error
    assert result.intent == "generate_logo"
    assert len(result.raw_output["matches"]) >= 2


def test_rules_report_cross_intent_ambiguity(taxonomy):
    result = RuleRouter(taxonomy).route(
        RouteRequest(text="Tạo logo và poster cho sự kiện")
    )

    assert result.status == RouterStatus.AMBIGUOUS
    assert result.intent is None


def test_rules_prefer_specific_child_over_creative_parent(taxonomy):
    result = RuleRouter(taxonomy).route(
        RouteRequest(text="Thiết kế logo cho thương hiệu")
    )

    assert result.status == RouterStatus.OK
    assert result.intent == "generate_logo"
    assert "creative" in result.metadata["all_matched_intents"]


def test_image_intent_reports_missing_execution_context(taxonomy):
    result = RuleRouter(taxonomy).route(
        RouteRequest(text="Mô tả nội dung ảnh này")
    )

    assert result.intent == "chat_with_image"
    assert result.metadata["missing_required_context"] is True


def test_sklearn_excludes_unknown_from_classes(small_taxonomy):
    artifact = build_artifact(small_taxonomy)
    router = SklearnRouter(artifact)
    router.taxonomy = small_taxonomy
    result = router.route(RouteRequest(text="weather forecast"), threshold=0.99)

    assert "unknown" not in artifact["model"].classes_
    assert result.status == RouterStatus.UNKNOWN
    assert artifact_is_current(artifact, small_taxonomy)


def test_semantic_router_builds_index_lazily(small_taxonomy):
    loads = []
    router = SemanticRouter(
        small_taxonomy,
        model_loader=lambda name: loads.append(name) or FakeEncoder(),
    )

    assert loads == []
    result = router.route(RouteRequest(text="alpha request"), threshold=0.5)

    assert result.status == RouterStatus.OK, result.error
    assert result.intent == "alpha"
    assert len(loads) == 1
    assert router.initialized

    router.reset_initialization()

    assert not router.initialized


def test_gemini_structured_result(small_taxonomy):
    usage = SimpleNamespace(
        prompt_token_count=10,
        candidates_token_count=5,
        thoughts_token_count=2,
        cached_content_token_count=0,
        total_token_count=17,
    )
    response = SimpleNamespace(
        text='{"intent":"beta","confidence":0.9,"reasoning":"beta evidence"}',
        usage_metadata=usage,
        candidates=[SimpleNamespace(finish_reason="STOP")],
    )
    router = GeminiRouter(
        small_taxonomy,
        api_key="test",
        client=FakeGeminiClient(response),
    )

    result = router.route(RouteRequest(text="beta please"), threshold=0.6)

    assert result.status == RouterStatus.OK
    assert result.intent == "beta"
    assert result.raw_output["usage"]["input_tokens"] == 10
    assert result.raw_output["usage"]["thinking_tokens"] == 2


def test_blank_pricing_does_not_fail_classification(small_taxonomy, monkeypatch):
    for name in (
        "GEMINI_INPUT_PRICE_PER_1M_TOKENS",
        "GEMINI_OUTPUT_PRICE_PER_1M_TOKENS",
        "GEMINI_CACHED_INPUT_PRICE_PER_1M_TOKENS",
    ):
        monkeypatch.setenv(name, "")
    response = SimpleNamespace(
        text='{"intent":"alpha","confidence":0.8,"reasoning":"alpha"}',
        usage_metadata=SimpleNamespace(
            prompt_token_count=100,
            candidates_token_count=20,
            thoughts_token_count=5,
            cached_content_token_count=0,
            total_token_count=125,
        ),
        candidates=[SimpleNamespace(finish_reason="STOP")],
    )
    router = GeminiRouter(
        small_taxonomy, api_key="test", client=FakeGeminiClient(response)
    )

    result = router.route(RouteRequest(text="alpha"))

    assert result.status == RouterStatus.OK
    assert result.raw_output["estimated_cost"]["available"] is False


def test_cost_includes_thinking_tokens(small_taxonomy, monkeypatch):
    monkeypatch.setenv("GEMINI_INPUT_PRICE_PER_1M_TOKENS", "0.25")
    monkeypatch.setenv("GEMINI_OUTPUT_PRICE_PER_1M_TOKENS", "1.50")
    monkeypatch.setenv("GEMINI_CACHED_INPUT_PRICE_PER_1M_TOKENS", "0.025")
    usage = {
        "input_tokens": 100,
        "output_tokens": 20,
        "thinking_tokens": 5,
        "cached_input_tokens": 0,
    }

    cost = GeminiRouter._estimated_cost(usage)

    assert cost["available"] is True
    assert cost["billed_output_tokens"] == 25
    assert cost["amount"] == pytest.approx(0.0000625)


def test_create_ai_art_prompt_limit_is_enforced(taxonomy):
    long_prompt = " ".join(["word"] * 26)
    response = SimpleNamespace(
        text=json.dumps(
            {
                "intent": "create_ai_art",
                "confidence": 0.9,
                "reasoning": "art request",
                "prompt": long_prompt,
            }
        ),
        usage_metadata=None,
        candidates=[SimpleNamespace(finish_reason="STOP")],
    )
    router = GeminiRouter(taxonomy, api_key="test", client=FakeGeminiClient(response))

    result = router.route(RouteRequest(text="draw something"))

    assert result.status == RouterStatus.ERROR
    assert result.error.code == "SCHEMA_FAILURE"
    assert "25 words" in result.error.message


def test_gemini_without_key_is_unavailable(small_taxonomy):
    result = GeminiRouter(small_taxonomy, api_key=None).route(
        RouteRequest(text="alpha")
    )

    assert result.status == RouterStatus.UNAVAILABLE
    assert result.error.code == "MISSING_API_KEY"

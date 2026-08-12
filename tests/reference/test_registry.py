from __future__ import annotations

from reference_runtime.registry import ReferenceIntentRegistry


def test_registry_contains_required_intents():
    registry = ReferenceIntentRegistry()
    expected = {
        "creative",
        "create_ai_art",
        "generate_logo",
        "generate_poster",
        "generate_flyer",
        "chat_with_image",
        "image_to_image_generation",
        "real_time_search",
        "deep_research",
        "unknown",
    }
    assert expected <= set(registry._specs)


def test_creative_and_unknown_are_not_executable():
    registry = ReferenceIntentRegistry()
    assert registry.is_executable("creative") is False
    assert registry.is_executable("unknown") is False


def test_archived_intents_remain_in_registry_but_are_not_executable():
    registry = ReferenceIntentRegistry()
    for name in (
        "creative",
        "generate_logo",
        "generate_poster",
        "generate_flyer",
    ):
        spec = registry.get(name)
        assert spec is not None
        assert spec.archived is True
        assert registry.is_executable(name) is False
    assert "create_image" not in registry._specs
    assert "image_generation" not in registry._specs
    assert set(registry.executable_names) == {
        "create_ai_art",
        "chat_with_image",
        "image_to_image_generation",
        "real_time_search",
        "deep_research",
    }


def test_deep_research_is_active_executable():
    registry = ReferenceIntentRegistry()
    spec = registry.get("deep_research")
    assert spec is not None
    assert spec.archived is False
    assert registry.is_executable("deep_research") is True


def test_deep_research_reuses_real_field_name():
    registry = ReferenceIntentRegistry()
    spec = registry.get("deep_research")
    assert spec is not None
    assert spec.schema_source == "partial_reuse"
    assert spec.required_argument_names == ["final_prompt"]


def test_image_to_image_generation_requires_style_and_image():
    registry = ReferenceIntentRegistry()
    spec = registry.get("image_to_image_generation")
    assert spec.requires_image is True
    assert spec.required_argument_names == ["style"]
    assert "ghibli" in spec.argument("style").enum


def test_clarification_templates_are_bounded_to_three_options():
    registry = ReferenceIntentRegistry()
    for key in (
        "creative_ambiguous_type",
        "create_vs_edit",
        "missing_image",
        "missing_style",
        "dependency_reference_ambiguous",
    ):
        clarification = registry.clarification_template(key)
        assert len(clarification.options) <= 3
        assert clarification.question

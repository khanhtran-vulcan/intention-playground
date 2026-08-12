from __future__ import annotations

from reference_runtime.model_catalog import (
    CUSTOM_MODEL_CHOICE,
    GEMINI_MODELS,
    OPENAI_MODELS,
    format_option,
    note_for,
    resolve_default_choice,
    select_options,
)


def test_select_options_appends_custom_sentinel():
    options = select_options(GEMINI_MODELS)
    assert options[-1] == CUSTOM_MODEL_CHOICE
    assert len(options) == len(GEMINI_MODELS) + 1


def test_format_option_shows_tag():
    label = format_option(GEMINI_MODELS[0].model_id, GEMINI_MODELS)
    assert GEMINI_MODELS[0].model_id in label
    assert GEMINI_MODELS[0].tag in label


def test_format_option_custom_sentinel():
    assert "Other" in format_option(CUSTOM_MODEL_CHOICE, GEMINI_MODELS)


def test_note_for_known_and_unknown_model():
    assert note_for(GEMINI_MODELS[0].model_id, GEMINI_MODELS)
    assert note_for("not-a-real-model", GEMINI_MODELS) is None


def test_resolve_default_choice_no_env_value_picks_recommended():
    choice, custom = resolve_default_choice(GEMINI_MODELS, None)
    assert choice == "gemini-3.1-flash-lite"
    assert custom == ""


def test_resolve_default_choice_env_value_matches_catalog():
    choice, custom = resolve_default_choice(GEMINI_MODELS, "gemini-3.1-flash-lite")
    assert choice == "gemini-3.1-flash-lite"
    assert custom == ""


def test_resolve_default_choice_env_value_unrecognized_falls_back_to_custom():
    choice, custom = resolve_default_choice(GEMINI_MODELS, "gemini-9.9-mystery")
    assert choice == CUSTOM_MODEL_CHOICE
    assert custom == "gemini-9.9-mystery"


def test_every_catalog_entry_has_a_tag_and_note():
    for models in (GEMINI_MODELS, OPENAI_MODELS):
        for model in models:
            assert model.tag
            assert model.note


def test_each_catalog_has_exactly_one_recommended_default():
    for models in (GEMINI_MODELS, OPENAI_MODELS):
        recommended = [model for model in models if model.tag == "recommended"]
        assert len(recommended) == 1

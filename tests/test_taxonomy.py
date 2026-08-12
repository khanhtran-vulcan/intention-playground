import json

import pytest
from pydantic import ValidationError

from core.taxonomy import Taxonomy
from routers.sklearn_router import training_config_hash


def test_fingerprint_is_independent_of_key_and_intent_order(small_taxonomy):
    payload = small_taxonomy.model_dump(mode="json")
    payload["intents"].reverse()
    reordered = Taxonomy.model_validate(json.loads(json.dumps(payload)))

    assert reordered.fingerprint == small_taxonomy.fingerprint


def test_training_hash_includes_label_order_independently(small_taxonomy):
    assert len(training_config_hash(small_taxonomy)) == 64


def test_rejects_example_shared_across_intents(small_taxonomy):
    payload = small_taxonomy.model_dump(mode="json")
    payload["intents"][1]["examples"].append("alpha one")

    with pytest.raises(ValidationError, match="appears in both"):
        Taxonomy.model_validate(payload)


def test_rejects_invalid_regex(small_taxonomy):
    payload = small_taxonomy.model_dump(mode="json")
    payload["intents"][0]["patterns"] = ["("]

    with pytest.raises(ValidationError, match="invalid regex"):
        Taxonomy.model_validate(payload)


def test_requires_reserved_unknown(small_taxonomy):
    payload = small_taxonomy.model_dump(mode="json")
    payload["intents"] = [
        intent for intent in payload["intents"] if intent["name"] != "unknown"
    ]

    with pytest.raises(ValidationError, match="exactly one"):
        Taxonomy.model_validate(payload)


def test_rejects_hierarchy_cycle(small_taxonomy):
    payload = small_taxonomy.model_dump(mode="json")
    payload["intents"][0]["parent"] = "beta"
    payload["intents"][1]["parent"] = "alpha"

    with pytest.raises(ValidationError, match="cycle"):
        Taxonomy.model_validate(payload)


def test_default_taxonomy_contains_creative_hierarchy_and_styles(taxonomy):
    assert taxonomy.is_ancestor("creative", "generate_logo")
    assert taxonomy.is_ancestor("creative", "generate_poster")
    styles = taxonomy.get("image_to_image_generation").properties["style"].enum

    assert len(styles) == 17
    assert styles[-1] == "other"

from pathlib import Path

import pytest

from core.taxonomy import Taxonomy


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def taxonomy() -> Taxonomy:
    return Taxonomy.model_validate_json(
        (ROOT / "data" / "intents.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def small_taxonomy() -> Taxonomy:
    return Taxonomy.model_validate(
        {
            "intents": [
                {
                    "name": "alpha",
                    "prompt_section": "Alpha intent",
                    "examples": ["alpha one", "alpha two"],
                    "image_examples": [],
                    "patterns": ["alpha"],
                },
                {
                    "name": "beta",
                    "prompt_section": "Beta intent",
                    "examples": ["beta one", "beta two"],
                    "image_examples": [],
                    "patterns": ["beta"],
                },
                {
                    "name": "unknown",
                    "prompt_section": "Outside the taxonomy",
                    "examples": ["weather"],
                    "image_examples": [],
                    "patterns": [],
                },
            ]
        }
    )

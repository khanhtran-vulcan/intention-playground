"""Backward-compatible re-exports for the renamed Pre-router module."""

from reference_runtime.pre_router import (
    DEFAULT_STATIC_RULES,
    FAREWELL,
    GREETING,
    PRODUCT_FAQ,
    RULE_VERSION,
    NormalizedForms,
    StaticRule,
    Tier0Decision,
    Tier0Engine,
    canonical_text,
    folded_text,
    normalize,
    normalize_forms,
)

__all__ = [
    "DEFAULT_STATIC_RULES",
    "FAREWELL",
    "GREETING",
    "PRODUCT_FAQ",
    "RULE_VERSION",
    "NormalizedForms",
    "StaticRule",
    "Tier0Decision",
    "Tier0Engine",
    "canonical_text",
    "folded_text",
    "normalize",
    "normalize_forms",
]

"""Backward-compatible classifier package — re-exports from `router/`."""

from reference_runtime.router.base import ClassifierProvider, RouterProvider
from reference_runtime.router.fake import FakeClassifierProvider, FakeRouterProvider
from reference_runtime.router.schema import (
    AMBIGUITY_TOKENS,
    CANDIDATE_JSON_SCHEMA_TEMPLATE,
    ROUTER_JSON_SCHEMA,
    build_system_prompt,
)

__all__ = [
    "AMBIGUITY_TOKENS",
    "CANDIDATE_JSON_SCHEMA_TEMPLATE",
    "ClassifierProvider",
    "FakeClassifierProvider",
    "FakeRouterProvider",
    "ROUTER_JSON_SCHEMA",
    "RouterProvider",
    "build_system_prompt",
]

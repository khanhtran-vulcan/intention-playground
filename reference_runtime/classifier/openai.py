"""Backward-compatible re-exports — prefer `reference_runtime.router.openai`."""

from reference_runtime.router.openai import (
    DEFAULT_OPENAI_MODEL,
    OpenAIClassifierProvider,
    OpenAIRouterProvider,
)

__all__ = [
    "DEFAULT_OPENAI_MODEL",
    "OpenAIClassifierProvider",
    "OpenAIRouterProvider",
]

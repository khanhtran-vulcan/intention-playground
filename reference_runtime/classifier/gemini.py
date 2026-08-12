"""Backward-compatible re-exports — prefer `reference_runtime.router.gemini`."""

from reference_runtime.router.gemini import (
    DEFAULT_GEMINI_MODEL,
    GeminiClassifierProvider,
    GeminiRouterProvider,
)

__all__ = [
    "DEFAULT_GEMINI_MODEL",
    "GeminiClassifierProvider",
    "GeminiRouterProvider",
]

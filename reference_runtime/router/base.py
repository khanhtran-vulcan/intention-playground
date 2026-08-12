"""Common Structured LLM Router provider interface."""

from __future__ import annotations

from typing import Protocol

from reference_runtime.contracts import RouterDecisionTrace, RoutingRequest


class RouterProvider(Protocol):
    name: str
    model: str | None

    def route(self, request: RoutingRequest) -> RouterDecisionTrace: ...


# Backward-compatible alias.
ClassifierProvider = RouterProvider

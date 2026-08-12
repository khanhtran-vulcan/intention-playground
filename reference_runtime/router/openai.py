"""OpenAI Structured LLM Router adapter (≤1 generative call)."""

from __future__ import annotations

import json
import os
from typing import Any

from reference_runtime.contracts import (
    DependencyEdge,
    Outcome,
    RouterDecisionTrace,
    RoutingRequest,
    Usage,
    UsageModel,
)
from reference_runtime.registry import ReferenceIntentRegistry
from reference_runtime.registry_loader import PROMPT_VERSION, registry_version
from reference_runtime.router.conversation import format_conversation_for_router
from reference_runtime.router.schema import ROUTER_JSON_SCHEMA, build_system_prompt


DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def _temperature_unsupported(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "temperature" in text and (
        "unsupported" in text or "only the default" in text
    )


class OpenAIRouterProvider:
    name = "OpenAI Structured Router"

    def __init__(
        self,
        registry: ReferenceIntentRegistry,
        model_name: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        client: Any = None,
    ):
        self.registry = registry
        self.model = model_name or os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
        self.api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
        self.timeout_seconds = timeout_seconds
        self._client = client
        self.schema = ROUTER_JSON_SCHEMA

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        from openai import OpenAI

        self._client = OpenAI(api_key=self.api_key, timeout=self.timeout_seconds)
        return self._client

    def route(self, request: RoutingRequest) -> RouterDecisionTrace:
        return self.classify(request)

    def classify(self, request: RoutingRequest) -> RouterDecisionTrace:
        if not self.api_key and self._client is None:
            return self._error_candidate("PROVIDER_MISSING_CREDENTIALS")

        system_prompt = build_system_prompt(request.tool_names)
        try:
            client = self._get_client()
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": format_conversation_for_router(request)},
            ]
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_router",
                    "schema": self.schema,
                    "strict": False,
                },
            }
            # Prefer temperature=0 for routing; some GPT-5.* models only allow default (1).
            try:
                response = client.chat.completions.create(
                    model=self.model,
                    temperature=0,
                    messages=messages,
                    response_format=response_format,
                )
            except Exception as exc:
                if not _temperature_unsupported(exc):
                    raise
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format=response_format,
                )
        except Exception:
            return self._error_candidate("PROVIDER_REQUEST_FAILED")

        try:
            choice = response.choices[0].message.content
            parsed = json.loads(choice)
            usage = None
            if getattr(response, "usage", None) is not None:
                usage = Usage(
                    prompt_tokens=int(response.usage.prompt_tokens or 0),
                    completion_tokens=int(response.usage.completion_tokens or 0),
                    total_tokens=int(response.usage.total_tokens or 0),
                )
            return self._candidate_from_payload(parsed, usage=usage)
        except Exception:
            return self._error_candidate("INVALID_PROVIDER_OUTPUT")

    def _candidate_from_payload(
        self, payload: dict[str, Any], *, usage: Usage | None = None
    ) -> RouterDecisionTrace:
        outcome_raw = str(payload.get("outcome") or "FALLBACK")
        try:
            proposed = Outcome(outcome_raw)
        except ValueError:
            proposed = Outcome.FALLBACK

        route = payload.get("route") or {}
        response_block = payload.get("response") or {}
        selected = route.get("selected_intent") or payload.get("selected_intent") or None
        arguments_src = route.get("arguments") if "arguments" in route else payload.get("arguments")
        missing = (
            route.get("missing_inputs") if "missing_inputs" in route else payload.get("missing_inputs")
        )
        deps = route.get("dependencies") if "dependencies" in route else payload.get("dependencies")

        return RouterDecisionTrace(
            provider=self.name,
            model=self.model,
            proposed_outcome=proposed,
            response_text=(response_block.get("text") or payload.get("response_text") or None),
            goals=[str(item) for item in (route.get("goals") or payload.get("goals") or [])],
            candidate_intents=[
                str(item)
                for item in (route.get("candidate_intents") or payload.get("candidate_intents") or [])
            ],
            dependencies=[
                DependencyEdge(intent=str(edge["intent"]), depends_on=str(edge["depends_on"]))
                for edge in (deps or [])
            ],
            selected_intent=selected,
            arguments={str(k): str(v) for k, v in (arguments_src or {}).items()},
            missing_inputs=[str(item) for item in (missing or [])],
            reason_code=str(payload.get("reason_code") or "PROVIDER_DECISION"),
            prompt_version=PROMPT_VERSION,
            registry_version=registry_version(),
            usage_model=UsageModel(provider="openai", model=self.model),
            usage=usage,
        )

    def _error_candidate(self, reason_code: str) -> RouterDecisionTrace:
        return RouterDecisionTrace(
            provider=self.name,
            model=self.model,
            proposed_outcome=Outcome.FALLBACK,
            selected_intent=None,
            reason_code=reason_code,
            provider_error_code=reason_code,  # type: ignore[arg-type]
            prompt_version=PROMPT_VERSION,
            registry_version=registry_version(),
            usage_model=UsageModel(provider="openai", model=self.model),
        )


OpenAIClassifierProvider = OpenAIRouterProvider

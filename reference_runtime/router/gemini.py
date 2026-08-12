"""Gemini Structured LLM Router adapter (≤1 generative call)."""

from __future__ import annotations

import gc
import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any

from reference_runtime.contracts import (
    DependencyEdge,
    Outcome,
    RouterDecisionTrace,
    RoutingRequest,
    Usage,
    UsageModel,
)
from reference_runtime.debug_trace import (
    checkpoint,
    checkpoint_exception,
    summarize_gemini_response,
)
from reference_runtime.registry import ReferenceIntentRegistry
from reference_runtime.registry_loader import PROMPT_VERSION, registry_version
from reference_runtime.router.conversation import format_conversation_for_router
from reference_runtime.router.schema import ROUTER_JSON_SCHEMA, build_system_prompt


# gemini-2.5-flash (non-lite) routinely DEADLINE_EXCEEDs on this router schema
# (~20–30s/call). Prefer a Lite ID for structured routing benchmarks.
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"
_SLOW_STRUCTURED_MODELS = frozenset({"gemini-2.5-flash", "models/gemini-2.5-flash"})


def _extract_response_text(response: Any) -> str:
    """Pull JSON/text parts only — skip thought / thought_signature parts.

    Gemini 3.x Lite models often return opaque `thought_signature` parts. Using
    `response.text` emits warnings and can pull non-JSON content into the parse
    path. Prefer explicit text parts.
    """
    checkpoint("gemini.extract.start", summary=summarize_gemini_response(response))
    chunks: list[str] = []
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) if content is not None else None
        if not parts:
            continue
        for part in parts:
            if getattr(part, "thought", None):
                continue
            if getattr(part, "thought_signature", None) is not None and not getattr(
                part, "text", None
            ):
                continue
            text = getattr(part, "text", None)
            if text:
                chunks.append(text)
    if chunks:
        joined = "".join(chunks).strip()
        checkpoint(
            "gemini.extract.parts_ok",
            n_chunks=len(chunks),
            text_len=len(joined),
            used_response_text=False,
        )
        return joined

    # Fallback for simple test doubles that only expose `.text`.
    # Real google-genai responses: accessing `.text` logs the thought_signature warning.
    checkpoint("gemini.extract.fallback_response_text")
    fallback = getattr(response, "text", None)
    if fallback:
        checkpoint(
            "gemini.extract.fallback_ok",
            text_len=len(str(fallback)),
            used_response_text=True,
        )
        return str(fallback).strip()
    checkpoint("gemini.extract.empty")
    return ""


def _is_timeout_error(exc: BaseException) -> bool:
    name = type(exc).__name__
    text = str(exc).upper()
    return (
        isinstance(exc, (TimeoutError, FuturesTimeoutError))
        or "DEADLINE_EXCEEDED" in text
        or "TIMED OUT" in text
        or "TIMEOUT" in name.upper()
    )


def _invalid_argument(exc: BaseException) -> bool:
    text = str(exc).upper()
    return "INVALID_ARGUMENT" in text or "INVALID ARGUMENT" in text


class GeminiRouterProvider:
    name = "Gemini Structured Router"

    def __init__(
        self,
        registry: ReferenceIntentRegistry,
        model_name: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        client: Any = None,
    ):
        self.registry = registry
        self.model = model_name or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY")
        self.timeout_seconds = timeout_seconds
        self._client = client
        self.schema = ROUTER_JSON_SCHEMA

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        from google import genai
        from google.genai import types

        # retry_options=None → never retry (SDK default). Important: 504s must not
        # multiply into multi-minute hangs across 35 benchmark scenarios.
        self._client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(timeout=int(self.timeout_seconds * 1_000)),
        )
        return self._client

    def route(self, request: RoutingRequest) -> RouterDecisionTrace:
        return self.classify(request)

    def classify(self, request: RoutingRequest) -> RouterDecisionTrace:
        checkpoint(
            "gemini.classify.enter",
            model=self.model,
            timeout_s=self.timeout_seconds,
            n_messages=len(request.messages),
            n_tools=len(request.tool_names),
            has_client=self._client is not None,
            has_api_key=bool(self.api_key),
        )
        if not self.api_key and self._client is None:
            checkpoint("gemini.classify.missing_credentials")
            return self._error_candidate("PROVIDER_MISSING_CREDENTIALS")

        system_prompt = build_system_prompt(request.tool_names)
        try:
            from google.genai import types

            checkpoint("gemini.client.get")
            client = self._get_client()
            checkpoint("gemini.client.ready", client_type=type(client).__name__)
            config_kwargs: dict[str, Any] = {
                "system_instruction": system_prompt,
                "response_mime_type": "application/json",
                "response_json_schema": self.schema,
                "temperature": 0,
            }
            # thinking_budget=0 helps on some Lite models; gemini-2.5-flash hangs with it,
            # and gemini-3.5-flash-lite rejects it (INVALID_ARGUMENT) — retry without.
            use_thinking = self.model.strip().lower() not in _SLOW_STRUCTURED_MODELS
            if use_thinking:
                config_kwargs["thinking_config"] = types.ThinkingConfig(
                    include_thoughts=False,
                    thinking_budget=0,
                )
            try:
                config = types.GenerateContentConfig(**config_kwargs)
                checkpoint("gemini.config.built", use_thinking=use_thinking)
            except Exception as exc:
                checkpoint_exception("gemini.config.thinking_unsupported", exc)
                config_kwargs.pop("thinking_config", None)
                config = types.GenerateContentConfig(**config_kwargs)
                checkpoint("gemini.config.built", use_thinking=False, retried=True)

            contents = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=format_conversation_for_router(request))],
                )
            ]

            def _call(cfg: Any) -> Any:
                checkpoint("gemini.generate_content.start", model=self.model)
                result = client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=cfg,
                )
                checkpoint(
                    "gemini.generate_content.return",
                    summary=summarize_gemini_response(result),
                )
                return result

            # Hard wall-clock cap on top of HttpOptions — some SDK paths ignore HTTP timeout.
            checkpoint("gemini.threadpool.enter")
            with ThreadPoolExecutor(max_workers=1) as pool:
                try:
                    checkpoint("gemini.threadpool.submit")
                    response = pool.submit(_call, config).result(
                        timeout=self.timeout_seconds + 2.0
                    )
                    checkpoint("gemini.threadpool.result_ok")
                except Exception as exc:
                    if "thinking_config" not in config_kwargs or not _invalid_argument(
                        exc
                    ):
                        raise
                    checkpoint_exception("gemini.threadpool.retry_without_thinking", exc)
                    config_kwargs.pop("thinking_config", None)
                    config = types.GenerateContentConfig(**config_kwargs)
                    response = pool.submit(_call, config).result(
                        timeout=self.timeout_seconds + 2.0
                    )
                    checkpoint("gemini.threadpool.result_ok", retried=True)
            checkpoint("gemini.threadpool.exit")
        except Exception as exc:
            checkpoint_exception("gemini.classify.request_failed", exc)
            if _is_timeout_error(exc):
                return self._error_candidate("PROVIDER_TIMEOUT")
            return self._error_candidate("PROVIDER_REQUEST_FAILED")

        try:
            checkpoint("gemini.parse.start")
            raw_text = _extract_response_text(response)
            checkpoint("gemini.parse.json_loads", raw_len=len(raw_text))
            parsed = json.loads(raw_text)
            usage = None
            meta = getattr(response, "usage_metadata", None)
            if meta is not None:
                prompt_tokens = int(getattr(meta, "prompt_token_count", 0) or 0)
                completion_tokens = int(getattr(meta, "candidates_token_count", 0) or 0)
                total_tokens = int(
                    getattr(meta, "total_token_count", 0) or (prompt_tokens + completion_tokens)
                )
                usage = Usage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                )
            # Drop large SDK response before Streamlit rerender (macOS segfault mitigation).
            checkpoint("gemini.response.del_before")
            del response
            gc.collect()
            checkpoint("gemini.response.del_after", gc_collected=True)
            candidate = self._candidate_from_payload(parsed, usage=usage)
            checkpoint(
                "gemini.classify.exit_ok",
                outcome=candidate.proposed_outcome.value,
                reason=candidate.reason_code,
                selected=candidate.selected_intent,
            )
            return candidate
        except Exception as exc:
            checkpoint_exception("gemini.classify.invalid_output", exc)
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
            usage_model=UsageModel(provider="gemini", model=self.model),
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
            usage_model=UsageModel(provider="gemini", model=self.model),
        )


GeminiClassifierProvider = GeminiRouterProvider

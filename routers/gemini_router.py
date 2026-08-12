from __future__ import annotations

import json
import os
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from core.request import RouteRequest
from core.taxonomy import OutputProperty, Taxonomy
from routers.base import (
    RouteResult,
    RouterError,
    RouterStatus,
    request_metadata,
    sanitize_raw_output,
)


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


class GeminiRouter:
    provider = "Gemini Structured Output"

    def __init__(
        self,
        taxonomy: Taxonomy,
        model_name: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 15.0,
        client: Any = None,
    ):
        self.taxonomy = taxonomy
        self.model_name = model_name or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY")
        self.timeout_seconds = timeout_seconds
        self._client = client
        property_names = sorted(
            {
                name
                for intent in taxonomy.known_intents
                for name in intent.properties
            }
        )
        self.schema = {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "enum": taxonomy.labels},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reasoning": {"type": "string"},
                **{name: {"type": "string"} for name in property_names},
            },
            "required": ["intent", "confidence", "reasoning"],
            "additionalProperties": False,
        }
        self.property_names = property_names

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        from google import genai
        from google.genai import types

        self._client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(timeout=int(self.timeout_seconds * 1_000)),
        )
        return self._client

    def _prompt(self, request: RouteRequest) -> str:
        definitions = []
        for intent in self.taxonomy.intents:
            parent = f" Parent: {intent.parent}." if intent.parent else ""
            examples = "; ".join((intent.examples + intent.image_examples)[:3])
            property_instructions = self._property_instructions(intent.properties)
            definitions.append(
                f"- {intent.name}:{parent} {intent.prompt_section}"
                f"{property_instructions} Examples: {examples}"
            )
        return (
            "You are an intent classifier. Select exactly one intent from the schema. "
            "Prefer a specific child intent over its parent when the requested asset type "
            "is clear. Explicit creation output wins over real-time search when a timestamp "
            "is merely content for an asset. Logo, poster, and flyer outputs win over image "
            "style transformation. Use unknown only when no intent has enough evidence. "
            "Return conditional properties only for the selected intent. Confidence is a "
            "self-assessed score from 0 to 1, not a calibrated probability.\n\n"
            + "\n".join(definitions)
            + f"\n\nAttached images: {request.image_count}\nMessage:\n{request.text}"
        )

    @staticmethod
    def _property_instructions(properties: dict[str, OutputProperty]) -> str:
        if not properties:
            return " Return no extra properties."
        instructions = []
        for name, definition in properties.items():
            details = ["required" if definition.required else "optional"]
            if definition.description:
                details.append(definition.description)
            if definition.max_words is not None:
                details.append(f"at most {definition.max_words} words")
            if definition.enum is not None:
                details.append("one of: " + ", ".join(definition.enum))
            instructions.append(f"{name} ({'; '.join(details)})")
        return " Properties: " + "; ".join(instructions) + "."

    def _contents(self, request: RouteRequest) -> Any:
        from google.genai import types

        parts = [types.Part.from_text(text=self._prompt(request))]
        parts.extend(
            types.Part.from_bytes(data=image.data, mime_type=image.mime_type)
            for image in request.images
        )
        return types.Content(role="user", parts=parts)

    @staticmethod
    def _usage(response: Any) -> dict[str, int | None]:
        usage = getattr(response, "usage_metadata", None)
        return {
            "input_tokens": getattr(usage, "prompt_token_count", None),
            "output_tokens": getattr(usage, "candidates_token_count", None),
            "thinking_tokens": getattr(usage, "thoughts_token_count", None),
            "cached_input_tokens": getattr(usage, "cached_content_token_count", None),
            "total_tokens": getattr(usage, "total_token_count", None),
        }

    @staticmethod
    def _finish_reason(response: Any) -> str | None:
        try:
            reason = response.candidates[0].finish_reason
            return getattr(reason, "name", None) or str(reason)
        except (AttributeError, IndexError, TypeError):
            return None

    @staticmethod
    def _response_text(response: Any) -> str:
        try:
            parts = response.candidates[0].content.parts
            text = "".join(
                part.text for part in parts if getattr(part, "text", None) is not None
            )
            if text:
                return text
        except (AttributeError, IndexError, TypeError):
            pass
        return response.text

    @staticmethod
    def _price(name: str) -> tuple[Decimal | None, str | None]:
        raw = (os.getenv(name) or "").strip()
        if not raw:
            return None, None
        try:
            value = Decimal(raw)
        except InvalidOperation:
            return None, f"{name} is not a valid decimal"
        if not value.is_finite() or value < 0:
            return None, f"{name} must be a non-negative finite decimal"
        return value, None

    @classmethod
    def _estimated_cost(cls, usage: dict[str, int | None]) -> dict[str, Any]:
        currency = (os.getenv("PRICING_CURRENCY") or "USD").strip() or "USD"
        input_price, input_error = cls._price("GEMINI_INPUT_PRICE_PER_1M_TOKENS")
        output_price, output_error = cls._price("GEMINI_OUTPUT_PRICE_PER_1M_TOKENS")
        cached_price, cached_error = cls._price(
            "GEMINI_CACHED_INPUT_PRICE_PER_1M_TOKENS"
        )
        errors = [error for error in (input_error, output_error, cached_error) if error]
        if errors:
            return {
                "available": False,
                "currency": currency,
                "reason": "; ".join(errors),
            }
        if input_price is None or output_price is None:
            return {
                "available": False,
                "currency": currency,
                "reason": "Input and output pricing are not configured.",
            }

        input_tokens = Decimal(usage.get("input_tokens") or 0)
        output_tokens = Decimal(usage.get("output_tokens") or 0)
        thinking_tokens = Decimal(usage.get("thinking_tokens") or 0)
        cached_tokens = Decimal(usage.get("cached_input_tokens") or 0)
        regular_input_tokens = max(input_tokens - cached_tokens, Decimal(0))
        effective_cached_price = cached_price if cached_price is not None else input_price
        amount = (
            regular_input_tokens * input_price
            + cached_tokens * effective_cached_price
            + (output_tokens + thinking_tokens) * output_price
        ) / Decimal(1_000_000)
        return {
            "available": True,
            "amount": float(amount),
            "currency": currency,
            "billed_output_tokens": int(output_tokens + thinking_tokens),
        }

    def _validate_properties(
        self, intent: str, parsed: dict[str, Any]
    ) -> dict[str, Any] | None:
        expected = self.taxonomy.get(intent).properties if intent != "unknown" else {}
        result: dict[str, Any] = {}
        for name in self.property_names:
            value = parsed.get(name)
            definition = expected.get(name)
            if definition is None:
                if value not in (None, ""):
                    raise ValueError(
                        f"property {name!r} is not allowed for intent {intent!r}"
                    )
                continue
            if value in (None, ""):
                if definition.required:
                    raise ValueError(
                        f"property {name!r} is required for intent {intent!r}"
                    )
                continue
            if not isinstance(value, str):
                raise ValueError(f"property {name!r} must be a string")
            normalized = value.strip()
            if definition.enum is not None and normalized not in definition.enum:
                raise ValueError(
                    f"property {name!r} must be one of {definition.enum}"
                )
            if (
                definition.max_words is not None
                and len(normalized.split()) > definition.max_words
            ):
                raise ValueError(
                    f"property {name!r} cannot exceed {definition.max_words} words"
                )
            result[name] = normalized
        return result or None

    def route(self, request: RouteRequest, threshold: float = 0.60) -> RouteResult:
        started = time.perf_counter()
        if not self.api_key and self._client is None:
            return RouteResult(
                provider=self.provider,
                status=RouterStatus.UNAVAILABLE,
                latency_ms=(time.perf_counter() - started) * 1_000,
                reason="Gemini is disabled because no API key is configured.",
                metadata={
                    "model": self.model_name,
                    "score_type": "llm_self_assessed",
                    **request_metadata(self.taxonomy, None, request),
                },
                error=RouterError(
                    code="MISSING_API_KEY",
                    message="Set GEMINI_API_KEY to enable Gemini.",
                    retryable=False,
                ),
            )

        try:
            from google.genai import types

            response = self._get_client().models.generate_content(
                model=self.model_name,
                contents=self._contents(request),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=self.schema,
                    temperature=0,
                ),
            )
        except Exception as exc:
            return self._error_result(
                request,
                started,
                "GEMINI_REQUEST_FAILED",
                "Gemini request failed before a structured response was received.",
                exc,
            )

        usage = self._usage(response)
        telemetry = {
            "finish_reason": self._finish_reason(response),
            "usage": usage,
            "estimated_cost": self._estimated_cost(usage),
        }
        parsed: dict[str, Any] | None = None
        try:
            parsed = json.loads(self._response_text(response))
            if not isinstance(parsed, dict):
                raise ValueError("Gemini response must be a JSON object")
            intent = str(parsed["intent"])
            confidence = float(parsed["confidence"])
            if intent not in self.taxonomy.labels or not 0 <= confidence <= 1:
                raise ValueError("Gemini response violates the active taxonomy schema")
            properties = self._validate_properties(intent, parsed)
        except Exception as exc:
            return self._error_result(
                request,
                started,
                "SCHEMA_FAILURE",
                "Gemini returned a response that failed conditional schema validation.",
                exc,
                raw_output={"parsed": parsed, **telemetry},
            )

        accepted = intent != "unknown" and confidence >= threshold
        return RouteResult(
            provider=self.provider,
            status=RouterStatus.OK if accepted else RouterStatus.UNKNOWN,
            intent=intent if accepted else "unknown",
            confidence=confidence,
            latency_ms=(time.perf_counter() - started) * 1_000,
            reason=str(parsed.get("reasoning", "Gemini returned a structured result.")),
            properties=properties if accepted else None,
            raw_output=sanitize_raw_output({"parsed": parsed, **telemetry}),
            metadata={
                "score_type": "llm_self_assessed",
                "threshold": threshold,
                "model": self.model_name,
                **request_metadata(
                    self.taxonomy, intent if accepted else "unknown", request
                ),
            },
        )

    def _error_result(
        self,
        request: RouteRequest,
        started: float,
        code: str,
        reason: str,
        exc: Exception,
        raw_output: dict[str, Any] | None = None,
    ) -> RouteResult:
        return RouteResult(
            provider=self.provider,
            status=RouterStatus.ERROR,
            latency_ms=(time.perf_counter() - started) * 1_000,
            reason=reason,
            raw_output=sanitize_raw_output(raw_output),
            metadata={
                "model": self.model_name,
                "score_type": "llm_self_assessed",
                **request_metadata(self.taxonomy, None, request),
            },
            error=RouterError(
                code=code,
                message=str(exc)[:500],
                retryable=code != "SCHEMA_FAILURE",
            ),
        )

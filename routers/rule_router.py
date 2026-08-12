from __future__ import annotations

import time

import regex

from core.taxonomy import Taxonomy
from core.request import RouteRequest
from routers.base import (
    RouteResult,
    RouterError,
    RouterStatus,
    request_metadata,
    sanitize_raw_output,
)


class RuleRouter:
    provider = "Rules"

    def __init__(self, taxonomy: Taxonomy, match_timeout_seconds: float = 0.05):
        self.taxonomy = taxonomy
        self.match_timeout_seconds = match_timeout_seconds
        self.rules = [
            (intent.name, pattern, regex.compile(pattern, regex.IGNORECASE))
            for intent in taxonomy.known_intents
            for pattern in intent.patterns
        ]

    def route(self, request: RouteRequest) -> RouteResult:
        started = time.perf_counter()
        matches: list[dict[str, str]] = []
        try:
            for intent, pattern, compiled in self.rules:
                if compiled.search(request.text, timeout=self.match_timeout_seconds):
                    matches.append({"intent": intent, "pattern": pattern})
        except TimeoutError:
            return RouteResult(
                provider=self.provider,
                status=RouterStatus.ERROR,
                latency_ms=(time.perf_counter() - started) * 1_000,
                reason="A configured rule exceeded its execution timeout.",
                raw_output=sanitize_raw_output({"matches_before_timeout": matches}),
                metadata={"score_type": "deterministic_rule_match"},
                error=RouterError(code="TIMEOUT", message="Rule matching timed out.", retryable=False),
            )

        matched_intents = sorted({match["intent"] for match in matches})
        elapsed = (time.perf_counter() - started) * 1_000
        if not matched_intents:
            return RouteResult(
                provider=self.provider,
                status=RouterStatus.UNKNOWN,
                intent="unknown",
                confidence=0.0,
                latency_ms=elapsed,
                reason="No configured rule matched.",
                raw_output={"matches": []},
                metadata={
                    "score_type": "deterministic_rule_match",
                    **request_metadata(self.taxonomy, "unknown", request),
                },
            )
        most_specific = [
            intent
            for intent in matched_intents
            if not any(
                self.taxonomy.is_ancestor(intent, other)
                for other in matched_intents
                if other != intent
            )
        ]
        highest_priority = max(
            self.taxonomy.get(intent).rule_priority for intent in most_specific
        )
        finalists = [
            intent
            for intent in most_specific
            if self.taxonomy.get(intent).rule_priority == highest_priority
        ]
        if len(finalists) > 1:
            return RouteResult(
                provider=self.provider,
                status=RouterStatus.AMBIGUOUS,
                intent=None,
                confidence=None,
                latency_ms=elapsed,
                reason="Rules from multiple intents matched.",
                raw_output=sanitize_raw_output({"matches": matches}),
                metadata={
                    "score_type": "deterministic_rule_match",
                    "matched_intents": matched_intents,
                    "finalists": finalists,
                    **request_metadata(self.taxonomy, None, request),
                },
            )
        selected_intent = finalists[0]
        selected_matches = [
            match for match in matches if match["intent"] == selected_intent
        ]
        return RouteResult(
            provider=self.provider,
            status=RouterStatus.OK,
            intent=selected_intent,
            confidence=1.0,
            latency_ms=elapsed,
            reason=f"Matched {len(selected_matches)} configured rule(s) for {selected_intent}.",
            raw_output=sanitize_raw_output({"matches": matches}),
            metadata={
                "score_type": "deterministic_rule_match",
                "all_matched_intents": matched_intents,
                **request_metadata(self.taxonomy, selected_intent, request),
            },
        )

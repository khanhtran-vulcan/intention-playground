from __future__ import annotations

import concurrent.futures
import time
from typing import Callable

from core.request import RouteRequest
from routers.base import RouteResult, RouterError, RouterStatus, sanitize_raw_output
from routers.gemini_router import GeminiRouter
from routers.rule_router import RuleRouter
from routers.semantic_router import SemanticRouter
from routers.sklearn_router import SklearnRouter


def _timeout_result(provider: str, timeout_seconds: float) -> RouteResult:
    return RouteResult(
        provider=provider,
        status=RouterStatus.ERROR,
        latency_ms=timeout_seconds * 1_000,
        reason=f"Provider exceeded the {timeout_seconds:.1f}s deadline.",
        error=RouterError(code="TIMEOUT", message="Provider timed out.", retryable=True),
    )


def run_local_parallel(
    calls: dict[str, Callable[[], RouteResult]], timeout_seconds: float
) -> dict[str, RouteResult]:
    return run_parallel_with_timeouts(
        {name: (call, timeout_seconds) for name, call in calls.items()}
    )


def run_parallel_with_timeouts(
    calls: dict[str, tuple[Callable[[], RouteResult], float]],
) -> dict[str, RouteResult]:
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(calls))
    started = time.perf_counter()
    futures = {executor.submit(call): name for name, (call, _) in calls.items()}
    deadlines = {name: timeout for name, (_, timeout) in calls.items()}
    results: dict[str, RouteResult] = {}
    pending = set(futures)
    while pending:
        elapsed = time.perf_counter() - started
        expired = [
            future for future in pending if elapsed >= deadlines[futures[future]]
        ]
        for future in expired:
            name = futures[future]
            future.cancel()
            results[name] = _timeout_result(name, deadlines[name])
            pending.remove(future)
        if not pending:
            break
        next_deadline = min(deadlines[futures[future]] for future in pending)
        wait_for = max(next_deadline - (time.perf_counter() - started), 0.001)
        done, _ = concurrent.futures.wait(
            pending,
            timeout=wait_for,
            return_when=concurrent.futures.FIRST_COMPLETED,
        )
        for future in done:
            name = futures[future]
            pending.remove(future)
            try:
                results[name] = future.result()
            except Exception as exc:
                results[name] = RouteResult(
                    provider=name,
                    status=RouterStatus.ERROR,
                    latency_ms=0,
                    reason="Provider raised an unexpected error.",
                    error=RouterError(
                        code="UNEXPECTED_ERROR", message=str(exc)[:500], retryable=True
                    ),
                )
    executor.shutdown(wait=False, cancel_futures=True)
    return results


class HybridRouter:
    provider = "Hybrid Router"

    def __init__(
        self,
        rule_router: RuleRouter,
        sklearn_router: SklearnRouter,
        semantic_router: SemanticRouter,
        gemini_router: GeminiRouter,
    ):
        self.rule_router = rule_router
        self.sklearn_router = sklearn_router
        self.semantic_router = semantic_router
        self.gemini_router = gemini_router

    def route(
        self,
        request: RouteRequest,
        ml_threshold: float = 0.20,
        semantic_threshold: float = 0.55,
        gemini_threshold: float = 0.60,
        local_timeout_seconds: float = 2.0,
    ) -> RouteResult:
        started = time.perf_counter()
        trace: list[str] = []
        components: dict[str, RouteResult] = {}

        rules = self.rule_router.route(request)
        components["rules"] = rules
        trace.append(f"rules:{rules.status.value}:{rules.intent or '-'}")
        if rules.status == RouterStatus.OK:
            return self._result(started, rules, trace + ["rules:accepted"], components)

        semantic_initialization_ms: float | None = None
        semantic_initialization_failure: RouteResult | None = None
        initialize_semantic = getattr(self.semantic_router, "initialize", None)
        semantic_initialized = bool(getattr(self.semantic_router, "initialized", False))
        if callable(initialize_semantic) and not semantic_initialized:
            initialization_started = time.perf_counter()
            try:
                semantic_initialization_ms = initialize_semantic()
            except Exception as exc:
                semantic_initialization_failure = RouteResult(
                    provider="Semantic Router",
                    status=RouterStatus.UNAVAILABLE,
                    latency_ms=(time.perf_counter() - initialization_started) * 1_000,
                    reason="The embedding model or semantic index could not be initialized.",
                    metadata={"score_type": "cosine_similarity"},
                    error=RouterError(
                        code="SEMANTIC_UNAVAILABLE",
                        message=str(exc)[:500],
                        retryable=True,
                    ),
                )

        local = run_local_parallel(
            {
                "ml": lambda: self.sklearn_router.route(request, ml_threshold),
                "semantic": (
                    (lambda: semantic_initialization_failure)
                    if semantic_initialization_failure is not None
                    else lambda: self.semantic_router.route(request, semantic_threshold)
                ),
            },
            timeout_seconds=local_timeout_seconds,
        )
        if semantic_initialization_ms is not None:
            semantic_result = local["semantic"]
            local["semantic"] = semantic_result.model_copy(
                update={
                    "metadata": {
                        **semantic_result.metadata,
                        "cold_initialization_ms": semantic_initialization_ms,
                    }
                }
            )
        components.update(local)
        ml = local["ml"]
        semantic = local["semantic"]
        trace.extend(
            [
                f"ml:{ml.status.value}:{ml.intent or '-'}:{ml.confidence}",
                f"semantic:{semantic.status.value}:{semantic.intent or '-'}:{semantic.confidence}",
            ]
        )
        if (
            ml.status == RouterStatus.OK
            and semantic.status == RouterStatus.OK
            and ml.intent == semantic.intent
        ):
            consensus = RouteResult(
                provider=self.provider,
                status=RouterStatus.OK,
                intent=ml.intent,
                confidence=None,
                latency_ms=0,
                reason="Classical ML and Semantic Router reached local consensus.",
                metadata={
                    **ml.metadata,
                    "score_type": "local_consensus",
                },
            )
            return self._result(
                started, consensus, trace + ["consensus:accepted"], components
            )

        degraded_local = any(
            result.status in {RouterStatus.ERROR, RouterStatus.UNAVAILABLE}
            for result in (ml, semantic)
        )
        trace.append("consensus:rejected")
        gemini = self.gemini_router.route(request, gemini_threshold)
        components["gemini"] = gemini
        trace.append(f"gemini:{gemini.status.value}:{gemini.intent or '-'}")
        if gemini.status in {RouterStatus.OK, RouterStatus.UNKNOWN}:
            if degraded_local and gemini.status == RouterStatus.OK:
                gemini = gemini.model_copy(update={"status": RouterStatus.DEGRADED})
            return self._result(started, gemini, trace + ["gemini:accepted"], components)

        fallback = RouteResult(
            provider=self.provider,
            status=RouterStatus.DEGRADED,
            intent="unknown",
            confidence=None,
            latency_ms=0,
            reason="Local routers did not reach consensus and Gemini was unavailable.",
            error=RouterError(
                code="NO_DECISION_PROVIDER",
                message="No provider could produce an accepted decision.",
                retryable=True,
            ),
        )
        return self._result(started, fallback, trace + ["fallback:unknown"], components)

    def _result(
        self,
        started: float,
        decision: RouteResult,
        trace: list[str],
        components: dict[str, RouteResult],
    ) -> RouteResult:
        component_payload = {
            key: value.model_dump(mode="json") for key, value in components.items()
        }
        return RouteResult(
            provider=self.provider,
            status=decision.status,
            intent=decision.intent,
            confidence=decision.confidence,
            latency_ms=(time.perf_counter() - started) * 1_000,
            reason=decision.reason,
            properties=decision.properties,
            raw_output=sanitize_raw_output(decision.raw_output),
            metadata={
                **decision.metadata,
                "score_type": decision.metadata.get("score_type", "hybrid_decision"),
                "decision_path": trace,
                "components": sanitize_raw_output(component_payload),
            },
            error=decision.error,
        )

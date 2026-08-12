from routers.base import RouteResult, RouterError, RouterStatus
from core.request import RouteRequest
from routers.hybrid_router import HybridRouter


class StubRouter:
    def __init__(self, result):
        self.result = result

    def route(self, *args, **kwargs):
        return self.result


def result(provider, status, intent=None, confidence=None):
    return RouteResult(
        provider=provider,
        status=status,
        intent=intent,
        confidence=confidence,
        latency_ms=1,
        reason="test",
        error=(
            RouterError(code="TEST_ERROR", message="failed")
            if status in {RouterStatus.ERROR, RouterStatus.UNAVAILABLE}
            else None
        ),
    )


def test_hybrid_stops_on_rule_match():
    router = HybridRouter(
        StubRouter(result("Rules", RouterStatus.OK, "alpha", 1.0)),
        StubRouter(result("ML", RouterStatus.ERROR)),
        StubRouter(result("Semantic", RouterStatus.ERROR)),
        StubRouter(result("Gemini", RouterStatus.ERROR)),
    )

    routed = router.route(RouteRequest(text="anything"))

    assert routed.intent == "alpha"
    assert routed.metadata["decision_path"][-1] == "rules:accepted"


def test_hybrid_accepts_local_consensus():
    router = HybridRouter(
        StubRouter(result("Rules", RouterStatus.UNKNOWN, "unknown", 0.0)),
        StubRouter(result("ML", RouterStatus.OK, "alpha", 0.8)),
        StubRouter(result("Semantic", RouterStatus.OK, "alpha", 0.7)),
        StubRouter(result("Gemini", RouterStatus.ERROR)),
    )

    routed = router.route(RouteRequest(text="anything"))

    assert routed.status == RouterStatus.OK
    assert routed.intent == "alpha"
    assert routed.metadata["decision_path"][-1] == "consensus:accepted"


def test_hybrid_degrades_to_unknown_when_gemini_unavailable():
    router = HybridRouter(
        StubRouter(result("Rules", RouterStatus.UNKNOWN, "unknown", 0.0)),
        StubRouter(result("ML", RouterStatus.OK, "alpha", 0.8)),
        StubRouter(result("Semantic", RouterStatus.OK, "beta", 0.8)),
        StubRouter(result("Gemini", RouterStatus.UNAVAILABLE)),
    )

    routed = router.route(RouteRequest(text="anything"))

    assert routed.status == RouterStatus.DEGRADED
    assert routed.intent == "unknown"
    assert routed.metadata["decision_path"][-1] == "fallback:unknown"

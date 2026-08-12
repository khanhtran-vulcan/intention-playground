import pandas as pd

from core.evaluation import evaluate_router, validate_evaluation_frame
from routers.base import RouteResult, RouterStatus


def test_evaluation_reports_abstention_metrics(small_taxonomy):
    frame = pd.DataFrame(
        [
            {"text": "alpha", "expected_intent": "alpha"},
            {"text": "weather", "expected_intent": "unknown"},
        ]
    )

    def route(request):
        intent = "alpha" if request.text == "alpha" else "unknown"
        status = RouterStatus.OK if intent == "alpha" else RouterStatus.UNKNOWN
        return RouteResult(
            provider="test",
            status=status,
            intent=intent,
            confidence=0.9,
            latency_ms=2,
            reason="test",
        )

    report = evaluate_router(
        "test", route, frame, small_taxonomy, warmup_calls=0
    )

    assert report.metrics["overall_accuracy"] == 1.0
    assert report.metrics["unknown_recall"] == 1.0
    assert report.metrics["coverage"] == 0.5
    assert report.metrics["selective_accuracy"] == 1.0


def test_evaluation_rejects_unknown_labels(small_taxonomy):
    frame = pd.DataFrame([{"text": "x", "expected_intent": "missing"}])

    try:
        validate_evaluation_frame(frame, small_taxonomy)
    except ValueError as exc:
        assert "outside taxonomy" in str(exc)
    else:
        raise AssertionError("invalid label was accepted")

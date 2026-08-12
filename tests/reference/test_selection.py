from __future__ import annotations

from reference_runtime.candidates import DEFAULT_SELECTION_CANDIDATES, parse_candidates
from reference_runtime.evaluation import ReferenceEvaluationReport
from reference_runtime.selection import (
    extract_selection_row,
    load_pricing,
    rank_candidates,
    recommend,
)


def test_default_candidates_match_operator_shortlist():
    ids = [c.model_id for c in DEFAULT_SELECTION_CANDIDATES]
    assert "gpt-5.6-luna" in ids
    assert "gemini-3.5-flash-lite" in ids
    assert "gpt-5-nano" in ids
    assert "gemini-2.5-flash-lite" not in ids


def test_parse_candidates_infers_provider():
    rows = parse_candidates("gpt-5-nano,gemini:gemini-3.1-flash-lite")
    assert rows[0].provider == "openai"
    assert rows[0].model_id == "gpt-5-nano"
    assert rows[1].provider == "gemini"
    assert rows[1].model_id == "gemini-3.1-flash-lite"


def test_pricing_snapshot_covers_default_candidates():
    pricing = load_pricing()
    for candidate in DEFAULT_SELECTION_CANDIDATES:
        assert candidate.model_id in pricing, candidate.model_id


def _stub_report(*, model: str, accuracy: float, router_p95: float, tokens: int):
    return ReferenceEvaluationReport(
        provider="stub",
        model=model,
        prompt_version="router-v1",
        registry_version="yaml-registry-v1",
        schema_version="reference-v1",
        total_scenarios=1,
        outcome_accuracy=accuracy,
        provider_error_count=0,
        provider_error_rate=0.0,
        outcome_accuracy_excluding_provider_errors=accuracy,
        outcome_accuracy_vision_scenarios=None,
        outcome_accuracy_text_scenarios=accuracy,
        vision_scenario_count=0,
        text_scenario_count=1,
        intent_accuracy=None,
        reason_code_accuracy=None,
        false_route_rate=0.0,
        response_false_positive_rate=0.0,
        fallback_rate=0.0,
        dependency_outcome_accuracy=None,
        next_executable_prerequisite_accuracy=None,
        validator_catch_rate=None,
        policy_reject_correctness=None,
        false_reject_rate=0.0,
        pre_router_p50_ms=None,
        pre_router_p95_ms=None,
        pre_router_avg_ms=None,
        t0_avg_ms=None,
        t0_p50_ms=None,
        t0_p95_ms=None,
        t1_avg_ms=None,
        t1_p50_ms=None,
        t1_p95_ms=None,
        total_avg_ms=None,
        total_p50_ms=None,
        total_p95_ms=None,
        average_stage_latency_ms={},
        stage_p50_ms={},
        stage_p95_ms={"router": router_p95},
        clarification_completion_rate=None,
        average_clarification_turns=None,
        clarify_to_route_rate=None,
        rows=[],
    )


def test_rank_prefers_accuracy_then_latency_then_tokens():
    a = extract_selection_row(_stub_report(model="a", accuracy=0.80, router_p95=2000, tokens=800))
    b = extract_selection_row(_stub_report(model="b", accuracy=0.80, router_p95=1500, tokens=900))
    c = extract_selection_row(_stub_report(model="c", accuracy=0.70, router_p95=1000, tokens=100))
    # Force token means via monkeypatch fields
    a.mean_total_tokens = 800
    b.mean_total_tokens = 900
    c.mean_total_tokens = 100
    ranked = rank_candidates([a, b, c])
    assert ranked[0].model == "b"  # same acc, lower p95
    assert ranked[1].model == "a"
    assert ranked[2].model == "c"  # below floor


def test_recommend_primary_fallback():
    high = extract_selection_row(
        _stub_report(model="gpt-5.6-luna", accuracy=0.85, router_p95=1800, tokens=700)
    )
    mid = extract_selection_row(
        _stub_report(model="gemini-3.5-flash-lite", accuracy=0.80, router_p95=1600, tokens=750)
    )
    low = extract_selection_row(
        _stub_report(model="gpt-5-nano", accuracy=0.60, router_p95=1200, tokens=500)
    )
    rec = recommend([high, mid, low], accuracy_floor=0.75)
    assert rec.primary == "gpt-5.6-luna"
    assert rec.fallback == "gemini-3.5-flash-lite"

from __future__ import annotations

from reference_runtime.contracts import Outcome, RouterDecisionTrace
from reference_runtime.evaluation import (
    _latency_stats,
    _row_t0_latency_ms,
    _row_t1_latency_ms,
    _row_total_latency_ms,
    evaluate_reference,
    export_report,
)
from reference_runtime.registry import registry_with_archived_active
from reference_runtime.router.fake import FakeRouterProvider
from reference_runtime.runtime import ReferenceRouter
from reference_runtime.scenarios import CLARIFICATION_CHAINS, SCENARIOS, Scenario


class AlwaysSearchClassifier:
    name = "always-search"
    model = "test"

    def classify(self, request):
        return RouterDecisionTrace(
            provider=self.name,
            model=self.model,
            proposed_outcome=Outcome.ROUTE,
            selected_intent="real_time_search",
            reason_code="TEST",
        )

    def route(self, request):
        return self.classify(request)


def test_evaluate_reference_perfect_fake_provider_scores_full_marks():
    router = ReferenceRouter(router=FakeRouterProvider(), registry=registry_with_archived_active())
    report = evaluate_reference(router, SCENARIOS, CLARIFICATION_CHAINS)

    assert report.total_scenarios == len(SCENARIOS)
    assert report.outcome_accuracy == 1.0
    assert report.intent_accuracy == 1.0
    assert report.reason_code_accuracy == 1.0
    assert report.dependency_outcome_accuracy == 1.0
    assert report.next_executable_prerequisite_accuracy == 1.0
    assert report.validator_catch_rate == 1.0
    assert report.policy_reject_correctness == 1.0
    assert report.false_reject_rate == 0.0
    assert report.false_route_rate == 0.0
    assert report.clarification_completion_rate == 1.0
    assert report.average_clarification_turns is not None
    assert "pre_router" in report.average_stage_latency_ms
    assert report.pre_router_p50_ms is not None
    assert report.pre_router_p95_ms is not None
    assert report.pre_router_avg_ms is not None
    assert report.t0_avg_ms is not None
    assert report.total_avg_ms is not None
    assert report.latency_by_actual_outcome
    assert all(row.total_latency_ms > 0 for row in report.rows)
    assert all(row.t0_latency_ms >= 0 for row in report.rows)


def test_latency_helpers_and_per_outcome_buckets():
    stage_latency = {
        "normalize": 1.0,
        "policy_gate": 2.0,
        "pre_router": 3.0,
        "router": 40.0,
        "validator": 5.0,
    }
    assert _row_total_latency_ms(stage_latency) == 51.0
    assert _row_t0_latency_ms(stage_latency) == 6.0
    assert _row_t1_latency_ms(stage_latency) == 40.0
    assert _row_t1_latency_ms({"normalize": 1.0}) is None

    stats = _latency_stats([10.0, 20.0, 30.0, 40.0])
    assert stats.count == 4
    assert stats.avg_ms == 25.0
    assert stats.p50_ms == 30.0
    assert stats.p95_ms == 40.0


def test_export_report_includes_latency_columns(tmp_path):
    router = ReferenceRouter(router=FakeRouterProvider(), registry=registry_with_archived_active())
    report = evaluate_reference(router, SCENARIOS[:3])
    paths = export_report(report, tmp_path, basename="latency_test")
    csv_text = paths["csv"].read_text(encoding="utf-8")
    summary_text = paths["summary"].read_text(encoding="utf-8")
    assert "total_latency_ms" in csv_text
    assert "t0_latency_ms" in csv_text
    assert "t1_latency_ms" in csv_text
    assert "T0 (normalize + policy + pre_router)" in summary_text
    assert "Latency by actual outcome" in summary_text


def test_no_confidence_metric_anywhere_in_the_report():
    router = ReferenceRouter(router=FakeRouterProvider(), registry=registry_with_archived_active())
    report = evaluate_reference(router, SCENARIOS, CLARIFICATION_CHAINS)
    field_names = {f for f in report.__dataclass_fields__}
    assert not any("confidence" in name for name in field_names)


def test_report_rows_carry_per_scenario_detail():
    router = ReferenceRouter(router=FakeRouterProvider(), registry=registry_with_archived_active())
    report = evaluate_reference(router, SCENARIOS)
    ids = {row.scenario_id for row in report.rows}
    assert ids == {scenario.id for scenario in SCENARIOS}


def test_next_executable_metric_rejects_right_outcome_with_wrong_intent():
    from reference_runtime.scenarios import DEFAULT_TOOL_NAMES

    scenario = Scenario(
        id="wrong-next-intent",
        category="dependency",
        description="Expected research prerequisite before illustration.",
        text="Research first, then illustration",
        expected_outcome="ROUTE",
        expected_name="deep_research",
        tools=DEFAULT_TOOL_NAMES,
    )
    report = evaluate_reference(
        ReferenceRouter(router=AlwaysSearchClassifier(), registry=registry_with_archived_active()),
        (scenario,),
    )
    assert report.dependency_outcome_accuracy == 1.0
    assert report.next_executable_prerequisite_accuracy == 0.0
    assert report.false_route_rate == 1.0


def test_validator_catch_rate_excludes_rows_where_validator_never_ran():
    from reference_runtime.scenarios import DEFAULT_TOOL_NAMES

    scenarios = (
        Scenario(
            id="pre-router",
            category="pre_router_static",
            description="Pre-router static row.",
            text="Xin chào",
            expected_outcome="RESPONSE",
        ),
        Scenario(
            id="validator-miss",
            category="fallback",
            description="Expected fallback but classifier routes.",
            text="unknown",
            expected_outcome="FALLBACK",
            tools=DEFAULT_TOOL_NAMES,
        ),
    )
    report = evaluate_reference(
        ReferenceRouter(router=AlwaysSearchClassifier(), registry=registry_with_archived_active()),
        scenarios,
    )
    assert report.validator_catch_rate == 0.0

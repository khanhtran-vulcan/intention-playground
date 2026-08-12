"""Reference Runtime evaluation + model benchmark harness.

Metrics never use public confidence (none exists on the Client contract).
Reason codes are scored from internal traces only.
"""

from __future__ import annotations

import csv
import json
import statistics
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from reference_runtime.contracts import Message, Outcome, RequestContext, RoutingRequest, Tool, ToolFunction
from reference_runtime.registry_loader import PROMPT_VERSION, registry_version
from reference_runtime.runtime import ReferenceRouter
from reference_runtime.scenarios import FAKE_IMAGE, ClarificationChain, Scenario

# Return False to stop evaluating further scenarios (partial report still built).
ProgressCallback = Callable[[int, int, Scenario, "ScenarioRow"], bool | None]

_PROVIDER_FAIL_REASON_CODES = frozenset(
    {
        "PROVIDER_MISSING_CREDENTIALS",
        "PROVIDER_TIMEOUT",
        "PROVIDER_REQUEST_FAILED",
        "INVALID_PROVIDER_OUTPUT",
    }
)


@dataclass
class LatencyStats:
    count: int
    avg_ms: float | None
    p50_ms: float | None
    p95_ms: float | None


@dataclass
class ScenarioRow:
    scenario_id: str
    category: str
    expected_outcome: str
    actual_outcome: str
    outcome_match: bool
    expected_name: str | None
    actual_name: str | None
    intent_match: bool | None
    expected_reason_code: str | None
    actual_reason_code: str
    reason_code_match: bool | None
    stage_latency_ms: dict[str, float]
    total_latency_ms: float = 0.0
    t0_latency_ms: float = 0.0
    t1_latency_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class ClarificationChainRow:
    chain_id: str
    completed: bool
    turns_taken: int
    steps: list[dict[str, Any]]


@dataclass
class ReferenceEvaluationReport:
    provider: str
    model: str | None
    prompt_version: str
    registry_version: str
    schema_version: str
    total_scenarios: int
    outcome_accuracy: float
    provider_error_count: int
    provider_error_rate: float
    outcome_accuracy_excluding_provider_errors: float | None
    outcome_accuracy_vision_scenarios: float | None
    outcome_accuracy_text_scenarios: float | None
    vision_scenario_count: int
    text_scenario_count: int
    intent_accuracy: float | None
    reason_code_accuracy: float | None
    false_route_rate: float | None
    response_false_positive_rate: float | None
    fallback_rate: float
    dependency_outcome_accuracy: float | None
    next_executable_prerequisite_accuracy: float | None
    validator_catch_rate: float | None
    policy_reject_correctness: float | None
    false_reject_rate: float
    pre_router_p50_ms: float | None
    pre_router_p95_ms: float | None
    pre_router_avg_ms: float | None
    t0_avg_ms: float | None
    t0_p50_ms: float | None
    t0_p95_ms: float | None
    t1_avg_ms: float | None
    t1_p50_ms: float | None
    t1_p95_ms: float | None
    total_avg_ms: float | None
    total_p50_ms: float | None
    total_p95_ms: float | None
    average_stage_latency_ms: dict[str, float]
    stage_p50_ms: dict[str, float | None]
    stage_p95_ms: dict[str, float | None]
    clarification_completion_rate: float | None
    average_clarification_turns: float | None
    clarify_to_route_rate: float | None
    latency_by_actual_outcome: dict[str, LatencyStats] = field(default_factory=dict)
    latency_by_actual_outcome_t0: dict[str, LatencyStats] = field(default_factory=dict)
    latency_by_actual_outcome_t1: dict[str, LatencyStats] = field(default_factory=dict)
    outcome_breakdown: dict[str, int] = field(default_factory=dict)
    rows: list[ScenarioRow] = field(default_factory=list)
    clarification_rows: list[ClarificationChainRow] = field(default_factory=list)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct * (len(ordered) - 1))))
    return ordered[index]


def _accuracy(flags: list[bool]) -> float | None:
    return (sum(flags) / len(flags)) if flags else None


_T0_STAGES = ("normalize", "policy_gate", "pre_router")


def _row_total_latency_ms(stage_latency: dict[str, float]) -> float:
    return float(sum(stage_latency.values()))


def _row_t0_latency_ms(stage_latency: dict[str, float]) -> float:
    return float(sum(stage_latency.get(stage, 0.0) for stage in _T0_STAGES))


def _row_t1_latency_ms(stage_latency: dict[str, float]) -> float | None:
    if "router" not in stage_latency:
        return None
    return float(stage_latency["router"])


def _latency_stats(values: list[float]) -> LatencyStats:
    if not values:
        return LatencyStats(count=0, avg_ms=None, p50_ms=None, p95_ms=None)
    return LatencyStats(
        count=len(values),
        avg_ms=statistics.fmean(values),
        p50_ms=_percentile(values, 0.50),
        p95_ms=_percentile(values, 0.95),
    )


def _latency_stats_by_key(rows: list[ScenarioRow], key: str) -> dict[str, LatencyStats]:
    buckets: dict[str, list[float]] = {}
    for row in rows:
        if key == "total":
            value = row.total_latency_ms
        elif key == "t0":
            value = row.t0_latency_ms
        elif key == "t1":
            if row.t1_latency_ms is None:
                continue
            value = row.t1_latency_ms
        else:
            continue
        buckets.setdefault(row.actual_outcome, []).append(value)
    return {outcome: _latency_stats(values) for outcome, values in sorted(buckets.items())}


def evaluate_scenario(router: ReferenceRouter, scenario: Scenario) -> ScenarioRow:
    request = scenario.to_routing_request()
    result = router.route(request)
    response = result.response
    actual_outcome = response.outcome.value
    outcome_match = actual_outcome == scenario.expected_outcome

    intent_match: bool | None = None
    if scenario.expected_outcome == Outcome.ROUTE.value:
        intent_match = response.name == scenario.expected_name

    actual_reason = result.trace.final_reason_code
    reason_code_match: bool | None = None
    if scenario.expected_reason_code is not None:
        reason_code_match = actual_reason == scenario.expected_reason_code

    usage = response.usage
    stage_latency = {stage.stage: stage.latency_ms for stage in result.trace.stages}
    return ScenarioRow(
        scenario_id=scenario.id,
        category=scenario.category,
        expected_outcome=scenario.expected_outcome,
        actual_outcome=actual_outcome,
        outcome_match=outcome_match,
        expected_name=scenario.expected_name,
        actual_name=response.name,
        intent_match=intent_match,
        expected_reason_code=scenario.expected_reason_code,
        actual_reason_code=actual_reason,
        reason_code_match=reason_code_match,
        stage_latency_ms=stage_latency,
        total_latency_ms=_row_total_latency_ms(stage_latency),
        t0_latency_ms=_row_t0_latency_ms(stage_latency),
        t1_latency_ms=_row_t1_latency_ms(stage_latency),
        prompt_tokens=usage.prompt_tokens if usage else None,
        completion_tokens=usage.completion_tokens if usage else None,
        total_tokens=usage.total_tokens if usage else None,
    )


def evaluate_clarification_chain(
    router: ReferenceRouter, chain: ClarificationChain
) -> ClarificationChainRow:
    from reference_runtime.scenarios import default_tools

    steps: list[dict[str, Any]] = []
    completed = True
    turns_taken = 0
    for turn_count, step in enumerate(chain.steps):
        request = RoutingRequest(
            messages=[
                Message(
                    role="user",
                    content=step.user_text,
                    files=[FAKE_IMAGE] if chain.with_image else [],
                )
            ],
            tools=default_tools(),
            context=RequestContext(clarification_turn_count=turn_count),
        )
        result = router.route(request)
        actual_outcome = result.response.outcome.value
        matched = actual_outcome == step.expected_outcome and (
            step.expected_name is None or result.response.name == step.expected_name
        )
        steps.append(
            {
                "turn": turn_count,
                "expected_outcome": step.expected_outcome,
                "actual_outcome": actual_outcome,
                "matched": matched,
            }
        )
        turns_taken += 1
        if not matched:
            completed = False
            break
        if actual_outcome != Outcome.CLARIFY.value:
            break
    return ClarificationChainRow(
        chain_id=chain.id, completed=completed, turns_taken=turns_taken, steps=steps
    )


def evaluate_reference(
    router: ReferenceRouter,
    scenarios: tuple[Scenario, ...],
    clarification_chains: tuple[ClarificationChain, ...] = (),
    *,
    progress: ProgressCallback | None = None,
) -> ReferenceEvaluationReport:
    rows: list[ScenarioRow] = []
    total = len(scenarios)
    aborted_early = False
    for index, scenario in enumerate(scenarios, start=1):
        row = evaluate_scenario(router, scenario)
        rows.append(row)
        if progress is not None and progress(index, total, scenario, row) is False:
            aborted_early = True
            break

    if aborted_early:
        clarification_chains = ()

    outcome_accuracy = _accuracy([row.outcome_match for row in rows]) or 0.0

    vision_ids = {scenario.id for scenario in scenarios if scenario.with_image}
    vision_rows = [row for row in rows if row.scenario_id in vision_ids]
    text_rows = [row for row in rows if row.scenario_id not in vision_ids]
    provider_error_rows = [
        row for row in rows if row.actual_reason_code in _PROVIDER_FAIL_REASON_CODES
    ]
    non_provider_rows = [
        row for row in rows if row.actual_reason_code not in _PROVIDER_FAIL_REASON_CODES
    ]
    provider_error_count = len(provider_error_rows)
    provider_error_rate = (provider_error_count / len(rows)) if rows else 0.0
    outcome_accuracy_excluding_provider_errors = _accuracy(
        [row.outcome_match for row in non_provider_rows]
    )
    outcome_accuracy_vision_scenarios = _accuracy([row.outcome_match for row in vision_rows])
    outcome_accuracy_text_scenarios = _accuracy([row.outcome_match for row in text_rows])

    intent_accuracy = _accuracy([row.intent_match for row in rows if row.intent_match is not None])
    reason_code_accuracy = _accuracy(
        [row.reason_code_match for row in rows if row.reason_code_match is not None]
    )

    # false_route_rate: actual ROUTE where gold is not ROUTE or wrong intent
    route_actual = [row for row in rows if row.actual_outcome == Outcome.ROUTE.value]
    false_routes = [
        row
        for row in route_actual
        if row.expected_outcome != Outcome.ROUTE.value
        or (row.expected_name is not None and row.actual_name != row.expected_name)
    ]
    false_route_rate = (len(false_routes) / len(route_actual)) if route_actual else None

    # RESPONSE FP: RESPONSE where gold requires capability / reject / clarify
    response_actual = [row for row in rows if row.actual_outcome == Outcome.RESPONSE.value]
    response_fp = [
        row
        for row in response_actual
        if row.expected_outcome not in {Outcome.RESPONSE.value}
    ]
    response_false_positive_rate = (
        (len(response_fp) / len(response_actual)) if response_actual else None
    )

    fallback_rate = (
        sum(1 for row in rows if row.actual_outcome == Outcome.FALLBACK.value) / len(rows)
        if rows
        else 0.0
    )

    dependency_rows = [row for row in rows if row.category == "dependency"]
    dependency_outcome_accuracy = _accuracy([row.outcome_match for row in dependency_rows])
    next_executable_prerequisite_accuracy = _accuracy(
        [
            row.outcome_match
            and (row.expected_name is None or row.actual_name == row.expected_name)
            for row in dependency_rows
        ]
    )

    validator_non_route_rows = [
        row
        for row in rows
        if row.expected_outcome != Outcome.ROUTE.value and "validator" in row.stage_latency_ms
    ]
    validator_catch_rate = _accuracy([row.outcome_match for row in validator_non_route_rows])

    reject_rows = [row for row in rows if row.category == "reject"]
    expected_reject_rows = [
        row for row in reject_rows if row.expected_outcome == Outcome.REJECT.value
    ]
    policy_reject_correctness = _accuracy([row.outcome_match for row in expected_reject_rows])

    non_reject_expected_rows = [row for row in rows if row.expected_outcome != Outcome.REJECT.value]
    false_reject_rate = (
        sum(1 for row in non_reject_expected_rows if row.actual_outcome == Outcome.REJECT.value)
        / len(non_reject_expected_rows)
        if non_reject_expected_rows
        else 0.0
    )

    stage_values: dict[str, list[float]] = {}
    for row in rows:
        for stage, latency in row.stage_latency_ms.items():
            stage_values.setdefault(stage, []).append(latency)
    average_stage_latency_ms = {
        stage: statistics.fmean(values) for stage, values in stage_values.items()
    }
    stage_p50_ms = {stage: _percentile(values, 0.50) for stage, values in stage_values.items()}
    stage_p95_ms = {stage: _percentile(values, 0.95) for stage, values in stage_values.items()}
    pre_router_latencies = stage_values.get("pre_router", []) or stage_values.get("tier0", [])
    pre_router_p50 = _percentile(pre_router_latencies, 0.50)
    pre_router_p95 = _percentile(pre_router_latencies, 0.95)
    pre_router_avg = statistics.fmean(pre_router_latencies) if pre_router_latencies else None

    t0_values = [row.t0_latency_ms for row in rows]
    t1_values = [row.t1_latency_ms for row in rows if row.t1_latency_ms is not None]
    total_values = [row.total_latency_ms for row in rows]
    t0_stats = _latency_stats(t0_values)
    t1_stats = _latency_stats(t1_values)
    total_stats = _latency_stats(total_values)

    clarification_rows = [
        evaluate_clarification_chain(router, chain) for chain in clarification_chains
    ]
    clarification_completion_rate = _accuracy([row.completed for row in clarification_rows])
    average_clarification_turns = (
        statistics.fmean([row.turns_taken for row in clarification_rows])
        if clarification_rows
        else None
    )
    clarify_to_route = [
        row
        for row in clarification_rows
        if row.completed and any(step.get("actual_outcome") == "ROUTE" for step in row.steps)
    ]
    clarify_to_route_rate = (
        (len(clarify_to_route) / len(clarification_rows)) if clarification_rows else None
    )

    outcome_breakdown: dict[str, int] = {}
    for row in rows:
        outcome_breakdown[row.actual_outcome] = outcome_breakdown.get(row.actual_outcome, 0) + 1

    provider_obj = getattr(router, "router", None) or getattr(router, "classifier", None)
    provider_name = getattr(provider_obj, "name", "unknown")
    model_name = getattr(provider_obj, "model", None)

    return ReferenceEvaluationReport(
        provider=provider_name,
        model=model_name,
        prompt_version=PROMPT_VERSION,
        registry_version=registry_version(),
        schema_version="reference-v1",
        total_scenarios=len(rows),
        outcome_accuracy=outcome_accuracy,
        provider_error_count=provider_error_count,
        provider_error_rate=provider_error_rate,
        outcome_accuracy_excluding_provider_errors=outcome_accuracy_excluding_provider_errors,
        outcome_accuracy_vision_scenarios=outcome_accuracy_vision_scenarios,
        outcome_accuracy_text_scenarios=outcome_accuracy_text_scenarios,
        vision_scenario_count=len(vision_rows),
        text_scenario_count=len(text_rows),
        intent_accuracy=intent_accuracy,
        reason_code_accuracy=reason_code_accuracy,
        false_route_rate=false_route_rate,
        response_false_positive_rate=response_false_positive_rate,
        fallback_rate=fallback_rate,
        dependency_outcome_accuracy=dependency_outcome_accuracy,
        next_executable_prerequisite_accuracy=next_executable_prerequisite_accuracy,
        validator_catch_rate=validator_catch_rate,
        policy_reject_correctness=policy_reject_correctness,
        false_reject_rate=false_reject_rate,
        pre_router_p50_ms=pre_router_p50,
        pre_router_p95_ms=pre_router_p95,
        pre_router_avg_ms=pre_router_avg,
        t0_avg_ms=t0_stats.avg_ms,
        t0_p50_ms=t0_stats.p50_ms,
        t0_p95_ms=t0_stats.p95_ms,
        t1_avg_ms=t1_stats.avg_ms,
        t1_p50_ms=t1_stats.p50_ms,
        t1_p95_ms=t1_stats.p95_ms,
        total_avg_ms=total_stats.avg_ms,
        total_p50_ms=total_stats.p50_ms,
        total_p95_ms=total_stats.p95_ms,
        average_stage_latency_ms=average_stage_latency_ms,
        stage_p50_ms=stage_p50_ms,
        stage_p95_ms=stage_p95_ms,
        latency_by_actual_outcome=_latency_stats_by_key(rows, "total"),
        latency_by_actual_outcome_t0=_latency_stats_by_key(rows, "t0"),
        latency_by_actual_outcome_t1=_latency_stats_by_key(rows, "t1"),
        clarification_completion_rate=clarification_completion_rate,
        average_clarification_turns=average_clarification_turns,
        clarify_to_route_rate=clarify_to_route_rate,
        outcome_breakdown=outcome_breakdown,
        rows=rows,
        clarification_rows=clarification_rows,
    )


def report_to_dict(report: ReferenceEvaluationReport) -> dict[str, Any]:
    payload = asdict(report)
    return payload



def _latency_outcome_table(by_outcome: dict[str, LatencyStats]) -> list[str]:
    if not by_outcome:
        return ["(no samples)", ""]
    lines = [
        "| Outcome | n | avg ms | p50 ms | p95 ms |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for outcome, stats in by_outcome.items():
        lines.append(
            f"| {outcome} | {stats.count} | "
            f"{stats.avg_ms:.2f} | {stats.p50_ms:.2f} | {stats.p95_ms:.2f} |"
        )
    lines.append("")
    return lines


def export_report(
    report: ReferenceEvaluationReport,
    output_dir: Path,
    *,
    basename: str | None = None,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = basename or f"benchmark_{int(time.time())}"
    json_path = output_dir / f"{stamp}.json"
    csv_path = output_dir / f"{stamp}_rows.csv"
    summary_path = output_dir / f"{stamp}_summary.md"

    json_path.write_text(json.dumps(report_to_dict(report), indent=2, ensure_ascii=False), encoding="utf-8")

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "scenario_id",
                "category",
                "expected_outcome",
                "actual_outcome",
                "outcome_match",
                "expected_name",
                "actual_name",
                "intent_match",
                "expected_reason_code",
                "actual_reason_code",
                "reason_code_match",
                "total_latency_ms",
                "t0_latency_ms",
                "t1_latency_ms",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
            ],
        )
        writer.writeheader()
        for row in report.rows:
            writer.writerow(
                {
                    "scenario_id": row.scenario_id,
                    "category": row.category,
                    "expected_outcome": row.expected_outcome,
                    "actual_outcome": row.actual_outcome,
                    "outcome_match": row.outcome_match,
                    "expected_name": row.expected_name,
                    "actual_name": row.actual_name,
                    "intent_match": row.intent_match,
                    "expected_reason_code": row.expected_reason_code,
                    "actual_reason_code": row.actual_reason_code,
                    "reason_code_match": row.reason_code_match,
                    "total_latency_ms": row.total_latency_ms,
                    "t0_latency_ms": row.t0_latency_ms,
                    "t1_latency_ms": row.t1_latency_ms,
                    "prompt_tokens": row.prompt_tokens,
                    "completion_tokens": row.completion_tokens,
                    "total_tokens": row.total_tokens,
                }
            )

    summary_path.write_text(
        "\n".join(
            [
                f"# Benchmark summary — {report.provider} / {report.model}",
                "",
                f"- promptVersion: `{report.prompt_version}`",
                f"- registryVersion: `{report.registry_version}`",
                f"- schemaVersion: `{report.schema_version}`",
                f"- scenarios: {report.total_scenarios}",
                f"- outcome_accuracy: {report.outcome_accuracy:.3f}",
                f"- outcome_accuracy (excl provider errors): "
                f"{report.outcome_accuracy_excluding_provider_errors}",
                f"- provider_errors: {report.provider_error_count} "
                f"({report.provider_error_rate:.3f})",
                f"- vision scenarios: {report.vision_scenario_count} "
                f"acc={report.outcome_accuracy_vision_scenarios}",
                f"- text scenarios: {report.text_scenario_count} "
                f"acc={report.outcome_accuracy_text_scenarios}",
                f"- intent_accuracy: {report.intent_accuracy}",
                f"- false_route_rate: {report.false_route_rate}",
                f"- response_false_positive_rate: {report.response_false_positive_rate}",
                f"- fallback_rate: {report.fallback_rate:.3f}",
                f"- pre_router avg/p50/p95 ms: {report.pre_router_avg_ms} / {report.pre_router_p50_ms} / {report.pre_router_p95_ms}",
                f"- T0 (normalize+policy+pre_router) avg/p50/p95 ms: {report.t0_avg_ms:.2f} / {report.t0_p50_ms:.2f} / {report.t0_p95_ms:.2f}"
                if report.t0_avg_ms is not None
                else "- T0 (normalize+policy+pre_router) avg/p50/p95 ms: —",
                f"- T1 (router/LLM) avg/p50/p95 ms: {report.t1_avg_ms:.2f} / {report.t1_p50_ms:.2f} / {report.t1_p95_ms:.2f}"
                if report.t1_avg_ms is not None
                else "- T1 (router/LLM) avg/p50/p95 ms: — (no router calls in suite)",
                f"- E2E total avg/p50/p95 ms: {report.total_avg_ms:.2f} / {report.total_p50_ms:.2f} / {report.total_p95_ms:.2f}"
                if report.total_avg_ms is not None
                else "- E2E total avg/p50/p95 ms: —",
                f"- clarify→route rate: {report.clarify_to_route_rate}",
                "",
                "## Latency by actual outcome",
                "",
                "### E2E total",
                "",
                *_latency_outcome_table(report.latency_by_actual_outcome),
                "### T0 (normalize + policy + pre_router)",
                "",
                *_latency_outcome_table(report.latency_by_actual_outcome_t0),
                "### T1 (router / LLM only)",
                "",
                *_latency_outcome_table(report.latency_by_actual_outcome_t1),
                "## Per-stage average / p50 / p95 (ms)",
                "",
                "| Stage | avg | p50 | p95 |",
                "| --- | ---: | ---: | ---: |",
                *[
                    f"| `{stage}` | {report.average_stage_latency_ms.get(stage, 0):.3f} | "
                    f"{(report.stage_p50_ms.get(stage) or 0):.3f} | "
                    f"{(report.stage_p95_ms.get(stage) or 0):.3f} |"
                    for stage in sorted(report.average_stage_latency_ms)
                ],
                "",
                "Use this report to propose Overview §3.4 release thresholds (M5).",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return {"json": json_path, "csv": csv_path, "summary": summary_path}


def run_benchmark(
    *,
    providers: list[Any],
    scenarios: tuple[Scenario, ...],
    clarification_chains: tuple[ClarificationChain, ...] = (),
    output_dir: Path | None = None,
) -> list[ReferenceEvaluationReport]:
    """Run evaluate_reference for each provider and optionally export reports."""
    from reference_runtime.registry_loader import registry_from_yaml

    reports: list[ReferenceEvaluationReport] = []
    registry = registry_from_yaml()
    out = output_dir or Path("benchmark_reports")
    for provider in providers:
        router = ReferenceRouter(router=provider, registry=registry)
        report = evaluate_reference(router, scenarios, clarification_chains)
        reports.append(report)
        model_slug = (report.model or report.provider).replace(" ", "_").replace("/", "_")
        export_report(report, out, basename=f"benchmark_{model_slug}")
    return reports

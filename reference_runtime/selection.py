"""Model-selection metrics + ranking (DocAtlas §15.3 / Overview §3.4).

Three selection metrics only:
  1. accuracy — public outcome match; ROUTE also requires correct capability name
     (outcome_accuracy already encodes that). false_route + RESPONSE FP are floor gates.
  2. latency — router-stage p95 ms (NOT pre-router).
  3. cost — mean total_tokens / LLM request; optional $ from pricing_snapshot.yaml.

Watch-only (logged, not ranked): fallback_rate, clarify→route, reason_code accuracy.
"""

from __future__ import annotations

import csv
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from reference_runtime.evaluation import ReferenceEvaluationReport

ROOT = Path(__file__).resolve().parent
DEFAULT_PRICING_PATH = ROOT / "pricing_snapshot.yaml"

# Soft proposal from prior baseline (gpt-4o-mini ≈ 0.771). Product approves later.
DEFAULT_PROPOSED_ACCURACY_FLOOR = 0.75
# Hard-fail components when above these rates (proposed; Product may tighten).
DEFAULT_MAX_FALSE_ROUTE_RATE = 0.15
DEFAULT_MAX_RESPONSE_FP_RATE = 0.10


@dataclass(frozen=True)
class ModelPrice:
    input_usd_per_1m: float
    output_usd_per_1m: float


@dataclass
class SelectionRow:
    provider: str
    model: str
    accuracy: float
    false_route_rate: float | None
    response_false_positive_rate: float | None
    router_avg_ms: float | None
    router_p95_ms: float | None
    mean_total_tokens: float | None
    mean_prompt_tokens: float | None
    mean_completion_tokens: float | None
    llm_call_count: int
    est_usd_per_request: float | None
    est_usd_total: float | None
    passes_floor: bool
    fail_reasons: list[str] = field(default_factory=list)
    prompt_version: str = ""
    registry_version: str = ""
    schema_version: str = ""
    total_scenarios: int = 0
    watch_fallback_rate: float | None = None
    accuracy_excluding_provider_errors: float | None = None
    vision_accuracy: float | None = None
    provider_error_rate: float | None = None


@dataclass
class SelectionRecommendation:
    primary: str | None
    fallback: str | None
    proposed_accuracy_floor: float
    ranking_order: list[str]
    notes: list[str] = field(default_factory=list)


def load_pricing(path: Path | None = None) -> dict[str, ModelPrice]:
    pricing_path = path or DEFAULT_PRICING_PATH
    if not pricing_path.exists():
        return {}
    payload = yaml.safe_load(pricing_path.read_text(encoding="utf-8")) or {}
    models = payload.get("models") or {}
    out: dict[str, ModelPrice] = {}
    for model_id, row in models.items():
        if row is None:
            continue
        inp = row.get("input_usd_per_1m")
        outp = row.get("output_usd_per_1m")
        if inp is None or outp is None:
            continue
        out[str(model_id)] = ModelPrice(float(inp), float(outp))
    return out


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def extract_selection_row(
    report: ReferenceEvaluationReport,
    *,
    pricing: dict[str, ModelPrice] | None = None,
    accuracy_floor: float = DEFAULT_PROPOSED_ACCURACY_FLOOR,
    max_false_route: float = DEFAULT_MAX_FALSE_ROUTE_RATE,
    max_response_fp: float = DEFAULT_MAX_RESPONSE_FP_RATE,
) -> SelectionRow:
    pricing = pricing if pricing is not None else load_pricing()
    model = report.model or "unknown"

    prompt_vals = [float(r.prompt_tokens) for r in report.rows if r.prompt_tokens is not None]
    completion_vals = [
        float(r.completion_tokens) for r in report.rows if r.completion_tokens is not None
    ]
    total_vals = [float(r.total_tokens) for r in report.rows if r.total_tokens is not None]

    mean_prompt = _mean(prompt_vals)
    mean_completion = _mean(completion_vals)
    mean_total = _mean(total_vals)
    llm_call_count = len(total_vals)

    est_usd: float | None = None
    est_usd_total: float | None = None
    price = pricing.get(model)
    if price is not None and prompt_vals and completion_vals:
        # Pair by overlapping LLM rows that have both prompt+completion reported.
        paired = [
            (float(r.prompt_tokens), float(r.completion_tokens))
            for r in report.rows
            if r.prompt_tokens is not None and r.completion_tokens is not None
        ]
        if paired:
            costs = [
                (p / 1_000_000.0) * price.input_usd_per_1m
                + (c / 1_000_000.0) * price.output_usd_per_1m
                for p, c in paired
            ]
            est_usd = statistics.fmean(costs)
            est_usd_total = sum(costs)

    router_avg = (report.average_stage_latency_ms or {}).get("router")
    router_p95 = (report.stage_p95_ms or {}).get("router")

    fail_reasons: list[str] = []
    if report.outcome_accuracy < accuracy_floor:
        fail_reasons.append(
            f"accuracy {report.outcome_accuracy:.3f} < floor {accuracy_floor:.3f}"
        )
    if report.false_route_rate is not None and report.false_route_rate > max_false_route:
        fail_reasons.append(
            f"false_route {report.false_route_rate:.3f} > max {max_false_route:.3f}"
        )
    if (
        report.response_false_positive_rate is not None
        and report.response_false_positive_rate > max_response_fp
    ):
        fail_reasons.append(
            f"response_fp {report.response_false_positive_rate:.3f} > max {max_response_fp:.3f}"
        )

    return SelectionRow(
        provider=report.provider,
        model=model,
        accuracy=report.outcome_accuracy,
        false_route_rate=report.false_route_rate,
        response_false_positive_rate=report.response_false_positive_rate,
        router_avg_ms=router_avg,
        router_p95_ms=router_p95,
        mean_total_tokens=mean_total,
        mean_prompt_tokens=mean_prompt,
        mean_completion_tokens=mean_completion,
        llm_call_count=llm_call_count,
        est_usd_per_request=est_usd,
        est_usd_total=est_usd_total,
        passes_floor=not fail_reasons,
        fail_reasons=fail_reasons,
        prompt_version=report.prompt_version,
        registry_version=report.registry_version,
        schema_version=report.schema_version,
        total_scenarios=report.total_scenarios,
        watch_fallback_rate=report.fallback_rate,
        accuracy_excluding_provider_errors=report.outcome_accuracy_excluding_provider_errors,
        vision_accuracy=report.outcome_accuracy_vision_scenarios,
        provider_error_rate=report.provider_error_rate,
    )


def _rank_key(row: SelectionRow) -> tuple:
    # Higher accuracy better; lower latency better; lower tokens better; $ tie-break.
    return (
        0 if row.passes_floor else 1,
        -row.accuracy,
        row.router_p95_ms if row.router_p95_ms is not None else float("inf"),
        row.mean_total_tokens if row.mean_total_tokens is not None else float("inf"),
        row.est_usd_per_request if row.est_usd_per_request is not None else float("inf"),
        row.model,
    )


def rank_candidates(rows: list[SelectionRow]) -> list[SelectionRow]:
    return sorted(rows, key=_rank_key)


def recommend(
    rows: list[SelectionRow],
    *,
    accuracy_floor: float = DEFAULT_PROPOSED_ACCURACY_FLOOR,
) -> SelectionRecommendation:
    ranked = rank_candidates(rows)
    # Exclude Fake from production primary/fallback.
    live = [r for r in ranked if not str(r.model).startswith("fake")]
    passers = [r for r in live if r.passes_floor]
    notes: list[str] = [
        f"Proposed accuracy floor={accuracy_floor:.3f} (from baseline; Product approves).",
        "Ranking among passers: accuracy → router p95 → mean tokens → est $.",
        "Watch metrics (fallback, clarify→route, reason_code) are not in selection score.",
    ]
    primary = passers[0].model if passers else None
    fallback = passers[1].model if len(passers) > 1 else None
    if not passers:
        notes.append("No live model passed the proposed floor — do not ship production router.")
    elif fallback is None:
        notes.append("Only one model passed floor — pick a second passer before relying on fallback.")
    return SelectionRecommendation(
        primary=primary,
        fallback=fallback,
        proposed_accuracy_floor=accuracy_floor,
        ranking_order=[r.model for r in live],
        notes=notes,
    )


def export_comparison(
    rows: list[SelectionRow],
    output_dir: Path,
    *,
    basename: str = "benchmark_comparison",
    accuracy_floor: float = DEFAULT_PROPOSED_ACCURACY_FLOOR,
    run_metadata: dict[str, Any] | None = None,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ranked = rank_candidates(rows)
    rec = recommend(ranked, accuracy_floor=accuracy_floor)
    live_ranked = [row for row in ranked if not str(row.model).startswith("fake")]
    run_cost_parts = [row.est_usd_total for row in live_ranked if row.est_usd_total is not None]
    run_est_usd_total = sum(run_cost_parts) if run_cost_parts else None
    run_llm_calls = sum(row.llm_call_count for row in live_ranked)

    json_path = output_dir / f"{basename}.json"
    csv_path = output_dir / f"{basename}.csv"
    md_path = output_dir / f"{basename}.md"

    payload: dict[str, Any] = {
        "recommendation": asdict(rec),
        "run_config": run_metadata or {},
        "run_totals": {
            "live_models": len(live_ranked),
            "llm_calls": run_llm_calls,
            "est_usd_total": run_est_usd_total,
        },
        "rows": [asdict(r) for r in ranked],
    }
    import json

    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    fieldnames = [
        "rank",
        "passes_floor",
        "provider",
        "model",
        "accuracy",
        "accuracy_excluding_provider_errors",
        "vision_accuracy",
        "provider_error_rate",
        "false_route_rate",
        "response_false_positive_rate",
        "router_avg_ms",
        "router_p95_ms",
        "llm_call_count",
        "mean_total_tokens",
        "est_usd_per_request",
        "est_usd_total",
        "fail_reasons",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index, row in enumerate(ranked, start=1):
            writer.writerow(
                {
                    "rank": index,
                    "passes_floor": row.passes_floor,
                    "provider": row.provider,
                    "model": row.model,
                    "accuracy": f"{row.accuracy:.4f}",
                    "accuracy_excluding_provider_errors": row.accuracy_excluding_provider_errors,
                    "vision_accuracy": row.vision_accuracy,
                    "provider_error_rate": row.provider_error_rate,
                    "false_route_rate": row.false_route_rate,
                    "response_false_positive_rate": row.response_false_positive_rate,
                    "router_avg_ms": row.router_avg_ms,
                    "router_p95_ms": row.router_p95_ms,
                    "llm_call_count": row.llm_call_count,
                    "mean_total_tokens": row.mean_total_tokens,
                    "est_usd_per_request": row.est_usd_per_request,
                    "est_usd_total": row.est_usd_total,
                    "fail_reasons": "; ".join(row.fail_reasons),
                }
            )

    lines = [
        "# Model selection comparison",
        "",
        f"- proposed accuracy floor: **{accuracy_floor:.3f}** (Product approves)",
        f"- primary: **{rec.primary or '(none)'}**",
        f"- fallback: **{rec.fallback or '(none)'}**",
        f"- ranking order: {', '.join(rec.ranking_order) or '(empty)'}",
        f"- run LLM calls (live): **{run_llm_calls}**",
        f"- run estimated cost (live models): **{_fmt_usd(run_est_usd_total)}**",
    ]
    if run_metadata:
        lines.append(f"- run config: `{run_metadata}`")
    lines.extend(
        [
        "",
        "## Selection metrics",
        "",
        "| Rank | Pass | Model | Accuracy | Acc excl provider | Vision acc | Router p95 ms | Est $/req |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for index, row in enumerate(live_ranked, start=1):
        lines.append(
            "| {rank} | {pass_} | `{model}` | {acc:.3f} | {acc_ex} | {vis} | {p95} | {usd} |".format(
                rank=index,
                pass_="yes" if row.passes_floor else "no",
                model=row.model,
                acc=row.accuracy,
                acc_ex=_fmt(row.accuracy_excluding_provider_errors),
                vis=_fmt(row.vision_accuracy),
                p95=_fmt(row.router_p95_ms, digits=0),
                usd=_fmt_usd(row.est_usd_per_request),
            )
        )
    lines.extend(["", "## Notes", ""])
    for note in rec.notes:
        lines.append(f"- {note}")
    for row in ranked:
        if row.fail_reasons:
            lines.append(f"- `{row.model}` fail: {'; '.join(row.fail_reasons)}")
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")

    return {"json": json_path, "csv": csv_path, "md": md_path}


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "—"
    if digits == 0:
        return f"{value:.0f}"
    return f"{value:.{digits}f}"


def _fmt_usd(value: float | None) -> str:
    if value is None:
        return "—"
    return f"${value:.6f}"

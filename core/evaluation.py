from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from core.taxonomy import Taxonomy
from core.request import RouteRequest
from routers.base import RouteResult, RouterStatus


REQUIRED_COLUMNS = {"text", "expected_intent"}


@dataclass
class EvaluationReport:
    provider: str
    metrics: dict[str, float | int | None]
    rows: pd.DataFrame
    confusion_matrix: pd.DataFrame


def validate_evaluation_frame(frame: pd.DataFrame, taxonomy: Taxonomy) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"evaluation CSV is missing columns: {', '.join(sorted(missing))}")
    columns = ["text", "expected_intent"]
    if "has_image" in frame.columns:
        columns.append("has_image")
    clean = frame.loc[:, columns].copy()
    if clean.isna().any().any():
        raise ValueError("evaluation rows cannot contain empty values")
    clean["text"] = clean["text"].astype(str).str.strip()
    clean["expected_intent"] = clean["expected_intent"].astype(str).str.strip()
    if (clean[["text", "expected_intent"]] == "").any().any():
        raise ValueError("evaluation rows cannot contain blank strings")
    if "has_image" in clean.columns:
        normalized_context = clean["has_image"].astype(str).str.strip().str.lower()
        invalid_context = ~normalized_context.isin(
            {"true", "false", "1", "0", "yes", "no"}
        )
        if invalid_context.any():
            raise ValueError("has_image values must be true or false")
    unknown_labels = sorted(set(clean["expected_intent"]) - set(taxonomy.labels))
    if unknown_labels:
        raise ValueError(f"evaluation contains labels outside taxonomy: {unknown_labels}")
    return clean


def evaluate_router(
    provider: str,
    route: Callable[[RouteRequest], RouteResult],
    frame: pd.DataFrame,
    taxonomy: Taxonomy,
    progress: Callable[[int, int], None] | None = None,
    warmup_calls: int = 1,
) -> EvaluationReport:
    data = validate_evaluation_frame(frame, taxonomy)
    for _ in range(warmup_calls):
        route(_request_from_row(data.iloc[0]))

    records: list[dict[str, object]] = []
    for index, row in data.iterrows():
        result = route(_request_from_row(row))
        prediction = result.intent if result.intent is not None else "unknown"
        records.append(
            {
                "text": row["text"],
                "expected_intent": row["expected_intent"],
                "predicted_intent": prediction,
                "status": result.status.value,
                "confidence": result.confidence,
                "properties": result.properties,
                "latency_ms": result.latency_ms,
                "error_code": result.error.code if result.error else None,
                "input_tokens": _raw_value(result, "usage", "input_tokens"),
                "output_tokens": _raw_value(result, "usage", "output_tokens"),
                "thinking_tokens": _raw_value(result, "usage", "thinking_tokens"),
                "estimated_cost": _raw_value(result, "estimated_cost", "amount"),
            }
        )
        if progress:
            progress(len(records), len(data))

    rows = pd.DataFrame(records)
    accepted = rows["status"].isin(
        [RouterStatus.OK.value, RouterStatus.DEGRADED.value]
    ) & (rows["predicted_intent"] != "unknown")
    correct = rows["predicted_intent"] == rows["expected_intent"]
    known = rows["expected_intent"] != "unknown"
    expected_unknown = ~known
    latencies = rows["latency_ms"].astype(float)
    schema_failures = rows["error_code"].eq("SCHEMA_FAILURE")
    metrics: dict[str, float | int | None] = {
        "rows": len(rows),
        "overall_accuracy": float(correct.mean()),
        "known_accuracy": float(correct[known].mean()) if known.any() else None,
        "unknown_recall": (
            float((rows.loc[expected_unknown, "predicted_intent"] == "unknown").mean())
            if expected_unknown.any()
            else None
        ),
        "false_acceptance_rate": (
            float((rows.loc[expected_unknown, "predicted_intent"] != "unknown").mean())
            if expected_unknown.any()
            else None
        ),
        "unknown_rate": float((rows["predicted_intent"] == "unknown").mean()),
        "coverage": float(accepted.mean()),
        "selective_accuracy": float(correct[accepted].mean()) if accepted.any() else None,
        "average_latency_ms": float(latencies.mean()),
        "median_latency_ms": float(latencies.median()),
        "p95_latency_ms": float(np.percentile(latencies, 95)),
        "schema_failure_rate": float(schema_failures.mean()),
        "input_tokens": _sum_optional(rows["input_tokens"]),
        "output_tokens": _sum_optional(rows["output_tokens"]),
        "thinking_tokens": _sum_optional(rows["thinking_tokens"]),
        "estimated_cost": _sum_optional(rows["estimated_cost"]),
    }
    labels = taxonomy.labels
    confusion = pd.crosstab(
        rows["expected_intent"],
        rows["predicted_intent"],
        rownames=["Expected"],
        colnames=["Predicted"],
        dropna=False,
    ).reindex(index=labels, columns=labels, fill_value=0)
    return EvaluationReport(
        provider=provider,
        metrics=metrics,
        rows=rows,
        confusion_matrix=confusion,
    )


def _raw_value(result: RouteResult, group: str, key: str) -> object:
    raw = result.raw_output
    if not isinstance(raw, dict):
        return None
    nested = raw.get(group)
    return nested.get(key) if isinstance(nested, dict) else None


def _sum_optional(values: pd.Series) -> float | int | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return None
    total = float(numeric.sum())
    return int(total) if math.isclose(total, round(total)) else total


def _request_from_row(row: pd.Series) -> RouteRequest:
    value = row.get("has_image", False)
    has_image = str(value).strip().lower() in {"true", "1", "yes"}
    return RouteRequest(
        text=str(row["text"]),
        image_count_hint=1 if has_image else 0,
    )

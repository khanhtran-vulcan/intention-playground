#!/usr/bin/env python3
"""CLI: Intention V1 model-selection benchmark harness.

Examples:
  # CI smoke (Fake only)
  make benchmark

  # Env-default providers (1 model each from GEMINI_MODEL / OPENAI_MODEL)
  make benchmark PROVIDERS=fake,gemini,openai

  # All selection candidates in parallel → comparison + primary/fallback
  make benchmark-select
  .venv/bin/python -m reference_runtime.benchmark_cli --candidates default --parallel
"""

from __future__ import annotations

import argparse
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

from reference_runtime.candidates import (
    DEFAULT_SELECTION_CANDIDATES,
    BenchmarkCandidate,
    candidates_to_spec,
    parse_candidates,
)
from reference_runtime.evaluation import ScenarioRow, evaluate_reference, export_report
from reference_runtime.registry_loader import registry_from_yaml
from reference_runtime.router.fake import FakeRouterProvider
from reference_runtime.runtime import ReferenceRouter
from reference_runtime.scenarios import (
    Scenario,
    clarification_chains_for_suite,
    scenarios_for_suite,
)
from reference_runtime.selection import (
    DEFAULT_PROPOSED_ACCURACY_FLOOR,
    export_comparison,
    extract_selection_row,
    recommend,
)

ROOT = Path(__file__).resolve().parent.parent
_PROVIDER_ENV = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
}
_PROVIDER_FAIL_CODES = frozenset(
    {
        "PROVIDER_MISSING_CREDENTIALS",
        "PROVIDER_TIMEOUT",
        "PROVIDER_REQUEST_FAILED",
        "INVALID_PROVIDER_OUTPUT",
    }
)
_SLOW_GEMINI_MODELS = frozenset({"gemini-2.5-flash", "models/gemini-2.5-flash"})
_DEFAULT_PARALLEL_WORKER_CAP = 3
_print_lock = threading.Lock()


def _load_env() -> Path | None:
    env_path = ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        return env_path
    load_dotenv()
    return None


def _log(message: str) -> None:
    with _print_lock:
        print(message, flush=True)


def _require_live_credentials(provider_keys: list[str]) -> None:
    missing = []
    for key in provider_keys:
        env_name = _PROVIDER_ENV.get(key)
        if env_name and not (os.getenv(env_name) or "").strip():
            missing.append(f"{key} needs {env_name}")
    if missing:
        env_hint = ROOT / ".env"
        raise SystemExit(
            "Live provider credentials missing from process env:\n  - "
            + "\n  - ".join(missing)
            + f"\nPut them in {env_hint} (CLI now loads that file) or export them, then re-run.\n"
            "Without keys, Gemini/OpenAI return PROVIDER_MISSING_CREDENTIALS → FALLBACK "
            "(~0.34 accuracy from deterministic stages only — not a real model score)."
        )


def _build_provider_from_name(name: str, registry, *, timeout_seconds: float):
    key = name.strip().lower()
    if key == "fake":
        return FakeRouterProvider()
    if key == "gemini":
        from reference_runtime.router.gemini import GeminiRouterProvider

        return GeminiRouterProvider(registry=registry, timeout_seconds=timeout_seconds)
    if key == "openai":
        from reference_runtime.router.openai import OpenAIRouterProvider

        return OpenAIRouterProvider(registry=registry, timeout_seconds=timeout_seconds)
    raise SystemExit(f"Unknown provider: {name}")


def _build_provider_from_candidate(
    candidate: BenchmarkCandidate, registry, *, timeout_seconds: float
):
    if candidate.provider == "gemini":
        from reference_runtime.router.gemini import GeminiRouterProvider

        return GeminiRouterProvider(
            registry=registry, model_name=candidate.model_id, timeout_seconds=timeout_seconds
        )
    if candidate.provider == "openai":
        from reference_runtime.router.openai import OpenAIRouterProvider

        return OpenAIRouterProvider(
            registry=registry, model_name=candidate.model_id, timeout_seconds=timeout_seconds
        )
    raise SystemExit(f"Unknown provider: {candidate.provider}")


def _credential_status_line(provider_keys: list[str]) -> str:
    parts = []
    seen = []
    for key in provider_keys:
        if key in seen:
            continue
        seen.append(key)
        env_name = _PROVIDER_ENV.get(key)
        if not env_name:
            parts.append(f"{key}=n/a")
            continue
        present = bool((os.getenv(env_name) or "").strip())
        parts.append(f"{env_name}={'yes' if present else 'NO'}")
    return ", ".join(parts)


def _warn_slow_gemini(provider: object) -> None:
    model = str(getattr(provider, "model", "") or "").strip().lower()
    if model in _SLOW_GEMINI_MODELS:
        _log(
            "  WARNING: model "
            f"{model} routinely times out on structured router JSON "
            "(~20–30s/call × 35 scenarios). Prefer a Lite Flash model."
        )


class _ProgressTracker:
    """Print per-scenario progress; abort after consecutive provider timeouts."""

    def __init__(self, *, abort_after_timeouts: int, prefix: str = "") -> None:
        self.abort_after_timeouts = abort_after_timeouts
        self.consecutive_timeouts = 0
        self.aborted = False
        self.prefix = prefix

    def __call__(
        self, index: int, total: int, scenario: Scenario, row: ScenarioRow
    ) -> bool:
        mark = "ok" if row.outcome_match else "miss"
        extra = ""
        if row.actual_reason_code in _PROVIDER_FAIL_CODES:
            extra = f" [{row.actual_reason_code}]"
            if row.actual_reason_code == "PROVIDER_TIMEOUT":
                self.consecutive_timeouts += 1
            else:
                self.consecutive_timeouts = 0
        else:
            self.consecutive_timeouts = 0

        router_ms = row.stage_latency_ms.get("router")
        latency = f" router={router_ms:.0f}ms" if router_ms is not None else ""
        _log(
            f"{self.prefix}[{index}/{total}] {scenario.id}: "
            f"{row.actual_outcome} ({mark}){extra}{latency}"
        )
        if (
            self.abort_after_timeouts > 0
            and self.consecutive_timeouts >= self.abort_after_timeouts
        ):
            self.aborted = True
            _log(
                f"{self.prefix}ABORTED after {self.consecutive_timeouts} consecutive "
                "PROVIDER_TIMEOUT (partial report still written)."
            )
            return False
        return True


def _run_one(
    *,
    provider,
    registry,
    output_dir: Path,
    quiet: bool,
    abort_after_timeouts: int,
    label_index: int,
    label_total: int,
    scenarios,
    clarification_chains,
):
    label = f"{getattr(provider, 'name', type(provider).__name__)}/{getattr(provider, 'model', '?')}"
    prefix = f"[{label_index}/{label_total} {getattr(provider, 'model', '?')}] "
    _log(f"\n[{label_index}/{label_total}] Running {label} …")
    _warn_slow_gemini(provider)
    started = time.perf_counter()
    router = ReferenceRouter(router=provider, registry=registry)
    tracker = (
        None
        if quiet
        else _ProgressTracker(abort_after_timeouts=abort_after_timeouts, prefix=prefix)
    )
    report = evaluate_reference(router, scenarios, clarification_chains, progress=tracker)
    model_slug = (report.model or report.provider).replace(" ", "_").replace("/", "_")
    paths = export_report(report, output_dir, basename=f"benchmark_{model_slug}")
    elapsed = time.perf_counter() - started

    fail_rows = [row for row in report.rows if row.actual_reason_code in _PROVIDER_FAIL_CODES]
    _log(
        f"{prefix}done in {elapsed:.1f}s → outcome_acc={report.outcome_accuracy:.3f} "
        f"acc_excl_provider={report.outcome_accuracy_excluding_provider_errors} "
        f"vision_acc={report.outcome_accuracy_vision_scenarios} "
        f"false_route={report.false_route_rate} "
        f"response_fp={report.response_false_positive_rate} "
        f"fallback_rate={report.fallback_rate:.3f}"
        + (" (partial — aborted early)" if tracker and tracker.aborted else "")
    )
    if fail_rows:
        from collections import Counter

        counts = Counter(row.actual_reason_code for row in fail_rows)
        _log(
            f"{prefix}WARNING: {len(fail_rows)}/{report.total_scenarios} rows hit provider "
            f"errors: {dict(counts)}"
        )
    _log(f"{prefix}wrote {paths['json'].name}")
    return report


def _resolve_candidates(args) -> list[tuple[str, object]]:
    """Return list of (kind, provider_or_candidate) where kind is 'fake'|'live'."""
    registry = registry_from_yaml()
    timeout = float(args.provider_timeout)
    items: list[tuple[str, object]] = []

    if args.candidates:
        spec = args.candidates.strip()
        if spec.lower() == "default":
            candidates = list(DEFAULT_SELECTION_CANDIDATES)
        else:
            candidates = parse_candidates(spec)
        if args.include_fake:
            items.append(("fake", FakeRouterProvider()))
        for candidate in candidates:
            items.append(
                (
                    "live",
                    _build_provider_from_candidate(candidate, registry, timeout_seconds=timeout),
                )
            )
        return items

    names = [part.strip() for part in args.providers.split(",") if part.strip()]
    for name in names:
        items.append(
            (
                "fake" if name.strip().lower() == "fake" else "live",
                _build_provider_from_name(name, registry, timeout_seconds=timeout),
            )
        )
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description="Intention V1 router model benchmark")
    parser.add_argument(
        "--providers",
        default="fake",
        help="Comma-separated: fake,gemini,openai (uses GEMINI_MODEL / OPENAI_MODEL).",
    )
    parser.add_argument(
        "--candidates",
        default="",
        help=(
            "'default' for selection shortlist, or "
            "provider:model,... e.g. openai:gpt-5.6-luna,gemini:gemini-3.5-flash-lite"
        ),
    )
    parser.add_argument(
        "--include-fake",
        action="store_true",
        help="With --candidates, also run Fake (CI baseline).",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Run candidates/providers concurrently (one thread per model).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help=(
            "Max parallel workers when --parallel (default: min(3, n_models); "
            "use 1 for fully sequential multi-model runs)."
        ),
    )
    parser.add_argument(
        "--provider-timeout",
        type=float,
        default=30.0,
        help="Router LLM timeout in seconds (OpenAI + Gemini).",
    )
    parser.add_argument(
        "--output-dir",
        default="benchmark_reports",
        help="Directory for JSON/CSV/summary exports",
    )
    parser.add_argument(
        "--allow-missing-credentials",
        action="store_true",
        help="Do not exit when live API keys are missing (scores will be ~deterministic-only).",
    )
    parser.add_argument(
        "--abort-after-timeouts",
        type=int,
        default=3,
        help="Stop a provider early after N consecutive PROVIDER_TIMEOUT rows (0=never).",
    )
    parser.add_argument(
        "--accuracy-floor",
        type=float,
        default=DEFAULT_PROPOSED_ACCURACY_FLOOR,
        help="Proposed accuracy floor for primary/fallback recommendation.",
    )
    parser.add_argument(
        "--suite",
        choices=("core", "deferred", "all"),
        default="core",
        help=(
            "Scenario suite: core (default, selection ranking), deferred (prompt-hard), "
            "or all (full regression including clarify chains)."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print per-scenario progress lines.",
    )
    args = parser.parse_args()

    env_path = _load_env()
    items = _resolve_candidates(args)
    live_keys = []
    for kind, provider in items:
        if kind == "fake":
            continue
        model = str(getattr(provider, "model", "") or "")
        live_keys.append("gemini" if model.startswith("gemini") else "openai")
    # Also include provider env from --providers mode
    if not args.candidates:
        for part in args.providers.split(","):
            key = part.strip().lower()
            if key in _PROVIDER_ENV:
                live_keys.append(key)

    scenarios = scenarios_for_suite(args.suite)
    clarification_chains = clarification_chains_for_suite(args.suite)
    deferred_n = sum(1 for s in scenarios_for_suite("deferred"))

    _log(f"Suite: {args.suite} · scenarios: {len(scenarios)} · clarify chains: {len(clarification_chains)}")
    _log(f"Provider timeout: {args.provider_timeout}s")
    if args.suite == "core":
        _log(
            f"  (deferred {deferred_n} prompt-hard cases skipped — re-run with --suite all after prompt fix)"
        )
    _log(f".env loaded: {env_path if env_path else '(not found)'}")
    _log(f"Credentials: {_credential_status_line(live_keys or ['fake'])}")
    if args.candidates:
        if args.candidates.strip().lower() == "default":
            _log(f"Candidates: {candidates_to_spec(DEFAULT_SELECTION_CANDIDATES)}")
        else:
            _log(f"Candidates: {args.candidates}")
    if not args.allow_missing_credentials and live_keys:
        _require_live_credentials(live_keys)

    registry = registry_from_yaml()
    out = Path(args.output_dir)
    total = len(items)
    reports = []

    def job(index_and_item):
        index, (_kind, provider) = index_and_item
        # Fresh registry per worker avoids shared mutable state surprises.
        return _run_one(
            provider=provider,
            registry=registry_from_yaml(),
            output_dir=out,
            quiet=args.quiet,
            abort_after_timeouts=args.abort_after_timeouts,
            label_index=index,
            label_total=total,
            scenarios=scenarios,
            clarification_chains=clarification_chains,
        )

    indexed = list(enumerate(items, start=1))
    run_metadata = {
        "suite": args.suite,
        "provider_timeout_seconds": args.provider_timeout,
        "parallel": bool(args.parallel and total > 1),
        "workers": 1,
        "scenario_count": len(scenarios),
        "clarification_chain_count": len(clarification_chains),
    }
    if args.parallel and total > 1:
        workers = args.workers if args.workers > 0 else min(_DEFAULT_PARALLEL_WORKER_CAP, total)
        run_metadata["workers"] = workers
        _log(f"Parallel workers: {workers} (cap default={_DEFAULT_PARALLEL_WORKER_CAP})")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(job, item): item[0] for item in indexed}
            # Preserve submission order in reports via index sort after gather
            by_index = {}
            for fut in as_completed(futures):
                idx = futures[fut]
                by_index[idx] = fut.result()
            reports = [by_index[i] for i in sorted(by_index)]
    else:
        for item in indexed:
            reports.append(job(item))

    selection_rows = [
        extract_selection_row(report, accuracy_floor=args.accuracy_floor)
        for report in reports
    ]
    comparison_paths = export_comparison(
        selection_rows,
        out,
        accuracy_floor=args.accuracy_floor,
        run_metadata=run_metadata,
    )
    rec = recommend(selection_rows, accuracy_floor=args.accuracy_floor)

    _log(f"\nWrote {len(reports)} per-model report(s) under {args.output_dir}/")
    for row in selection_rows:
        _log(
            f"- {row.provider}/{row.model}: "
            f"acc={row.accuracy:.3f} router_avg={_fmt_ms(row.router_avg_ms)} "
            f"router_p95={_fmt_ms(row.router_p95_ms)} "
            f"tokens={row.mean_total_tokens} $/req={row.est_usd_per_request} "
            f"$total={row.est_usd_total} pass={row.passes_floor}"
        )
    live_costs = [r.est_usd_total for r in selection_rows if r.est_usd_total is not None]
    _log(f"\nComparison: {comparison_paths['md'].name}")
    _log(f"Recommendation: primary={rec.primary} · fallback={rec.fallback}")
    _log(f"Proposed accuracy floor: {rec.proposed_accuracy_floor}")
    if live_costs:
        _log(f"Run estimated cost (all live models): ${sum(live_costs):.6f}")


def _fmt_ms(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.0f}ms"


if __name__ == "__main__":
    main()

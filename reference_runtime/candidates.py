"""Model-selection candidate list for Intention V1 router benchmark.

DocAtlas §15.3: run every candidate on the same release bundle, then rank by
accuracy → latency → cost. Fake is CI-only (not a production candidate).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkCandidate:
    """One live model to evaluate under a fixed provider adapter."""

    provider: str  # gemini | openai
    model_id: str
    note: str = ""


# Operator shortlist for primary/fallback selection (excludes retiring 2.5-flash-lite).
DEFAULT_SELECTION_CANDIDATES: tuple[BenchmarkCandidate, ...] = (
    BenchmarkCandidate("openai", "gpt-5.6-luna", "best overall (operator prior)"),
    BenchmarkCandidate("gemini", "gemini-3.5-flash-lite", "best Gemini (operator prior)"),
    BenchmarkCandidate("openai", "gpt-5-nano", "best cost (operator prior)"),
    BenchmarkCandidate("openai", "gpt-5.4-nano", "strong alternative"),
    BenchmarkCandidate("gemini", "gemini-3.1-flash-lite", "previous-gen Lite"),
    BenchmarkCandidate("openai", "gpt-5-mini", "higher quality mini"),
)


def parse_candidates(spec: str) -> list[BenchmarkCandidate]:
    """Parse `provider:model,provider:model` (or bare model IDs with inference)."""
    out: list[BenchmarkCandidate] = []
    for part in spec.split(","):
        token = part.strip()
        if not token:
            continue
        if ":" in token:
            provider, model_id = token.split(":", 1)
            provider = provider.strip().lower()
            model_id = model_id.strip()
        else:
            model_id = token
            provider = "gemini" if model_id.startswith("gemini") else "openai"
        if provider not in {"gemini", "openai"}:
            raise ValueError(f"Unknown provider in candidate: {token}")
        if not model_id:
            raise ValueError(f"Empty model id in candidate: {token}")
        out.append(BenchmarkCandidate(provider=provider, model_id=model_id))
    return out


def candidates_to_spec(candidates: tuple[BenchmarkCandidate, ...] | list[BenchmarkCandidate]) -> str:
    return ",".join(f"{c.provider}:{c.model_id}" for c in candidates)

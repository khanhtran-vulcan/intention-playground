from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.taxonomy import Taxonomy
from routers.gemini_router import GeminiRouter
from routers.hybrid_router import HybridRouter
from routers.rule_router import RuleRouter
from routers.semantic_router import DEFAULT_MODEL_NAME, SemanticRouter
from routers.sklearn_router import SklearnRouter, load_or_train_artifact


@dataclass(frozen=True)
class RuntimeState:
    taxonomy: Taxonomy
    taxonomy_hash: str
    rule_router: RuleRouter
    sklearn_router: SklearnRouter
    semantic_router: SemanticRouter
    gemini_router: GeminiRouter
    hybrid_router: HybridRouter


def build_runtime_state(
    taxonomy: Taxonomy,
    model_path: Path | None = None,
    persist_default_artifact: bool = False,
    semantic_model_name: str = DEFAULT_MODEL_NAME,
    gemini_model_name: str | None = None,
    gemini_timeout_seconds: float = 15.0,
) -> RuntimeState:
    # Build all local configuration before publishing the immutable session state.
    rule_router = RuleRouter(taxonomy)
    artifact = load_or_train_artifact(
        taxonomy,
        model_path=model_path,
        persist=persist_default_artifact,
    )
    sklearn_router = SklearnRouter(artifact)
    sklearn_router.taxonomy = taxonomy
    semantic_router = SemanticRouter(taxonomy, model_name=semantic_model_name)
    gemini_router = GeminiRouter(
        taxonomy,
        model_name=gemini_model_name,
        timeout_seconds=gemini_timeout_seconds,
    )
    hybrid_router = HybridRouter(
        rule_router, sklearn_router, semantic_router, gemini_router
    )
    return RuntimeState(
        taxonomy=taxonomy,
        taxonomy_hash=taxonomy.fingerprint,
        rule_router=rule_router,
        sklearn_router=sklearn_router,
        semantic_router=semantic_router,
        gemini_router=gemini_router,
        hybrid_router=hybrid_router,
    )

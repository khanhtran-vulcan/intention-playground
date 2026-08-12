from __future__ import annotations

import threading
import time
from functools import lru_cache
from typing import Any, Callable

import numpy as np

from core.taxonomy import Taxonomy
from core.request import RouteRequest
from routers.base import (
    RouteResult,
    RouterError,
    RouterStatus,
    request_metadata,
    sanitize_raw_output,
)


DEFAULT_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@lru_cache(maxsize=2)
def load_embedding_model(model_name: str = DEFAULT_MODEL_NAME) -> Any:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


class SemanticRouter:
    provider = "Semantic Router"

    def __init__(
        self,
        taxonomy: Taxonomy,
        model_name: str = DEFAULT_MODEL_NAME,
        model_loader: Callable[[str], Any] = load_embedding_model,
    ):
        self.model_name = model_name
        self.taxonomy = taxonomy
        self.model_loader = model_loader
        self.example_texts: list[str] = []
        self.example_labels: list[str] = []
        self.example_display_texts: list[str] = []
        for intent in taxonomy.known_intents:
            for example in intent.examples:
                self.example_texts.append(RouteRequest(text=example).classification_text())
                self.example_display_texts.append(example)
                self.example_labels.append(intent.name)
            for example in intent.image_examples:
                self.example_texts.append(
                    RouteRequest(text=example, image_count_hint=1).classification_text()
                )
                self.example_display_texts.append(example)
                self.example_labels.append(intent.name)
        self._model: Any = None
        self._embeddings: np.ndarray | None = None
        self._initialization_ms: float | None = None
        self._initialization_error: str | None = None
        self._lock = threading.Lock()

    @property
    def initialized(self) -> bool:
        return self._embeddings is not None

    @property
    def initialization_error(self) -> str | None:
        return self._initialization_error

    def reset_initialization(self) -> None:
        with self._lock:
            self._model = None
            self._embeddings = None
            self._initialization_ms = None
            self._initialization_error = None

    def initialize(self) -> float:
        if self._embeddings is not None:
            return self._initialization_ms or 0.0
        if self._initialization_error is not None:
            raise RuntimeError(self._initialization_error)
        with self._lock:
            if self._embeddings is not None:
                return self._initialization_ms or 0.0
            if self._initialization_error is not None:
                raise RuntimeError(self._initialization_error)
            started = time.perf_counter()
            try:
                self._model = self.model_loader(self.model_name)
                self._embeddings = np.asarray(
                    self._model.encode(self.example_texts, normalize_embeddings=True)
                )
                self._initialization_ms = (time.perf_counter() - started) * 1_000
                return self._initialization_ms
            except Exception as exc:
                self._initialization_error = str(exc)[:500]
                raise

    def route(self, request: RouteRequest, threshold: float = 0.55) -> RouteResult:
        started = time.perf_counter()
        initialized_now = self._embeddings is None
        try:
            initialization_ms = self.initialize()
            query = np.asarray(
                self._model.encode(
                    [request.classification_text()], normalize_embeddings=True
                )[0]
            )
            scores = self._embeddings @ query
            best_index = int(np.argmax(scores))
            best_score = max(-1.0, min(1.0, float(scores[best_index])))
            predicted_intent = self.example_labels[best_index]
            accepted = best_score >= threshold
            top_indices = np.argsort(scores)[::-1][:3]
            matches = [
                {
                    "text": self.example_display_texts[int(index)],
                    "intent": self.example_labels[int(index)],
                    "score": float(scores[int(index)]),
                }
                for index in top_indices
            ]
            return RouteResult(
                provider=self.provider,
                status=RouterStatus.OK if accepted else RouterStatus.UNKNOWN,
                intent=predicted_intent if accepted else "unknown",
                confidence=best_score,
                latency_ms=(time.perf_counter() - started) * 1_000,
                reason=(
                    f"Nearest example passed the {threshold:.2f} threshold."
                    if accepted
                    else f"Nearest example was below the {threshold:.2f} threshold."
                ),
                raw_output=sanitize_raw_output(
                    {"predicted_intent": predicted_intent, "matches": matches}
                ),
                metadata={
                    "score_type": "cosine_similarity",
                    "threshold": threshold,
                    "model": self.model_name,
                    "initialization_ms": initialization_ms if initialized_now else 0.0,
                    **request_metadata(
                        self.taxonomy,
                        predicted_intent if accepted else "unknown",
                        request,
                    ),
                },
            )
        except Exception as exc:
            return RouteResult(
                provider=self.provider,
                status=RouterStatus.UNAVAILABLE,
                latency_ms=(time.perf_counter() - started) * 1_000,
                reason="The embedding model or semantic index could not be initialized.",
                metadata={
                    "score_type": "cosine_similarity",
                    "model": self.model_name,
                    **request_metadata(self.taxonomy, None, request),
                },
                error=RouterError(
                    code="SEMANTIC_UNAVAILABLE",
                    message=str(exc)[:500],
                    retryable=True,
                ),
            )

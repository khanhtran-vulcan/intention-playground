from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from core.taxonomy import Taxonomy
from core.request import RouteRequest
from routers.base import (
    RouteResult,
    RouterStatus,
    request_metadata,
    sanitize_raw_output,
)


TRAINING_CONFIG: dict[str, Any] = {
    "normalization": "RouteRequest.classification_text.v1 + TfidfVectorizer(lowercase=True)",
    "vectorizer": {
        "analyzer": "char_wb",
        "ngram_range": (2, 5),
        "min_df": 1,
        "lowercase": True,
    },
    "classifier": {
        "max_iter": 1_000,
        "class_weight": "balanced",
        "random_state": 42,
    },
}


def training_config_hash(taxonomy: Taxonomy) -> str:
    payload = {
        "config": TRAINING_CONFIG,
        "label_order": sorted(intent.name for intent in taxonomy.known_intents),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def train_pipeline(taxonomy: Taxonomy) -> Pipeline:
    texts: list[str] = []
    labels: list[str] = []
    for intent in taxonomy.known_intents:
        for example in intent.examples:
            texts.append(RouteRequest(text=example).classification_text())
            labels.append(intent.name)
        for example in intent.image_examples:
            texts.append(
                RouteRequest(text=example, image_count_hint=1).classification_text()
            )
            labels.append(intent.name)
    pipeline = Pipeline(
        [
            ("tfidf", TfidfVectorizer(**TRAINING_CONFIG["vectorizer"])),
            ("classifier", LogisticRegression(**TRAINING_CONFIG["classifier"])),
        ]
    )
    pipeline.fit(texts, labels)
    return pipeline


def build_artifact(taxonomy: Taxonomy) -> dict[str, Any]:
    return {
        "model": train_pipeline(taxonomy),
        "metadata": {
            "taxonomy_hash": taxonomy.fingerprint,
            "training_config_hash": training_config_hash(taxonomy),
            "sklearn_version": sklearn.__version__,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def artifact_is_current(artifact: dict[str, Any], taxonomy: Taxonomy) -> bool:
    metadata = artifact.get("metadata", {})
    return (
        metadata.get("taxonomy_hash") == taxonomy.fingerprint
        and metadata.get("training_config_hash") == training_config_hash(taxonomy)
        and metadata.get("sklearn_version") == sklearn.__version__
        and "model" in artifact
    )


def load_or_train_artifact(
    taxonomy: Taxonomy,
    model_path: Path | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    if model_path is not None and model_path.exists():
        artifact = joblib.load(model_path)
        if isinstance(artifact, dict) and artifact_is_current(artifact, taxonomy):
            return artifact
    artifact = build_artifact(taxonomy)
    if persist and model_path is not None:
        model_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = model_path.with_suffix(f"{model_path.suffix}.tmp")
        joblib.dump(artifact, temporary_path)
        temporary_path.replace(model_path)
    return artifact


class SklearnRouter:
    provider = "TF-IDF + Logistic Regression"

    def __init__(self, artifact: dict[str, Any]):
        self.model: Pipeline = artifact["model"]
        self.artifact_metadata = artifact["metadata"]
        self.taxonomy: Taxonomy | None = None

    def route(self, request: RouteRequest, threshold: float = 0.20) -> RouteResult:
        started = time.perf_counter()
        probabilities = self.model.predict_proba([request.classification_text()])[0]
        labels = self.model.classes_
        best_index = int(probabilities.argmax())
        confidence = float(probabilities[best_index])
        predicted_intent = str(labels[best_index])
        accepted = confidence >= threshold
        scores = {
            str(label): float(score) for label, score in zip(labels, probabilities)
        }
        return RouteResult(
            provider=self.provider,
            status=RouterStatus.OK if accepted else RouterStatus.UNKNOWN,
            intent=predicted_intent if accepted else "unknown",
            confidence=confidence,
            latency_ms=(time.perf_counter() - started) * 1_000,
            reason=(
                f"Highest class probability passed the {threshold:.2f} threshold."
                if accepted
                else f"Highest class probability was below the {threshold:.2f} threshold."
            ),
            raw_output=sanitize_raw_output(
                {"predicted_intent": predicted_intent, "scores": scores}
            ),
            metadata={
                "score_type": "predict_proba",
                "threshold": threshold,
                "artifact": self.artifact_metadata,
                **(
                    request_metadata(self.taxonomy, predicted_intent if accepted else "unknown", request)
                    if self.taxonomy is not None
                    else {}
                ),
            },
        )

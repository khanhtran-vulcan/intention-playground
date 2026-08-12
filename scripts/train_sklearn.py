import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.taxonomy import load_taxonomy
from routers.sklearn_router import load_or_train_artifact


DATA_PATH = ROOT / "data" / "intents.json"
MODEL_PATH = ROOT / "models" / "sklearn_intent.joblib"


def train() -> None:
    taxonomy = load_taxonomy(DATA_PATH)
    artifact = load_or_train_artifact(taxonomy, MODEL_PATH, persist=True)
    print(
        f"Saved model to {MODEL_PATH} "
        f"(taxonomy {artifact['metadata']['taxonomy_hash'][:12]})"
    )


if __name__ == "__main__":
    train()

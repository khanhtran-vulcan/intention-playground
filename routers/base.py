from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


MAX_RAW_OUTPUT_CHARS = 4_000


class RouterStatus(str, Enum):
    OK = "ok"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"
    DEGRADED = "degraded"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


class RouterError(BaseModel):
    code: str
    message: str
    retryable: bool = False


class RouteResult(BaseModel):
    provider: str
    status: RouterStatus
    intent: str | None = None
    confidence: float | None = Field(default=None, ge=-1.0, le=1.0)
    latency_ms: float = Field(ge=0)
    reason: str
    properties: dict[str, Any] | None = None
    raw_output: dict[str, Any] | list[Any] | str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: RouterError | None = None


def request_metadata(
    taxonomy: Any, intent: str | None, request: Any
) -> dict[str, Any]:
    metadata = {
        "has_images": request.has_images,
        "image_count": request.image_count,
        "missing_required_context": False,
    }
    if intent not in (None, "unknown"):
        definition = taxonomy.get(intent)
        metadata["parent"] = definition.parent
        metadata["missing_required_context"] = (
            definition.required_context == "image" and not request.has_images
        )
    return metadata


def sanitize_raw_output(value: Any) -> dict[str, Any] | list[Any] | str | None:
    if value is None:
        return None
    try:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        serialized = repr(value)
    if len(serialized) <= MAX_RAW_OUTPUT_CHARS:
        return json.loads(serialized) if serialized[:1] in "[{\"" else serialized
    return {
        "truncated": True,
        "original_chars": len(serialized),
        "preview": serialized[:MAX_RAW_OUTPUT_CHARS],
    }

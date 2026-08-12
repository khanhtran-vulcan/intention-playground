"""Format routing requests as router user text (text-only; no image bytes)."""

from __future__ import annotations

from reference_runtime.contracts import RoutingRequest


def _attachment_summary(files: list) -> str | None:
    if not files:
        return None
    counts: dict[str, int] = {}
    for item in files:
        mime = getattr(item, "mime_type", None) or getattr(item, "type", None) or "file"
        counts[str(mime)] = counts.get(str(mime), 0) + 1
    parts = [f"{mime} x{count}" for mime, count in sorted(counts.items())]
    return ", ".join(parts)


def format_conversation_for_router(request: RoutingRequest) -> str:
    """Render recent turns for the structured router prompt.

  When a message has file attachments but no text, emit an explicit attachment
  line so models can distinguish image-only turns from empty input (fairer than
  a bare ``(attachment only)`` placeholder).
    """
    lines: list[str] = []
    for message in request.messages[-6:]:
        tag = (
            f"{message.role}:{message.capability_name}"
            if message.capability_name
            else message.role
        )
        content = (message.content or "").strip()
        attachment_line = _attachment_summary(message.files or [])
        if content and attachment_line:
            lines.append(f"[{tag}] {content}")
            lines.append(f"[{tag} attachments] {attachment_line}")
        elif content:
            lines.append(f"[{tag}] {content}")
        elif attachment_line:
            lines.append(f"[{tag}] (no text)")
            lines.append(f"[{tag} attachments] {attachment_line}")
        else:
            lines.append(f"[{tag}] (empty)")
    return "\n".join(lines)

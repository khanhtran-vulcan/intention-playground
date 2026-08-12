from __future__ import annotations

from reference_runtime.contracts import Message, RoutingRequest
from reference_runtime.router.conversation import format_conversation_for_router
from reference_runtime.scenarios import FAKE_IMAGE


def test_format_conversation_attachment_hint_when_no_text():
    request = RoutingRequest(
        messages=[Message(role="user", content="", files=[FAKE_IMAGE])],
        tools=[],
    )
    text = format_conversation_for_router(request)
    assert "[user] (no text)" in text
    assert "[user attachments]" in text
    assert "image/png" in text


def test_format_conversation_text_and_attachment():
    request = RoutingRequest(
        messages=[Message(role="user", content="What is this?", files=[FAKE_IMAGE])],
        tools=[],
    )
    text = format_conversation_for_router(request)
    assert "[user] What is this?" in text
    assert "[user attachments] image/png x1" in text

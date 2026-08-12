"""Mock Capability Executor -- Client-side simulator, outside the Router.

This module is never imported by `reference_runtime/runtime.py`. It exists to
demonstrate the capability-owned post-execution response contract (capability
generates `response_text` and `suggested_actions`; the Router never does) for the
V1.0 demo, since real capability execution is out of scope until V1.1.

Every result and every piece of UI text built from this module must make clear
this is a *mock* -- see docs/reference-runtime.md.
"""

from __future__ import annotations

from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field


class SuggestedAction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    label: str = Field(min_length=1, max_length=100)
    user_message: str = Field(min_length=1, max_length=500)


class CapabilityArtifact(BaseModel):
    type: str
    content: str


class CapabilityExecutionRequest(BaseModel):
    selected_route: str
    validated_arguments: dict[str, str] = Field(default_factory=dict)
    original_user_request: str = ""
    conversation_context: list[str] = Field(default_factory=list)


class CapabilityResult(BaseModel):
    capability_name: str
    status: Literal["completed", "failed"]
    response_text: str
    artifacts: list[CapabilityArtifact] = Field(default_factory=list)
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)
    error_message: str | None = None


def run_mock_deep_research(request: CapabilityExecutionRequest) -> CapabilityResult:
    topic = request.validated_arguments.get("final_prompt", "").strip()
    if not topic:
        return CapabilityResult(
            capability_name="deep_research",
            status="failed",
            response_text="Không thể thực hiện nghiên cứu vì thiếu chủ đề. [Mock capability execution]",
            error_message="missing required argument: final_prompt",
        )
    return CapabilityResult(
        capability_name="deep_research",
        status="completed",
        response_text=f"[Mock capability execution] Tôi đã tổng hợp các xu hướng nổi bật về {topic}.",
        artifacts=[
            CapabilityArtifact(
                type="research_summary",
                content=(
                    f"Specialty {topic}, sustainable packaging, traceable sourcing, and "
                    "premiumization are the leading mock signals this quarter."
                ),
            )
        ],
        suggested_actions=[
            SuggestedAction(
                label="Tạo poster",
                user_message=f"Tạo poster từ kết quả research về {topic} vừa rồi",
            ),
            SuggestedAction(
                label="Tạo hình minh họa",
                user_message=f"Tạo hình minh họa từ kết quả research về {topic} vừa rồi",
            ),
        ],
    )


def run_mock_generic_capability(request: CapabilityExecutionRequest) -> CapabilityResult:
    return CapabilityResult(
        capability_name=request.selected_route,
        status="completed",
        response_text=f"[Mock capability execution] Đã mô phỏng {request.selected_route} thành công.",
    )


_MOCK_HANDLERS: dict[str, Callable[[CapabilityExecutionRequest], CapabilityResult]] = {
    "deep_research": run_mock_deep_research,
}


def run_mock_capability(request: CapabilityExecutionRequest) -> CapabilityResult:
    handler = _MOCK_HANDLERS.get(request.selected_route, run_mock_generic_capability)
    return handler(request)

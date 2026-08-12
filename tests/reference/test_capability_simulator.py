from __future__ import annotations

from reference_runtime.capability_simulator import (
    CapabilityExecutionRequest,
    run_mock_capability,
    run_mock_deep_research,
)


def test_mock_deep_research_success_includes_suggested_poster_action():
    request = CapabilityExecutionRequest(
        selected_route="deep_research",
        validated_arguments={"final_prompt": "xu hướng cà phê"},
        original_user_request="Nghiên cứu xu hướng cà phê rồi tạo poster",
    )
    result = run_mock_deep_research(request)
    assert result.status == "completed"
    assert result.artifacts
    assert result.artifacts[0].type == "research_summary"
    assert result.suggested_actions
    assert any("poster" in a.user_message.lower() for a in result.suggested_actions)
    assert any("minh họa" in a.user_message.lower() for a in result.suggested_actions)
    assert "[Mock capability execution]" in result.response_text


def test_mock_deep_research_failure_has_no_suggested_actions():
    request = CapabilityExecutionRequest(selected_route="deep_research", validated_arguments={})
    result = run_mock_deep_research(request)
    assert result.status == "failed"
    assert result.suggested_actions == []
    assert result.artifacts == []
    assert result.error_message


def test_run_mock_capability_dispatches_by_route():
    result = run_mock_capability(
        CapabilityExecutionRequest(selected_route="deep_research", validated_arguments={"final_prompt": "x"})
    )
    assert result.capability_name == "deep_research"

    generic = run_mock_capability(
        CapabilityExecutionRequest(selected_route="generate_logo", validated_arguments={})
    )
    assert generic.capability_name == "generate_logo"
    assert generic.status == "completed"
    assert generic.suggested_actions == []

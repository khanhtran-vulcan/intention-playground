from __future__ import annotations

import reference_ui
from reference_runtime.contracts import Media, Message, RequestContext, RoutingRequest


class AttrState(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


def _state(**overrides) -> AttrState:
    state = AttrState(
        ref_messages=[],
        ref_turn_log=[],
        ref_turn_count=0,
        ref_last_request=None,
        ref_last_result=None,
        ref_last_capability_request=None,
        ref_last_capability_result=None,
        ref_provider_name="Deterministic Fake",
        ref_tools=list(reference_ui._ALL_EXECUTABLE_INTENTS),
        ref_pending_image_bytes=None,
        ref_pending_image_mime=None,
        ref_pending_image_name=None,
        ref_pending_tools=None,
        ref_uploader_revision=0,
        ref_scenario_query="",
        ref_scenario_category="all",
        ref_active_scenario_id=None,
        ref_selected_scenario_id=None,
        ref_scenario_confirm_run=False,
        ref_compose_mode="message",
        ref_selected_turn_index=None,
        ref_acceptance=None,
        ref_routing=False,
        ref_setup_confirm_reset=False,
        ref_inspect_force_open=False,
        _ref_keep_acceptance=False,
    )
    state.update(overrides)
    return state


def test_live_provider_never_blocked():
    assert reference_ui._live_provider_blocked() is False


def test_consumed_upload_rotates_uploader_and_is_not_reused(monkeypatch):
    state = _state(
        ref_pending_image_bytes=b"image",
        ref_pending_image_mime="image/png",
        ref_pending_image_name="one.png",
    )
    monkeypatch.setattr(reference_ui.st, "session_state", state)

    reference_ui._append_user_message("first")
    reference_ui._append_user_message("second")

    assert state.ref_uploader_revision == 1
    assert len(state.ref_messages[0].files) == 1
    assert state.ref_messages[1].files == []


def test_classifier_system_prompt_lists_registry_intents(monkeypatch):
    state = _state()
    monkeypatch.setattr(reference_ui.st, "session_state", state)
    prompt = reference_ui.build_classifier_system_prompt()
    assert "Available intents:" in prompt
    assert "deep_research" in prompt
    assert "create_ai_art" in prompt
    assert "real_time_search" in prompt
    assert "unknown" in prompt
    assert "generate_poster" not in prompt


def test_classifier_user_payload_includes_conversation_turns():
    request = RoutingRequest(
        messages=[Message(role="user", content="xin chào")],
        context=RequestContext(clarification_turn_count=2),
    )
    payload = reference_ui._format_classifier_user_payload(request)
    assert "[user] xin chào" in payload


def test_exact_request_is_preserved_before_clarification_counter_changes(monkeypatch):
    state = _state(
        ref_turn_count=2,
        ref_messages=[
            Message(
                role="user",
                content="Chuyển ảnh này sang phong cách khác",
                files=[Media(mime_type="image/png", data="ZmFrZQ==")],
            )
        ],
    )
    monkeypatch.setattr(reference_ui.st, "session_state", state)

    result = reference_ui._route_current_conversation()

    assert result.response.outcome.value == "CLARIFY"
    assert state.ref_last_request.context.clarification_turn_count == 2
    assert state.ref_turn_count == 3
    assert result.trace.final_reason_code


def test_pending_tools_applied_in_init_before_widget(monkeypatch):
    state = _state(
        ref_tools=["create_ai_art"],
        ref_pending_tools=["create_ai_art", "real_time_search"],
    )
    monkeypatch.setattr(reference_ui.st, "session_state", state)
    reference_ui._init_state()
    assert state.ref_tools == ["create_ai_art", "real_time_search"]
    assert state.ref_pending_tools is None


def test_effective_tools_prefers_pending(monkeypatch):
    state = _state(
        ref_tools=["create_ai_art"],
        ref_pending_tools=[],
    )
    monkeypatch.setattr(reference_ui.st, "session_state", state)
    assert reference_ui._effective_tools() == []


def test_current_request_or_none_when_conversation_empty(monkeypatch):
    state = _state()
    monkeypatch.setattr(reference_ui.st, "session_state", state)
    assert reference_ui._current_request_or_none() is None


def test_debug_bundle_includes_transcript_stages_final_and_errors(monkeypatch):
    state = _state(
        ref_messages=[
            Message(role="user", content="Xin chào"),
        ],
        ref_tools=["create_ai_art", "real_time_search"],
        ref_turn_count=0,
    )
    monkeypatch.setattr(reference_ui.st, "session_state", state)
    result = reference_ui._route_current_conversation()
    bundle = reference_ui._build_debug_bundle(result)

    assert "session" in bundle
    assert bundle["session"]["transcript"][0]["content"] == "Xin chào"
    assert bundle["session"]["current_user_message"]["content"] == "Xin chào"
    assert bundle["pipeline_stages"]
    assert {stage["stage"] for stage in bundle["pipeline_stages"]} >= {
        "normalize",
        "policy_gate",
        "pre_router",
    }
    assert bundle["final_public_response"]["outcome"].startswith("INTENTION_DETECT_OUTCOME_")
    assert "errors" in bundle
    assert "has_errors" in bundle
    assert "final_internal" in bundle
    assert "reason_code" in bundle["final_internal"]


def test_debug_bundle_captures_provider_error(monkeypatch):
    from reference_runtime.contracts import (
        Outcome,
        ReferenceRunResult,
        RoutingResponse,
        InternalTrace,
        PolicyTrace,
        RouterDecisionTrace,
    )

    state = _state(ref_messages=[Message(role="user", content="Tạo logo")])
    monkeypatch.setattr(reference_ui.st, "session_state", state)
    result = ReferenceRunResult(
        response=RoutingResponse(outcome=Outcome.FALLBACK),
        trace=InternalTrace(
            request_id="abc",
            stages=[],
            pre_router_hit=False,
            pre_router_rule_version="pre-router-v2",
            policy=PolicyTrace(decision="allow", rule_version="policy-v1"),
            router_decision=RouterDecisionTrace(
                provider="OpenAI",
                model="gpt-4o-mini",
                proposed_outcome=Outcome.FALLBACK,
                reason_code="PROVIDER_MISSING_CREDENTIALS",
                provider_error_code="PROVIDER_MISSING_CREDENTIALS",
            ),
            taxonomy_version="demo",
            final_reason_code="PROVIDER_MISSING_CREDENTIALS",
        ),
    )
    errors = reference_ui._collect_debug_errors(result)
    assert any(err["code"] == "PROVIDER_MISSING_CREDENTIALS" for err in errors)


def test_current_request_or_none_builds_from_messages(monkeypatch):
    state = _state(ref_messages=[Message(role="user", content="hi")])
    monkeypatch.setattr(reference_ui.st, "session_state", state)
    request = reference_ui._current_request_or_none()
    assert request is not None
    assert request.messages[0].content == "hi"


def test_pre_router_greeting_is_response(monkeypatch):
    state = _state(ref_messages=[Message(role="user", content="Xin chào")])
    monkeypatch.setattr(reference_ui.st, "session_state", state)
    result = reference_ui._route_current_conversation()
    assert result.response.outcome.value == "RESPONSE"
    assert result.response.response_text


def test_stage_timeline_rows_stringify_nested_detail(monkeypatch):
    """Nested dict Detail must be JSON text — st.dataframe+pyarrow segfaults on dict cells."""
    state = _state(ref_messages=[Message(role="user", content="Xin chào")])
    monkeypatch.setattr(reference_ui.st, "session_state", state)
    result = reference_ui._route_current_conversation()
    rows = reference_ui._stage_timeline_rows(result)
    assert rows
    for row in rows:
        assert isinstance(row["Detail"], str)
        assert isinstance(row["Stage"], str)
        assert isinstance(row["Status"], str)
        assert isinstance(row["Latency (ms)"], float)


def test_route_appends_turn_log_for_conversation_history(monkeypatch):
    state = _state(ref_messages=[Message(role="user", content="Xin chào")])
    monkeypatch.setattr(reference_ui.st, "session_state", state)
    result = reference_ui._route_current_conversation()
    assert result.response.outcome.value == "RESPONSE"
    assert len(state.ref_turn_log) == 1
    entry = state.ref_turn_log[0]
    assert entry["after_message_index"] == 0
    assert entry["outcome"] == "RESPONSE"
    assert entry["reason_code"]
    assert entry["preview"]


def test_filter_scenarios_by_query_and_category():
    scenarios = reference_ui._ui_scenarios()
    route_only = reference_ui._filter_scenarios(scenarios, "", "route")
    assert route_only
    assert all(s.category == "route" for s in route_only)
    hits = reference_ui._filter_scenarios(scenarios, "xin chào", "all")
    assert any(s.id == "static_greeting" for s in hits)
    empty = reference_ui._filter_scenarios(scenarios, "zzz-no-such-scenario", "all")
    assert empty == []


def test_load_scenario_resets_and_routes(monkeypatch):
    state = _state(
        ref_messages=[Message(role="user", content="old")],
        ref_turn_log=[{"after_message_index": 0, "outcome": "FALLBACK"}],
        ref_provider_name="Deterministic Fake",
    )
    monkeypatch.setattr(reference_ui.st, "session_state", state)
    scenario = next(s for s in reference_ui._ui_scenarios() if s.id == "static_greeting")
    reference_ui._load_scenario(scenario)
    assert state.ref_active_scenario_id == "static_greeting"
    assert any(m.content == "Xin chào" for m in state.ref_messages if m.role == "user")
    assert state.ref_last_result is not None
    assert state.ref_last_result.response.outcome.value == "RESPONSE"
    assert state.ref_turn_log
    assert state.ref_turn_log[-1]["outcome"] == "RESPONSE"
    assert state.ref_acceptance["expected_outcome"] == "RESPONSE"
    assert state.ref_turn_log[-1]["acceptance"]["passed"] is True
    assert state.ref_turn_log[-1]["acceptance"]["label"] == "PASS"


def test_filter_scenarios_more_bucket():
    scenarios = reference_ui._ui_scenarios()
    more = reference_ui._filter_scenarios(scenarios, "", "more")
    assert more
    assert all(s.category in reference_ui._MORE_SCENARIO_CATEGORIES for s in more)
    # Peer filters stay ≤4 (All / Route / Clarify / More filters).
    assert len(reference_ui._PRIMARY_SCENARIO_CATEGORIES) + 1 == 4


def test_config_summary_line(monkeypatch):
    state = _state(ref_provider_name="Deterministic Fake", ref_tools=["create_ai_art"])
    monkeypatch.setattr(reference_ui.st, "session_state", state)
    line = reference_ui._config_summary_line()
    assert "Fake" in line
    assert "1 tools" in line
    assert "No image" not in line
    assert "Default model" not in line


def test_request_scenario_run_confirms_when_thread_exists(monkeypatch):
    state = _state(ref_messages=[Message(role="user", content="keep me")])
    monkeypatch.setattr(reference_ui.st, "session_state", state)
    scenario = next(s for s in reference_ui._ui_scenarios() if s.id == "static_greeting")
    reference_ui._request_scenario_run(scenario)
    assert state.ref_scenario_confirm_run is True
    assert state.ref_selected_scenario_id == "static_greeting"
    assert any(m.content == "keep me" for m in state.ref_messages)


def test_request_scenario_run_loads_when_empty(monkeypatch):
    state = _state()
    monkeypatch.setattr(reference_ui.st, "session_state", state)
    scenario = next(s for s in reference_ui._ui_scenarios() if s.id == "static_greeting")
    reference_ui._request_scenario_run(scenario)
    assert state.ref_scenario_confirm_run is False
    assert state.ref_active_scenario_id == "static_greeting"
    assert state.ref_last_result is not None


def test_is_viewing_historical_turn(monkeypatch):
    state = _state(
        ref_turn_log=[
            {"outcome": "RESPONSE"},
            {"outcome": "ROUTE"},
        ],
        ref_selected_turn_index=0,
    )
    monkeypatch.setattr(reference_ui.st, "session_state", state)
    assert reference_ui._is_viewing_historical_turn() is True
    state.ref_selected_turn_index = 1
    assert reference_ui._is_viewing_historical_turn() is False

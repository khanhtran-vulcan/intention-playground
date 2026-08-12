"""Streamlit UI for the Intention V1 Reference Runtime demo.

Rendered from a dedicated "V1 Reference" tab in `app.py`. Kept in its own module
(mirroring how `core`/`routers` are separate from `app.py`) so the Comparison Lab
tabs in `app.py` stay untouched.

Three things this UI must keep visually distinct at all times (task instructions
section 13): the Public Client Contract, the Internal Reference Trace, and the
Mock Capability Contract. The Mock Capability Simulator is never presented as a
Router stage -- it only appears after an explicit "Run mock capability" click.
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Any

import streamlit as st

from reference_runtime.capability_simulator import (
    CapabilityExecutionRequest,
    CapabilityResult,
    run_mock_capability,
)
from reference_runtime.debug_trace import checkpoint, checkpoint_exception
from reference_runtime.router.fake import FakeRouterProvider
from reference_runtime.router.conversation import format_conversation_for_router
from reference_runtime.router.gemini import GeminiRouterProvider
from reference_runtime.router.openai import OpenAIRouterProvider
from reference_runtime.router.schema import ROUTER_JSON_SCHEMA, build_system_prompt
from reference_runtime.evaluation import evaluate_reference, export_report, run_benchmark
from reference_runtime.scenarios import CLARIFICATION_CHAINS, SCENARIOS as BENCHMARK_SCENARIOS
from reference_runtime.model_catalog import (
    CUSTOM_MODEL_CHOICE,
    GEMINI_MODELS,
    OPENAI_MODELS,
    format_option,
    note_for,
    resolve_default_choice,
    select_options,
)
from reference_runtime.contracts import (
    MAX_CLARIFICATION_TURNS,
    Media,
    Message,
    Outcome,
    ReferenceRunResult,
    RequestContext,
    RoutingRequest,
    Tool,
    ToolFunction,
    to_public_request,
    to_public_response,
)
from reference_runtime.registry import ReferenceIntentRegistry
from reference_runtime.registry_loader import registry_from_yaml
from reference_runtime.runtime import ReferenceRouter
from reference_runtime.scenarios import SCENARIOS
from reference_runtime.selection import load_pricing


PROVIDER_OPTIONS = (
    "Gemini Structured Output",
    "Deterministic Fake",
    "OpenAI Structured Output",
)
_REGISTRY = registry_from_yaml()
_ALL_EXECUTABLE_INTENTS = sorted(_REGISTRY.executable_names)
_DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"

_STATE_DEFAULTS: dict[str, Any] = {
    "ref_messages": [],
    "ref_turn_log": [],  # historical intent outcomes aligned to user message indices
    "ref_turn_count": 0,
    "ref_last_request": None,
    "ref_last_result": None,
    "ref_last_capability_request": None,
    "ref_last_capability_result": None,
    "ref_provider_name": "Gemini Structured Output",
    "ref_gemini_model_choice": None,  # resolved from GEMINI_MODEL / catalog default in _init_state
    "ref_gemini_model_custom": "",
    "ref_openai_model_choice": None,
    "ref_openai_model_custom": "",
    "ref_tools": list(_ALL_EXECUTABLE_INTENTS),
    "ref_pending_image_bytes": None,
    "ref_pending_image_mime": None,
    "ref_pending_image_name": None,
    "ref_pending_tools": None,
    "ref_uploader_revision": 0,
    "ref_scenario_query": "",
    "ref_scenario_category": "all",
    "ref_active_scenario_id": None,
    "ref_selected_scenario_id": None,  # browse selection; does not mutate conversation
    "ref_scenario_confirm_run": False,
    "ref_compose_mode": "message",  # message | scenario
    "ref_selected_turn_index": None,  # index into ref_turn_log; None = latest
    "ref_acceptance": None,  # {scenario_id, expected_outcome, expected_name} after scenario load
    "ref_routing": False,
    "ref_setup_confirm_reset": False,
    "ref_inspect_force_open": False,
}

# ≤4 peer filter choices in the dock (review DoD).
_PRIMARY_SCENARIO_CATEGORIES = ("all", "route", "clarify")
_MORE_SCENARIO_CATEGORIES = (
    "router_response",
    "reject",
    "pre_router_static",
    "fallback",
    "empty_tools",
    "dependency",
    "security",
)

_OUTCOME_COLORS: dict[Outcome, str] = {
    Outcome.RESPONSE: "#0f766e",
    Outcome.ROUTE: "#0ea5e9",
    Outcome.CLARIFY: "#c2410c",
    Outcome.FALLBACK: "#64748b",
    Outcome.REJECT: "#b91c1c",
}

_CATEGORY_LABELS: dict[str, str] = {
    "all": "All",
    "pre_router_static": "Pre-router",
    "router_response": "RESPONSE",
    "route": "ROUTE",
    "clarify": "CLARIFY",
    "fallback": "FALLBACK",
    "reject": "REJECT",
    "empty_tools": "Empty tools",
    "dependency": "Dependency",
    "security": "Security",
}


def _init_state() -> None:
    for key, value in _STATE_DEFAULTS.items():
        if key not in st.session_state:
            # Copy mutable defaults (lists) -- assigning the shared module-level
            # object directly would let st.session_state.ref_messages.append(...)
            # permanently mutate _STATE_DEFAULTS itself across reruns/sessions.
            st.session_state[key] = value.copy() if isinstance(value, list) else value
    if st.session_state.ref_gemini_model_choice is None:
        configured = (os.getenv("GEMINI_MODEL") or "").strip() or _DEFAULT_GEMINI_MODEL
        choice, custom = resolve_default_choice(GEMINI_MODELS, configured)
        st.session_state.ref_gemini_model_choice = choice
        st.session_state.ref_gemini_model_custom = custom
    if st.session_state.ref_openai_model_choice is None:
        choice, custom = resolve_default_choice(OPENAI_MODELS, os.getenv("OPENAI_MODEL"))
        st.session_state.ref_openai_model_choice = choice
        st.session_state.ref_openai_model_custom = custom
    # Apply deferred tools before the `ref_tools` multiselect widget is created.
    pending_tools = st.session_state.get("ref_pending_tools")
    if pending_tools is not None:
        # Drop archived intent names that scenarios may still carry.
        st.session_state.ref_tools = [
            name for name in pending_tools if name in _ALL_EXECUTABLE_INTENTS
        ] or list(_ALL_EXECUTABLE_INTENTS)
        st.session_state.ref_pending_tools = None


def _reset_state() -> None:
    for key, value in _STATE_DEFAULTS.items():
        if key == "ref_uploader_revision":
            st.session_state[key] = st.session_state.get(key, 0) + 1
            continue
        if key in (
            "ref_provider_name",
            "ref_gemini_model_choice",
            "ref_gemini_model_custom",
            "ref_openai_model_choice",
            "ref_openai_model_custom",
            "ref_tools",
            "ref_scenario_query",
            "ref_scenario_category",
            "ref_compose_mode",
            "ref_selected_scenario_id",
        ):
            continue  # keep runtime settings across a reset, only clear the conversation
        st.session_state[key] = value.copy() if isinstance(value, list) else value


def _effective_model(choice_key: str, custom_key: str) -> str | None:
    choice = st.session_state[choice_key]
    if choice == CUSTOM_MODEL_CHOICE:
        return (st.session_state[custom_key] or "").strip() or None
    return choice


def _build_router_provider():
    provider_name = st.session_state.ref_provider_name
    if provider_name == "Gemini Structured Output":
        model = _effective_model("ref_gemini_model_choice", "ref_gemini_model_custom")
        return GeminiRouterProvider(_REGISTRY, model_name=model)
    if provider_name == "OpenAI Structured Output":
        model = _effective_model("ref_openai_model_choice", "ref_openai_model_custom")
        return OpenAIRouterProvider(_REGISTRY, model_name=model)
    return FakeRouterProvider()


# Backward-compatible alias for tests.
_build_classifier = _build_router_provider


def _active_model_label() -> str:
    provider_name = st.session_state.ref_provider_name
    if provider_name == "Gemini Structured Output":
        return _effective_model("ref_gemini_model_choice", "ref_gemini_model_custom") or "n/a"
    if provider_name == "OpenAI Structured Output":
        return _effective_model("ref_openai_model_choice", "ref_openai_model_custom") or "n/a"
    return "n/a"


def _live_provider_blocked() -> bool:
    """Live providers are always allowed; keys come from `.env`."""
    return False


def build_classifier_system_prompt(registry: ReferenceIntentRegistry | None = None) -> str:
    tools = _effective_tools()
    return build_system_prompt(tools)


def _effective_tools() -> list[str]:
    """Tools for the next request. Prefer deferred scenario tools over widget state."""
    pending = st.session_state.get("ref_pending_tools")
    if pending is not None:
        return list(pending)
    return list(st.session_state.get("ref_tools") or _ALL_EXECUTABLE_INTENTS)


def _format_classifier_user_payload(request: RoutingRequest) -> str:
    return format_conversation_for_router(request)


def _current_request_or_none() -> RoutingRequest | None:
    """Return the last routed request, or build one if conversation is non-empty."""
    last = st.session_state.get("ref_last_request")
    if last is not None:
        return last
    if not st.session_state.get("ref_messages"):
        return None
    return _build_request()


def _render_classifier_prompt_panel() -> None:
    provider_name = st.session_state.ref_provider_name
    has_result = st.session_state.get("ref_last_result") is not None
    with st.expander(
        "Router prompt & schema",
        icon=":material/description:",
        expanded=not has_result,
    ):
        if provider_name == "Deterministic Fake":
            st.info(
                "Deterministic Fake does not call an LLM — no system prompt. "
                "Fixtures live in `reference_runtime/router/fake.py`."
            )
        else:
            st.caption("System prompt for Gemini/OpenAI Structured LLM Router (filtered by tools[]).")
            st.code(build_classifier_system_prompt(), language="text")
            with st.expander("Structured-output JSON schema", expanded=False):
                st.json(ROUTER_JSON_SCHEMA)

        request = _current_request_or_none()
        st.caption("User payload (conversation text) sent with the system prompt:")
        if request is None:
            st.code("(no conversation yet — send a message or load a scenario)", language="text")
        else:
            st.code(_format_classifier_user_payload(request), language="text")


def _build_request() -> RoutingRequest:
    return RoutingRequest(
        messages=list(st.session_state.ref_messages),
        tools=[Tool(function=ToolFunction(name=name)) for name in _effective_tools()],
        context=RequestContext(clarification_turn_count=st.session_state.ref_turn_count),
    )


def _route_current_conversation() -> ReferenceRunResult:
    provider_name = st.session_state.ref_provider_name
    checkpoint(
        "ui.route.enter",
        provider=provider_name,
        model=_active_model_label(),
        n_messages=len(st.session_state.ref_messages),
        turn_count=st.session_state.ref_turn_count,
    )
    router = ReferenceRouter(router=_build_router_provider(), registry=_REGISTRY)
    request = _build_request()
    try:
        result = router.route(request)
    except Exception as exc:
        checkpoint_exception("ui.route.exception", exc)
        raise
    checkpoint(
        "ui.route.done",
        outcome=result.response.outcome.value,
        reason=result.trace.final_reason_code,
        latency_ms=result.trace.total_latency_ms,
    )
    st.session_state.ref_last_request = request
    st.session_state.ref_last_result = result
    st.session_state.ref_last_capability_request = None
    st.session_state.ref_last_capability_result = None
    _append_turn_log(result)
    if result.response.outcome == Outcome.CLARIFY:
        st.session_state.ref_turn_count += 1
    else:
        st.session_state.ref_turn_count = 0
    checkpoint("ui.route.session_state_updated")
    return result


def _turn_preview(result: ReferenceRunResult) -> str:
    response = result.response
    if response.outcome == Outcome.ROUTE:
        args = response.arguments_dict()
        return json.dumps(args, ensure_ascii=False) if args else "{}"
    if response.outcome == Outcome.CLARIFY and response.clarification is not None:
        return response.clarification.question
    if response.outcome in (Outcome.RESPONSE, Outcome.REJECT):
        return response.response_text or "(empty response)"
    if response.outcome == Outcome.FALLBACK:
        provider_error = None
        if result.trace.router_decision is not None:
            provider_error = result.trace.router_decision.provider_error_code
        if provider_error:
            return f"FALLBACK — provider error `{provider_error}`"
        if result.trace.final_reason_code == "CLARIFICATION_LIMIT_REACHED":
            return "FALLBACK — clarification limit reached (3/3). Try a clearer request or reset."
        return "FALLBACK — no safe executable route."
    return response.outcome.value


def _acceptance_for_result(result: ReferenceRunResult) -> dict[str, Any] | None:
    acceptance = st.session_state.get("ref_acceptance")
    if not acceptance:
        return None
    expected_outcome = acceptance.get("expected_outcome")
    expected_name = acceptance.get("expected_name")
    actual_outcome = result.response.outcome.value
    actual_name = result.response.name
    outcome_ok = expected_outcome == actual_outcome
    name_ok = True
    if expected_name:
        name_ok = expected_name == actual_name
    passed = outcome_ok and name_ok
    return {
        "scenario_id": acceptance.get("scenario_id"),
        "expected_outcome": expected_outcome,
        "expected_name": expected_name,
        "actual_outcome": actual_outcome,
        "actual_name": actual_name,
        "passed": passed,
        "label": "PASS" if passed else "MISMATCH",
    }


def _append_turn_log(result: ReferenceRunResult) -> None:
    """Record intent outcome against the latest user message so the transcript keeps history."""
    user_index = next(
        (
            index
            for index in range(len(st.session_state.ref_messages) - 1, -1, -1)
            if st.session_state.ref_messages[index].role == "user"
        ),
        None,
    )
    if user_index is None:
        return
    cost = _estimate_run_cost_usd(result)
    usage = result.response.usage
    entry = {
        "after_message_index": user_index,
        "outcome": result.response.outcome.value,
        "name": result.response.name,
        "reason_code": result.trace.final_reason_code,
        "preview": _turn_preview(result),
        "latency_ms": round(result.trace.total_latency_ms, 1),
        "tokens": usage.total_tokens if usage else None,
        "cost_usd": cost,
        "acceptance": _acceptance_for_result(result),
    }
    log = list(st.session_state.get("ref_turn_log") or [])
    log.append(entry)
    st.session_state.ref_turn_log = log
    st.session_state.ref_selected_turn_index = len(log) - 1


def _append_user_message(text: str) -> None:
    files = []
    if st.session_state.ref_pending_image_bytes is not None:
        import base64

        files.append(
            Media(
                mime_type=st.session_state.ref_pending_image_mime or "image/png",
                data=base64.b64encode(st.session_state.ref_pending_image_bytes).decode("ascii"),
                filename=st.session_state.ref_pending_image_name,
            )
        )
        st.session_state.ref_pending_image_bytes = None
        st.session_state.ref_pending_image_mime = None
        st.session_state.ref_pending_image_name = None
        st.session_state.ref_uploader_revision += 1
    st.session_state.ref_messages.append(Message(role="user", content=text, files=files))
    checkpoint("ui.append_user_message", text_len=len(text), n_files=len(files))


def _submit_user_text(text: str) -> None:
    text = text.strip()
    if not text:
        return
    checkpoint("ui.submit_user_text", text_len=len(text))
    # Free chat clears acceptance expectation unless set by scenario load in same turn.
    if not st.session_state.get("_ref_keep_acceptance"):
        st.session_state.ref_acceptance = None
        st.session_state.ref_active_scenario_id = None
    st.session_state._ref_keep_acceptance = False
    _append_user_message(text)
    _route_current_conversation()
    checkpoint("ui.submit_user_text.done")


def _run_mock_capability() -> None:
    result = st.session_state.ref_last_result
    if result is None or result.response.outcome != Outcome.ROUTE:
        return
    latest_user = next(
        (m for m in reversed(st.session_state.ref_messages) if m.role == "user"), None
    )
    request = CapabilityExecutionRequest(
        selected_route=result.response.name or "",
        validated_arguments=result.response.arguments_dict(),
        original_user_request=(latest_user.content if latest_user else "") or "",
        conversation_context=[m.content or "" for m in st.session_state.ref_messages],
    )
    capability_result = run_mock_capability(request)
    st.session_state.ref_last_capability_request = request
    st.session_state.ref_last_capability_result = capability_result
    if capability_result.status == "completed":
        artifact_type = capability_result.artifacts[0].type if capability_result.artifacts else None
        st.session_state.ref_messages.append(
            Message(
                role="capability",
                content=capability_result.response_text,
                capability_name=capability_result.capability_name,
                artifact_type=artifact_type,
            )
        )


_AVATARS = {
    "user": ":material/person:",
    "assistant": ":material/smart_toy:",
    "capability": ":material/handyman:",
    "intent": ":material/alt_route:",
}


def _turns_for_message(message_index: int) -> list[tuple[int, dict[str, Any]]]:
    return [
        (i, entry)
        for i, entry in enumerate(st.session_state.get("ref_turn_log") or [])
        if entry.get("after_message_index") == message_index
    ]


def _latest_user_message_index() -> int | None:
    return next(
        (
            i
            for i in range(len(st.session_state.ref_messages) - 1, -1, -1)
            if st.session_state.ref_messages[i].role == "user"
        ),
        None,
    )


def _is_latest_turn_entry(entry: dict[str, Any]) -> bool:
    log = st.session_state.get("ref_turn_log") or []
    return bool(log) and entry is log[-1]


def _provider_short() -> str:
    name = st.session_state.ref_provider_name
    if "Fake" in name:
        return "Fake"
    if "Gemini" in name:
        return "Gemini"
    if "OpenAI" in name:
        return "OpenAI"
    return name


def _config_summary_line() -> str:
    tools_n = len(st.session_state.get("ref_tools") or [])
    parts = [f"{_provider_short()} · {tools_n} tools"]
    if "Fake" not in st.session_state.ref_provider_name:
        model = _active_model_label()
        if model and model != "n/a":
            parts.append(model)
    image = st.session_state.get("ref_pending_image_name")
    if image:
        parts.append(f"pending `{image}`")
    return " · ".join(parts)


def _scenario_by_id(scenario_id: str | None):
    if not scenario_id:
        return None
    return next((s for s in _ui_scenarios() if s.id == scenario_id), None)


def _is_viewing_historical_turn() -> bool:
    log = st.session_state.get("ref_turn_log") or []
    selected = st.session_state.get("ref_selected_turn_index")
    return bool(log) and selected is not None and selected != len(log) - 1


def _request_scenario_run(scenario) -> None:
    """Browse stays inert; execution always opens a new conversation (with confirm)."""
    has_thread = bool(st.session_state.get("ref_messages"))
    if has_thread and not st.session_state.get("ref_scenario_confirm_run"):
        st.session_state.ref_selected_scenario_id = scenario.id
        st.session_state.ref_scenario_confirm_run = True
        return
    st.session_state.ref_scenario_confirm_run = False
    _load_scenario(scenario)


def _render_intent_chip(
    entry: dict[str, Any],
    *,
    turn_index: int,
    key_suffix: str,
) -> None:
    """Conversation surface: compact chronology + contextual actions only."""
    try:
        outcome = Outcome(entry["outcome"])
    except ValueError:
        outcome = Outcome.FALLBACK
    color = _OUTCOME_COLORS.get(outcome, "#64748b")
    intent = entry.get("name")
    latency = entry.get("latency_ms")
    latency_txt = f"{latency:.0f} ms" if latency is not None else ""
    title = outcome.value if not intent else f"{outcome.value} · {intent}"
    selected = st.session_state.get("ref_selected_turn_index") == turn_index
    selected_cls = " intent-chip--selected" if selected else ""

    st.markdown(
        f"""
<div class="intent-chip{selected_cls}" style="--outcome:{color}">
  <div class="intent-chip__row">
    <span class="intent-chip__badge">{title}</span>
    <span class="intent-chip__meta">{latency_txt}</span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # Short hint only — full body/JSON lives in Current result.
    preview = (entry.get("preview") or "").strip()
    if preview and outcome != Outcome.ROUTE:
        one_line = " ".join(preview.split())
        if len(one_line) > 100:
            one_line = one_line[:97] + "…"
        st.caption(one_line)
    elif outcome == Outcome.ROUTE:
        st.caption("Arguments in Current result →")

    result: ReferenceRunResult | None = st.session_state.get("ref_last_result")
    is_latest = _is_latest_turn_entry(entry)
    show_mock = is_latest and outcome == Outcome.ROUTE and result is not None

    if show_mock:
        action_cols = st.columns(2)
        if action_cols[0].button(
            "Inspect this turn",
            key=f"inspect_turn_{key_suffix}",
            use_container_width=True,
        ):
            st.session_state.ref_selected_turn_index = turn_index
            st.session_state.ref_compose_mode = "message"
            st.rerun()
        route_name = result.response.name or intent or "capability"
        if action_cols[1].button(
            "Run demo mock",
            type="primary",
            icon=":material/play_arrow:",
            key=f"inline_mock_{key_suffix}",
            use_container_width=True,
            help=f"Demo mock · {route_name}",
        ):
            _run_mock_capability()
            st.rerun()
    else:
        if st.button(
            "Inspect this turn",
            key=f"inspect_turn_{key_suffix}",
            use_container_width=True,
        ):
            st.session_state.ref_selected_turn_index = turn_index
            st.session_state.ref_compose_mode = "message"
            st.rerun()

    if (
        is_latest
        and outcome == Outcome.CLARIFY
        and result is not None
        and result.response.clarification is not None
    ):
        turn_n = st.session_state.ref_turn_count
        remaining = MAX_CLARIFICATION_TURNS - turn_n
        if remaining == 1:
            st.caption(f"Clarification {turn_n}/{MAX_CLARIFICATION_TURNS} · one attempt remaining")
        else:
            st.caption(f"Clarification {turn_n}/{MAX_CLARIFICATION_TURNS}")
        options = result.response.clarification.options
        if options:
            columns = st.columns(len(options))
            for column, option in zip(columns, options):
                if column.button(
                    option.label,
                    key=f"clarify_option_{option.id}_{key_suffix}_{st.session_state.ref_turn_count}",
                    use_container_width=True,
                ):
                    _submit_user_text(option.value)
                    st.rerun()
        st.caption("Or type a free-text answer in the dock below.")

    if is_latest and outcome == Outcome.REJECT:
        st.warning("Stopped by policy. A new message will be evaluated independently.")


def _render_transcript() -> None:
    messages = st.session_state.ref_messages
    if not messages:
        st.markdown(
            '<div class="empty-thread">'
            "<strong>Start with a message or run a known scenario.</strong>"
            "<p>Use the interaction dock below — Write message or Pick scenario. "
            "Each turn keeps a compact outcome in this thread.</p>"
            "</div>",
            unsafe_allow_html=True,
        )
        cols = st.columns(2)
        if cols[0].button("Write a message", use_container_width=True, key="empty_write"):
            st.session_state.ref_compose_mode = "message"
            st.rerun()
        if cols[1].button("Pick a scenario", use_container_width=True, key="empty_pick"):
            st.session_state.ref_compose_mode = "scenario"
            st.rerun()
        return

    for index, message in enumerate(messages):
        avatar = _AVATARS[message.role]
        with st.chat_message("user" if message.role == "user" else "assistant", avatar=avatar):
            if message.role == "capability":
                st.caption(f"DEMO MOCK · `{message.capability_name}`")
            st.write(message.content or "(attachment)")
            for file in message.files:
                st.caption(f":material/attachment: {file.filename or file.mime_type}")

        for turn_index, entry in _turns_for_message(index):
            with st.chat_message("assistant", avatar=_AVATARS["intent"]):
                _render_intent_chip(
                    entry, turn_index=turn_index, key_suffix=f"{index}_{turn_index}"
                )

    capability_result: CapabilityResult | None = st.session_state.get(
        "ref_last_capability_result"
    )
    if (
        capability_result is not None
        and capability_result.status == "completed"
        and capability_result.suggested_actions
    ):
        st.caption("Suggested next turns (demo mock)")
        action_cols = st.columns(min(3, len(capability_result.suggested_actions)))
        for column, action in zip(action_cols, capability_result.suggested_actions):
            if column.button(
                action.label,
                key=f"suggested_action_{action.label}",
                use_container_width=True,
            ):
                _submit_user_text(action.user_message)
                st.rerun()


def _estimate_run_cost_usd(result: ReferenceRunResult) -> float | None:
    usage = result.response.usage
    model = (result.response.usage_model.model if result.response.usage_model else None) or ""
    if usage is None or not model:
        return None
    price = load_pricing().get(model)
    if price is None:
        return None
    return (usage.prompt_tokens / 1_000_000.0) * price.input_usd_per_1m + (
        usage.completion_tokens / 1_000_000.0
    ) * price.output_usd_per_1m


def _render_result_hero(result: ReferenceRunResult) -> None:
    """Authoritative diagnostic for the latest turn — no competing primary CTAs."""
    response = result.response
    color = _OUTCOME_COLORS[response.outcome]
    latency_ms = result.trace.total_latency_ms
    usage = response.usage
    cost_usd = _estimate_run_cost_usd(result)
    reason = result.trace.final_reason_code
    intent = response.name

    st.markdown(
        f"""
<div class="result-hero" style="--outcome:{color}">
  <div class="result-hero__badge">{response.outcome.value}</div>
  <div class="result-hero__intent">{intent or "—"}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    acceptance = _acceptance_for_result(result)
    if acceptance:
        badge = "pass" if acceptance["passed"] else "mismatch"
        expected_name = acceptance.get("expected_name")
        expected_bit = acceptance["expected_outcome"]
        if expected_name:
            expected_bit += f" / {expected_name}"
        actual_bit = acceptance["actual_outcome"]
        if acceptance.get("actual_name"):
            actual_bit += f" / {acceptance['actual_name']}"
        st.markdown(
            f'<div class="acceptance acceptance--{badge}">'
            f"Expected {expected_bit} → Actual {actual_bit} · "
            f"<strong>{acceptance['label']}</strong></div>",
            unsafe_allow_html=True,
        )
        if not acceptance["passed"]:
            rec1, rec2 = st.columns(2)
            if rec1.button(
                "Inspect difference",
                key="mismatch_inspect",
                use_container_width=True,
            ):
                st.session_state.ref_inspect_force_open = True
                st.rerun()
            if rec2.button(
                "Run again",
                key="mismatch_rerun",
                use_container_width=True,
                type="primary",
            ):
                scenario = _scenario_by_id(st.session_state.get("ref_active_scenario_id"))
                if scenario is not None:
                    st.session_state.ref_scenario_confirm_run = False
                    _load_scenario(scenario)
                    st.rerun()

    if response.outcome == Outcome.CLARIFY:
        turn_n = st.session_state.ref_turn_count
        remaining = MAX_CLARIFICATION_TURNS - turn_n
        suffix = " · one attempt remaining" if remaining == 1 else ""
        st.info(
            f"Awaiting clarification · {turn_n}/{MAX_CLARIFICATION_TURNS}{suffix} "
            "— answer options on the conversation turn."
        )
    elif response.outcome == Outcome.REJECT:
        st.error("Stopped by policy. Do not treat this as a soft chat fallback.")
    elif response.outcome == Outcome.FALLBACK:
        provider_error = None
        if result.trace.router_decision is not None:
            provider_error = result.trace.router_decision.provider_error_code
        if provider_error == "PROVIDER_MISSING_CREDENTIALS":
            st.error(
                f"API key missing for {_provider_short()}. "
                f"({reason})"
            )
            c1, c2 = st.columns(2)
            if c1.button(
                "Switch to Deterministic Fake",
                type="primary",
                key="switch_to_fake",
                use_container_width=True,
            ):
                st.session_state.ref_provider_name = "Deterministic Fake"
                st.rerun()
            if c2.button("Open Setup hint", key="open_setup_hint", use_container_width=True):
                st.info("Use the **Setup** button in the header to change provider or paste keys.")
        elif provider_error:
            st.error(f"Provider error `{provider_error}` ({reason}).")
        elif reason == "CLARIFICATION_LIMIT_REACHED":
            st.warning("Clarification limit reached.")
            c1, c2 = st.columns(2)
            if c1.button("Start over", type="primary", key="clarify_limit_reset", use_container_width=True):
                _reset_state()
                st.rerun()
            if c2.button(
                "Continue as normal chat",
                key="clarify_limit_continue",
                use_container_width=True,
            ):
                st.session_state.ref_compose_mode = "message"
                st.rerun()

    body = _turn_preview(result)
    if response.outcome == Outcome.ROUTE:
        st.code(body, language="json")
    elif response.outcome not in (Outcome.FALLBACK,) or body:
        if response.outcome != Outcome.FALLBACK or "provider error" not in body:
            st.markdown(f'<div class="result-response">{body}</div>', unsafe_allow_html=True)

    cost_txt = f"${cost_usd:.5f}" if cost_usd is not None else "—"
    tokens_txt = str(usage.total_tokens) if usage else "—"
    st.caption(
        f"{latency_ms:.0f} ms · {tokens_txt} tokens · {cost_txt} · `{reason}` · {_provider_short()}"
    )
    st.caption("Primary actions (clarify / demo mock) live on the conversation turn.")

    capability_result: CapabilityResult | None = st.session_state.ref_last_capability_result
    if capability_result is not None:
        with st.container(border=True):
            route_ok = response.outcome == Outcome.ROUTE
            st.markdown(
                f"**Router:** `{response.outcome.value}`"
                + (f" · `{intent}`" if intent else "")
                + (" · success" if route_ok else "")
            )
            st.markdown(
                f"**Demo mock:** `{capability_result.capability_name}` "
                f"({capability_result.status})"
            )
            if capability_result.status == "failed":
                st.error(
                    capability_result.error_message
                    or "Demo mock failed to complete — this is not a routing failure."
                )
            else:
                st.write(capability_result.response_text)
            for artifact in capability_result.artifacts:
                with st.expander(f"Artifact: {artifact.type}", expanded=False):
                    st.write(artifact.content)


def _render_outcome_card(result: ReferenceRunResult) -> None:
    _render_result_hero(result)


def _render_historical_turn_summary(entry: dict[str, Any], *, turn_number: int) -> None:
    try:
        outcome = Outcome(entry["outcome"])
    except ValueError:
        outcome = Outcome.FALLBACK
    color = _OUTCOME_COLORS.get(outcome, "#64748b")
    st.markdown(
        f"""
<div class="result-hero" style="--outcome:{color}">
  <div class="result-hero__badge">{entry['outcome']}</div>
  <div class="result-hero__intent">{entry.get('name') or "—"}</div>
</div>
""",
        unsafe_allow_html=True,
    )
    acceptance = entry.get("acceptance")
    if acceptance:
        badge = "pass" if acceptance.get("passed") else "mismatch"
        st.markdown(
            f'<div class="acceptance acceptance--{badge}">'
            f"Expected {acceptance.get('expected_outcome')} → Actual {acceptance.get('actual_outcome')} · "
            f"<strong>{acceptance.get('label')}</strong></div>",
            unsafe_allow_html=True,
        )
    latency = entry.get("latency_ms")
    st.caption(
        f"{(f'{latency:.0f} ms' if latency is not None else '—')} · "
        f"`{entry.get('reason_code') or '—'}` · Turn {turn_number} historical summary"
    )
    st.info(
        "Full Public / Internal / Mock contracts are available for the **latest** turn only. "
        "They are hidden while you inspect history."
    )
    if st.button("Show latest turn", type="primary", key="show_latest_turn", use_container_width=True):
        log = st.session_state.get("ref_turn_log") or []
        st.session_state.ref_selected_turn_index = len(log) - 1 if log else None
        st.rerun()


def _stage_timeline_rows(result: ReferenceRunResult) -> list[dict[str, Any]]:
    """Primitive-only rows for the stage table (no nested dicts — pyarrow segfaults)."""
    rows: list[dict[str, Any]] = []
    for stage in result.trace.stages:
        hit = stage.detail.get("hit")
        decision = (
            stage.detail.get("decision")
            or stage.detail.get("outcome")
            or stage.detail.get("proposed_outcome")
        )
        status = "hit" if hit is True else ("miss" if hit is False else (decision or "ok"))
        detail = stage.detail or {}
        rows.append(
            {
                "Stage": stage.stage,
                "Status": str(status),
                "Latency (ms)": round(float(stage.latency_ms), 3),
                "Detail": json.dumps(detail, ensure_ascii=False, sort_keys=True),
            }
        )
    return rows


def _render_stage_timeline(result: ReferenceRunResult) -> None:
    # Do NOT use st.dataframe here: Streamlit→pandas→pyarrow segfaults (SIGSEGV /
    # make Error 139) when a column holds nested dicts (seen in Docker + macOS).
    checkpoint("ui.render.stage_timeline.enter", n_stages=len(result.trace.stages))
    st.markdown("**Per-step Intent pipeline**")
    rows = _stage_timeline_rows(result)
    if not rows:
        st.caption("No pipeline stages recorded.")
    else:
        header = "| Stage | Status | Latency (ms) | Detail |"
        sep = "| --- | --- | ---: | --- |"
        body = []
        for row in rows:
            detail = str(row["Detail"]).replace("|", "\\|")
            body.append(
                f"| `{row['Stage']}` | {row['Status']} | {row['Latency (ms)']} | `{detail}` |"
            )
        st.markdown("\n".join([header, sep, *body]))
    st.caption(
        f"Pre-router `{result.trace.pre_router_rule_version}` · "
        f"Taxonomy `{result.trace.taxonomy_version}` · "
        f"Prompt `{result.trace.prompt_version}` · "
        f"Registry `{result.trace.registry_version}` · "
        f"Total {result.trace.total_latency_ms:.2f} ms"
    )
    checkpoint("ui.render.stage_timeline.exit")


def _render_contract_inspectors(result: ReferenceRunResult) -> None:
    request = st.session_state.ref_last_request or _current_request_or_none()
    public_tab, internal_tab, mock_tab = st.tabs(["Public", "Internal", "Mock"])
    with public_tab:
        st.caption("Client wire contract (camelCase public JSON).")
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Request**")
            if request is None:
                st.info("No request yet.")
            else:
                st.json(to_public_request(request))
        with col_b:
            st.markdown("**Response**")
            st.json(to_public_response(result.response))
    with internal_tab:
        st.caption("Internal Reference Trace — not the Client contract.")
        with st.expander("Pipeline stages", expanded=False):
            _render_stage_timeline(result)
        st.json(json.loads(result.trace.model_dump_json(exclude_none=True)))
    with mock_tab:
        st.caption("Demo mock capability contract (outside the Router).")
        capability_request = st.session_state.ref_last_capability_request
        capability_result = st.session_state.ref_last_capability_result
        if capability_request is None or capability_result is None:
            st.info("Run **Run demo mock** on a ROUTE turn to inspect this contract.")
        else:
            st.json(json.loads(capability_request.model_dump_json()))
            st.json(json.loads(capability_result.model_dump_json()))


def _render_model_picker(label: str, choice_key: str, custom_key: str, models) -> None:
    options = select_options(models)
    current = st.session_state.get(choice_key)
    # Explicit index, not just `key=`: on the very first render of a selectbox
    # with a given key, Streamlit has been observed to display `options[0]`
    # even when `st.session_state[key]` was already set to something else by
    # `_init_state()` -- session_state itself stays correct (confirmed: a
    # caption read via st.session_state[choice_key] right after this widget
    # showed the right value while the widget's own displayed label lagged
    # one render behind). Passing index explicitly makes the displayed label
    # correct on the first render too, not just after a second rerun.
    index = options.index(current) if current in options else 0
    st.selectbox(
        label,
        options,
        index=index,
        key=choice_key,
        format_func=lambda model_id: format_option(model_id, models),
    )
    choice = st.session_state[choice_key]
    if choice == CUSTOM_MODEL_CHOICE:
        st.text_input(
            "Custom model ID",
            key=custom_key,
            help="Not validated against the catalog -- type any model ID your provider supports.",
        )
    else:
        note = note_for(choice, models)
        if note:
            st.caption(note)
    with st.expander("Model comparison notes", icon=":material/list_alt:", expanded=False):
        rows = "\n".join(f"| `{m.model_id}` | {m.tag} | {m.note} |" for m in models)
        st.markdown("| Model | Tag | Note |\n|---|---|---|\n" + rows)
        st.caption(
            "Sourced from external research dated August 2026; Gemini entries were live-verified "
            "against the real API on 2026-08-03, OpenAI entries were not (no OPENAI_API_KEY in this "
            "environment). Provider catalogs drift -- use \"Other\" above for anything missing."
        )


def _redact_media_in_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    redacted = []
    for message in messages:
        message = dict(message)
        files = []
        for file in message.get("files") or []:
            file = dict(file)
            data = file.get("data") or ""
            file["data"] = (
                f"<omitted: {file.get('mimeType') or file.get('mime_type', 'unknown')}, "
                f"{len(data)} base64 chars>"
            )
            files.append(file)
        message["files"] = files
        redacted.append(message)
    return redacted


def _serialize_session_message(message: Message) -> dict[str, Any]:
    """Full demo transcript message (includes capability tags; media redacted)."""
    item: dict[str, Any] = {"role": message.role}
    if message.content is not None:
        item["content"] = message.content
    if message.capability_name:
        item["capability_name"] = message.capability_name
    if message.artifact_type:
        item["artifact_type"] = message.artifact_type
    if message.files:
        item["files"] = [
            {
                "mimeType": media.mime_type,
                "data": f"<omitted: {media.mime_type}, {len(media.data)} base64 chars>",
                **({"filename": media.filename} if media.filename else {}),
            }
            for media in message.files
        ]
    return item


def _collect_debug_errors(result: ReferenceRunResult) -> list[dict[str, Any]]:
    """Structured errors / failure signals for the copy-debug bundle."""
    errors: list[dict[str, Any]] = []
    trace = result.trace

    if trace.policy.decision == "block":
        errors.append(
            {
                "source": "policy_gate",
                "code": trace.final_reason_code,
                "category": trace.policy.category,
                "rule_id": trace.policy.rule_id,
                "message": result.response.response_text,
            }
        )

    decision = trace.router_decision
    if decision is not None and decision.provider_error_code:
        errors.append(
            {
                "source": "router_provider",
                "code": decision.provider_error_code,
                "provider": decision.provider,
                "model": decision.model,
                "message": f"Provider failed: {decision.provider_error_code}",
            }
        )

    if trace.validator is not None and trace.validator.issues:
        errors.append(
            {
                "source": "validator",
                "code": trace.final_reason_code,
                "failed_predicates": list(trace.validator.failed_predicates),
                "issues": list(trace.validator.issues),
                "message": "; ".join(trace.validator.issues),
            }
        )

    # Non-success terminal outcomes that are not already covered above.
    if result.response.outcome == Outcome.FALLBACK and not any(
        err["source"] in {"router_provider", "validator"} for err in errors
    ):
        errors.append(
            {
                "source": "final_outcome",
                "code": trace.final_reason_code,
                "outcome": result.response.outcome.value,
                "message": "No safe executable route (FALLBACK).",
            }
        )

    capability_result: CapabilityResult | None = st.session_state.get("ref_last_capability_result")
    if capability_result is not None and capability_result.status == "failed":
        errors.append(
            {
                "source": "mock_capability",
                "code": "CAPABILITY_FAILED",
                "capability_name": capability_result.capability_name,
                "message": capability_result.error_message or capability_result.response_text,
            }
        )

    return errors


def _pipeline_stage_snapshots(result: ReferenceRunResult) -> list[dict[str, Any]]:
    """Per-stage response/state snapshot for debug copy."""
    trace = result.trace
    snapshots: list[dict[str, Any]] = []
    for stage in trace.stages:
        entry: dict[str, Any] = {
            "stage": stage.stage,
            "latency_ms": round(stage.latency_ms, 3),
            "detail": stage.detail,
        }
        if stage.stage == "normalize":
            entry["normalized_text"] = trace.normalized_text
        elif stage.stage == "policy_gate":
            entry["decision"] = trace.policy.decision
            entry["category"] = trace.policy.category
            entry["rule_id"] = trace.policy.rule_id
            if trace.policy.decision == "block":
                entry["response"] = {
                    "outcome": Outcome.REJECT.value,
                    "response_text": result.response.response_text,
                    "reason_code": trace.final_reason_code,
                }
        elif stage.stage == "pre_router":
            entry["hit"] = trace.pre_router_hit
            if trace.pre_router_hit:
                entry["response"] = {
                    "outcome": Outcome.RESPONSE.value,
                    "response_text": result.response.response_text,
                    "reason_code": trace.final_reason_code,
                }
        elif stage.stage == "router" and trace.router_decision is not None:
            decision = trace.router_decision
            entry["response"] = {
                "proposed_outcome": decision.proposed_outcome.value,
                "selected_intent": decision.selected_intent,
                "arguments": decision.arguments,
                "missing_inputs": decision.missing_inputs,
                "response_text": decision.response_text,
                "reason_code": decision.reason_code,
                "provider_error_code": decision.provider_error_code,
                "goals": decision.goals,
                "candidate_intents": decision.candidate_intents,
                "dependencies": [edge.model_dump() for edge in decision.dependencies],
                "usage_model": decision.usage_model.model_dump() if decision.usage_model else None,
                "usage": decision.usage.model_dump() if decision.usage else None,
            }
        elif stage.stage == "validator" and trace.validator is not None:
            entry["response"] = {
                "outcome": result.response.outcome.value,
                "name": result.response.name,
                "arguments": result.response.arguments,
                "response_text": result.response.response_text,
                "clarification": (
                    result.response.clarification.model_dump()
                    if result.response.clarification
                    else None
                ),
                "reason_code": trace.final_reason_code,
                "passed_predicates": list(trace.validator.passed_predicates),
                "failed_predicates": list(trace.validator.failed_predicates),
                "issues": list(trace.validator.issues),
            }
        snapshots.append(entry)
    return snapshots


def _build_debug_bundle(result: ReferenceRunResult) -> dict[str, Any]:
    """Full copy-debug payload: transcript, current message, stages, final, errors."""
    session_messages = [
        _serialize_session_message(message) for message in st.session_state.ref_messages
    ]
    current_user = next(
        (message for message in reversed(st.session_state.ref_messages) if message.role == "user"),
        None,
    )

    routed_request = st.session_state.ref_last_request or _current_request_or_none()
    if routed_request is None:
        public_request: dict[str, Any] = {"messages": []}
        internal_request: dict[str, Any] | None = None
    else:
        public_request = to_public_request(routed_request)
        public_request["messages"] = _redact_media_in_messages(public_request.get("messages", []))
        internal_request = json.loads(routed_request.model_dump_json())
        internal_request["messages"] = _redact_media_in_messages(internal_request.get("messages", []))

    errors = _collect_debug_errors(result)
    bundle: dict[str, Any] = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "provider": st.session_state.ref_provider_name,
        "model": _active_model_label(),
        "session": {
            "clarification_turn_count": st.session_state.ref_turn_count,
            "tools": list(st.session_state.ref_tools),
            "transcript": session_messages,
            "current_user_message": (
                _serialize_session_message(current_user) if current_user else None
            ),
        },
        "routed_request": {
            "public": public_request,
            "internal": internal_request,
        },
        "pipeline_stages": _pipeline_stage_snapshots(result),
        "final_public_response": to_public_response(result.response),
        "final_internal": {
            "outcome": result.response.outcome.value,
            "wire_outcome": result.response.outcome.wire_value,
            "reason_code": result.trace.final_reason_code,
            "response": json.loads(result.response.model_dump_json(exclude_none=True)),
            "trace_meta": {
                "request_id": result.trace.request_id,
                "pre_router_hit": result.trace.pre_router_hit,
                "pre_router_rule_version": result.trace.pre_router_rule_version,
                "taxonomy_version": result.trace.taxonomy_version,
                "prompt_version": result.trace.prompt_version,
                "registry_version": result.trace.registry_version,
                "total_latency_ms": result.trace.total_latency_ms,
            },
        },
        "errors": errors,
        "has_errors": bool(errors),
        "internal_trace": json.loads(result.trace.model_dump_json(exclude_none=True)),
    }

    capability_request = st.session_state.ref_last_capability_request
    capability_result = st.session_state.ref_last_capability_result
    if capability_request is not None and capability_result is not None:
        bundle["mock_capability"] = {
            "request": json.loads(capability_request.model_dump_json()),
            "result": json.loads(capability_result.model_dump_json()),
        }
    return bundle


def _render_debug_bundle(result: ReferenceRunResult) -> None:
    with st.expander("Debug bundle for Claude", icon=":material/bug_report:", expanded=False):
        bundle = _build_debug_bundle(result)
        st.caption(
            "Full dump for copy: session transcript, current user message, per-stage responses, "
            "final public/internal output, and errors (if any). Image bytes are redacted. "
            "Hover the block for a copy icon."
        )
        if bundle["has_errors"]:
            st.warning(f"{len(bundle['errors'])} error signal(s) in this run — see `errors` array.")
        st.code(json.dumps(bundle, ensure_ascii=False, indent=2), language="json")


_FLOW_EXPLAINER_MD = """\
**Normalize** — Unicode NFKC + diacritic fold for rule matching.

**Policy Gate** — first gate. MVP fixture rules (NSFW/illegal seeds). Block → `REJECT`; later stages skip.

**Pre-router** — deterministic, 0 LLM. Exact full-message static phrases only. Hit → `RESPONSE`.

**Structured LLM Router** — ≤1 generative call. Tagged union: `RESPONSE | ROUTE | CLARIFY | FALLBACK`.

**Validator** — deterministic only: schema, tools allowlist, registry requires_*, clarify templates.
Empty `tools` → no `ROUTE`. Reason codes stay INTERNAL.

**5 public outcomes:** `RESPONSE`, `ROUTE`, `CLARIFY`, `FALLBACK`, `REJECT`
(wire: `INTENTION_DETECT_OUTCOME_*`).

See `docs/reference-runtime.md`.
"""

_UI_CSS = """
<style>
:root {
  --ink: #0f172a;
  --muted: #64748b;
  --accent: #0f766e;
  --surface: #f8fafc;
  --panel: #ffffff;
  --line: #e2e8f0;
  --danger: #b91c1c;
  --ok: #047857;
}
.block-container {
  max-width: min(1440px, 94vw) !important;
  padding-top: 0.55rem !important;
  padding-bottom: 1.25rem !important;
  padding-left: 1.1rem !important;
  padding-right: 1.1rem !important;
}
div[data-testid="stHorizontalBlock"] { gap: 1.1rem; }
.pane-label, .dock-label {
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  margin: 0 0 0.35rem;
}
.ref-header h2 {
  font-size: 1.35rem !important;
  margin-bottom: 0.1rem !important;
}
.empty-thread {
  padding: 0.95rem 0.9rem;
  border-radius: 12px;
  background: linear-gradient(180deg, var(--surface), var(--panel));
  border: 1px solid var(--line);
  margin-bottom: 0.4rem;
}
.empty-thread p { margin: 0.35rem 0 0; color: var(--muted); line-height: 1.4; }
.intent-chip {
  border: 1px solid color-mix(in srgb, var(--outcome) 30%, var(--line));
  background: color-mix(in srgb, var(--outcome) 8%, white);
  border-radius: 10px;
  padding: 0.4rem 0.55rem;
  margin-bottom: 0.3rem;
}
.intent-chip--selected {
  outline: 2px solid color-mix(in srgb, var(--outcome) 55%, transparent);
}
.intent-chip__row {
  display: flex; flex-wrap: wrap; gap: 0.35rem 0.65rem; align-items: baseline;
}
.intent-chip__badge {
  font-size: 0.92rem; font-weight: 800; letter-spacing: -0.01em; color: var(--outcome);
}
.intent-chip__meta {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.7rem; color: var(--muted);
}
.result-hero {
  border: 1px solid color-mix(in srgb, var(--outcome) 28%, var(--line));
  border-radius: 12px;
  background: color-mix(in srgb, var(--outcome) 8%, white);
  padding: 0.75rem 0.9rem;
  margin: 0 0 0.55rem;
}
.result-hero__badge {
  font-size: 1.4rem; font-weight: 800; letter-spacing: -0.03em; color: var(--outcome);
  line-height: 1.1;
}
.result-hero__intent {
  margin-top: 0.15rem;
  font-size: 1rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: var(--ink);
  word-break: break-word;
}
.result-response {
  margin: 0.3rem 0 0.45rem;
  padding: 0.65rem 0.75rem;
  border-radius: 10px;
  background: var(--surface);
  border: 1px solid var(--line);
  font-size: 0.92rem;
  line-height: 1.4;
}
.acceptance {
  border-radius: 8px;
  padding: 0.4rem 0.6rem;
  margin: 0 0 0.45rem;
  font-size: 0.82rem;
  border: 1px solid var(--line);
}
.acceptance--pass {
  background: #ecfdf5; border-color: #a7f3d0; color: var(--ok);
}
.acceptance--mismatch {
  background: #fef2f2; border-color: #fecaca; color: var(--danger);
}
.scenario-row {
  padding: 0.35rem 0.2rem;
  border-bottom: 1px solid var(--line);
}
[data-testid="stChatInput"] {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
}
/* Prefer latest-first feel on stacked (narrow) layouts: right column order is CSS-limited;
   keep dock visually anchored under the conversation scroll region. */
@media (max-width: 900px) {
  .block-container { padding-top: 0.4rem !important; }
}
</style>
"""


def _inject_ui_css() -> None:
    st.markdown(_UI_CSS, unsafe_allow_html=True)
    st.session_state._ref_ui_css_injected = True


def _render_benchmark_panel() -> None:
    with st.expander("Model benchmark harness", icon=":material/analytics:", expanded=False):
        st.caption(
            "Runs the scenario suite for selected providers and exports JSON/CSV/summary under "
            "`benchmark_reports/`."
        )
        selected = st.multiselect(
            "Candidates",
            ["fake", "gemini", "openai"],
            default=["fake"],
            key="ref_benchmark_providers",
        )
        if st.button("Run benchmark", type="primary", key="ref_run_benchmark"):
            providers = []
            for name in selected:
                if name == "fake":
                    providers.append(FakeRouterProvider())
                elif name == "gemini":
                    model = _effective_model("ref_gemini_model_choice", "ref_gemini_model_custom")
                    providers.append(GeminiRouterProvider(_REGISTRY, model_name=model))
                elif name == "openai":
                    model = _effective_model("ref_openai_model_choice", "ref_openai_model_custom")
                    providers.append(OpenAIRouterProvider(_REGISTRY, model_name=model))
            with st.spinner("Running benchmark…"):
                reports = run_benchmark(
                    providers=providers,
                    scenarios=BENCHMARK_SCENARIOS,
                    clarification_chains=CLARIFICATION_CHAINS,
                    output_dir=__import__("pathlib").Path("benchmark_reports"),
                )
            for report in reports:
                st.success(
                    f"{report.provider}/{report.model}: "
                    f"outcome_acc={report.outcome_accuracy:.3f} · "
                    f"false_route={report.false_route_rate} · "
                    f"response_fp={report.response_false_positive_rate}"
                )

def _ui_scenarios():
    """Core suite only — archived-intent scenarios stay in deferred/benchmark."""
    return [s for s in SCENARIOS if s.phase == "core"]


def _load_scenario(scenario) -> None:
    checkpoint("ui.load_scenario", scenario_id=scenario.id)
    _reset_state()
    st.session_state.ref_active_scenario_id = scenario.id
    st.session_state.ref_acceptance = {
        "scenario_id": scenario.id,
        "expected_outcome": scenario.expected_outcome,
        "expected_name": scenario.expected_name,
    }
    st.session_state._ref_keep_acceptance = True
    if scenario.tools is not None:
        st.session_state.ref_pending_tools = list(scenario.tools)
    if scenario.with_image:
        st.session_state.ref_pending_image_bytes = b"fake-demo-image-bytes"
        st.session_state.ref_pending_image_mime = "image/png"
        st.session_state.ref_pending_image_name = "scenario-demo.png"
    for role, content, capability_name in scenario.capability_history:
        st.session_state.ref_messages.append(
            Message(role=role, content=content, capability_name=capability_name or None)
        )
    st.session_state.ref_turn_count = scenario.clarification_turn_count
    _submit_user_text(scenario.text)
    checkpoint("ui.load_scenario.before_rerun")


def _filter_scenarios(scenarios: list, query: str, category: str) -> list:
    needle = (query or "").strip().lower()
    filtered = []
    for scenario in scenarios:
        if category == "more":
            if scenario.category not in _MORE_SCENARIO_CATEGORIES:
                continue
        elif category != "all" and scenario.category != category:
            continue
        if needle:
            haystack = " ".join(
                [
                    scenario.id,
                    scenario.category,
                    scenario.description,
                    scenario.text,
                    scenario.expected_outcome,
                    scenario.expected_name or "",
                    scenario.expected_reason_code or "",
                ]
            ).lower()
            if needle not in haystack:
                continue
        filtered.append(scenario)
    return filtered


def _render_compact_scenario_list() -> None:
    """Browse-only list. Execution happens via the right-pane CTA (or confirm)."""
    ui_scenarios = _ui_scenarios()
    primary = list(_PRIMARY_SCENARIO_CATEGORIES) + ["more"]
    labels = []
    for cat in primary:
        if cat == "more":
            labels.append("More filters")
        elif cat == "route":
            labels.append("Route")
        elif cat == "clarify":
            labels.append("Clarify")
        else:
            labels.append(_CATEGORY_LABELS.get(cat, cat))

    st.text_input(
        "Search scenarios",
        key="ref_scenario_query",
        placeholder="Search scenarios…",
        label_visibility="collapsed",
    )

    current_cat = st.session_state.get("ref_scenario_category") or "all"
    if current_cat not in primary:
        if current_cat in _MORE_SCENARIO_CATEGORIES:
            current_cat = "more"
        else:
            current_cat = "all"
    default_label = (
        "More filters"
        if current_cat == "more"
        else ("Route" if current_cat == "route" else "Clarify" if current_cat == "clarify" else "All")
    )
    selected_label = st.pills(
        "Category",
        labels,
        selection_mode="single",
        default=default_label if default_label in labels else "All",
        key="ref_scenario_category_pills",
        label_visibility="collapsed",
    )
    label_to_cat = {labels[i]: primary[i] for i in range(len(primary))}
    st.session_state.ref_scenario_category = label_to_cat.get(selected_label or "All", "all")

    filtered = _filter_scenarios(
        ui_scenarios,
        st.session_state.get("ref_scenario_query") or "",
        st.session_state.ref_scenario_category,
    )
    st.caption(
        f"{len(filtered)} / {len(ui_scenarios)} · Selecting does **not** change the conversation"
    )

    selected_id = st.session_state.get("ref_selected_scenario_id")
    with st.container(height=200, border=True):
        if not filtered:
            st.info("No scenarios match.")
            return
        for scenario in filtered:
            is_selected = scenario.id == selected_id
            meta = scenario.expected_outcome
            if scenario.expected_name:
                meta += f" · {scenario.expected_name}"
            mark = "● " if is_selected else "○ "
            row_cols = st.columns([5.2, 1])
            with row_cols[0]:
                st.markdown(
                    f"{mark}**{scenario.id}**  \n"
                    f"`Expected {meta}`"
                )
            with row_cols[1]:
                if st.button(
                    "Select",
                    key=f"scenario_select_{scenario.id}",
                    use_container_width=True,
                    type="primary" if is_selected else "secondary",
                ):
                    st.session_state.ref_selected_scenario_id = scenario.id
                    st.session_state.ref_scenario_confirm_run = False
                    st.rerun()


def _render_scenario_selection_panel() -> None:
    """Right pane while browsing scenarios — detail + single destructive CTA."""
    st.markdown('<div class="pane-label">Selected scenario</div>', unsafe_allow_html=True)
    scenario = _scenario_by_id(st.session_state.get("ref_selected_scenario_id"))
    if scenario is None:
        st.info("Select a scenario in the dock. Browsing does not change the conversation.")
        return

    meta = scenario.expected_outcome
    if scenario.expected_name:
        meta += f" · {scenario.expected_name}"
    st.markdown(f"### `{scenario.id}`")
    st.caption(f"Expected {meta}")
    st.write(scenario.description)
    with st.expander("Fixture text", expanded=True):
        st.code(scenario.text, language=None)

    has_thread = bool(st.session_state.get("ref_messages"))
    st.caption("Starts a **new** conversation (replaces the current thread).")

    if st.session_state.get("ref_scenario_confirm_run") and has_thread:
        st.warning("Running this scenario will replace the current conversation.")
        c1, c2 = st.columns(2)
        if c1.button("Cancel", key="scenario_run_cancel", use_container_width=True):
            st.session_state.ref_scenario_confirm_run = False
            st.rerun()
        if c2.button(
            "Run as new conversation",
            type="primary",
            key="scenario_run_confirm",
            use_container_width=True,
        ):
            st.session_state.ref_scenario_confirm_run = False
            _load_scenario(scenario)
            st.session_state.ref_compose_mode = "message"
            st.rerun()
        return

    c1, c2 = st.columns(2)
    if c1.button("Cancel", key="scenario_cancel_select", use_container_width=True):
        st.session_state.ref_selected_scenario_id = None
        st.session_state.ref_scenario_confirm_run = False
        st.session_state.ref_compose_mode = "message"
        st.rerun()
    if c2.button(
        "Run as new conversation",
        type="primary",
        key="scenario_run_primary",
        use_container_width=True,
    ):
        _request_scenario_run(scenario)
        if not st.session_state.get("ref_scenario_confirm_run"):
            st.session_state.ref_compose_mode = "message"
        st.rerun()


def _render_setup_surface() -> None:
    st.markdown("##### Setup")
    st.caption(_config_summary_line())
    st.selectbox("Router provider", PROVIDER_OPTIONS, key="ref_provider_name")
    if st.session_state.ref_provider_name == "Gemini Structured Output":
        _render_model_picker(
            "Gemini model", "ref_gemini_model_choice", "ref_gemini_model_custom", GEMINI_MODELS
        )
    elif st.session_state.ref_provider_name == "OpenAI Structured Output":
        _render_model_picker(
            "OpenAI model", "ref_openai_model_choice", "ref_openai_model_custom", OPENAI_MODELS
        )
    if st.session_state.ref_provider_name != "Deterministic Fake":
        needed = (
            "GEMINI_API_KEY"
            if "Gemini" in st.session_state.ref_provider_name
            else "OPENAI_API_KEY"
        )
        if not (os.getenv(needed) or "").strip():
            st.error(
                f"`{needed}` missing — live calls FALLBACK. Switch to Deterministic Fake "
                "or fill `.env` and restart."
            )
            if st.button("Switch to Deterministic Fake", key="setup_switch_fake"):
                st.session_state.ref_provider_name = "Deterministic Fake"
                st.rerun()

    st.multiselect(
        "Client tools (V1 active intents)",
        _ALL_EXECUTABLE_INTENTS,
        key="ref_tools",
        help="Remove one to demo UNSUPPORTED_CAPABILITY.",
    )
    uploaded_image = st.file_uploader(
        "Image for next message only",
        type=["jpg", "jpeg", "png", "webp"],
        key=f"ref_image_upload_{st.session_state.ref_uploader_revision}",
    )
    if uploaded_image is not None:
        st.session_state.ref_pending_image_bytes = uploaded_image.getvalue()
        st.session_state.ref_pending_image_mime = uploaded_image.type
        st.session_state.ref_pending_image_name = uploaded_image.name
    pending_name = st.session_state.get("ref_pending_image_name")
    if pending_name:
        clear_cols = st.columns([3, 1])
        clear_cols[0].caption(f"Image attached for next message · {pending_name}")
        if clear_cols[1].button("Remove", key="clear_pending_image"):
            st.session_state.ref_pending_image_bytes = None
            st.session_state.ref_pending_image_mime = None
            st.session_state.ref_pending_image_name = None
            st.session_state.ref_uploader_revision += 1
            st.rerun()

    st.divider()
    has_thread = bool(st.session_state.get("ref_messages"))
    if has_thread and not st.session_state.get("ref_setup_confirm_reset"):
        if st.button("Reset conversation…", use_container_width=True, key="reset_ask"):
            st.session_state.ref_setup_confirm_reset = True
            st.rerun()
    elif has_thread and st.session_state.get("ref_setup_confirm_reset"):
        st.warning("This clears messages, intents, and results. Provider/tools are kept.")
        c1, c2 = st.columns(2)
        if c1.button("Confirm reset", type="primary", use_container_width=True, key="reset_yes"):
            st.session_state.ref_setup_confirm_reset = False
            _reset_state()
            st.rerun()
        if c2.button("Cancel", use_container_width=True, key="reset_no"):
            st.session_state.ref_setup_confirm_reset = False
            st.rerun()
    else:
        if st.button("Reset conversation", use_container_width=True, key="reset_empty"):
            _reset_state()
            st.rerun()


def _render_interaction_dock() -> None:
    st.markdown('<div class="dock-label">Next</div>', unsafe_allow_html=True)
    mode = st.segmented_control(
        "Compose mode",
        options=["Write message", "Pick scenario"],
        selection_mode="single",
        default=(
            "Pick scenario"
            if st.session_state.get("ref_compose_mode") == "scenario"
            else "Write message"
        ),
        key="ref_compose_mode_control",
        label_visibility="collapsed",
    )
    st.session_state.ref_compose_mode = (
        "scenario" if mode == "Pick scenario" else "message"
    )

    if st.session_state.ref_compose_mode == "scenario":
        _render_compact_scenario_list()
        return

    pending = st.session_state.get("ref_pending_image_name")
    caption = _config_summary_line()
    if pending:
        caption += f" · pending `{pending}`"
    st.caption(caption)
    if st.session_state.get("ref_routing"):
        st.caption("Routing…")
    user_text = st.chat_input("Message or clarification answer…")
    if user_text:
        checkpoint("ui.chat_input.received", text_len=len(user_text))
        st.session_state.ref_routing = True
        try:
            _submit_user_text(user_text)
        finally:
            st.session_state.ref_routing = False
        checkpoint("ui.chat_input.before_rerun")
        st.rerun()


def _render_current_result_panel() -> None:
    log = st.session_state.get("ref_turn_log") or []
    result: ReferenceRunResult | None = st.session_state.get("ref_last_result")
    selected = st.session_state.get("ref_selected_turn_index")
    historical = _is_viewing_historical_turn()

    if historical and selected is not None and 0 <= selected < len(log):
        turn_number = selected + 1
        st.markdown(
            f'<div class="pane-label">Turn {turn_number} · Historical summary</div>',
            unsafe_allow_html=True,
        )
        _render_historical_turn_summary(log[selected], turn_number=turn_number)
        return

    turn_n = len(log)
    label = f"Turn {turn_n} · Latest" if turn_n else "Current result"
    st.markdown(f'<div class="pane-label">{label}</div>', unsafe_allow_html=True)

    if not log and result is None:
        st.info(
            "Run a message or scenario to see outcome, acceptance, and next-step guidance here."
        )
        return

    if result is not None:
        _render_outcome_card(result)
    else:
        st.info("No result yet.")


def _render_inspect_and_advanced(result: ReferenceRunResult | None) -> None:
    if result is None:
        return
    if _is_viewing_historical_turn():
        return  # contracts must not appear under a historical summary
    force_open = bool(st.session_state.get("ref_inspect_force_open"))
    with st.expander(
        "Contracts for latest turn",
        icon=":material/search:",
        expanded=force_open,
    ):
        if force_open:
            st.session_state.ref_inspect_force_open = False
        _render_contract_inspectors(result)
    with st.expander("Advanced", icon=":material/construction:", expanded=False):
        _render_debug_bundle(result)
        _render_classifier_prompt_panel()
        _render_benchmark_panel()
        with st.expander("How V1 Reference works", expanded=False):
            st.markdown(_FLOW_EXPLAINER_MD)


def _render_header() -> None:
    left, right = st.columns([3.2, 1.2], vertical_alignment="center")
    with left:
        st.markdown(
            '<div class="ref-header"><h2>Intention V1 Reference</h2></div>',
            unsafe_allow_html=True,
        )
        st.caption(_config_summary_line())
    with right:
        with st.popover("Setup", use_container_width=True):
            _render_setup_surface()


def _render_right_pane() -> None:
    browsing = (
        st.session_state.get("ref_compose_mode") == "scenario"
        and st.session_state.get("ref_selected_scenario_id")
    )
    if browsing or (
        st.session_state.get("ref_compose_mode") == "scenario"
        and st.session_state.get("ref_scenario_confirm_run")
    ):
        _render_scenario_selection_panel()
        return

    # When picking scenarios but nothing selected yet, still show current result
    # so an existing thread remains visible while browsing.
    if st.session_state.get("ref_compose_mode") == "scenario":
        _render_scenario_selection_panel()
        st.divider()
        _render_current_result_panel()
        result: ReferenceRunResult | None = st.session_state.ref_last_result
        if not _is_viewing_historical_turn():
            _render_inspect_and_advanced(result)
        return

    _render_current_result_panel()
    result = st.session_state.ref_last_result
    _render_inspect_and_advanced(result)


def render() -> None:
    """
    Direction contract (Operate / structural pass):
    THESIS: Thread = chronology+action; Result = authoritative diagnostic; browse ≠ mutate.
    OWN-WORLD: Wide slate console, teal outcome accent, compact turns, result-first inspector.
    STORY: Operator starts in the dock, reads scoped result without Setup/debug noise.
    FIRST VIEWPORT: Bounded conversation + dock | scoped result (+ collapsed contracts).
    FORM: Workspace split ~1.7/1, seed operate-structural-2026-08-08.
    """
    checkpoint("ui.render.enter")
    _init_state()
    _inject_ui_css()
    checkpoint(
        "ui.render.state_ready",
        provider=st.session_state.ref_provider_name,
        n_messages=len(st.session_state.ref_messages),
        has_last_result=st.session_state.ref_last_result is not None,
    )

    _render_header()

    left, right = st.columns([1.7, 1], gap="large")

    with left:
        st.markdown('<div class="pane-label">Conversation</div>', unsafe_allow_html=True)
        turn_n = len(st.session_state.get("ref_turn_log") or [])
        msg_n = len(st.session_state.ref_messages)
        st.caption(f"{msg_n} messages · {turn_n} intent turns")
        # Bounded scroll so the interaction dock stays in the first-viewport budget.
        with st.container(height=360, border=True):
            checkpoint("ui.render.before_transcript")
            _render_transcript()
        _render_interaction_dock()

    with right:
        _render_right_pane()

    checkpoint("ui.render.exit")

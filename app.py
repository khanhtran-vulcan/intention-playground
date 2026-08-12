from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pydantic import ValidationError

import reference_ui
from core.evaluation import EvaluationReport, evaluate_router, validate_evaluation_frame
from core.request import ImageAttachment, RouteRequest
from core.runtime import RuntimeState, build_runtime_state
from core.taxonomy import Taxonomy, dump_taxonomy, load_taxonomy
from routers.base import RouteResult, RouterError, RouterStatus
from routers.gemini_router import DEFAULT_GEMINI_MODEL
from routers.hybrid_router import run_parallel_with_timeouts
from routers.semantic_router import DEFAULT_MODEL_NAME
from reference_runtime.debug_trace import checkpoint, install_crash_diagnostics


ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "intents.json"
EVALUATION_PATH = ROOT / "data" / "evaluation.csv"
MODEL_PATH = ROOT / "models" / "sklearn_intent.joblib"
PROVIDER_ORDER = [
    "Rules",
    "TF-IDF + Logistic Regression",
    "Semantic Router",
    "Gemini Structured Output",
]

load_dotenv(ROOT / ".env")
install_crash_diagnostics(where="app.module_import")
st.set_page_config(
    page_title="Intention Playground",
    page_icon="⇢",
    layout="wide",
    # "auto" (not "expanded"): Streamlit collapses the sidebar on narrow
    # viewports by itself. Forcing "expanded" made the sidebar cover most of
    # the screen on mobile widths on every load.
    initial_sidebar_state="auto",
)
checkpoint("app.after_set_page_config")
st.markdown(
    """
    <style>
    :root { --ink: #17212b; --accent: #d95d39; }
    .block-container { max-width: 1240px; padding-top: 2rem; }
    h1, h2, h3 { letter-spacing: -0.025em; }
    .block-container h1 { font-size: clamp(1.75rem, 4.5vw, 2.75rem); }
    [data-testid="stMetricValue"] { color: var(--accent); }
    .flow {
      border-left: 4px solid var(--accent); padding: .75rem 1rem;
      background: color-mix(in srgb, var(--accent) 8%, transparent);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      line-height: 1.7;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def initialize_session() -> RuntimeState:
    existing_runtime = st.session_state.get("runtime")
    if existing_runtime is not None and not all(
        hasattr(intent, "prompt_section")
        for intent in existing_runtime.taxonomy.intents
    ):
        for key in (
            "runtime",
            "taxonomy_draft",
            "taxonomy_draft_revision",
            "compare_results",
            "hybrid_result",
            "evaluation_reports",
        ):
            st.session_state.pop(key, None)
    if "semantic_model_name" not in st.session_state:
        st.session_state.semantic_model_name = os.getenv(
            "SEMANTIC_MODEL", DEFAULT_MODEL_NAME
        )
    if "gemini_model_name" not in st.session_state:
        st.session_state.gemini_model_name = os.getenv(
            "GEMINI_MODEL", DEFAULT_GEMINI_MODEL
        )
    if "runtime" not in st.session_state:
        taxonomy = load_taxonomy(DATA_PATH)
        with st.spinner("Preparing the default runtime..."):
            st.session_state.runtime = build_runtime_state(
                taxonomy,
                model_path=MODEL_PATH,
                persist_default_artifact=True,
                semantic_model_name=st.session_state.semantic_model_name,
                gemini_model_name=st.session_state.gemini_model_name,
            )
        st.session_state.taxonomy_draft = taxonomy.model_dump(mode="json")
        st.session_state.taxonomy_draft_revision = 0
    return st.session_state.runtime


runtime = initialize_session()

with st.sidebar:
    st.header("Runtime settings")
    ml_threshold = st.slider("ML threshold", 0.0, 1.0, 0.20, 0.05)
    semantic_threshold = st.slider("Semantic threshold", 0.0, 1.0, 0.55, 0.05)
    gemini_threshold = st.slider("Gemini threshold", 0.0, 1.0, 0.60, 0.05)
    local_timeout = st.number_input(
        "Local router timeout (seconds)", 0.1, 30.0, 2.0, 0.5
    )
    gemini_timeout = st.number_input(
        "Gemini timeout (seconds, apply below)", 1.0, 120.0, 15.0, 1.0
    )
    st.caption("Provider confidence scores are not directly comparable.")
    if runtime.semantic_router.initialization_error:
        if st.button("Retry semantic initialization", use_container_width=True):
            runtime.semantic_router.reset_initialization()
            st.rerun()
    with st.expander("Model settings"):
        semantic_model_name = st.text_input(
            "Semantic model", value=st.session_state.semantic_model_name
        )
        gemini_model_name = st.text_input(
            "Gemini model", value=st.session_state.gemini_model_name
        )
        if st.button("Apply model settings", use_container_width=True):
            try:
                candidate = build_runtime_state(
                    runtime.taxonomy,
                    model_path=None,
                    semantic_model_name=semantic_model_name.strip(),
                    gemini_model_name=gemini_model_name.strip(),
                    gemini_timeout_seconds=float(gemini_timeout),
                )
                st.session_state.runtime = candidate
                st.session_state.semantic_model_name = semantic_model_name.strip()
                st.session_state.gemini_model_name = gemini_model_name.strip()
                for key in ("compare_results", "hybrid_result", "evaluation_reports"):
                    st.session_state.pop(key, None)
                st.rerun()
            except Exception as exc:
                st.error(f"Model settings were not applied: {exc}")
    st.divider()
    st.caption(f"Taxonomy `{runtime.taxonomy_hash[:12]}`")
    st.caption(f"{len(runtime.taxonomy.known_intents)} known intents + unknown")

st.title("Intention Router Playground")
st.caption(
    "Compare deterministic rules, classical ML, semantic similarity, and a structured LLM classifier."
)

reference_tab, compare_tab, evaluate_tab, hybrid_tab, taxonomy_tab = st.tabs(
    ["V1 Reference", "Compare", "Evaluate", "Hybrid", "Taxonomy"]
)

with reference_tab:
    reference_ui.render()


def route_calls(
    request: RouteRequest,
) -> dict[str, tuple[Callable[[], RouteResult], float]]:
    return {
        "Rules": (lambda: runtime.rule_router.route(request), float(local_timeout)),
        "TF-IDF + Logistic Regression": (
            lambda: runtime.sklearn_router.route(request, ml_threshold),
            float(local_timeout),
        ),
        "Semantic Router": (
            lambda: runtime.semantic_router.route(request, semantic_threshold),
            float(local_timeout),
        ),
        "Gemini Structured Output": (
            lambda: runtime.gemini_router.route(request, gemini_threshold),
            float(gemini_timeout),
        ),
    }


def build_request(text: str, uploaded_image: object | None = None) -> RouteRequest:
    images = []
    if uploaded_image is not None:
        images.append(
            ImageAttachment(
                name=uploaded_image.name,
                mime_type=uploaded_image.type,
                data=uploaded_image.getvalue(),
            )
        )
    return RouteRequest(text=text, images=images)


def ensure_semantic_initialized(
    request: RouteRequest,
) -> tuple[float | None, RouteResult | None]:
    if runtime.semantic_router.initialized:
        return None, None
    started = time.perf_counter()
    try:
        with st.spinner(
            "Initializing the semantic model and index. The first run may download model weights..."
        ):
            initialization_ms = runtime.semantic_router.initialize()
        return initialization_ms, None
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1_000
        return None, RouteResult(
            provider="Semantic Router",
            status=RouterStatus.UNAVAILABLE,
            latency_ms=elapsed_ms,
            reason="The embedding model or semantic index could not be initialized.",
            metadata={
                "score_type": "cosine_similarity",
                "model": runtime.semantic_router.model_name,
                "has_images": request.has_images,
                "image_count": request.image_count,
                "missing_required_context": False,
            },
            error=RouterError(
                code="SEMANTIC_UNAVAILABLE",
                message=str(exc)[:500],
                retryable=True,
            ),
        )


def render_result_card(result: RouteResult) -> None:
    with st.container(border=True):
        st.subheader(result.provider)
        left, right = st.columns(2)
        left.metric("Intent", result.intent or "—")
        right.metric(
            "Confidence",
            "—" if result.confidence is None else f"{result.confidence:.3f}",
        )
        st.caption(
            f"Status: **{result.status.value}** · Latency: **{result.latency_ms:.1f} ms** · "
            f"Score: `{result.metadata.get('score_type', 'n/a')}`"
        )
        st.write(result.reason)
        if result.properties:
            st.markdown("**Conditional properties**")
            st.json(result.properties)
        if result.metadata.get("missing_required_context"):
            st.warning("This intent requires an image, but no image was attached.")
        raw = result.raw_output if isinstance(result.raw_output, dict) else {}
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else None
        estimated_cost = (
            raw.get("estimated_cost")
            if isinstance(raw.get("estimated_cost"), dict)
            else None
        )
        if usage:
            token_columns = st.columns(4)
            token_columns[0].metric("Input tokens", usage.get("input_tokens") or 0)
            token_columns[1].metric("Output tokens", usage.get("output_tokens") or 0)
            token_columns[2].metric("Thinking tokens", usage.get("thinking_tokens") or 0)
            token_columns[3].metric("Cached tokens", usage.get("cached_input_tokens") or 0)
        if estimated_cost:
            if estimated_cost.get("available"):
                st.caption(
                    "Estimated call cost: "
                    f"{estimated_cost['amount']:.8f} {estimated_cost['currency']}"
                )
            else:
                st.caption(
                    "Estimated call cost: unavailable · "
                    + estimated_cost.get("reason", "Pricing is not configured.")
                )
        if result.error:
            st.error(f"{result.error.code}: {result.error.message}")
        with st.expander("Raw output and metadata"):
            st.json(
                {
                    "raw_output": result.raw_output,
                    "metadata": result.metadata,
                    "error": result.error.model_dump() if result.error else None,
                }
            )


def clear_result_state() -> None:
    for key in (
        "compare_results",
        "hybrid_result",
        "evaluation_reports",
        "evaluation_initialization",
    ):
        st.session_state.pop(key, None)


with compare_tab:
    st.markdown(
        '<div class="flow">User message → Rules │ TF-IDF │ Semantic │ Gemini<br>'
        "                             ↓<br>"
        "                     Intent comparison</div>",
        unsafe_allow_html=True,
    )
    compare_text = st.text_area(
        "User message",
        value="Tạo poster cho lễ hội âm nhạc ngày 20/8",
        height=100,
        key="compare_text",
    )
    compare_image = st.file_uploader(
        "Optional image (one JPEG, PNG, or WebP; maximum 10 MB)",
        type=["jpg", "jpeg", "png", "webp"],
        key="compare_image",
    )
    if st.button("Run comparison", type="primary", key="run_compare"):
        try:
            compare_request = build_request(compare_text, compare_image)
        except (ValueError, ValidationError) as exc:
            st.warning(f"Invalid request: {exc}")
        else:
            initialization_ms, initialization_failure = ensure_semantic_initialized(
                compare_request
            )
            calls = route_calls(compare_request)
            if initialization_failure is not None:
                calls["Semantic Router"] = (
                    lambda result=initialization_failure: result,
                    float(local_timeout),
                )
            with st.spinner("Running four providers in parallel..."):
                st.session_state.compare_results = run_parallel_with_timeouts(
                    calls
                )
            if initialization_ms is not None:
                semantic_result = st.session_state.compare_results["Semantic Router"]
                st.session_state.compare_results["Semantic Router"] = (
                    semantic_result.model_copy(
                        update={
                            "metadata": {
                                **semantic_result.metadata,
                                "cold_initialization_ms": initialization_ms,
                            }
                        }
                    )
                )

    results = st.session_state.get("compare_results")
    if results:
        ordered = [results[name] for name in PROVIDER_ORDER]
        summary = pd.DataFrame(
            [
                {
                    "Provider": result.provider,
                    "Status": result.status.value,
                    "Intent": result.intent,
                    "Confidence": result.confidence,
                    "Score type": result.metadata.get("score_type"),
                    "Latency (ms)": round(result.latency_ms, 2),
                }
                for result in ordered
            ]
        )
        st.subheader("Comparison")
        st.dataframe(summary, use_container_width=True, hide_index=True)
        known_predictions = {
            result.intent
            for result in ordered
            if result.intent not in (None, "unknown")
        }
        if len(known_predictions) > 1:
            st.warning("Providers disagree on the predicted intent.")
        elif all(result.intent in (None, "unknown") for result in ordered):
            st.info("All available providers abstained.")
        columns = st.columns(2)
        for index, result in enumerate(ordered):
            with columns[index % 2]:
                render_result_card(result)


def evaluation_routes() -> dict[str, Callable[[RouteRequest], RouteResult]]:
    return {
        "Rules": runtime.rule_router.route,
        "TF-IDF + Logistic Regression": lambda request: runtime.sklearn_router.route(
            request, ml_threshold
        ),
        "Semantic Router": lambda request: runtime.semantic_router.route(
            request, semantic_threshold
        ),
        "Gemini Structured Output": lambda request: runtime.gemini_router.route(
            request, gemini_threshold
        ),
        "Hybrid Router": lambda request: runtime.hybrid_router.route(
            request,
            ml_threshold,
            semantic_threshold,
            gemini_threshold,
            float(local_timeout),
        ),
    }


def render_report(report: EvaluationReport) -> None:
    st.subheader(report.provider)
    metrics = report.metrics
    row_one = st.columns(5)
    metric_specs = [
        ("Overall accuracy", "overall_accuracy", ".1%"),
        ("Known accuracy", "known_accuracy", ".1%"),
        ("Unknown recall", "unknown_recall", ".1%"),
        ("Coverage", "coverage", ".1%"),
        ("Selective accuracy", "selective_accuracy", ".1%"),
    ]
    for column, (label, key, fmt) in zip(row_one, metric_specs):
        value = metrics[key]
        column.metric(label, "—" if value is None else format(value, fmt))
    row_two = st.columns(5)
    for column, (label, key) in zip(
        row_two,
        [
            ("False acceptance", "false_acceptance_rate"),
            ("Unknown rate", "unknown_rate"),
            ("Average latency", "average_latency_ms"),
            ("Median latency", "median_latency_ms"),
            ("P95 latency", "p95_latency_ms"),
        ],
    ):
        value = metrics[key]
        suffix = "%" if "rate" in key else " ms"
        display = "—" if value is None else (
            f"{value * 100:.1f}{suffix}" if "rate" in key else f"{value:.1f}{suffix}"
        )
        column.metric(label, display)
    if metrics["input_tokens"] is not None:
        st.caption(
            f"Tokens: {metrics['input_tokens']} input / {metrics['output_tokens']} output / "
            f"{metrics['thinking_tokens']} thinking · "
            f"Estimated cost: {metrics['estimated_cost'] if metrics['estimated_cost'] is not None else 'unavailable'}"
        )
    left, right = st.columns([1, 1.3])
    with left:
        st.markdown("**Confusion matrix**")
        st.dataframe(report.confusion_matrix, use_container_width=True)
    with right:
        with st.expander("Per-message results"):
            st.dataframe(report.rows, use_container_width=True, hide_index=True)


with evaluate_tab:
    st.subheader("Demo evaluation set")
    st.caption(
        "The bundled set is a smoke benchmark, not evidence of production quality. "
        "Local providers receive one warm-up call before measured inference."
    )
    evaluation_source = st.radio(
        "Dataset", ["Bundled CSV", "Upload CSV"], horizontal=True
    )
    uploaded_csv = None
    if evaluation_source == "Upload CSV":
        uploaded_csv = st.file_uploader("Upload text,expected_intent CSV", type="csv")
    if evaluation_source == "Upload CSV" and uploaded_csv is None:
        evaluation_frame = None
        st.info("Upload a CSV to enable evaluation.")
    else:
        try:
            evaluation_frame = (
                pd.read_csv(uploaded_csv)
                if uploaded_csv is not None
                else pd.read_csv(EVALUATION_PATH)
            )
            evaluation_frame = validate_evaluation_frame(
                evaluation_frame, runtime.taxonomy
            )
            st.caption(f"{len(evaluation_frame)} rows loaded")
        except Exception as exc:
            evaluation_frame = None
            st.error(f"Invalid evaluation data: {exc}")

    selected_providers = st.multiselect(
        "Providers",
        list(evaluation_routes()),
        default=["Rules", "TF-IDF + Logistic Regression", "Semantic Router"],
    )
    llm_providers = {
        "Gemini Structured Output",
        "Hybrid Router",
    } & set(selected_providers)
    estimated_llm_requests = (
        (len(evaluation_frame) + 1) * len(llm_providers)
        if evaluation_frame is not None
        else 0
    )
    acknowledge_cost = True
    if llm_providers:
        st.warning(
            f"Worst case: up to {estimated_llm_requests} Gemini requests including warm-up."
        )
        acknowledge_cost = st.checkbox(
            "I understand this evaluation may consume Gemini API quota."
        )
    can_run = (
        evaluation_frame is not None
        and bool(selected_providers)
        and acknowledge_cost
        and estimated_llm_requests <= 100
    )
    if estimated_llm_requests > 100:
        st.error("Reduce rows or LLM providers; the limit is 100 potential Gemini requests.")
    if st.button("Run evaluation", type="primary", disabled=not can_run):
        reports: list[EvaluationReport] = []
        initialization: dict[str, float] = {}
        routes = evaluation_routes()
        if "Semantic Router" in selected_providers or "Hybrid Router" in selected_providers:
            first_row = evaluation_frame.iloc[0]
            first_request = RouteRequest(
                text=str(first_row["text"]),
                image_count_hint=(
                    1
                    if str(first_row.get("has_image", False)).lower()
                    in {"true", "1", "yes"}
                    else 0
                ),
            )
            initialization_ms, initialization_failure = ensure_semantic_initialized(
                first_request
            )
            if initialization_ms is not None:
                initialization["Semantic model + index"] = initialization_ms
            if initialization_failure is not None:
                st.warning(initialization_failure.error.message)
        progress_bar = st.progress(0.0, text="Starting evaluation...")
        total_steps = len(selected_providers) * len(evaluation_frame)
        completed_before = 0
        for provider in selected_providers:
            report = evaluate_router(
                provider,
                routes[provider],
                evaluation_frame,
                runtime.taxonomy,
                progress=lambda current, total, offset=completed_before: progress_bar.progress(
                    (offset + current) / total_steps,
                    text=f"Evaluating {provider}: {current}/{total}",
                ),
                warmup_calls=1,
            )
            reports.append(report)
            completed_before += len(evaluation_frame)
        progress_bar.empty()
        st.session_state.evaluation_reports = reports
        st.session_state.evaluation_initialization = initialization
    if st.session_state.get("evaluation_initialization"):
        st.caption(
            "Cold initialization: "
            + ", ".join(
                f"{name} {latency:.1f} ms"
                for name, latency in st.session_state.evaluation_initialization.items()
            )
        )
    for report in st.session_state.get("evaluation_reports", []):
        render_report(report)
        st.divider()


with hybrid_tab:
    st.markdown(
        '<div class="flow">Rules → ML + Semantic consensus → Gemini fallback → unknown/degraded</div>',
        unsafe_allow_html=True,
    )
    hybrid_text = st.text_area(
        "User message",
        value="Chuyển ảnh này sang phong cách Ghibli",
        height=100,
        key="hybrid_text",
    )
    hybrid_image = st.file_uploader(
        "Optional image (one JPEG, PNG, or WebP; maximum 10 MB)",
        type=["jpg", "jpeg", "png", "webp"],
        key="hybrid_image",
    )
    if st.button("Run hybrid router", type="primary"):
        try:
            hybrid_request = build_request(hybrid_text, hybrid_image)
        except (ValueError, ValidationError) as exc:
            st.warning(f"Invalid request: {exc}")
        else:
            with st.spinner("Following the hybrid decision policy..."):
                st.session_state.hybrid_result = runtime.hybrid_router.route(
                    hybrid_request,
                    ml_threshold,
                    semantic_threshold,
                    gemini_threshold,
                    float(local_timeout),
                )
    if st.session_state.get("hybrid_result"):
        render_result_card(st.session_state.hybrid_result)
        decision_path = st.session_state.hybrid_result.metadata.get("decision_path", [])
        st.code("\n".join(decision_path), language="text")


with taxonomy_tab:
    st.subheader("Session taxonomy")
    st.caption(
        "Edits are isolated to this browser session. Refreshing or restarting may discard "
        "changes unless you export them. Apply builds a candidate runtime before atomic swap."
    )
    import_column, export_column = st.columns(2)
    with import_column:
        uploaded_taxonomy = st.file_uploader("Import taxonomy JSON", type="json")
        if st.button("Load imported draft", disabled=uploaded_taxonomy is None):
            try:
                imported = Taxonomy.model_validate_json(uploaded_taxonomy.getvalue())
                st.session_state.taxonomy_draft = imported.model_dump(mode="json")
                st.session_state.taxonomy_draft_revision += 1
                st.rerun()
            except (ValidationError, ValueError) as exc:
                st.error(f"Import failed validation: {exc}")
    with export_column:
        st.download_button(
            "Export active taxonomy",
            data=dump_taxonomy(runtime.taxonomy),
            file_name="intents.json",
            mime="application/json",
            use_container_width=True,
        )

    draft = st.session_state.taxonomy_draft
    draft_revision = st.session_state.taxonomy_draft_revision
    if st.button("Add intent"):
        draft["intents"].append(
            {
                "name": f"new_intent_{len(draft['intents'])}",
                "parent": None,
                "prompt_section": "Describe when the classifier should select this intent",
                "examples": ["Add a training example"],
                "image_examples": [],
                "patterns": [],
                "required_context": None,
                "rule_priority": 0,
                "properties": {},
            }
        )
        st.session_state.taxonomy_draft_revision += 1
        st.rerun()

    with st.form("taxonomy_editor"):
        edited_intents = []
        delete_indexes: set[int] = set()
        for index, intent in enumerate(draft["intents"]):
            with st.expander(intent["name"], expanded=index == 0):
                name = st.text_input(
                    "Name", intent["name"], key=f"name_{draft_revision}_{index}"
                )
                parent_options = [None] + [
                    item["name"]
                    for item in draft["intents"]
                    if item["name"] not in {intent["name"], "unknown"}
                ]
                current_parent = intent.get("parent")
                parent = st.selectbox(
                    "Parent intent",
                    parent_options,
                    index=(
                        parent_options.index(current_parent)
                        if current_parent in parent_options
                        else 0
                    ),
                    key=f"parent_{draft_revision}_{index}",
                    disabled=name == "unknown",
                )
                prompt_section = st.text_area(
                    "Prompt section",
                    intent["prompt_section"],
                    key=f"prompt_section_{draft_revision}_{index}",
                )
                examples = st.text_area(
                    "Training examples (one per line)",
                    "\n".join(intent.get("examples", [])),
                    height=180,
                    key=f"examples_{draft_revision}_{index}",
                )
                image_examples = st.text_area(
                    "Examples with an attached image (one per line)",
                    "\n".join(intent.get("image_examples", [])),
                    height=140,
                    key=f"image_examples_{draft_revision}_{index}",
                )
                patterns = st.text_area(
                    "Regex rules (one per line)",
                    "\n".join(intent.get("patterns", [])),
                    height=120,
                    key=f"patterns_{draft_revision}_{index}",
                    disabled=name == "unknown",
                )
                required_context = st.selectbox(
                    "Required execution context",
                    [None, "image"],
                    index=1 if intent.get("required_context") == "image" else 0,
                    key=f"required_context_{draft_revision}_{index}",
                    disabled=name == "unknown",
                )
                rule_priority = st.number_input(
                    "Rule priority",
                    min_value=0,
                    max_value=1_000,
                    value=int(intent.get("rule_priority", 0)),
                    key=f"rule_priority_{draft_revision}_{index}",
                    disabled=name == "unknown",
                )
                properties_json = st.text_area(
                    "Conditional properties (JSON object)",
                    json.dumps(
                        intent.get("properties", {}), ensure_ascii=False, indent=2
                    ),
                    height=180,
                    key=f"properties_{draft_revision}_{index}",
                    disabled=name == "unknown",
                )
                delete = st.checkbox(
                    "Delete this intent",
                    key=f"delete_{draft_revision}_{index}",
                    disabled=name == "unknown",
                )
                if delete:
                    delete_indexes.add(index)
                edited_intents.append(
                    {
                        "name": name,
                        "parent": parent,
                        "prompt_section": prompt_section,
                        "examples": [line for line in examples.splitlines() if line.strip()],
                        "image_examples": [
                            line for line in image_examples.splitlines() if line.strip()
                        ],
                        "patterns": [line for line in patterns.splitlines() if line.strip()],
                        "required_context": required_context,
                        "rule_priority": int(rule_priority),
                        "properties_json": properties_json,
                    }
                )
        apply_taxonomy = st.form_submit_button(
            "Validate & Apply", type="primary", use_container_width=True
        )
    if apply_taxonomy:
        try:
            candidate_intents = []
            for index, intent in enumerate(edited_intents):
                if index in delete_indexes:
                    continue
                candidate = dict(intent)
                candidate["properties"] = json.loads(
                    candidate.pop("properties_json") or "{}"
                )
                candidate_intents.append(candidate)
            candidate_payload = {"intents": candidate_intents}
            candidate_taxonomy = Taxonomy.model_validate(candidate_payload)
            sparse = [
                intent.name
                for intent in candidate_taxonomy.known_intents
                if len(intent.examples) + len(intent.image_examples) < 10
            ]
            candidate_runtime = build_runtime_state(
                candidate_taxonomy,
                model_path=None,
                semantic_model_name=st.session_state.semantic_model_name,
                gemini_model_name=st.session_state.gemini_model_name,
                gemini_timeout_seconds=float(gemini_timeout),
            )
            st.session_state.runtime = candidate_runtime
            st.session_state.taxonomy_draft = candidate_taxonomy.model_dump(mode="json")
            st.session_state.taxonomy_draft_revision += 1
            clear_result_state()
            if sparse:
                st.warning(
                    "Applied, but these intents have fewer than 10 examples: "
                    + ", ".join(sparse)
                )
            else:
                st.success("Taxonomy validated and applied atomically.")
            st.rerun()
        except (ValidationError, ValueError, RuntimeError) as exc:
            st.error(f"Candidate rejected; the active runtime is unchanged: {exc}")

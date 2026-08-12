from __future__ import annotations

import ast
from pathlib import Path

from reference_runtime.contracts import (
    Message,
    Outcome,
    RequestContext,
    RoutingRequest,
    Tool,
    ToolFunction,
)
from reference_runtime.registry import registry_with_archived_active
from reference_runtime.router.fake import FakeRouterProvider
from reference_runtime.runtime import ReferenceRouter


ROOT = Path(__file__).resolve().parents[2]

DEFAULT_TOOLS = [
    Tool(function=ToolFunction(name=n))
    for n in [
        "deep_research",
        "generate_poster",
        "generate_logo",
        "generate_flyer",
        "create_ai_art",
        "image_to_image_generation",
        "chat_with_image",
        "real_time_search",
        "creative",
    ]
]


def _request(text: str, turn_count: int = 0, *, tools: list[Tool] | None = None) -> RoutingRequest:
    return RoutingRequest(
        messages=[Message(role="user", content=text)],
        tools=list(DEFAULT_TOOLS if tools is None else tools),
        context=RequestContext(clarification_turn_count=turn_count),
    )


class CountingClassifier:
    def __init__(self, delegate):
        self.delegate = delegate
        self.calls = 0
        self.name = delegate.name
        self.model = delegate.model

    def classify(self, request):
        self.calls += 1
        return self.delegate.classify(request)

    def route(self, request):
        return self.classify(request)


class CountingPreRouter:
    def __init__(self, delegate):
        self.delegate = delegate
        self.calls = 0
        self.rule_version = delegate.rule_version

    def evaluate(self, text, forms=None):
        self.calls += 1
        return self.delegate.evaluate(text, forms=forms)


def test_runtime_module_never_imports_capability_simulator():
    source = (ROOT / "reference_runtime" / "runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    assert not any("capability_simulator" in name for name in imported_modules)


def test_runtime_local_import_graph_cannot_reach_capability_simulator():
    pending = ["reference_runtime", "reference_runtime.runtime"]
    visited: set[str] = set()
    while pending:
        module = pending.pop()
        if module in visited:
            continue
        visited.add(module)
        relative = module.removeprefix("reference_runtime").lstrip(".")
        path = (
            ROOT / "reference_runtime" / "__init__.py"
            if not relative
            else ROOT / "reference_runtime" / f"{relative.replace('.', '/')}.py"
        )
        if not path.exists():
            package_init = ROOT / "reference_runtime" / relative.replace(".", "/") / "__init__.py"
            if not package_init.exists():
                continue
            path = package_init
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]
            else:
                continue
            pending.extend(name for name in imported if name.startswith("reference_runtime"))

    assert "reference_runtime.capability_simulator" not in visited


def test_reject_short_circuits_pre_router_and_router():
    from reference_runtime.pre_router import PreRouterEngine

    pre_router = CountingPreRouter(PreRouterEngine())
    classifier = CountingClassifier(FakeRouterProvider())
    router = ReferenceRouter(classifier=classifier, pre_router=pre_router, registry=registry_with_archived_active())

    result = router.route(_request("This is a CSAM_TEST_FIXTURE message"))

    assert result.response.outcome == Outcome.REJECT
    assert result.response.response_text
    assert pre_router.calls == 0
    assert classifier.calls == 0
    assert result.trace.policy.decision == "block"
    assert result.trace.policy.matched_surface == "canonical"
    assert result.trace.router_decision is None
    assert result.trace.final_reason_code == "POLICY_VIOLATION"
    assert result.trace.canonical_text is not None
    assert result.trace.normalized_text is not None
    assert "csam" in result.trace.normalized_text


def test_allowed_request_reaches_pre_router_and_router():
    from reference_runtime.pre_router import PreRouterEngine

    pre_router = CountingPreRouter(PreRouterEngine())
    classifier = CountingClassifier(FakeRouterProvider())
    router = ReferenceRouter(classifier=classifier, pre_router=pre_router, registry=registry_with_archived_active())

    result = router.route(_request("Tạo poster cho đêm nhạc"))

    assert result.trace.policy.decision == "allow"
    assert pre_router.calls == 1
    assert classifier.calls == 1
    assert result.response.outcome == Outcome.ROUTE
    assert result.response.name == "generate_poster"


def test_pre_router_hit_produces_response_without_calling_router():
    classifier = CountingClassifier(FakeRouterProvider())
    router = ReferenceRouter(classifier=classifier, registry=registry_with_archived_active())

    result = router.route(_request("Xin chào"))

    assert result.response.outcome == Outcome.RESPONSE
    assert result.response.response_text
    assert classifier.calls == 0
    assert result.trace.pre_router_hit is True
    assert result.trace.final_reason_code.startswith("PREROUTER_STATIC_")


def test_exactly_one_outcome_and_no_public_confidence_or_dependency_graph():
    router = ReferenceRouter(classifier=FakeRouterProvider(), registry=registry_with_archived_active())
    result = router.route(_request("Nghiên cứu xu hướng cà phê rồi tạo poster"))

    assert isinstance(result.response.outcome, Outcome)
    assert "confidence" not in type(result.response).model_fields
    assert "dependencies" not in type(result.response).model_fields
    assert "goals" not in type(result.response).model_fields
    assert "reason_code" not in type(result.response).model_fields
    assert result.trace.router_decision.dependencies


def test_route_has_exactly_one_executable_intent():
    router = ReferenceRouter(classifier=FakeRouterProvider(), registry=registry_with_archived_active())
    result = router.route(_request("Tạo logo cho quán cà phê"))
    assert result.response.outcome == Outcome.ROUTE
    assert isinstance(result.response.name, str) and result.response.name


def test_empty_tools_cannot_route():
    router = ReferenceRouter(classifier=FakeRouterProvider(), registry=registry_with_archived_active())
    result = router.route(_request("Tạo logo cho quán cà phê", tools=[]))
    assert result.response.outcome == Outcome.FALLBACK
    assert result.trace.final_reason_code == "UNSUPPORTED_CAPABILITY"


def test_clarification_limit_reached_end_to_end():
    router = ReferenceRouter(classifier=FakeRouterProvider(), registry=registry_with_archived_active())
    result = router.route(_request("Chuyển ảnh sang phong cách khác lạ chưa biết", turn_count=3))
    assert result.response.outcome in (Outcome.CLARIFY, Outcome.FALLBACK)


def test_clarification_limit_reached_forces_fallback_for_missing_style():
    from reference_runtime.contracts import Media

    router = ReferenceRouter(classifier=FakeRouterProvider(), registry=registry_with_archived_active())
    request = RoutingRequest(
        messages=[
            Message(
                role="user",
                content="Chuyển ảnh này sang phong cách khác",
                files=[Media(mime_type="image/png", data="ZmFrZQ==", filename="a.png")],
            )
        ],
        tools=list(DEFAULT_TOOLS),
        context=RequestContext(clarification_turn_count=3),
    )
    result = router.route(request)
    assert result.response.outcome == Outcome.FALLBACK
    assert result.trace.final_reason_code == "CLARIFICATION_LIMIT_REACHED"


def test_stage_trace_and_latency_are_recorded():
    router = ReferenceRouter(classifier=FakeRouterProvider(), registry=registry_with_archived_active())
    result = router.route(_request("Tạo poster cho đêm nhạc"))
    stage_names = [stage.stage for stage in result.trace.stages]
    assert stage_names == ["normalize", "policy_gate", "pre_router", "router", "validator"]
    assert result.trace.total_latency_ms >= 0

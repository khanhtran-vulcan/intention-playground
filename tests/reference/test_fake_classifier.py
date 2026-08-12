from __future__ import annotations

from reference_runtime.contracts import Media, Message, Outcome, RoutingRequest, Tool, ToolFunction
from reference_runtime.router.fake import FakeRouterProvider


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


def _request(text: str, *, with_image: bool = False, capability_history: list[Message] | None = None) -> RoutingRequest:
    messages = list(capability_history or [])
    files = (
        [Media(mime_type="image/png", data="ZmFrZQ==", filename="a.png")]
        if with_image
        else []
    )
    messages.append(Message(role="user", content=text, files=files))
    return RoutingRequest(messages=messages, tools=list(DEFAULT_TOOLS))


def test_coffee_scenario_selects_deep_research_with_dependency_edge():
    classifier = FakeRouterProvider()
    candidate = classifier.classify(_request("Nghiên cứu xu hướng cà phê rồi tạo poster"))
    assert candidate.selected_intent == "deep_research"
    assert candidate.reason_code == "NEXT_EXECUTABLE_PREREQUISITE"
    assert candidate.arguments["final_prompt"]
    assert any(
        edge.intent == "generate_poster" and edge.depends_on == "deep_research"
        for edge in candidate.dependencies
    )


def test_independent_intents_selected_by_explicit_order():
    classifier = FakeRouterProvider()
    candidate = classifier.classify(_request("Tìm tin mới và tạo ảnh một con mèo"))
    assert candidate.selected_intent == "real_time_search"
    assert candidate.reason_code == "EXPLICIT_ORDER_PRIORITY"
    assert set(candidate.candidate_intents) == {"real_time_search", "create_ai_art"}


def test_deep_research_then_illustration_selects_research_first():
    classifier = FakeRouterProvider()
    candidate = classifier.classify(
        _request("deep research về giá vàng hôm nay, rồi tạo cho tôi hình ảnh minh hoạ")
    )
    assert candidate.selected_intent == "deep_research"
    assert candidate.reason_code == "MULTI_INTENT_SEQUENCE"
    assert set(candidate.candidate_intents) == {"deep_research", "create_ai_art"}
    assert candidate.arguments.get("final_prompt")


def test_dependency_already_satisfied_routes_directly_to_poster():
    classifier = FakeRouterProvider()
    history = [
        Message(
            role="capability",
            content="Tôi đã tổng hợp các xu hướng cà phê nổi bật.",
            capability_name="deep_research",
            artifact_type="research_summary",
        )
    ]
    candidate = classifier.classify(
        _request("Tạo poster từ kết quả research vừa rồi", capability_history=history)
    )
    assert candidate.selected_intent == "generate_poster"
    assert candidate.reason_code == "DEPENDENCY_ALREADY_SATISFIED"
    assert candidate.dependencies == []


def test_cyclic_dependency_fixture():
    classifier = FakeRouterProvider()
    candidate = classifier.classify(
        _request(
            "Tạo demo minh hoạ vòng lặp phụ thuộc giữa nghiên cứu và hình minh họa"
        )
    )
    assert candidate.selected_intent is None
    assert candidate.reason_code == "CYCLIC_DEPENDENCY"
    edges = {(edge.intent, edge.depends_on) for edge in candidate.dependencies}
    assert ("create_ai_art", "deep_research") in edges
    assert ("deep_research", "create_ai_art") in edges


def test_unsupported_prerequisite_fixture():
    classifier = FakeRouterProvider()
    candidate = classifier.classify(
        _request("Tạo hình minh họa dựa trên báo cáo tài chính nội bộ")
    )
    assert candidate.selected_intent is None
    assert candidate.reason_code == "UNSUPPORTED_PREREQUISITE"
    assert candidate.dependencies[0].depends_on == "UNSUPPORTED_PREREQUISITE"


def test_missing_reference_generic_is_dependency_ambiguous():
    classifier = FakeRouterProvider()
    candidate = classifier.classify(_request("Tạo hình minh họa từ báo cáo chưa tồn tại"))
    assert candidate.selected_intent is None
    assert candidate.missing_inputs == ["dependency_reference"]
    assert candidate.reason_code == "DEPENDENCY_REFERENCE_AMBIGUOUS"


def test_create_vs_edit_ambiguity():
    classifier = FakeRouterProvider()
    candidate = classifier.classify(_request("Làm cho ảnh này đẹp hơn", with_image=True))
    assert candidate.selected_intent is None
    assert candidate.missing_inputs == ["create_or_edit_choice"]
    assert set(candidate.candidate_intents) == {"create_ai_art", "image_to_image_generation"}


def test_style_transform_with_image_and_style():
    classifier = FakeRouterProvider()
    candidate = classifier.classify(
        _request("Chuyển ảnh này sang phong cách Ghibli", with_image=True)
    )
    assert candidate.selected_intent == "image_to_image_generation"
    assert candidate.arguments["style"] == "ghibli"
    assert candidate.missing_inputs == []


def test_style_transform_with_image_missing_style():
    classifier = FakeRouterProvider()
    candidate = classifier.classify(_request("Chuyển ảnh này sang phong cách khác", with_image=True))
    assert candidate.proposed_outcome.value == "CLARIFY"
    assert candidate.selected_intent is None
    assert candidate.candidate_intents == ["image_to_image_generation"]
    assert candidate.missing_inputs == ["style"]


def test_style_transform_without_image_is_missing_image():
    classifier = FakeRouterProvider()
    candidate = classifier.classify(_request("Chuyển ảnh sang phong cách anime"))
    assert candidate.proposed_outcome.value == "CLARIFY"
    assert candidate.selected_intent == "image_to_image_generation"
    assert candidate.missing_inputs == ["image"]


def test_chat_with_image_present():
    classifier = FakeRouterProvider()
    candidate = classifier.classify(_request("Ảnh này có gì?", with_image=True))
    assert candidate.selected_intent == "chat_with_image"
    assert candidate.missing_inputs == []


def test_chat_with_image_missing_image():
    classifier = FakeRouterProvider()
    candidate = classifier.classify(_request("Ảnh này có gì?"))
    assert candidate.proposed_outcome.value == "CLARIFY"
    assert candidate.selected_intent is None
    assert candidate.candidate_intents == ["chat_with_image"]
    assert candidate.missing_inputs == ["image"]


def test_single_capability_intents():
    classifier = FakeRouterProvider()
    assert classifier.classify(_request("Tạo logo cho quán cà phê")).selected_intent == "generate_logo"
    assert classifier.classify(_request("Tạo flyer quảng cáo khóa học")).selected_intent == "generate_flyer"
    assert classifier.classify(_request("Tạo poster cho đêm nhạc")).selected_intent == "generate_poster"
    assert (
        classifier.classify(_request("Giá vàng lúc 9 giờ sáng")).selected_intent == "real_time_search"
    )
    assert (
        classifier.classify(_request("Vẽ một chú mèo phi hành gia")).selected_intent == "create_ai_art"
    )


def test_creative_generic_is_ambiguous_type():
    classifier = FakeRouterProvider()
    candidate = classifier.classify(_request("Tôi cần một creative asset cho chiến dịch"))
    assert candidate.selected_intent == "creative"
    assert candidate.missing_inputs == ["creative_type"]


def test_general_reasoning_maps_to_direct_response():
    classifier = FakeRouterProvider()
    candidate = classifier.route(_request("Kể cho tôi một câu chuyện"))
    assert candidate.proposed_outcome == Outcome.RESPONSE
    assert candidate.response_text
    assert candidate.reason_code == "ROUTER_DIRECT_RESPONSE"


def test_default_unknown():
    classifier = FakeRouterProvider()
    candidate = classifier.classify(_request("asdkjq09u123"))
    assert candidate.selected_intent == "unknown"
    assert candidate.reason_code == "UNKNOWN_INTENT"

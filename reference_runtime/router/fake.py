"""Deterministic, offline Structured LLM Router fixture."""

from __future__ import annotations

import regex

from reference_runtime.contracts import (
    DependencyEdge,
    Outcome,
    RouterDecisionTrace,
    RoutingRequest,
)
from reference_runtime.pre_router import normalize as fold_normalize
from reference_runtime.registry_loader import PROMPT_VERSION, registry_version


_KEYWORDS: dict[str, tuple[str, ...]] = {
    "research": (
        "nghien cuu",
        "research",
        "deep research",
        "deep reserch",
        "nghiên cứu",
    ),
    "poster": ("poster", "ap phich"),
    "logo": ("logo",),
    "flyer": ("flyer", "to roi", "leaflet", "to buom"),
    "create_art": (
        "ve mot",
        "ve chu",
        "ve robot",
        "tao anh",
        "sinh anh",
        "lam anh ai",
        "minh hoa",
        "hinh anh minh hoa",
        "artwork",
        "illustration",
        "tranh",
        "digital art",
    ),
    "style_transform": (
        "phong cach",
        "style",
        "chuyen anh",
        "chuyen buc",
        "bien anh",
        "bien hinh",
        "restyle",
        "chuyen sang",
        "doi sang",
    ),
    "search": (
        "thoi tiet",
        "ty gia",
        "tin tuc",
        "tim tin",
        "tin moi",
        "gia vang",
        "gia bitcoin",
        "gia co phieu",
        "ket qua xo so",
        "hien tai",
        "hom nay",
        "moi nhat",
        "weather",
        "stock market",
        "right now",
    ),
    "chat_image": (
        "anh nay co gi",
        "mo ta anh",
        "mo ta buc anh",
        "bao nhieu nguoi trong",
        "describe this image",
        "noi dung anh",
        "noi dung hinh",
    ),
    "creative_generic": (
        "thiet ke sang tao",
        "an pham dep",
        "san pham do hoa",
        "visual moi",
        "creative asset",
        "creative design",
        "noi dung hinh anh nhung chua biet loai nao",
    ),
    "create_or_edit_ambiguous": (
        "lam no dep hon",
        "lam dep hon",
        "lam cho anh nay dep hon",
        "improve this",
        "make it better",
    ),
    "cyclic_demo_fixture": ("vong lap phu thuoc",),
    "unsupported_prerequisite_fixture": ("bao cao tai chinh noi bo",),
    "missing_reference_generic": (
        "bao cao chua ton tai",
        "ket qua chua co",
        "nghien cuu chua co ket qua",
    ),
    "general_reasoning": (
        "ke cho toi",
        "tell me a story",
        "dich cau nay",
        "translate this",
        "giai phuong trinh",
        "viet email",
        "tom tat doan van",
        "ban ten la gi",
        "la gi",
        "what is",
        "what are",
        "jwt",
    ),
}

_STYLE_ALIASES: dict[str, str] = {
    "ghibli": "ghibli",
    "anime": "anime",
    "disney": "disney",
    "manga": "manga",
    "one piece": "one_piece",
    "naruto": "naruto",
    "dragon ball": "dragon_ball",
    "bleach": "bleach",
    "attack on titan": "attack_on_titan",
    "demon slayer": "demon_slayer",
    "doraemon": "doraemon",
    "sailor moon": "sailor_moon",
    "simpson": "the_simpson",
    "rick and morty": "rick_and_morty",
    "south park": "south_park",
    "genshin": "genshin_impact",
}

_TOPIC_SPLIT_PATTERN = regex.compile(r"\b(roi|sau do|then)\b", regex.IGNORECASE)
_TOPIC_LEADING_VERB_PATTERN = regex.compile(r"^\s*(nghien cuu|research)\s+", regex.IGNORECASE)

_DIRECT_RESPONSE_TEXT = (
    "Demo: đây là câu trả lời trực tiếp cho câu hỏi chung (reference fixture)."
)


def _mentions(text: str, keys: tuple[str, ...]) -> bool:
    return any(key in text for key in keys)


def _first_match_index(text: str, keys: tuple[str, ...]) -> int:
    positions = [text.find(key) for key in keys if key in text]
    return min(positions) if positions else -1


def _prior_capability_result(request: RoutingRequest, capability_name: str) -> bool:
    return any(
        message.role == "capability" and message.capability_name == capability_name
        for message in request.messages
    )


def _extract_topic(raw_text: str) -> str:
    folded = fold_normalize(raw_text)
    match = _TOPIC_SPLIT_PATTERN.search(folded)
    if match is None:
        topic_source = raw_text.strip()
    else:
        cut_words = len(folded[: match.start()].split())
        topic_source = " ".join(raw_text.split()[:cut_words]).strip()
    topic_source = _TOPIC_LEADING_VERB_PATTERN.sub("", fold_normalize(topic_source))
    return topic_source.strip().rstrip(",.;:") or raw_text.strip()


def _extract_style(folded_text: str) -> str | None:
    for alias, style in _STYLE_ALIASES.items():
        if alias in folded_text:
            return style
    return None


class FakeRouterProvider:
    name = "Deterministic Fake Router"
    model = "fake-router-v1"

    def route(self, request: RoutingRequest) -> RouterDecisionTrace:
        return self.classify(request)

    def classify(self, request: RoutingRequest) -> RouterDecisionTrace:
        message = request.latest_user_message
        raw_text = (message.content if message else "") or ""
        text = fold_normalize(raw_text)
        has_image = request.has_images_in_latest_user_turn()

        if _mentions(text, _KEYWORDS["cyclic_demo_fixture"]):
            return self._decision(
                proposed_outcome=Outcome.FALLBACK,
                goals=["demonstrate a cyclic dependency fixture"],
                candidate_intents=["create_ai_art", "deep_research"],
                dependencies=[
                    DependencyEdge(intent="create_ai_art", depends_on="deep_research"),
                    DependencyEdge(intent="deep_research", depends_on="create_ai_art"),
                ],
                reason_code="CYCLIC_DEPENDENCY",
            )

        if _mentions(text, _KEYWORDS["unsupported_prerequisite_fixture"]) and _mentions(
            text, _KEYWORDS["create_art"]
        ):
            return self._decision(
                proposed_outcome=Outcome.FALLBACK,
                goals=["create an illustration from an unsupported prerequisite"],
                candidate_intents=["create_ai_art"],
                dependencies=[
                    DependencyEdge(intent="create_ai_art", depends_on="UNSUPPORTED_PREREQUISITE")
                ],
                reason_code="UNSUPPORTED_PREREQUISITE",
            )

        if _mentions(text, _KEYWORDS["missing_reference_generic"]) and _mentions(
            text, _KEYWORDS["create_art"]
        ):
            return self._decision(
                proposed_outcome=Outcome.CLARIFY,
                goals=["create an illustration referencing an unresolved research result"],
                candidate_intents=["create_ai_art", "deep_research"],
                dependencies=[DependencyEdge(intent="create_ai_art", depends_on="deep_research")],
                missing_inputs=["dependency_reference"],
                reason_code="DEPENDENCY_REFERENCE_AMBIGUOUS",
            )

        wants_research = _mentions(text, _KEYWORDS["research"])
        wants_poster = _mentions(text, _KEYWORDS["poster"])
        if wants_research and wants_poster:
            if _prior_capability_result(request, "deep_research"):
                return self._decision(
                    proposed_outcome=Outcome.ROUTE,
                    goals=["create a poster from the earlier research result"],
                    candidate_intents=["generate_poster"],
                    selected_intent="generate_poster",
                    reason_code="DEPENDENCY_ALREADY_SATISFIED",
                )
            return self._decision(
                proposed_outcome=Outcome.ROUTE,
                goals=["research the topic", "create a poster from the research"],
                candidate_intents=["deep_research", "generate_poster"],
                dependencies=[DependencyEdge(intent="generate_poster", depends_on="deep_research")],
                selected_intent="deep_research",
                arguments={"final_prompt": _extract_topic(raw_text)},
                reason_code="NEXT_EXECUTABLE_PREREQUISITE",
            )

        if (
            wants_poster
            and _prior_capability_result(request, "deep_research")
            and _mentions(text, ("ket qua", "nghien cuu", "vua roi", "o tren", "research"))
        ):
            return self._decision(
                proposed_outcome=Outcome.ROUTE,
                goals=["create a poster from the earlier research result"],
                candidate_intents=["generate_poster"],
                selected_intent="generate_poster",
                reason_code="DEPENDENCY_ALREADY_SATISFIED",
            )

        wants_search = _mentions(text, _KEYWORDS["search"])
        wants_create_art = _mentions(text, _KEYWORDS["create_art"])
        wants_research = _mentions(text, _KEYWORDS["research"])

        # Explicit deep-research + create-image: research is the next executable step.
        if wants_research and wants_create_art:
            if _prior_capability_result(request, "deep_research"):
                return self._decision(
                    proposed_outcome=Outcome.ROUTE,
                    goals=["create an illustration from the earlier research result"],
                    candidate_intents=["create_ai_art"],
                    selected_intent="create_ai_art",
                    arguments={"prompt": _truncate_words(raw_text, 25)},
                    reason_code="DEPENDENCY_ALREADY_SATISFIED",
                )
            return self._decision(
                proposed_outcome=Outcome.ROUTE,
                goals=["research the topic", "create an illustration from the research"],
                candidate_intents=["deep_research", "create_ai_art"],
                selected_intent="deep_research",
                arguments={"final_prompt": _extract_topic(raw_text)},
                reason_code="MULTI_INTENT_SEQUENCE",
            )

        if wants_search and wants_create_art and not wants_research:
            search_index = _first_match_index(text, _KEYWORDS["search"])
            art_index = _first_match_index(text, _KEYWORDS["create_art"])
            selected = "real_time_search" if search_index <= art_index else "create_ai_art"
            arguments = {"prompt": _truncate_words(raw_text, 25)} if selected == "create_ai_art" else {}
            return self._decision(
                proposed_outcome=Outcome.ROUTE,
                goals=["find recent information", "create a new image"],
                candidate_intents=["real_time_search", "create_ai_art"],
                selected_intent=selected,
                arguments=arguments,
                reason_code="EXPLICIT_ORDER_PRIORITY",
            )

        if wants_research:
            return self._decision(
                proposed_outcome=Outcome.ROUTE,
                goals=["research the topic"],
                candidate_intents=["deep_research"],
                selected_intent="deep_research",
                arguments={"final_prompt": _extract_topic(raw_text)},
                reason_code="EXPLICIT_SINGLE_CAPABILITY",
            )

        if wants_poster:
            return self._decision(
                proposed_outcome=Outcome.ROUTE,
                goals=["create a poster"],
                candidate_intents=["generate_poster"],
                selected_intent="generate_poster",
                reason_code="EXPLICIT_SINGLE_CAPABILITY",
            )

        if _mentions(text, _KEYWORDS["logo"]):
            return self._decision(
                proposed_outcome=Outcome.ROUTE,
                goals=["create a logo"],
                candidate_intents=["generate_logo"],
                selected_intent="generate_logo",
                reason_code="EXPLICIT_SINGLE_CAPABILITY",
            )

        if _mentions(text, _KEYWORDS["flyer"]):
            return self._decision(
                proposed_outcome=Outcome.ROUTE,
                goals=["create a flyer"],
                candidate_intents=["generate_flyer"],
                selected_intent="generate_flyer",
                reason_code="EXPLICIT_SINGLE_CAPABILITY",
            )

        if _mentions(text, _KEYWORDS["create_or_edit_ambiguous"]) and not _mentions(
            text, _KEYWORDS["style_transform"]
        ):
            return self._decision(
                proposed_outcome=Outcome.CLARIFY,
                goals=["clarify whether to create a new image or edit the attached one"],
                candidate_intents=["create_ai_art", "image_to_image_generation"],
                missing_inputs=["create_or_edit_choice"],
                reason_code="CREATE_VS_EDIT_AMBIGUOUS",
            )

        if _mentions(text, _KEYWORDS["style_transform"]):
            style = _extract_style(text)
            if has_image:
                arguments = {"style": style} if style else {}
                return self._decision(
                    proposed_outcome=Outcome.ROUTE if style else Outcome.CLARIFY,
                    goals=["transform the attached image into a requested style"],
                    candidate_intents=["image_to_image_generation"],
                    selected_intent="image_to_image_generation" if style else None,
                    arguments=arguments,
                    missing_inputs=[] if style else ["style"],
                    reason_code="EXPLICIT_SINGLE_CAPABILITY" if style else "MISSING_STYLE",
                )
            return self._decision(
                proposed_outcome=Outcome.CLARIFY,
                goals=["transform an image into a requested style"],
                candidate_intents=["image_to_image_generation"],
                selected_intent="image_to_image_generation",
                arguments={"style": style} if style else {},
                missing_inputs=["image"],
                reason_code="MISSING_REQUIRED_IMAGE",
            )

        if _mentions(text, _KEYWORDS["chat_image"]):
            return self._decision(
                proposed_outcome=Outcome.ROUTE if has_image else Outcome.CLARIFY,
                goals=["describe the attached image"],
                candidate_intents=["chat_with_image"],
                selected_intent="chat_with_image" if has_image else None,
                missing_inputs=[] if has_image else ["image"],
                reason_code="EXPLICIT_SINGLE_CAPABILITY" if has_image else "MISSING_REQUIRED_IMAGE",
            )

        if wants_search:
            return self._decision(
                proposed_outcome=Outcome.ROUTE,
                goals=["answer using live information"],
                candidate_intents=["real_time_search"],
                selected_intent="real_time_search",
                reason_code="EXPLICIT_SINGLE_CAPABILITY",
            )

        if wants_create_art:
            return self._decision(
                proposed_outcome=Outcome.ROUTE,
                goals=["create a new illustration"],
                candidate_intents=["create_ai_art"],
                selected_intent="create_ai_art",
                arguments={"prompt": _truncate_words(raw_text, 25)},
                reason_code="EXPLICIT_SINGLE_CAPABILITY",
            )

        if _mentions(text, _KEYWORDS["creative_generic"]):
            return self._decision(
                proposed_outcome=Outcome.CLARIFY,
                goals=["create an unspecified creative asset"],
                candidate_intents=["creative"],
                selected_intent="creative",
                missing_inputs=["creative_type"],
                reason_code="AMBIGUOUS_CREATIVE_TYPE",
            )

        if _mentions(text, _KEYWORDS["general_reasoning"]):
            return self._decision(
                proposed_outcome=Outcome.RESPONSE,
                response_text=_DIRECT_RESPONSE_TEXT,
                reason_code="ROUTER_DIRECT_RESPONSE",
            )

        return self._decision(
            proposed_outcome=Outcome.FALLBACK,
            goals=[],
            candidate_intents=["unknown"],
            selected_intent="unknown",
            reason_code="UNKNOWN_INTENT",
        )

    def _decision(
        self,
        *,
        proposed_outcome: Outcome,
        reason_code: str,
        goals: list[str] | None = None,
        candidate_intents: list[str] | None = None,
        selected_intent: str | None = None,
        dependencies: list[DependencyEdge] | None = None,
        arguments: dict[str, str] | None = None,
        missing_inputs: list[str] | None = None,
        response_text: str | None = None,
    ) -> RouterDecisionTrace:
        return RouterDecisionTrace(
            provider=self.name,
            model=self.model,
            proposed_outcome=proposed_outcome,
            response_text=response_text,
            goals=goals or [],
            candidate_intents=candidate_intents or [],
            dependencies=dependencies or [],
            selected_intent=selected_intent,
            arguments=arguments or {},
            missing_inputs=missing_inputs or [],
            reason_code=reason_code,
            prompt_version=PROMPT_VERSION,
            registry_version=registry_version(),
        )


FakeClassifierProvider = FakeRouterProvider


def _truncate_words(text: str, max_words: int) -> str:
    return " ".join(text.split()[:max_words])

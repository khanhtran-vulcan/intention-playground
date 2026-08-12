"""Deterministic Pre-router: exact full-message static RESPONSE only (0 LLM).

Semantic informational requests always miss and flow to the Structured LLM Router.
Explicit client mode / high-precision regex route rules are out of V1 scope.

Text surfaces (do not treat as interchangeable):

- ``raw`` — original user text
- ``canonical`` — NFKC + casefold + punctuation→space + collapse whitespace
  (accents preserved). Primary surface for Policy Gate and Pre-router.
- ``folded`` — canonical + Vietnamese accent fold (lossy). Pre-router uses
  folded as a fallback **only when the input had no accents**
  (``canonical == folded``), so distinct words like ``cháo`` vs ``chào``
  do not collide. Policy rules may opt into folded explicitly.

``normalize()`` is a backward-compatible alias for the folded surface.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass

from reference_runtime.contracts import Outcome


RULE_VERSION = "pre-router-v2"

# Punctuation / symbols / underscore → space, then collapse whitespace.
# ``_`` is a ``\w`` character in Python Unicode regex, so include it explicitly.
_PUNCT_TO_SPACE = re.compile(r"[\W_]+", flags=re.UNICODE)
_COLLAPSE_WS = re.compile(r"\s+")


def _fold_diacritics(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _punct_to_space_and_collapse(text: str) -> str:
    text = _PUNCT_TO_SPACE.sub(" ", text)
    return _COLLAPSE_WS.sub(" ", text).strip()


def canonical_text(text: str) -> str:
    """NFKC + casefold + punctuation→space + collapse whitespace (accents kept)."""
    normalized = unicodedata.normalize("NFKC", text or "").strip().casefold()
    return _punct_to_space_and_collapse(normalized)


def folded_text(text: str) -> str:
    """Canonical pipeline plus Vietnamese accent fold (lossy)."""
    # Fold before punct→space so diacritic marks are stripped from letters first.
    normalized = unicodedata.normalize("NFKC", text or "").strip().casefold()
    normalized = _fold_diacritics(normalized)
    return _punct_to_space_and_collapse(normalized)


@dataclass(frozen=True)
class NormalizedForms:
    raw: str
    canonical: str
    folded: str


def normalize_forms(text: str) -> NormalizedForms:
    raw = text or ""
    return NormalizedForms(
        raw=raw,
        canonical=canonical_text(raw),
        folded=folded_text(raw),
    )


def normalize(text: str) -> str:
    """Folded surface alias for Fake router / legacy callers."""
    return folded_text(text)


@dataclass(frozen=True)
class StaticRule:
    rule_id: str
    # Accent-preserving phrases (and ASCII phrases identical on both surfaces).
    canonical_matches: frozenset[str]
    # Accent-folded phrases for unaccented user input (canonical == folded only).
    folded_matches: frozenset[str]
    response_text: str

    @property
    def matches(self) -> frozenset[str]:
        """Backward-compatible union of both match sets."""
        return self.canonical_matches | self.folded_matches


GREETING = StaticRule(
    rule_id="greeting",
    canonical_matches=frozenset({"hi", "hello", "xin chào", "chào bạn", "chào"}),
    folded_matches=frozenset({"hi", "hello", "xin chao", "chao ban", "chao"}),
    response_text="Chào bạn! Mình có thể giúp gì cho bạn hôm nay?",
)
THANKS = StaticRule(
    rule_id="thanks",
    canonical_matches=frozenset(
        {"thanks", "thank you", "cảm ơn", "cảm ơn bạn", "cảm ơn nhé"}
    ),
    folded_matches=frozenset(
        {"thanks", "thank you", "cam on", "cam on ban", "cam on nhe"}
    ),
    response_text="Không có gì, rất vui được giúp bạn!",
)
FAREWELL = StaticRule(
    rule_id="farewell",
    canonical_matches=frozenset({"bye", "goodbye", "tạm biệt", "hẹn gặp lại"}),
    folded_matches=frozenset({"bye", "goodbye", "tam biet", "hen gap lai"}),
    response_text="Tạm biệt, hẹn gặp lại bạn!",
)
PRODUCT_FAQ = StaticRule(
    rule_id="product_faq_capabilities",
    canonical_matches=frozenset({"bạn làm được gì", "what can you do"}),
    folded_matches=frozenset({"ban lam duoc gi", "what can you do"}),
    response_text=(
        "Mình có thể tạo ảnh AI, logo, poster, tờ rơi, chỉnh sửa ảnh theo phong cách, "
        "tìm kiếm thông tin thời gian thực, và thực hiện nghiên cứu chuyên sâu."
    ),
)

DEFAULT_STATIC_RULES: tuple[StaticRule, ...] = (GREETING, THANKS, FAREWELL, PRODUCT_FAQ)


@dataclass(frozen=True)
class PreRouterDecision:
    hit: bool
    outcome: Outcome | None
    rule_id: str | None
    response_text: str | None
    reason_code: str | None = None
    latency_ms: float = 0.0
    matched_surface: str | None = None


class PreRouterEngine:
    rule_version = RULE_VERSION

    def __init__(self, static_rules: tuple[StaticRule, ...] = DEFAULT_STATIC_RULES):
        self.static_rules = static_rules
        self._canonical_lookup = {
            phrase: rule
            for rule in static_rules
            for phrase in rule.canonical_matches
        }
        self._folded_lookup = {
            phrase: rule for rule in static_rules for phrase in rule.folded_matches
        }

    def evaluate(
        self,
        text: str,
        forms: NormalizedForms | None = None,
    ) -> PreRouterDecision:
        started = time.perf_counter()
        forms = forms if forms is not None else normalize_forms(text)

        rule = self._canonical_lookup.get(forms.canonical)
        matched_surface: str | None = "canonical" if rule is not None else None
        # Folded fallback only when the input had no accents to lose
        # (canonical == folded). Prevents "cháo" → greeting via "chao".
        if rule is None and forms.canonical == forms.folded:
            rule = self._folded_lookup.get(forms.folded)
            if rule is not None:
                matched_surface = "folded"

        elapsed = (time.perf_counter() - started) * 1_000
        if rule is None:
            return PreRouterDecision(
                hit=False,
                outcome=None,
                rule_id=None,
                response_text=None,
                latency_ms=elapsed,
            )
        reason_code = f"PREROUTER_STATIC_{rule.rule_id.upper()}"
        return PreRouterDecision(
            hit=True,
            outcome=Outcome.RESPONSE,
            rule_id=rule.rule_id,
            response_text=rule.response_text,
            reason_code=reason_code,
            latency_ms=elapsed,
            matched_surface=matched_surface,
        )


# Backward-compatible aliases used by legacy tests and tier0 imports.
Tier0Engine = PreRouterEngine
Tier0Decision = PreRouterDecision
RULE_VERSION_TIER0 = RULE_VERSION

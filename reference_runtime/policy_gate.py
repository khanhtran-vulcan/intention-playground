"""Deterministic Policy Gate.

Runs before Pre-router and the Structured LLM Router for every request. On a
block, the Router returns `REJECT` immediately and no other stage executes --
see `reference_runtime/runtime.py::ReferenceRouter.route`.

Matching uses two text surfaces from `NormalizedForms`:

- ``canonical`` (primary) — NFKC + casefold + punctuation→space; accents kept
- ``folded`` (opt-in per rule) — lossy Vietnamese accent fold

When Latin+Cyrillic letters both appear, folded-surface matches are skipped for
that request. This is a **narrow mixed-script heuristic**, not full UTS #39
confusable / spoof protection.

Deliberately narrow and deterministic: this is a demo fixture set, not a
production moderation model. Per the BE doc, generic "NSFW" content is not a
violation by default -- only requests matching an explicit blocking category are
rejected. Downstream capabilities keep their own moderation as defense in depth.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

import regex

from reference_runtime.pre_router import NormalizedForms, normalize_forms


RULE_VERSION = "policy-v2"

PolicySurface = Literal["canonical", "folded"]

_LATIN_LETTER = regex.compile(r"\p{Script=Latin}")
_CYRILLIC_LETTER = regex.compile(r"\p{Script=Cyrillic}")


def mixed_script_suspected(text: str) -> bool:
    """Heuristic: True when the string contains both Latin and Cyrillic letters.

    Not a substitute for UTS #39 confusable detection.
    """
    sample = text or ""
    return bool(_LATIN_LETTER.search(sample) and _CYRILLIC_LETTER.search(sample))


@dataclass(frozen=True)
class PolicyRule:
    rule_id: str
    category: str
    pattern: str
    response_text: str
    surfaces: frozenset[PolicySurface] = field(
        default_factory=lambda: frozenset({"canonical"})
    )


_CANONICAL_ONLY: frozenset[PolicySurface] = frozenset({"canonical"})
_CANONICAL_AND_FOLDED: frozenset[PolicySurface] = frozenset({"canonical", "folded"})


DEFAULT_RULES: tuple[PolicyRule, ...] = (
    PolicyRule(
        rule_id="csam_demo_fixture",
        category="csam",
        pattern=r"\b(csam[_ ]test[_ ]fixture|child sexual abuse material)\b",
        response_text="Tôi không thể hỗ trợ yêu cầu này.",
        surfaces=_CANONICAL_ONLY,
    ),
    PolicyRule(
        rule_id="weapons_demo_fixture",
        category="weapons_instructions",
        # Canonical: accented Vietnamese + English. Folded: ASCII-folded VI.
        pattern=(
            r"(hướng dẫn (chế tạo|làm) (bom|vũ khí)|"
            r"huong dan (che tao|lam) (bom|vu khi)|"
            r"how to (build|make) a bomb|"
            r"instructions? to (build|make) a weapon at home)"
        ),
        response_text="Tôi không thể hỗ trợ yêu cầu này.",
        surfaces=_CANONICAL_AND_FOLDED,
    ),
    PolicyRule(
        rule_id="self_harm_demo_fixture",
        category="self_harm_instructions",
        pattern=(
            r"(cách (tự tử|tự sát)|"
            r"cach (tu tu|tu sat)|"
            r"how to commit suicide|self[- ]harm method)"
        ),
        response_text=(
            "Mình không thể hướng dẫn việc này. Nếu bạn đang gặp khó khăn, hãy liên hệ "
            "đường dây hỗ trợ tâm lý gần bạn."
        ),
        surfaces=_CANONICAL_AND_FOLDED,
    ),
)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    category: str | None
    rule_id: str | None
    response_text: str | None
    latency_ms: float
    mixed_script_suspected: bool = False
    matched_surface: PolicySurface | None = None


class PolicyGate:
    rule_version = RULE_VERSION

    def __init__(self, rules: tuple[PolicyRule, ...] = DEFAULT_RULES):
        self.rules = rules
        self._compiled = [
            (rule, regex.compile(rule.pattern, regex.IGNORECASE | regex.VERSION1))
            for rule in rules
        ]

    def evaluate(
        self,
        text: str | NormalizedForms,
    ) -> PolicyDecision:
        started = time.perf_counter()
        forms = text if isinstance(text, NormalizedForms) else normalize_forms(text)
        mixed = mixed_script_suspected(forms.raw) or mixed_script_suspected(
            forms.canonical
        )
        surface_values: dict[PolicySurface, str] = {
            "canonical": forms.canonical,
            "folded": forms.folded,
        }

        for rule, compiled in self._compiled:
            surfaces = rule.surfaces
            if mixed:
                surfaces = surfaces & _CANONICAL_ONLY
            if not surfaces:
                continue
            # Prefer canonical before folded when both are allowed.
            ordered: tuple[PolicySurface, ...] = (
                ("canonical", "folded")
                if "folded" in surfaces and "canonical" in surfaces
                else tuple(sorted(surfaces))
            )
            for surface in ordered:
                if surface not in surfaces:
                    continue
                haystack = surface_values[surface]
                if compiled.search(haystack or ""):
                    return PolicyDecision(
                        allowed=False,
                        category=rule.category,
                        rule_id=rule.rule_id,
                        response_text=rule.response_text,
                        latency_ms=(time.perf_counter() - started) * 1_000,
                        mixed_script_suspected=mixed,
                        matched_surface=surface,
                    )
        return PolicyDecision(
            allowed=True,
            category=None,
            rule_id=None,
            response_text=None,
            latency_ms=(time.perf_counter() - started) * 1_000,
            mixed_script_suspected=mixed,
            matched_surface=None,
        )

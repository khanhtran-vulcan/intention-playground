"""Validator: turns a router decision into RESPONSE | ROUTE | CLARIFY | FALLBACK.

Applies the readiness rule from the BE doc independently of what the router
itself reported -- the router's `reason_code` is informational (goes to the
internal trace); the Validator recomputes the final reason from the predicate
checklist below:

    selected_intent_is_executable_now
    AND prerequisites_are_satisfied_or_not_required
    AND arguments_match_selected_capability_schema
    AND undeclared arguments are stripped (additionalProperties: false soft-strip)
    AND max-word arguments are truncated to schema limits (soft-coerce)
    AND required_context_is_present
    AND no_blocking_ambiguity
    AND no_unsupported_or_cyclic_dependency

Clarification questions come from the registry's templates, never invented ad hoc
by a provider.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from reference_runtime.contracts import (
    Clarification,
    MAX_CLARIFICATION_TURNS,
    Outcome,
    RouterDecisionTrace,
    RoutingRequest,
)
from reference_runtime.registry import ReferenceIntentRegistry


_AMBIGUITY_TOKEN_TEMPLATES: dict[str, tuple[str, str]] = {
    "create_or_edit_choice": ("create_vs_edit", "CREATE_VS_EDIT_AMBIGUOUS"),
    "creative_type": ("creative_ambiguous_type", "AMBIGUOUS_CREATIVE_TYPE"),
    "image": ("missing_image", "MISSING_REQUIRED_IMAGE"),
    "style": ("missing_style", "MISSING_REQUIRED_ARGUMENT"),
    "dependency_reference": ("dependency_reference_ambiguous", "DEPENDENCY_REFERENCE_AMBIGUOUS"),
}

# Common model hallucinations → canonical schema keys (before soft-strip).
_ARGUMENT_ALIASES: dict[str, dict[str, str]] = {
    "deep_research": {
        "query": "final_prompt",
        "topic": "final_prompt",
        "prompt": "final_prompt",
        "research_topic": "final_prompt",
    },
    "create_ai_art": {
        "text": "prompt",
        "description": "prompt",
    },
}

_PROVIDER_FAILURE_REASON_CODES = frozenset(
    {
        "PROVIDER_MISSING_CREDENTIALS",
        "PROVIDER_TIMEOUT",
        "PROVIDER_REQUEST_FAILED",
        "INVALID_PROVIDER_OUTPUT",
    }
)


@dataclass
class ValidatorDecision:
    outcome: Outcome
    reason_code: str
    name: str | None = None
    arguments: str | None = None
    response_text: str | None = None
    clarification: Clarification | None = None
    passed_predicates: list[str] = field(default_factory=list)
    failed_predicates: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def _truncate_words(text: str, max_words: int) -> str:
    return " ".join(str(text).split()[:max_words])


def _normalize_candidate_arguments(
    selected: str,
    raw_arguments: dict[str, str],
    declared_names: set[str],
) -> tuple[dict[str, str], list[str]]:
    """Alias-map then soft-strip undeclared keys. Returns (args, notes)."""
    notes: list[str] = []
    args = {str(k): str(v) for k, v in raw_arguments.items()}
    aliases = _ARGUMENT_ALIASES.get(selected, {})
    for alias, canonical in aliases.items():
        if alias not in args:
            continue
        if not str(args.get(canonical, "")).strip():
            args[canonical] = args[alias]
            notes.append(f"aliased argument {alias!r} → {canonical!r}")
        if alias != canonical:
            del args[alias]
    extra = sorted(set(args) - declared_names)
    for key in extra:
        del args[key]
    if extra:
        notes.append(f"stripped undeclared arguments: {extra}")
    return args, notes


def _dependency_context_satisfied(request: RoutingRequest, depends_on: str) -> bool:
    return any(
        message.role == "capability" and message.capability_name == depends_on
        for message in request.messages
    )


def _has_dependency_cycle(candidate: RouterDecisionTrace) -> bool:
    graph: dict[str, set[str]] = {}
    for edge in candidate.dependencies:
        graph.setdefault(edge.intent, set()).add(edge.depends_on)
        graph.setdefault(edge.depends_on, set())

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(dependency) for dependency in graph[node]):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


class Validator:
    def validate(
        self,
        request: RoutingRequest,
        candidate: RouterDecisionTrace,
        registry: ReferenceIntentRegistry,
    ) -> ValidatorDecision:
        passed: list[str] = []
        failed: list[str] = []
        issues: list[str] = []

        if candidate.provider_error_code in _PROVIDER_FAILURE_REASON_CODES:
            failed.append("selected_intent_is_executable_now")
            return ValidatorDecision(
                outcome=Outcome.FALLBACK,
                reason_code=candidate.provider_error_code,
                failed_predicates=failed,
            )

        if candidate.proposed_outcome == Outcome.RESPONSE:
            if not (candidate.response_text or "").strip():
                failed.append("response_text_present")
                return ValidatorDecision(
                    outcome=Outcome.FALLBACK,
                    reason_code="INVALID_ROUTER_RESPONSE",
                    failed_predicates=failed,
                )
            passed.append("response_text_present")
            return ValidatorDecision(
                outcome=Outcome.RESPONSE,
                reason_code=candidate.reason_code or "ROUTER_DIRECT_RESPONSE",
                response_text=candidate.response_text,
                passed_predicates=passed,
            )

        if candidate.proposed_outcome == Outcome.FALLBACK:
            return ValidatorDecision(
                outcome=Outcome.FALLBACK,
                reason_code=candidate.reason_code or "ROUTER_FALLBACK",
                passed_predicates=passed,
                failed_predicates=failed,
            )

        if _has_dependency_cycle(candidate):
            failed.append("no_unsupported_or_cyclic_dependency")
            return ValidatorDecision(
                outcome=Outcome.FALLBACK,
                reason_code="CYCLIC_DEPENDENCY",
                failed_predicates=failed,
            )
        passed.append("no_unsupported_or_cyclic_dependency:structural")

        if any(edge.depends_on == "UNSUPPORTED_PREREQUISITE" for edge in candidate.dependencies):
            failed.append("no_unsupported_or_cyclic_dependency")
            return ValidatorDecision(
                outcome=Outcome.FALLBACK,
                reason_code="UNSUPPORTED_PREREQUISITE",
                failed_predicates=failed,
            )

        turn_count = request.context.clarification_turn_count

        def clarify_or_limit(token: str) -> ValidatorDecision:
            template_key, reason_code = _AMBIGUITY_TOKEN_TEMPLATES[token]
            if turn_count >= MAX_CLARIFICATION_TURNS:
                failed.append("no_blocking_ambiguity")
                return ValidatorDecision(
                    outcome=Outcome.FALLBACK,
                    reason_code="CLARIFICATION_LIMIT_REACHED",
                    failed_predicates=failed,
                    issues=[f"clarification turn limit reached while resolving {token!r}"],
                )
            failed.append("no_blocking_ambiguity")
            return ValidatorDecision(
                outcome=Outcome.CLARIFY,
                reason_code=reason_code,
                clarification=registry.clarification_template(template_key),
                failed_predicates=failed,
            )

        if candidate.proposed_outcome == Outcome.CLARIFY:
            for token in candidate.missing_inputs:
                if token in _AMBIGUITY_TOKEN_TEMPLATES:
                    return clarify_or_limit(token)
            failed.append("no_blocking_ambiguity")
            return ValidatorDecision(
                outcome=Outcome.FALLBACK,
                reason_code="UNRESOLVABLE_AMBIGUITY",
                failed_predicates=failed,
                issues=issues,
            )

        for token in candidate.missing_inputs:
            if token in _AMBIGUITY_TOKEN_TEMPLATES:
                return clarify_or_limit(token)
            issues.append(f"unrecognized missing_input token: {token!r}")
            failed.append("no_blocking_ambiguity")
            return ValidatorDecision(
                outcome=Outcome.FALLBACK,
                reason_code="UNRESOLVABLE_AMBIGUITY",
                failed_predicates=failed,
                issues=issues,
            )
        passed.append("no_blocking_ambiguity")

        selected = candidate.selected_intent
        if selected is None:
            failed.append("selected_intent_is_executable_now")
            return ValidatorDecision(
                outcome=Outcome.FALLBACK,
                reason_code=candidate.reason_code or "NO_EXECUTABLE_INTENT",
                failed_predicates=failed,
            )

        if selected == "unknown":
            failed.append("selected_intent_is_executable_now")
            return ValidatorDecision(
                outcome=Outcome.FALLBACK,
                reason_code="UNKNOWN_INTENT",
                failed_predicates=failed,
            )

        if not registry.exists(selected):
            failed.append("selected_intent_is_executable_now")
            return ValidatorDecision(
                outcome=Outcome.FALLBACK,
                reason_code="UNSUPPORTED_OPERATION",
                failed_predicates=failed,
            )

        spec = registry.get(selected)
        if not spec.executable or spec.archived:
            failed.append("selected_intent_is_executable_now")
            return ValidatorDecision(
                outcome=Outcome.FALLBACK,
                reason_code="UNSUPPORTED_OPERATION",
                failed_predicates=failed,
            )

        if not request.tools:
            failed.append("selected_intent_is_executable_now")
            return ValidatorDecision(
                outcome=Outcome.FALLBACK,
                reason_code="UNSUPPORTED_CAPABILITY",
                failed_predicates=failed,
                issues=["empty tools allowlist: ROUTE is not permitted"],
            )

        if request.tools and selected not in request.tool_names:
            failed.append("selected_intent_is_executable_now")
            return ValidatorDecision(
                outcome=Outcome.FALLBACK,
                reason_code="UNSUPPORTED_CAPABILITY",
                failed_predicates=failed,
            )
        passed.append("selected_intent_is_executable_now")

        if spec.requires_image and not any(message.files for message in request.messages):
            return clarify_or_limit("image")
        passed.append("required_context_is_present")

        declared_names = {argument.name for argument in spec.arguments}
        args, normalize_notes = _normalize_candidate_arguments(
            selected, candidate.arguments, declared_names
        )
        issues.extend(normalize_notes)

        missing_required = [
            name
            for name in spec.required_argument_names
            if not str(args.get(name, "")).strip()
        ]
        if missing_required:
            if "style" in missing_required:
                return clarify_or_limit("style")
            failed.append("arguments_match_selected_capability_schema")
            return ValidatorDecision(
                outcome=Outcome.FALLBACK,
                reason_code="MISSING_REQUIRED_ARGUMENT",
                failed_predicates=failed,
                issues=issues + [f"missing required arguments: {missing_required}"],
            )

        for argument in spec.arguments:
            value = args.get(argument.name)
            if value is None:
                continue
            if argument.enum is not None and value not in argument.enum:
                failed.append("arguments_match_selected_capability_schema")
                return ValidatorDecision(
                    outcome=Outcome.FALLBACK,
                    reason_code="INVALID_ARGUMENT_VALUE",
                    failed_predicates=failed,
                    issues=issues + [f"{argument.name!r} must be one of {argument.enum}"],
                )
            if argument.max_words is not None:
                words = str(value).split()
                if len(words) > argument.max_words:
                    truncated = _truncate_words(str(value), argument.max_words)
                    args[argument.name] = truncated
                    issues.append(
                        f"truncated {argument.name!r} from {len(words)} to "
                        f"{argument.max_words} words"
                    )
        passed.append("arguments_match_selected_capability_schema")
        passed.append("no_undeclared_arguments")

        for edge in candidate.dependencies:
            if edge.intent != selected:
                continue
            if not _dependency_context_satisfied(request, edge.depends_on):
                failed.append("prerequisites_are_satisfied_or_not_required")
                return ValidatorDecision(
                    outcome=Outcome.FALLBACK,
                    reason_code="PREREQUISITE_NOT_SATISFIED",
                    failed_predicates=failed,
                    issues=issues + [f"{edge.depends_on!r} has not produced a capability result yet"],
                )
        passed.append("prerequisites_are_satisfied_or_not_required")

        filtered_arguments = {
            argument.name: args[argument.name]
            for argument in spec.arguments
            if argument.name in args
        }
        return ValidatorDecision(
            outcome=Outcome.ROUTE,
            reason_code=candidate.reason_code or "NEXT_EXECUTABLE_READY",
            name=selected,
            arguments=json.dumps(filtered_arguments, ensure_ascii=False),
            passed_predicates=passed,
            issues=issues,
        )

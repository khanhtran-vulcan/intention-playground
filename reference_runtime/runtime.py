"""`ReferenceRouter`: Normalize → Policy → Pre-router → Structured LLM Router → Validator.

Structural invariant: never imports `capability_simulator`. Router cannot invoke
capabilities by construction.
"""

from __future__ import annotations

import time
import uuid

from reference_runtime.contracts import (
    InternalTrace,
    Outcome,
    PolicyTrace,
    ReferenceRunResult,
    RoutingRequest,
    RoutingResponse,
    StageTrace,
    ValidatorTrace,
)
from reference_runtime.policy_gate import PolicyGate
from reference_runtime.pre_router import PreRouterEngine, normalize_forms
from reference_runtime.registry import ReferenceIntentRegistry
from reference_runtime.registry_loader import PROMPT_VERSION, registry_from_yaml, registry_version
from reference_runtime.router.base import RouterProvider
from reference_runtime.validator import Validator


class ReferenceRouter:
    def __init__(
        self,
        classifier: RouterProvider | None = None,
        router: RouterProvider | None = None,
        registry: ReferenceIntentRegistry | None = None,
        policy_gate: PolicyGate | None = None,
        tier0: PreRouterEngine | None = None,
        pre_router: PreRouterEngine | None = None,
        validator: Validator | None = None,
    ):
        self.router = router or classifier
        if self.router is None:
            from reference_runtime.router.fake import FakeRouterProvider

            self.router = FakeRouterProvider()
        self.classifier = self.router  # backward-compatible alias
        self.registry = registry or registry_from_yaml()
        self.policy_gate = policy_gate or PolicyGate()
        self.pre_router = pre_router or tier0 or PreRouterEngine()
        self.tier0 = self.pre_router  # backward-compatible alias
        self.validator = validator or Validator()

    def route(self, request: RoutingRequest) -> ReferenceRunResult:
        request_id = uuid.uuid4().hex
        stages: list[StageTrace] = []
        latest = request.latest_user_message
        raw_text = (latest.content if latest else "") or ""

        started = time.perf_counter()
        forms = normalize_forms(raw_text)
        stages.append(
            StageTrace(
                stage="normalize",
                latency_ms=(time.perf_counter() - started) * 1_000,
                detail={
                    "canonical_len": len(forms.canonical),
                    "folded_len": len(forms.folded),
                    "normalized_len": len(forms.folded),
                },
            )
        )

        started = time.perf_counter()
        policy_decision = self.policy_gate.evaluate(forms)
        stages.append(
            StageTrace(
                stage="policy_gate",
                latency_ms=(time.perf_counter() - started) * 1_000,
                detail={
                    "decision": "allow" if policy_decision.allowed else "block",
                    "mixed_script_suspected": policy_decision.mixed_script_suspected,
                    "matched_surface": policy_decision.matched_surface,
                },
            )
        )
        if not policy_decision.allowed:
            return self._finish(
                request_id=request_id,
                stages=stages,
                forms=forms,
                response=RoutingResponse(
                    outcome=Outcome.REJECT,
                    response_text=policy_decision.response_text,
                ),
                pre_router_hit=False,
                policy=PolicyTrace(
                    decision="block",
                    category=policy_decision.category,
                    rule_id=policy_decision.rule_id,
                    rule_version=self.policy_gate.rule_version,
                    mixed_script_suspected=policy_decision.mixed_script_suspected,
                    matched_surface=policy_decision.matched_surface,
                ),
                router_decision=None,
                validator_trace=None,
                final_reason_code="POLICY_VIOLATION",
            )

        allow_policy_trace = PolicyTrace(
            decision="allow",
            category=None,
            rule_id=None,
            rule_version=self.policy_gate.rule_version,
            mixed_script_suspected=policy_decision.mixed_script_suspected,
            matched_surface=None,
        )

        started = time.perf_counter()
        pre_decision = self.pre_router.evaluate(raw_text, forms=forms)
        stages.append(
            StageTrace(
                stage="pre_router",
                latency_ms=(time.perf_counter() - started) * 1_000,
                detail={"hit": pre_decision.hit, "rule_id": pre_decision.rule_id},
            )
        )
        if pre_decision.hit and pre_decision.outcome == Outcome.RESPONSE:
            reason_code = pre_decision.reason_code or "PREROUTER_STATIC"
            return self._finish(
                request_id=request_id,
                stages=stages,
                forms=forms,
                response=RoutingResponse(
                    outcome=Outcome.RESPONSE,
                    response_text=pre_decision.response_text,
                ),
                pre_router_hit=True,
                policy=allow_policy_trace,
                router_decision=None,
                validator_trace=None,
                final_reason_code=reason_code,
            )

        started = time.perf_counter()
        router_decision = self.router.route(request)
        stages.append(
            StageTrace(
                stage="router",
                latency_ms=(time.perf_counter() - started) * 1_000,
                detail={
                    "provider": router_decision.provider,
                    "proposed_outcome": router_decision.proposed_outcome.value,
                    "reason_code": router_decision.reason_code,
                },
            )
        )

        started = time.perf_counter()
        decision = self.validator.validate(request, router_decision, self.registry)
        stages.append(
            StageTrace(
                stage="validator",
                latency_ms=(time.perf_counter() - started) * 1_000,
                detail={"outcome": decision.outcome.value, "reason_code": decision.reason_code},
            )
        )

        response = RoutingResponse(
            outcome=decision.outcome,
            name=decision.name,
            arguments=decision.arguments,
            response_text=decision.response_text,
            clarification=decision.clarification,
            usage_model=router_decision.usage_model,
            usage=router_decision.usage,
        )
        return self._finish(
            request_id=request_id,
            stages=stages,
            forms=forms,
            response=response,
            pre_router_hit=False,
            policy=allow_policy_trace,
            router_decision=router_decision,
            validator_trace=ValidatorTrace(
                passed_predicates=decision.passed_predicates,
                failed_predicates=decision.failed_predicates,
                issues=decision.issues,
            ),
            final_reason_code=decision.reason_code,
        )

    def _finish(
        self,
        *,
        request_id: str,
        stages: list[StageTrace],
        forms,
        response: RoutingResponse,
        pre_router_hit: bool,
        policy: PolicyTrace,
        router_decision,
        validator_trace,
        final_reason_code: str,
    ) -> ReferenceRunResult:
        trace = InternalTrace(
            request_id=request_id,
            stages=stages,
            normalized_text=forms.folded,
            canonical_text=forms.canonical,
            pre_router_hit=pre_router_hit,
            pre_router_rule_version=self.pre_router.rule_version,
            policy=policy,
            router_decision=router_decision,
            validator=validator_trace,
            taxonomy_version=self.registry.taxonomy_version,
            prompt_version=PROMPT_VERSION,
            registry_version=registry_version(),
            final_reason_code=final_reason_code,
        )
        return ReferenceRunResult(response=response, trace=trace)

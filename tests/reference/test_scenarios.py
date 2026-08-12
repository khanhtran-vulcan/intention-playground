from __future__ import annotations

from reference_runtime.registry import registry_with_archived_active
from reference_runtime.router.fake import FakeRouterProvider
from reference_runtime.runtime import ReferenceRouter
from reference_runtime.scenarios import CLARIFICATION_CHAINS, SCENARIOS, scenarios_by_category


def test_scenario_ids_are_unique():
    ids = [scenario.id for scenario in SCENARIOS]
    assert len(ids) == len(set(ids))


def test_all_required_categories_are_covered():
    categories = {scenario.category for scenario in SCENARIOS}
    assert categories == {
        "pre_router_static",
        "router_response",
        "route",
        "dependency",
        "clarify",
        "fallback",
        "reject",
        "security",
        "empty_tools",
    }


def test_scenarios_by_category_filters_correctly():
    assert all(s.category == "route" for s in scenarios_by_category("route"))
    assert len(scenarios_by_category("reject")) >= 3


def test_every_scenario_matches_the_fake_provider_end_to_end():
    router = ReferenceRouter(router=FakeRouterProvider(), registry=registry_with_archived_active())
    failures = []
    for scenario in SCENARIOS:
        result = router.route(scenario.to_routing_request())
        if result.response.outcome.value != scenario.expected_outcome:
            failures.append((scenario.id, scenario.expected_outcome, result.response.outcome.value))
        if scenario.expected_name is not None and result.response.name != scenario.expected_name:
            failures.append((scenario.id, scenario.expected_name, result.response.name))
        if (
            scenario.expected_reason_code is not None
            and result.trace.final_reason_code != scenario.expected_reason_code
        ):
            failures.append(
                (scenario.id, scenario.expected_reason_code, result.trace.final_reason_code)
            )
    assert not failures, failures


def test_clarification_chains_resolve_as_designed():
    from reference_runtime.evaluation import evaluate_clarification_chain

    router = ReferenceRouter(router=FakeRouterProvider(), registry=registry_with_archived_active())
    for chain in CLARIFICATION_CHAINS:
        row = evaluate_clarification_chain(router, chain)
        assert row.completed, row.steps


def test_route_scenarios_include_tools():
    for scenario in scenarios_by_category("route"):
        assert scenario.tools, scenario.id
        assert scenario.to_routing_request().tools


def test_benchmark_scenarios_use_only_five_executable_tools():
    from reference_runtime.scenarios import BENCHMARK_TOOL_NAMES, SCENARIOS

    allowed = set(BENCHMARK_TOOL_NAMES)
    for scenario in SCENARIOS:
        if scenario.tools is None:
            continue
        assert set(scenario.tools).issubset(allowed), scenario.id
        if scenario.expected_name is not None:
            assert scenario.expected_name in allowed, scenario.id


def test_core_suite_excludes_prompt_hard_deferred_cases():
    from reference_runtime.scenarios import (
        clarification_chains_for_suite,
        scenarios_for_suite,
    )

    core = scenarios_for_suite("core")
    deferred = scenarios_for_suite("deferred")
    assert core and deferred
    assert {s.id for s in core}.isdisjoint({s.id for s in deferred})
    assert len(core) + len(deferred) == len(SCENARIOS)
    # Universal misses / still-deferred fixtures
    deferred_ids = {s.id for s in deferred}
    for sid in (
        "route_image_to_image_generation",
        "dependency_reference_ambiguous",
        "security_prompt_injection_ignored",
    ):
        assert sid in deferred_ids
    core_ids = {s.id for s in core}
    assert "route_deep_research_standalone" in core_ids
    assert "route_deep_research_then_illustration" in core_ids
    assert "dependency_research_then_art_followup" in core_ids
    assert "dependency_independent_intents_priority" in core_ids
    for archived_id in (
        "route_generate_logo",
        "route_generate_poster",
        "route_generate_flyer",
        "clarify_ambiguous_creative_type",
    ):
        assert archived_id not in {s.id for s in SCENARIOS}
    assert clarification_chains_for_suite("core") == ()
    assert clarification_chains_for_suite("all") == CLARIFICATION_CHAINS

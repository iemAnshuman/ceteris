"""Field rules, comparators, waivers and the aggregate decision.

Design sections 7.3 to 7.6 and 12.2.
"""

from __future__ import annotations

import itertools

import pytest

from ceteris import policy as p


# --- comparators --------------------------------------------------------------


def test_typed_exact_keeps_one_from_two():
    """Integer 1, string "1" and boolean true are three observations."""
    assert len({repr(p.typed_exact(v)) for v in (1, "1", True)}) == 3


def test_typed_exact_preserves_array_order():
    assert p.typed_exact([1, 2]) != p.typed_exact([2, 1])


def test_typed_exact_is_recursive_and_key_order_insensitive():
    assert p.typed_exact({"a": [1, {"b": 2}]}) == p.typed_exact({"a": [1, {"b": 2}]})
    assert p.typed_exact({"a": 1, "b": 2}) == p.typed_exact({"b": 2, "a": 1})
    assert p.typed_exact({"a": [1, 2]}) != p.typed_exact({"a": [2, 1]})


def test_multiset_ignores_order_and_keeps_duplicates():
    assert p.multiset([1, 2, 2]) == p.multiset([2, 1, 2])
    assert p.multiset([1, 2, 2]) != p.multiset([1, 2])


def test_a_logical_path_is_not_lowercased_or_resolved():
    assert p.comparator("logical-path@1")("/A/b") != p.comparator("logical-path@1")("/a/b")


def test_an_unknown_comparator_is_refused():
    with pytest.raises(ValueError, match="unknown comparator"):
        p.comparator("vibes@1")


# --- precedence ---------------------------------------------------------------


def test_the_highest_priority_rule_wins():
    policy = p.FieldPolicy((
        p.Rule("broad", "hardware.*", priority=0, severity="material"),
        p.Rule("specific", "hardware.gpu_models", priority=10, severity="critical"),
    ))
    assert policy.severity_of("hardware.gpu_models") == "critical"
    assert policy.severity_of("hardware.cpu_model") == "material"


def test_source_order_never_decides():
    rules = [
        p.Rule("a", "hardware.*", priority=0, severity="material"),
        p.Rule("b", "hardware.gpu_models", priority=5, severity="critical"),
        p.Rule("c", "*.gpu_models", priority=1, severity="informational"),
    ]
    answers = {
        p.FieldPolicy(tuple(order)).severity_of("hardware.gpu_models")
        for order in itertools.permutations(rules)
    }
    assert answers == {"critical"}


def test_equal_priority_rules_that_disagree_are_refused():
    policy = p.FieldPolicy((
        p.Rule("one", "runtime.env.*", priority=3, severity="critical"),
        p.Rule("two", "*.LCI_SIZE", priority=3, severity="informational"),
    ))
    with pytest.raises(p.AmbiguousPolicy) as exc:
        policy.severity_of("runtime.env.LCI_SIZE")
    assert "'one'" in str(exc.value) and "'two'" in str(exc.value)


def test_equal_priority_rules_that_agree_collapse_and_keep_their_ids():
    policy = p.FieldPolicy((
        p.Rule("one", "runtime.env.*", priority=3, severity="critical"),
        p.Rule("two", "*.LCI_SIZE", priority=3, severity="critical"),
    ))
    decided = policy.decide("runtime.env.LCI_SIZE")
    assert decided["severity"] == "critical"
    assert decided["matched_by"] == ["one", "two"]


def test_an_unmatched_field_is_material_and_typed_exact():
    policy = p.FieldPolicy(())
    assert policy.severity_of("something.new") == "material"
    assert policy.comparator_of("something.new") == "typed-exact@1"
    assert policy.gates("something.new")


def test_a_rule_can_be_scoped():
    policy = p.FieldPolicy((
        p.Rule("nodes", "system.*", priority=1, severity="critical", scope="node/n01"),
    ))
    assert policy.severity_of("system.turbo", "node/n01") == "critical"
    assert policy.severity_of("system.turbo", "subject") == "material"


def test_a_bare_prefix_becomes_an_explicit_glob_before_hashing():
    assert p.expand_prefix("build") == "build.*"
    assert p.expand_prefix("build.*") == "build.*"
    assert p.expand_prefix("build.cxx_flags") == "build.cxx_flags.*"


def test_the_policy_identity_covers_the_engine_and_the_rules():
    a = p.FieldPolicy((p.Rule("x", "a.*", priority=1),))
    b = p.FieldPolicy((p.Rule("x", "a.*", priority=2),))
    assert a.identity != b.identity
    assert a.identity == p.FieldPolicy((p.Rule("x", "a.*", priority=1),)).identity


def test_an_invalid_rule_is_refused_at_construction():
    with pytest.raises(ValueError):
        p.Rule("x", "a.*", severity="quite-bad")
    with pytest.raises(ValueError):
        p.Rule("x", "a.*", priority="high")


# --- waivers ------------------------------------------------------------------


def test_a_waiver_needs_a_reason_and_a_reference():
    with pytest.raises(ValueError, match="reason"):
        p.Waiver("w1", "hardware.cpu_model", reason="  ", reference="ticket-1")
    with pytest.raises(ValueError, match="reference"):
        p.Waiver("w1", "hardware.cpu_model", reason="same partition", reference="")


@pytest.mark.parametrize("code", p.UNWAIVABLE)
def test_the_things_a_waiver_cannot_reach(code):
    with pytest.raises(p.UnwaivableObligation):
        p.check_waivable(code)


def test_an_ordinary_obligation_can_be_waived():
    p.check_waivable("field_difference")


def test_expiry_is_judged_against_the_campaign_not_against_today():
    """Re-reading an old report must not change what it decided."""
    waiver = p.Waiver("w1", "hardware.cpu_model", reason="r", reference="t", expires="2026-01-31")
    assert not waiver.expired_at("2026-01-15T10:00:00Z")
    assert waiver.expired_at("2026-02-01T10:00:00Z")
    assert not waiver.expired_at(None)


def test_a_waiver_can_be_scoped_to_one_comparison():
    waiver = p.Waiver("w1", "hardware.*", reason="r", reference="t", comparisons=("c1",))
    assert waiver.covers("hardware.cpu_model", "c1")
    assert not waiver.covers("hardware.cpu_model", "c2")


# --- declared variation -------------------------------------------------------


def test_vary_permits_a_difference_between_the_named_variants():
    v = p.Variation(patterns=("source.commit",), across_variants=("base", "candidate"))
    assert v.permits("source.commit", ["base", "candidate"])


def test_vary_does_not_permit_a_difference_between_repeats_of_one_variant():
    """That is not the change that was intended."""
    v = p.Variation(patterns=("source.commit",), across_variants=("base", "candidate"))
    assert not v.permits("source.commit", ["candidate", "candidate"])


def test_vary_does_not_reach_a_variant_it_did_not_name():
    v = p.Variation(patterns=("source.commit",), across_variants=("base", "candidate"))
    assert not v.permits("source.commit", ["base", "third"])


def test_an_intended_change_that_did_not_happen_is_an_experiment_failure():
    v = p.Variation(require_observed_change=("artifact.program.digest",))
    assert v.unmet_assertions(["source.commit"]) == ["artifact.program.digest"]
    assert v.unmet_assertions(["artifact.program.digest"]) == []


# --- the aggregate decision ---------------------------------------------------


def test_a_clean_run_passes():
    assert p.Decision().acceptance() == "passed"


def test_a_failed_correctness_check_fails_whatever_the_timing_said():
    assert p.Decision(correctness="failed", measurement="assessed").acceptance() == "failed"


def test_a_failed_execution_fails():
    assert p.Decision(execution="failed").acceptance() == "failed"


def test_incomplete_coverage_is_inconclusive_not_failed():
    assert p.Decision(coverage="incomplete").acceptance() == "inconclusive"


def test_indeterminate_comparability_is_inconclusive():
    assert p.Decision(comparability="indeterminate").acceptance() == "inconclusive"


def test_an_accepted_waiver_is_visible_in_the_summary():
    decision = p.Decision(obligations=[
        p.Obligation("o1", "coverage", "waived", waiver_id="w1")])
    assert decision.acceptance() == "passed_with_waivers"


def test_a_violated_obligation_fails_even_with_other_waivers():
    decision = p.Decision(obligations=[
        p.Obligation("o1", "coverage", "waived", waiver_id="w1"),
        p.Obligation("o2", "comparability", "violated"),
    ])
    assert decision.acceptance() == "failed"


def test_an_unresolved_obligation_is_inconclusive():
    decision = p.Decision(obligations=[p.Obligation("o1", "coverage", "unresolved")])
    assert decision.acceptance() == "inconclusive"


def test_a_diagnostic_comparison_never_issues_an_acceptance():
    decision = p.Decision(diagnostic=True, measurement="assessed")
    assert decision.acceptance() == "not_evaluated"
    assert not decision.eligible_for_acceptance


def test_every_reason_is_kept_even_once_one_has_decided():
    decision = p.Decision(
        correctness="failed", coverage="incomplete",
        obligations=[p.Obligation("o1", "coverage", "violated", "the node never reported")])
    assert decision.acceptance() == "failed"
    body = decision.to_json()
    assert body["coverage"] == "incomplete"
    assert body["obligations"][0]["detail"] == "the node never reported"

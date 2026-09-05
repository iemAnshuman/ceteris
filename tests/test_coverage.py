"""Expected evidence against observed evidence. Design section 7.2."""

from __future__ import annotations

import pytest

from ceteris import coverage as c


def cap(capability="cpu.topology", scope="subject", stage="before", status="observed",
        reason=None, field_states=None) -> dict:
    return {"capability": capability, "scope": scope, "stage": stage,
            "status": status, "reason": reason, "field_states": field_states or {}}


def req(**kw) -> c.Requirement:
    base = dict(id="r1", capability="cpu.topology", scope_selector="subject",
                stages=("before",))
    base.update(kw)
    return c.Requirement(**base)


def results_of(requirement, capabilities, **kw):
    return c.evaluate_requirement(requirement, capabilities, **kw)


# --- the basic judgement ------------------------------------------------------


def test_an_observed_capability_satisfies_its_requirement():
    got = results_of(req(), [cap()])
    assert [r.result for r in got] == ["satisfied"]


def test_no_evidence_at_all_is_incomplete():
    got = results_of(req(), [])
    assert got[0].result == "incomplete" and "no evidence" in got[0].reason


@pytest.mark.parametrize("status", ["unavailable", "unsupported", "excluded"])
def test_anything_short_of_an_observation_is_incomplete(status):
    got = results_of(req(), [cap(status=status, reason="because")])
    assert got[0].result == "incomplete"


def test_structural_absence_satisfies_only_when_the_requirement_allows_it():
    absent = [cap(status="not_applicable", reason="this machine has no GPU")]
    assert results_of(req(), absent)[0].result == "incomplete"
    assert results_of(req(allow_not_applicable=True), absent)[0].result == "satisfied"


def test_claimed_absence_without_applicability_evidence_is_incomplete():
    got = results_of(req(allow_not_applicable=True), [cap(status="not_applicable")])
    assert got[0].result == "incomplete" and "applicability" in got[0].reason


def test_an_observed_capability_whose_fields_are_unknown_contradicts_itself():
    got = results_of(req(), [cap(field_states={"hardware.cpu_model": "unknown"})])
    assert got[0].result == "incomplete" and "contradicts" in got[0].reason


def test_every_required_stage_is_judged_separately():
    got = results_of(req(stages=("before", "after")), [cap(stage="before")])
    assert [(r.stage, r.result) for r in got] == [
        ("before", "satisfied"), ("after", "incomplete")]


# --- scope --------------------------------------------------------------------


def test_node_scope_expands_to_every_allocated_node():
    got = results_of(req(scope_selector="all_allocated_nodes"),
                     [cap(scope="node/n01")], allocated_nodes=["n01", "n02"])
    assert [(r.scope, r.result) for r in got] == [
        ("node/n01", "satisfied"), ("node/n02", "incomplete")]


def test_requiring_every_node_with_no_node_named_is_unresolved():
    got = results_of(req(scope_selector="all_allocated_nodes"), [])
    assert got[0].result == "unresolved"


def test_an_explicit_scope_list_is_honoured():
    got = results_of(req(scope_selector=["controller", "subject"]),
                     [cap(scope="controller")])
    assert [(r.scope, r.result) for r in got] == [
        ("controller", "satisfied"), ("subject", "incomplete")]


def test_a_count_of_nodes_is_not_an_inventory():
    """Fifteen reports from fourteen nodes is not a fingerprint of fifteen."""
    got = c.evaluate([], [cap(scope="node/n01"), cap(scope="node/n01")],
                     expected_nodes=["n01", "n02"])
    assert got["state"] == "incomplete"
    assert {i["node"] for i in got["node_issues"]} == {"n02"}


def test_evidence_from_an_unexpected_node_is_reported():
    got = c.evaluate([], [cap(scope="node/n09")], expected_nodes=["n01"])
    problems = {i["node"]: i["problem"] for i in got["node_issues"]}
    assert "n01" in problems and "n09" in problems


# --- the `when` grammar -------------------------------------------------------


def lookup_from(fields=None, parameters=None):
    return c.reference_lookup(fields or {}, parameters or {})


def test_a_missing_condition_means_the_requirement_applies():
    assert c.evaluate_condition(None, lookup_from()) is True


def test_equality_is_typed():
    fields = {"subject": {"hardware.arch": {"state": "value", "v": "x86_64"}}}
    ref = "field:subject:hardware.arch"
    assert c.evaluate_condition({"equals": {"ref": ref, "value": "x86_64"}},
                                lookup_from(fields)) is True
    assert c.evaluate_condition({"equals": {"ref": ref, "value": "arm64"}},
                                lookup_from(fields)) is False


def test_one_and_the_string_one_are_not_equal():
    fields = {"subject": {"n": {"state": "value", "v": 1}}}
    assert c.evaluate_condition({"equals": {"ref": "field:subject:n", "value": "1"}},
                                lookup_from(fields)) is False


def test_an_unreadable_input_is_unresolved_never_false():
    """A requirement must not quietly stop applying because a probe failed."""
    fields = {"subject": {"hardware.arch": {"state": "unknown", "reason": "sysctl failed"}}}
    got = c.evaluate_condition(
        {"equals": {"ref": "field:subject:hardware.arch", "value": "x86_64"}},
        lookup_from(fields))
    assert got is None


def test_false_dominates_all_and_true_dominates_any():
    fields = {"subject": {"a": {"state": "value", "v": 1},
                          "b": {"state": "unknown", "reason": "x"}}}
    look = lookup_from(fields)
    yes = {"equals": {"ref": "field:subject:a", "value": 1}}
    no = {"equals": {"ref": "field:subject:a", "value": 2}}
    unknown = {"equals": {"ref": "field:subject:b", "value": 1}}
    assert c.evaluate_condition({"all": [no, unknown]}, look) is False
    assert c.evaluate_condition({"any": [yes, unknown]}, look) is True
    assert c.evaluate_condition({"all": [yes, unknown]}, look) is None
    assert c.evaluate_condition({"any": [no, unknown]}, look) is None


def test_a_parameter_reference_resolves_from_the_plan():
    look = lookup_from(parameters={"platform": "linux"})
    assert c.evaluate_condition({"equals": {"ref": "parameter:platform", "value": "linux"}},
                                look) is True
    assert c.evaluate_condition({"equals": {"ref": "parameter:absent", "value": "x"}},
                                look) is None


@pytest.mark.parametrize("expression", [
    {"all": []},
    {"any": []},
    {"all": [{"equals": {"ref": "parameter:x", "value": 1}}], "any": []},
    {"sometimes": [{}]},
    {"equals": {"ref": "parameter:x"}},
    "not an object",
])
def test_expressions_outside_the_grammar_are_refused(expression):
    with pytest.raises(c.ConditionError):
        c.evaluate_condition(expression, lookup_from())


def test_a_requirement_whose_condition_is_false_simply_does_not_apply():
    fields = {"subject": {"hardware.arch": {"state": "value", "v": "arm64"}}}
    got = results_of(req(when={"equals": {"ref": "field:subject:hardware.arch",
                                          "value": "x86_64"}}),
                     [], fields=fields)
    assert got == []


def test_a_requirement_whose_condition_is_unresolved_is_unresolved():
    fields = {"subject": {"hardware.arch": {"state": "unknown", "reason": "x"}}}
    got = results_of(req(when={"equals": {"ref": "field:subject:hardware.arch",
                                          "value": "x86_64"}}),
                     [], fields=fields)
    assert got[0].result == "unresolved"


# --- the aggregate ------------------------------------------------------------


def test_coverage_is_sufficient_only_when_every_requirement_is_satisfied():
    good = c.evaluate([req()], [cap()])
    assert good["state"] == "sufficient" and good["incomplete"] == []

    bad = c.evaluate([req(), req(id="r2", capability="os.identity")], [cap()])
    assert bad["state"] == "incomplete"
    assert [r["requirement_id"] for r in bad["incomplete"]] == ["r2"]


def test_the_expected_set_comes_from_the_plan_not_from_what_arrived():
    """A requirement nobody managed to observe must not cease to be one."""
    got = c.evaluate([req(id="never-observed", capability="parallelism.subject_affinity")], [])
    assert got["state"] == "incomplete"
    assert got["incomplete"][0]["capability"] == "parallelism.subject_affinity"

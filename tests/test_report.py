"""Semantic report assembly. Design section 12."""

from __future__ import annotations

import pytest

from ceteris import report as r
from ceteris.policy import Decision, Obligation


def build(**kw):
    base = dict(plan_digest="sha256:" + "a" * 64, comparison_id="candidate-v-base",
                coverage={"state": "sufficient", "incomplete": [], "unresolved": []},
                field_results=[], metric_results=[], selected_records=[])
    base.update(kw)
    return r.build(**base)


def passing_metric(case="compress/small", metric="elapsed", result="pass"):
    return {"case_id": case, "metric_id": metric, "primary": True, "status": "assessed",
            "predicate": {"type": "non_regression", "threshold": "0.05", "result": result}}


# --- the dimensions -----------------------------------------------------------


def test_a_clean_evaluation_passes():
    report = build(metric_results=[passing_metric()], correctness="validated")
    assert report.acceptance == "passed"
    assert report.exit_code() == 0


def test_a_failed_predicate_fails_the_policy():
    report = build(metric_results=[passing_metric(result="fail")], correctness="validated")
    assert report.acceptance == "failed"
    assert report.exit_code() == 1


def test_an_inconclusive_predicate_with_full_coverage_is_exit_four():
    report = build(metric_results=[passing_metric(result="inconclusive")],
                   correctness="validated")
    assert report.acceptance == "inconclusive"
    assert report.exit_code() == 4


def test_incomplete_coverage_is_exit_two_not_four():
    """Not knowing and not resolving are different answers."""
    report = build(
        coverage={"state": "incomplete", "unresolved": [],
                  "incomplete": [{"requirement_id": "r1", "capability": "cpu.topology",
                                  "reason": "no evidence"}]},
        metric_results=[passing_metric()])
    assert report.acceptance == "inconclusive"
    assert report.exit_code() == 2


def test_an_undeclared_difference_makes_the_comparison_incompatible():
    report = build(field_results=[{"path": "build.cxx_flags",
                                   "classification": "undeclared_difference"}],
                   metric_results=[passing_metric()])
    assert report.decision.comparability == "incompatible"
    assert report.acceptance == "failed"


def test_an_unreadable_field_is_indeterminate_not_incompatible():
    report = build(field_results=[{"path": "hardware.gpu_driver",
                                   "classification": "indeterminate",
                                   "reason": "nvidia-smi timed out"}],
                   metric_results=[passing_metric()])
    assert report.decision.comparability == "indeterminate"
    assert report.acceptance == "inconclusive"


def test_a_waived_difference_is_visible_in_the_summary():
    report = build(field_results=[{"path": "hardware.cpu_model", "classification": "waived",
                                   "reason": "same partition", "waiver_id": "w1"}],
                   metric_results=[passing_metric()], correctness="validated")
    assert report.acceptance == "passed_with_waivers"
    obligations = report.decision.to_json()["obligations"]
    assert any(o["waiver_id"] == "w1" for o in obligations)


def test_a_failed_correctness_check_beats_a_good_measurement():
    report = build(metric_results=[passing_metric()], correctness="failed")
    assert report.acceptance == "failed"


def test_a_diagnostic_report_never_issues_an_acceptance():
    report = build(metric_results=[passing_metric()], diagnostic=True)
    assert report.acceptance == "not_evaluated"


def test_no_primary_metric_means_the_measurement_is_unavailable():
    report = build(metric_results=[])
    assert report.decision.measurement == "unavailable"
    assert report.acceptance == "inconclusive"


def test_every_reason_survives_even_after_one_has_decided():
    report = build(
        coverage={"state": "incomplete", "unresolved": [],
                  "incomplete": [{"requirement_id": "r1", "capability": "cpu.topology",
                                  "reason": "the node never reported"}]},
        field_results=[{"path": "build.cxx_flags", "classification": "undeclared_difference"}],
        metric_results=[passing_metric()], correctness="failed")
    body = report.to_json()
    assert body["dimensions"]["acceptance"] == "failed"
    assert body["dimensions"]["coverage"] == "incomplete"
    assert body["dimensions"]["comparability"] == "incompatible"
    assert body["coverage"]["incomplete"][0]["reason"] == "the node never reported"


# --- determinism --------------------------------------------------------------


def test_the_report_digest_does_not_depend_on_input_order():
    first = build(field_results=[{"path": "b", "classification": "matched"},
                                 {"path": "a", "classification": "matched"}],
                  metric_results=[passing_metric("c2"), passing_metric("c1")])
    second = build(field_results=[{"path": "a", "classification": "matched"},
                                  {"path": "b", "classification": "matched"}],
                   metric_results=[passing_metric("c1"), passing_metric("c2")])
    assert first.digest == second.digest


def test_the_report_digest_changes_when_the_decision_changes():
    passing = build(metric_results=[passing_metric()], correctness="validated")
    failing = build(metric_results=[passing_metric(result="fail")], correctness="validated")
    assert passing.digest != failing.digest


def test_records_are_ordered_by_assignment_identity():
    report = build(selected_records=[
        {"pair_id": "p2", "slot": "first", "run_id": "b"},
        {"pair_id": "p1", "slot": "second", "run_id": "a"},
        {"pair_id": "p1", "slot": "first", "run_id": "c"},
    ])
    order = [(x["pair_id"], x["slot"]) for x in report.to_json()["selected_records"]]
    assert order == [("p1", "first"), ("p1", "second"), ("p2", "first")]


# --- issues -------------------------------------------------------------------


def test_an_issue_carries_a_stable_code_and_data_only_remediation():
    issue = r.Issue("stale_export", "blocking", "collection",
                    "the export was not written by this run",
                    remediation="let the adapter own the export path")
    assert issue.code in r.ISSUE_CODES
    body = issue.to_json()
    assert body["remediation"] == "let the adapter own the export path"


def test_structural_issues_are_a_usage_exit_not_a_policy_one():
    report = build(metric_results=[passing_metric()],
                   issues=[r.Issue("duplicate_observation", "blocking", "selection",
                                   "one record offered twice")])
    assert report.exit_code() == 3


def test_a_blocking_issue_leads_the_headline():
    report = build(metric_results=[passing_metric(result="fail")],
                   issues=[r.Issue("harness_invalid", "blocking", "collection",
                                   "loadgen reported INVALID")])
    assert "loadgen reported INVALID" in r.headline(report)


def test_the_headline_names_the_comparison_and_the_state():
    report = build(metric_results=[passing_metric()], correctness="validated")
    line = r.headline(report)
    assert line.startswith("candidate-v-base") and "PASSED" in line


def test_the_headline_explains_incomplete_coverage():
    report = build(coverage={"state": "incomplete", "unresolved": [],
                             "incomplete": [{"requirement_id": "r1",
                                             "capability": "parallelism.subject_affinity",
                                             "reason": "not observed"}]},
                   metric_results=[passing_metric()])
    assert "parallelism.subject_affinity" in r.headline(report)


# --- lineage ------------------------------------------------------------------


def test_a_retrospective_report_says_so():
    report = build(metric_results=[passing_metric()], analysis_origin="retrospective")
    assert report.to_json()["analysis_origin"] == "retrospective"


def test_the_report_records_the_policy_it_was_judged_under():
    report = build(metric_results=[passing_metric()], policy_identity="sha256:" + "b" * 64)
    assert report.to_json()["policy_identity"] == "sha256:" + "b" * 64

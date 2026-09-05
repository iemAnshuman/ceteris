"""Schema 4 typed values and structural validation.

Design sections 5.4 to 5.7. The rule these tests exist to hold: a malformed
record is a structured issue with a stable code, never a traceback and never
a comparison of nonsense.
"""

from __future__ import annotations

import uuid

import pytest

from ceteris.protocol import models as m
from ceteris.protocol import validation as v


def a_run(**overrides) -> dict:
    """A minimal well-formed schema 4 run record."""
    run = {
        "kind": "ceteris.run",
        "schema_version": 4,
        "producer": {"name": "ceteris", "version": "0.4.0", "record_semantics": "ceteris.run@4"},
        "run_id": str(uuid.uuid4()),
        "campaign_id": str(uuid.uuid4()),
        "experiment_id": "compression-regression",
        "variant_id": "candidate",
        "plan_digest": "sha256:" + "a" * 64,
        "assignment": {"comparison_id": "c1", "pair_id": "p1", "slot": "candidate", "attempt": 1},
        "timestamps": {"start": "2026-09-05T10:00:00Z", "end": "2026-09-05T10:00:02Z",
                       "duration_s": "2.5"},
        "execution": {"requested_argv": ["bench"], "effective_argv": ["bench"],
                      "outcome": "completed", "exit_code": 0, "signal": None},
        "observations": {
            "before": {"status": "observed",
                       "scopes": {"subject": {"hardware.cpu_model": {"state": "value", "v": "M4"}}}},
            "after": {"status": "observed",
                      "scopes": {"subject": {"hardware.cpu_model": {"state": "value", "v": "M4"}}}},
        },
        "capabilities": [{"capability": "cpu.topology", "version": 1, "scope": "subject",
                          "stage": "before", "status": "observed",
                          "fields": ["hardware.cpu_model"], "reason": None, "evidence_refs": []}],
        "metrics": [{"case_id": "compress/small", "metric_id": "elapsed", "unit": "s",
                     "direction": "lower", "domain": "positive", "state": "value",
                     "estimate": "0.125", "aggregation": "median",
                     "sampling_unit": "process_execution", "raw_samples": ["0.124", "0.127"],
                     "inner_sample_count": 2, "source": {}}],
        "correctness": [],
        "drift": {"status": "observed", "changes": [], "issues": []},
        "issues": [],
        "requires": [],
    }
    run.update(overrides)
    return run


def codes(issues) -> set:
    return {issue.code for issue in issues}


# --- the envelope -------------------------------------------------------------


def test_a_well_formed_record_has_no_issues():
    assert v.validate_run(a_run()) == []


def test_another_schema_version_stops_validation_rather_than_guessing():
    issues = v.validate_run(a_run(schema_version=3))
    assert codes(issues) == {"unsupported_version"}


@pytest.mark.parametrize("member, bad, code", [
    ("run_id", "not-a-uuid", "invalid_uuid"),
    ("experiment_id", "has spaces", "invalid_identifier"),
    ("experiment_id", "../escape", "invalid_identifier"),
    ("plan_digest", "sha256:short", "invalid_digest"),
    ("kind", "ceteris.something", "invalid_structure"),
])
def test_malformed_members_are_named_not_raised(member, bad, code):
    assert code in codes(v.validate_run(a_run(**{member: bad})))


def test_an_uppercase_uuid_is_not_the_canonical_form():
    assert "invalid_uuid" in codes(v.validate_run(a_run(run_id=str(uuid.uuid4()).upper())))


def test_a_malformed_exit_code_is_a_validation_failure():
    run = a_run()
    run["execution"] = {**run["execution"], "exit_code": "zero"}
    assert "malformed_exit_code" in codes(v.validate_run(run))


def test_a_completed_execution_needs_an_exit_status():
    run = a_run()
    run["execution"] = {**run["execution"], "exit_code": None}
    assert "missing_value" in codes(v.validate_run(run))


def test_an_invalid_timestamp_is_named():
    run = a_run()
    run["timestamps"] = {**run["timestamps"], "start": "yesterday"}
    assert "invalid_timestamp" in codes(v.validate_run(run))


def test_a_negative_duration_is_refused():
    run = a_run()
    run["timestamps"] = {**run["timestamps"], "duration_s": "-1"}
    assert "invalid_structure" in codes(v.validate_run(run))


# --- observations and coverage ------------------------------------------------


def test_a_missing_snapshot_must_say_so_rather_than_be_absent():
    run = a_run()
    run["observations"] = {"before": run["observations"]["before"], "after": None}
    assert "missing_value" in codes(v.validate_run(run))


def test_an_unavailable_snapshot_must_give_a_reason():
    run = a_run()
    run["observations"] = {**run["observations"], "after": {"status": "unavailable"}}
    assert "missing_reason" in codes(v.validate_run(run))


def test_a_completed_run_with_a_missing_snapshot_is_incomplete_not_failed():
    """The outcome stands; the coverage does not."""
    run = a_run()
    run["observations"] = {**run["observations"],
                           "after": {"status": "unavailable", "reason": "the node went away"}}
    assert "incomplete_observation" in codes(v.validate_run(run))


def test_an_unknown_observation_scope_is_refused():
    """Scope says whose machine an observation describes. The capturing
    process's environment is never silently attributed to a remote rank."""
    run = a_run()
    run["observations"]["before"]["scopes"] = {"somewhere": {}}
    assert "invalid_scope" in codes(v.validate_run(run))


@pytest.mark.parametrize("scope, ok", [
    ("controller", True), ("subject", True), ("node/n01", True),
    ("validator/output-check", True), ("execution", True), ("campaign", True),
    ("node/", False), ("elsewhere", False),
])
def test_scope_vocabulary(scope, ok):
    assert m.valid_scope(scope) is ok


def test_a_field_cannot_be_both_unknown_and_have_a_value():
    run = a_run()
    run["observations"]["before"]["scopes"]["subject"] = {
        "x": {"state": "unknown", "v": 1, "reason": "hmm"}}
    assert "value_on_non_value_state" in codes(v.validate_run(run))


def test_not_applicable_needs_a_real_applicability_reason():
    run = a_run()
    run["observations"]["before"]["scopes"]["subject"] = {"x": {"state": "not_applicable"}}
    assert "missing_applicability_reason" in codes(v.validate_run(run))


# --- capabilities -------------------------------------------------------------


def test_a_capability_that_was_not_observed_must_say_why():
    run = a_run()
    run["capabilities"][0].update(status="unavailable", reason=None)
    assert "missing_reason" in codes(v.validate_run(run))


def test_one_capability_has_one_status_per_scope_and_stage():
    run = a_run()
    run["capabilities"] = run["capabilities"] + [dict(run["capabilities"][0])]
    assert "duplicate_capability" in codes(v.validate_run(run))


@pytest.mark.parametrize("status, answers", [
    ("observed", True), ("not_applicable", True),
    ("unavailable", False), ("unsupported", False), ("excluded", False),
])
def test_only_an_observation_or_a_structural_absence_answers_a_requirement(status, answers):
    cap = m.Capability("cpu.topology", 1, "subject", "before", status,
                       reason=None if status == "observed" else "because")
    assert cap.satisfies_requirement is answers


# --- metrics ------------------------------------------------------------------


def test_a_duplicate_metric_identity_is_refused():
    run = a_run()
    run["metrics"] = run["metrics"] + [dict(run["metrics"][0])]
    assert "duplicate_metric_identity" in codes(v.validate_run(run))


def test_drift_that_was_not_observed_cannot_list_changes():
    run = a_run(drift={"status": "unavailable", "changes": [{"path": "x"}]})
    assert "invalid_structure" in codes(v.validate_run(run))


def test_a_metric_needs_a_unit_a_direction_and_a_domain():
    for kwargs, code in [
        (dict(unit="furlongs"), "unknown_unit"),
        (dict(direction="sideways"), "unknown_enum_value"),
        (dict(domain="complex"), "unknown_enum_value"),
    ]:
        base = dict(case_id="c", metric_id="elapsed", unit="s", direction="lower",
                    domain="positive", estimate="1")
        base.update(kwargs)
        with pytest.raises(m.ProtocolError) as exc:
            m.Metric(**base)
        assert exc.value.code == code


def test_a_custom_unit_must_be_namespaced():
    m.Metric("c", "x", "acme.example:widgets", "lower", "positive", estimate="1")


def test_a_value_outside_the_declared_domain_is_refused():
    with pytest.raises(m.ProtocolError) as exc:
        m.Metric("c", "elapsed", "s", "lower", "positive", estimate="-1")
    assert exc.value.code == "domain_violation"
    m.Metric("c", "delta", "ratio", "none", "real", estimate="-1")     # real allows it


def test_a_metric_with_no_direction_cannot_drive_a_predicate():
    shown = m.Metric("c", "delta", "ratio", "none", "real", estimate="0.5")
    decides = m.Metric("c", "elapsed", "s", "lower", "positive", estimate="0.5")
    assert not shown.eligible_for_directional_predicate
    assert decides.eligible_for_directional_predicate


def test_a_missing_measurement_carries_a_reason_and_no_estimate():
    with pytest.raises(m.ProtocolError):
        m.Metric("c", "elapsed", "s", "lower", "positive", state="unknown", estimate="1")
    absent = m.Metric("c", "elapsed", "s", "lower", "positive",
                      state="unknown", reason="the pattern did not match")
    assert absent.estimate is None


def test_raw_samples_do_not_inflate_the_execution_count():
    metric = m.Metric("c", "elapsed", "s", "lower", "positive", estimate="0.125",
                      raw_samples=("0.124", "0.127"), inner_sample_count=2,
                      sampling_unit="process_execution")
    assert len(metric.raw_samples) == 2 and metric.inner_sample_count == 2
    # The sampling unit is what says whether these were separate executions.
    assert metric.sampling_unit == "process_execution"


# --- unit conversion ----------------------------------------------------------


@pytest.mark.parametrize("estimate, unit, to_unit, expected", [
    ("1500", "ms", "s", "1.5"),
    ("2", "s", "ns", "2000000000"),
    ("0.000001", "s", "us", "1"),
    ("1", "s", "s", "1"),
])
def test_time_converts_by_exact_powers_of_ten(estimate, unit, to_unit, expected):
    assert m.convert(estimate, unit, to_unit) == expected


@pytest.mark.parametrize("unit, to_unit", [("B", "s"), ("B", "B/s"), ("count", "ratio")])
def test_incompatible_units_are_refused_rather_than_guessed(unit, to_unit):
    """Bytes are not bits and a decimal prefix is not a binary one."""
    with pytest.raises(m.ProtocolError) as exc:
        m.convert("1", unit, to_unit)
    assert exc.value.code == "incompatible_units"


# --- limits -------------------------------------------------------------------


def test_a_file_over_the_size_limit_is_refused_before_it_is_parsed():
    payload = b'{"a": "' + b"x" * (v.MAX_FILE_BYTES + 10) + b'"}'
    obj, issues = v.load_run(payload)
    assert obj is None and codes(issues) == {"limit_exceeded"}


def test_too_many_metric_entries_is_refused():
    run = a_run()
    run["metrics"] = [{"case_id": f"c{i}", "metric_id": "m"} for i in range(v.MAX_METRIC_ENTRIES + 1)]
    assert "limit_exceeded" in codes(v.validate_run(run))


def test_too_many_raw_samples_is_refused():
    run = a_run()
    run["metrics"] = [{"case_id": "c", "metric_id": "m",
                       "raw_samples": ["1"] * (v.MAX_RAW_SAMPLES + 1)}]
    assert "limit_exceeded" in codes(v.validate_run(run))


def test_an_overlong_string_is_refused():
    issues = v.check_limits({"a": "x" * (v.MAX_STRING_CHARS + 1)})
    assert codes(issues) == {"limit_exceeded"}


def test_load_run_reports_unreadable_input_as_an_issue_not_a_traceback():
    obj, issues = v.load_run(b'{"a": 1, "a": 2}')
    assert obj is None and issues and "duplicate" in issues[0].message

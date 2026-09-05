"""Reading legacy records. Design section 16.2.

The property under test throughout: migration never repairs an omission.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ceteris import migration as m
from ceteris.protocol import validation as v

EXAMPLES = Path(__file__).parent.parent / "examples"


def legacy(**overrides) -> dict:
    record = {
        "meta": {"schema_version": 3, "label": "gzip-6", "captured_at": "2026-09-03T18:27:53+00:00",
                 "tool": "ceteris", "tool_version": "0.3.0", "kind": "run"},
        "fields": {
            "source.commit": {"s": "value", "v": "abc", "p": "git rev-parse HEAD"},
            "hardware.gpu_models": {"s": "not_applicable", "d": "nvidia-smi not on PATH"},
            "execution.command": {"s": "value", "v": "hyperfine -N 'gzip -6 f'"},
        },
        "run": {"exit_code": 0, "duration_s": 1.5, "output": "", "drift": []},
        "metrics": {"hyperfine.median_s": {"s": "value", "v": 0.6337}},
    }
    record.update(overrides)
    return record


# --- shape --------------------------------------------------------------------


def test_a_legacy_record_becomes_a_structurally_valid_schema_four_record():
    got = m.migrate(legacy())
    assert got.record["schema_version"] == 4
    issues = {i.code for i in v.validate_run(got.record)}
    # Run and campaign IDs are legitimately absent on an import.
    assert issues <= {"invalid_uuid", "incomplete_observation"}


def test_the_original_is_never_rewritten():
    source = legacy()
    before = json.dumps(source, sort_keys=True)
    m.migrate(source)
    assert json.dumps(source, sort_keys=True) == before


def test_a_migrated_record_says_it_was_converted_not_captured():
    """Calling to_json on an old record must not relabel it as new capture."""
    got = m.migrate(legacy())
    assert m.MIGRATION_ID in got.record["producer"]["record_semantics"]
    assert got.record["migration"]["source_digest"] == m.source_digest(legacy())
    assert got.record["migration"]["source_schema_version"] == 3


def test_an_unsupported_source_schema_is_refused():
    with pytest.raises(ValueError, match="legacy schema"):
        m.migrate(legacy(meta={"schema_version": 9}))


# --- what a legacy record cannot say ------------------------------------------


def test_there_is_no_prospective_plan_so_analysis_is_retrospective():
    got = m.migrate(legacy())
    assert "no_prospective_plan" in got.codes
    assert got.record["migration"]["analysis_origin"] == "retrospective"
    assert got.record["plan_digest"] is None


def test_pre_execution_identity_is_unavailable_not_assumed():
    """The source hashed after the run, so before is genuinely unknown."""
    got = m.migrate(legacy())
    assert "no_pre_execution_identity" in got.codes
    assert got.record["observations"]["before"]["status"] == "unavailable"
    assert got.record["observations"]["before"]["reason"]


def test_no_correctness_evidence_means_unverified_not_passed():
    got = m.migrate(legacy())
    assert "no_correctness_evidence" in got.codes
    assert got.record["correctness"] == []


def test_an_old_not_applicable_stays_ambiguous():
    """In schema 3 it could mean structurally absent or simply not captured."""
    got = m.migrate(legacy())
    assert "ambiguous_not_applicable" in got.codes


def test_an_empty_legacy_drift_list_is_not_read_as_no_drift():
    got = m.migrate(legacy())
    assert "no_drift_observation" in got.codes
    assert got.record["drift"]["status"] == "unavailable"


def test_a_record_that_did_observe_drift_keeps_that_claim():
    source = legacy()
    source["run"]["drift_observed"] = True
    got = m.migrate(source)
    assert got.record["drift"]["status"] == "observed"
    assert "no_drift_observation" not in got.codes


def test_aggregates_are_kept_and_inner_samples_are_not_invented():
    got = m.migrate(legacy())
    metric = got.record["metrics"][0]
    assert metric["estimate"] == "0.6337"
    assert metric["raw_samples"] == [] and metric["inner_sample_count"] is None
    assert "no_raw_samples" in got.codes


def test_a_legacy_metric_has_no_declared_unit_or_direction():
    """It never carried one, so it cannot drive a directional predicate."""
    metric = m.migrate(legacy()).record["metrics"][0]
    assert metric["direction"] == "none"
    assert metric["unit"].startswith("ceteris.legacy:")


def test_capability_coverage_is_never_inferred_from_what_happened_to_be_there():
    got = m.migrate(legacy())
    assert got.record["capabilities"] == []
    assert "no_capability_manifest" in got.codes


# --- identity -----------------------------------------------------------------


def test_importing_the_same_file_twice_is_one_observation():
    """A fresh UUID per import would look like two executions."""
    first = m.migrate(legacy()).record["source_observation_id"]
    second = m.migrate(legacy()).record["source_observation_id"]
    assert first == second


def test_two_different_records_get_different_observation_ids():
    other = legacy()
    other["fields"]["source.commit"]["v"] = "def"
    assert (m.migrate(legacy()).record["source_observation_id"]
            != m.migrate(other).record["source_observation_id"])


def test_a_migrated_record_carries_no_invented_run_id():
    assert m.migrate(legacy()).record["run_id"] is None


# --- policy -------------------------------------------------------------------


def test_a_migrated_record_qualifies_only_when_it_actually_satisfies_the_policy():
    got = m.migrate(legacy())
    assert m.qualifies_for(got, [])["qualifies"] is True
    blocked = m.qualifies_for(got, ["artifact.subject@1", "correctness.required@1"])
    assert blocked["qualifies"] is False
    assert "recapture" in blocked["reason"]
    assert blocked["missing_capabilities"] == ["artifact.subject@1", "correctness.required@1"]


# --- the committed examples ---------------------------------------------------


@pytest.mark.parametrize("name", ["hyperfine", "pingpong", "rostam"])
def test_every_committed_example_migrates_without_gaining_evidence(name):
    paths = sorted((EXAMPLES / name).glob("*.json"))
    assert paths, f"no committed examples under {name}"
    for path in paths:
        source = json.loads(path.read_text())
        got = m.migrate(source)
        assert got.record["migration"]["source_digest"] == m.source_digest(source)
        assert got.record["plan_digest"] is None
        assert got.record["correctness"] == []
        assert got.record["observations"]["before"]["status"] == "unavailable"

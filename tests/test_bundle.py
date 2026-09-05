"""Bundles, receipts and offline verification. Design section 13."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ceteris import bundle as b
from ceteris.protocol.encoding import canonical_bytes, digest


PLAN = {"kind": "ceteris.plan", "schema_version": 1, "experiment_id": "e1"}


def a_report(acceptance="passed") -> dict:
    return {
        "kind": "ceteris.report",
        "schema_version": 1,
        "plan_digest": digest(PLAN),
        "comparison_id": "candidate-v-base",
        "dimensions": {"acceptance": acceptance, "coverage": "sufficient"},
    }


def a_record(run_id="11111111-1111-4111-8111-111111111111") -> dict:
    return {"kind": "ceteris.run", "schema_version": 4, "run_id": run_id}


def written(tmp_path, **kw):
    defaults = dict(plan=PLAN, report=a_report(), records=[a_record()])
    defaults.update(kw)
    receipt = b.write(tmp_path / "bundle", **defaults)
    return tmp_path / "bundle", receipt


# --- the receipt --------------------------------------------------------------


def test_the_receipt_carries_nothing_but_a_manifest_reference():
    """No verdict, no counts, no percentage. A claim printed on the line is
    a claim nobody checked."""
    receipt = b.Receipt("sha256:" + "a" * 64)
    line = receipt.line()
    assert line == "ceteris-receipt v3 manifest=sha256:" + "a" * 64
    assert "verdict" not in line and "%" not in line
    assert b.parse_receipt(line).manifest_digest == receipt.manifest_digest


@pytest.mark.parametrize("line", [
    "ceteris-receipt v3 manifest=sha256:short",
    "ceteris-receipt v9 manifest=sha256:" + "a" * 64,
    "ceteris-certified v1 configs=2",
    "ceteris-receipt manifest=sha256:" + "a" * 64,
    "",
])
def test_a_malformed_or_unsupported_receipt_is_refused(line):
    with pytest.raises(b.ReceiptError):
        b.parse_receipt(line)


# --- writing and verifying ----------------------------------------------------


def test_a_written_bundle_verifies_against_its_receipt(tmp_path):
    root, receipt = written(tmp_path)
    result = b.verify(root, receipt.line())
    assert result.integrity and result.problems == []
    assert result.acceptance == "passed"


def test_protocol_members_are_written_as_canonical_bytes(tmp_path):
    """So a member's object digest and its byte digest are one number."""
    root, _ = written(tmp_path)
    assert (root / "plan.json").read_bytes() == canonical_bytes(PLAN)


def test_the_manifest_does_not_list_itself(tmp_path):
    root, _ = written(tmp_path)
    manifest = json.loads((root / "manifest.json").read_text())
    assert "manifest.json" not in {f["path"] for f in manifest["files"]}


def test_a_receipt_from_another_bundle_does_not_verify(tmp_path):
    root, _ = written(tmp_path)
    other = b.write(tmp_path / "other", plan=PLAN, report=a_report("failed"),
                    records=[a_record()])
    result = b.verify(root, other.line())
    assert not result.integrity
    assert "not the one that receipt was issued for" in result.problems[0]


def test_changing_a_member_breaks_verification(tmp_path):
    root, receipt = written(tmp_path)
    (root / "report.json").write_bytes(canonical_bytes(a_report("failed")))
    result = b.verify(root, receipt.line())
    assert not result.integrity
    assert any("digest" in p for p in result.problems)


def test_an_unlisted_extra_file_is_reported(tmp_path):
    root, receipt = written(tmp_path)
    (root / "records" / "sneaky.json").write_text("{}")
    result = b.verify(root, receipt.line())
    assert any("not listed" in p for p in result.problems)


def test_a_missing_listed_member_is_reported(tmp_path):
    root, receipt = written(tmp_path)
    (root / "records").glob("*.json").__next__().unlink()
    result = b.verify(root, receipt.line())
    assert any("missing from the bundle" in p for p in result.problems)


def test_a_bundle_with_no_manifest_is_refused(tmp_path):
    (tmp_path / "empty").mkdir()
    result = b.verify(tmp_path / "empty", b.Receipt("sha256:" + "a" * 64).line())
    assert not result.integrity and "no manifest" in result.problems[0]


# --- integrity is not acceptance ----------------------------------------------


def test_a_faithfully_recorded_failure_has_perfect_integrity(tmp_path):
    root, receipt = written(tmp_path, report=a_report("failed"))
    result = b.verify(root, receipt.line())
    assert result.integrity is True
    assert result.acceptance == "failed"


def test_require_pass_asks_the_other_question(tmp_path):
    root, receipt = written(tmp_path, report=a_report("failed"))
    result = b.verify(root, receipt.line(), require_pass=True)
    assert result.integrity is True
    assert any("its result is failed" in p for p in result.problems)


def test_a_passing_bundle_satisfies_require_pass(tmp_path):
    root, receipt = written(tmp_path)
    assert b.verify(root, receipt.line(), require_pass=True).problems == []


def test_the_verifier_never_claims_the_experiment_was_honest(tmp_path):
    root, receipt = written(tmp_path)
    result = b.verify(root, receipt.line())
    assert any("do not prove" in note for note in result.notes)
    assert result.producer_authentication == "none"


# --- recomputation ------------------------------------------------------------


def test_the_stored_report_must_be_what_the_plan_and_records_produce(tmp_path):
    """Otherwise the report is an assertion rather than a claim."""
    root, receipt = written(tmp_path)
    agreeing = b.verify(root, receipt.line(), recompute=lambda plan, records: a_report())
    assert agreeing.integrity
    assert any("recomputed" in n for n in agreeing.notes)

    disagreeing = b.verify(root, receipt.line(),
                           recompute=lambda plan, records: a_report("failed"))
    assert not disagreeing.integrity
    assert any("displayed result has been changed" in p for p in disagreeing.problems)


def test_a_report_computed_against_another_plan_is_caught(tmp_path):
    report = a_report()
    report["plan_digest"] = digest({"kind": "ceteris.plan", "schema_version": 1,
                                    "experiment_id": "something-else"})
    root, receipt = written(tmp_path, report=report)
    result = b.verify(root, receipt.line())
    assert any("different plan" in p for p in result.problems)


# --- availability levels ------------------------------------------------------


def test_a_records_only_bundle_does_not_satisfy_an_evidence_complete_requirement(tmp_path):
    root, receipt = written(tmp_path, level="records_only")
    result = b.verify(root, receipt.line(), required_level="evidence_complete")
    assert any("records_only" in p for p in result.problems)


def test_an_evidence_complete_bundle_satisfies_a_records_only_requirement(tmp_path):
    root, receipt = written(tmp_path, level="evidence_complete",
                            evidence=[("harness", b'{"results": []}')])
    assert b.verify(root, receipt.line(), required_level="records_only").problems == []


def test_an_unknown_level_is_refused(tmp_path):
    with pytest.raises(b.BundleError):
        b.write(tmp_path / "x", plan=PLAN, report=a_report(), records=[], level="perfect")


# --- member paths -------------------------------------------------------------


@pytest.mark.parametrize("name", [
    "/etc/passwd", "../escape", "a/../../b", "C:/windows", "a\\b", "", "a//b", "./a",
])
def test_paths_that_escape_the_bundle_are_refused(name):
    with pytest.raises(b.BundleError):
        b.safe_member_path(name)


def test_ordinary_member_paths_are_accepted():
    assert b.safe_member_path("records/abc.json") == "records/abc.json"
    assert b.safe_member_path("evidence/sha256/deadbeef") == "evidence/sha256/deadbeef"


def test_a_symlinked_member_is_refused(tmp_path):
    root, receipt = written(tmp_path)
    target = next((root / "records").glob("*.json"))
    payload = target.read_bytes()
    target.unlink()
    outside = tmp_path / "outside.json"
    outside.write_bytes(payload)
    target.symlink_to(outside)
    result = b.verify(root, receipt.line())
    assert any("symlink" in p for p in result.problems)


# --- redaction ----------------------------------------------------------------


def test_redaction_writes_a_new_bundle_and_leaves_the_original_alone(tmp_path):
    root, receipt = written(tmp_path)
    before = (root / "manifest.json").read_bytes()
    new_receipt = b.redact(root, tmp_path / "redacted",
                           remove=["records/11111111-1111-4111-8111-111111111111.json"],
                           reason="contains a customer path",
                           plan=PLAN, report=a_report(), records=[a_record()])
    assert (root / "manifest.json").read_bytes() == before
    assert new_receipt.manifest_digest != receipt.manifest_digest
    manifest = json.loads((tmp_path / "redacted" / "manifest.json").read_text())
    assert manifest["omitted"][0]["reason"] == "contains a customer path"
    assert not any(f["path"].startswith("records/") for f in manifest["files"])


def test_a_redacted_bundle_verifies_on_its_own_receipt(tmp_path):
    root, _ = written(tmp_path)
    new_receipt = b.redact(root, tmp_path / "redacted", remove=[],
                           reason="disclosure review", plan=PLAN,
                           report=a_report(), records=[a_record()])
    assert b.verify(tmp_path / "redacted", new_receipt.line()).integrity

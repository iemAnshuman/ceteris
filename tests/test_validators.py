"""Correctness evidence. Design section 10.2."""

from __future__ import annotations

import sys

import pytest

from ceteris import validators as v


SUBJECTS = {"program": "sha256:" + "a" * 64}
INPUTS = {"payload": "sha256:" + "b" * 64}


# --- command@1 ----------------------------------------------------------------


def test_a_checker_that_exits_zero_passes():
    claim = v.command([sys.executable, "-c", "raise SystemExit(0)"],
                      subjects=SUBJECTS, inputs=INPUTS, case_ids=["c1"])
    assert claim.result == "passed" and claim.exit_code == 0
    assert claim.case_ids == ("c1",)


def test_a_checker_that_exits_nonzero_fails_the_experiment():
    claim = v.command([sys.executable, "-c", "raise SystemExit(2)"])
    assert claim.result == "failed" and claim.exit_code == 2


def test_a_checker_that_cannot_be_launched_is_unverified_not_passed():
    """Absent evidence is not correctness."""
    claim = v.command(["definitely-not-a-real-checker-xyz"])
    assert claim.result == "unverified"


def test_a_checker_that_hangs_is_a_failure_with_its_timeout_recorded():
    claim = v.command([sys.executable, "-c", "import time; time.sleep(30)"], timeout_s=0.5)
    assert claim.result == "failed" and claim.timeout_s == 0.5
    assert "did not finish" in claim.detail


def test_the_checkers_output_is_kept_as_evidence():
    claim = v.command([sys.executable, "-c", "print('mismatch at byte 12'); raise SystemExit(1)"])
    assert "mismatch at byte 12" in claim.output_tail


# --- output-sha256@1 ----------------------------------------------------------


def test_matching_output_bytes_pass(tmp_path):
    from ceteris.identity import hash_file

    out = tmp_path / "out.bin"
    out.write_bytes(b"expected")
    claim = v.output_sha256(out, hash_file(out))
    assert claim.result == "passed" and claim.scope == "artifact"


def test_different_output_bytes_fail(tmp_path):
    out = tmp_path / "out.bin"
    out.write_bytes(b"something else")
    claim = v.output_sha256(out, "sha256:" + "0" * 64)
    assert claim.result == "failed"


def test_missing_output_cannot_pass(tmp_path):
    claim = v.output_sha256(tmp_path / "never-written.bin", "sha256:" + "0" * 64)
    assert claim.result == "failed" and "not produced" in claim.detail


# --- harness-status@1 ---------------------------------------------------------


@pytest.mark.parametrize("validity, expected", [
    ("valid", "passed"), ("invalid", "failed"),
    ("unverified", "unverified"), (None, "unverified"),
])
def test_a_harness_marker_is_preserved_not_interpreted(validity, expected):
    assert v.harness_status(validity).result == expected


def test_a_harness_that_says_nothing_is_not_a_clean_bill_of_health():
    assert v.harness_status(None).result == "unverified"


# --- binding ------------------------------------------------------------------


def test_a_claim_is_bound_to_the_identities_it_checked():
    """A claim from a previous build is evidence about that build."""
    claim = v.command([sys.executable, "-c", "pass"], subjects=SUBJECTS, inputs=INPUTS)
    assert claim.covers(SUBJECTS, INPUTS)
    assert not claim.covers({"program": "sha256:" + "c" * 64}, INPUTS)
    assert not claim.covers(SUBJECTS, {})


def test_an_invalid_result_or_scope_is_refused():
    with pytest.raises(ValueError):
        v.Claim("x@1", "probably-fine")
    with pytest.raises(ValueError):
        v.Claim("x@1", "passed", scope="wherever")


# --- summary ------------------------------------------------------------------


def test_all_passing_claims_validate():
    claims = [v.harness_status("valid"), v.command([sys.executable, "-c", "pass"])]
    assert v.summarise(claims, required=True)["state"] == "validated"


def test_one_failure_fails_the_whole_summary():
    claims = [v.harness_status("valid"), v.harness_status("invalid")]
    assert v.summarise(claims, required=True)["state"] == "failed"


def test_a_required_check_that_could_not_run_is_unverified_never_validated():
    claims = [v.command(["definitely-not-a-real-checker-xyz"])]
    got = v.summarise(claims, required=True)
    assert got["state"] == "unverified" and got["unverified"] == [v.COMMAND]


def test_no_claims_at_all_is_unverified():
    assert v.summarise([], required=True)["state"] == "unverified"
    assert v.summarise([], required=False)["state"] == "unverified"

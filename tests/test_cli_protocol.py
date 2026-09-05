"""The protocol commands: plan, migrate, bundle. Design section 14."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ceteris import bundle as bundle_mod
from ceteris.cli import main
from ceteris.compare import EXIT_INTEGRITY, EXIT_OK, EXIT_UNDECLARED, EXIT_USAGE
from ceteris.protocol.encoding import digest

EXAMPLES = Path(__file__).parent.parent / "examples"


def experiment_file(tmp_path, **overrides) -> str:
    document = {
        "kind": "ceteris.experiment", "schema_version": 1, "id": "compression-regression",
        "profile": "native-linux-local@1",
        "variants": [{"id": "base", "revision": "main"},
                     {"id": "candidate", "revision": "HEAD"}],
        "benchmark": {"adapter": "hyperfine@1", "argv": ["hyperfine", "-N", "./bench"]},
        "comparisons": [{"id": "candidate-v-base", "baseline": "base", "candidate": "candidate"}],
        "sampling": {"pairs": 20, "order": "balanced-random", "seed": "20260905"},
        "metrics": [{"case_id": "c1", "id": "elapsed", "unit": "s", "direction": "lower",
                     "domain": "positive", "primary": True,
                     "predicate": {"type": "non_regression", "max_relative_regression": "0.05"}}],
    }
    document.update(overrides)
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


# --- plan ---------------------------------------------------------------------


def test_plan_freezes_the_schedule_before_anything_runs(tmp_path, capsys):
    out = tmp_path / "plan.json"
    assert main(["plan", experiment_file(tmp_path), "-o", str(out),
                 "--revision", "base=" + "a" * 40,
                 "--revision", "candidate=" + "b" * 40]) == EXIT_OK
    plan = json.loads(out.read_text())
    assert plan["kind"] == "ceteris.plan"
    assert len(plan["schedule"]) == 40
    assert plan["variants"][0]["revision"] == "a" * 40


def test_planning_the_same_experiment_twice_gives_the_same_digest(tmp_path):
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    source = experiment_file(tmp_path)
    for out in (first, second):
        main(["plan", source, "-o", str(out), "--revision", "base=" + "a" * 40,
              "--revision", "candidate=" + "b" * 40])
    assert digest(json.loads(first.read_text())) == digest(json.loads(second.read_text()))


def test_an_invalid_experiment_is_a_usage_error_with_its_reasons(tmp_path, capsys):
    source = experiment_file(tmp_path, sampling={"pairs": 3, "order": "balanced-random",
                                                 "seed": "s"})
    assert main(["plan", source]) == EXIT_USAGE
    assert "balanced-random" in capsys.readouterr().err


def test_a_malformed_revision_argument_is_refused(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["plan", experiment_file(tmp_path), "--revision", "nonsense"])
    assert exc.value.code == EXIT_USAGE


# --- migrate ------------------------------------------------------------------


def test_migrate_names_what_the_original_could_not_say(tmp_path, capsys):
    source = sorted((EXAMPLES / "hyperfine").glob("*.json"))[0]
    out = tmp_path / "migrated.json"
    assert main(["migrate", str(source), "-o", str(out)]) == EXIT_OK
    captured = capsys.readouterr()
    assert "cannot add evidence" in captured.err
    assert "no_pre_execution_identity" in captured.err
    record = json.loads(out.read_text())
    assert record["schema_version"] == 4
    assert record["plan_digest"] is None


def test_migrate_json_carries_the_limitations_as_data(tmp_path, capsys):
    source = sorted((EXAMPLES / "pingpong").glob("*.json"))[0]
    assert main(["migrate", str(source), "--json"]) == EXIT_OK
    body = json.loads(capsys.readouterr().out)
    codes = {entry["code"] for entry in body["limitations"]}
    assert "no_prospective_plan" in codes
    assert body["record"]["correctness"] == []


# --- bundle -------------------------------------------------------------------


PLAN = {"kind": "ceteris.plan", "schema_version": 1, "experiment_id": "e1"}


def a_bundle(tmp_path, acceptance="passed", level="records_only"):
    report = {"kind": "ceteris.report", "schema_version": 1,
              "plan_digest": digest(PLAN), "comparison_id": "c1",
              "dimensions": {"acceptance": acceptance}}
    receipt = bundle_mod.write(tmp_path / "bundle", plan=PLAN, report=report,
                               records=[{"kind": "ceteris.run", "schema_version": 4,
                                         "run_id": "11111111-1111-4111-8111-111111111111"}],
                               level=level)
    return tmp_path / "bundle", receipt


def test_bundle_verify_reports_integrity_and_result(tmp_path, capsys):
    root, receipt = a_bundle(tmp_path)
    assert main(["bundle", "verify", str(root), receipt.line()]) == EXIT_OK
    out = capsys.readouterr().out
    assert "integrity verified" in out and "result passed" in out


def test_bundle_verify_never_claims_the_experiment_was_honest(tmp_path, capsys):
    root, receipt = a_bundle(tmp_path)
    main(["bundle", "verify", str(root), receipt.line()])
    assert "do not prove" in capsys.readouterr().out


def test_a_tampered_bundle_exits_with_the_integrity_code(tmp_path):
    root, receipt = a_bundle(tmp_path)
    (root / "report.json").write_bytes(b'{"kind":"ceteris.report"}')
    assert main(["bundle", "verify", str(root), receipt.line()]) == EXIT_INTEGRITY


def test_require_pass_separates_genuine_from_passing(tmp_path, capsys):
    root, receipt = a_bundle(tmp_path, acceptance="failed")
    assert main(["bundle", "verify", str(root), receipt.line()]) == EXIT_OK
    assert main(["bundle", "verify", str(root), receipt.line(), "--require-pass"]) == EXIT_UNDECLARED
    assert "result is failed" in capsys.readouterr().out


def test_a_records_only_bundle_cannot_satisfy_an_evidence_complete_requirement(tmp_path):
    root, receipt = a_bundle(tmp_path, level="records_only")
    assert main(["bundle", "verify", str(root), receipt.line(),
                 "--require-level", "evidence_complete"]) == EXIT_UNDECLARED


def test_bundle_inspect_lists_members_and_can_warn_about_disclosure(tmp_path, capsys):
    root, _ = a_bundle(tmp_path)
    assert main(["bundle", "inspect", str(root), "--disclosure"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "plan.json" in out and "records_only" in out
    assert "Disclosure" in out and "before sharing" in out


def test_bundle_verify_json_is_machine_readable(tmp_path, capsys):
    root, receipt = a_bundle(tmp_path)
    main(["bundle", "verify", str(root), receipt.line(), "--json"])
    body = json.loads(capsys.readouterr().out)
    assert body["integrity"] is True
    assert body["producer_authentication"] == "none"

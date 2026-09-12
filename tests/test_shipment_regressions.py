"""Counterexamples reproduced in the 2026-09-09 shipment review."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

from ceteris import certificate
from ceteris.cli import main
from ceteris.compare import compare, DuplicateObservation
from ceteris.model import Fingerprint, value, unknown
from ceteris.runner import _Spool, run_command
from conftest import fp


def test_relabelled_legacy_copies_cannot_manufacture_signal():
    examples = Path(__file__).parent.parent / "examples" / "hyperfine"
    originals = {}
    for path in sorted(examples.glob("*.json")):
        raw = json.loads(path.read_text())
        originals.setdefault(raw["meta"]["label"], raw)
    runs = []
    for original in originals.values():
        for i in range(3):
            raw = copy.deepcopy(original)
            raw["meta"].update(label=f"copy-{i}", repeat=i, series=f"new-{i}")
            runs.append(Fingerprint.from_json(raw))
    with pytest.raises(DuplicateObservation):
        compare(runs, vary=["execution.subject"], require_signal=True)


def test_execution_identity_survives_relabel_and_changed_measurement():
    a = fp("a", hardware__arch="arm64")
    a.meta["execution_id"] = "one-execution"
    b = copy.deepcopy(a)
    b.meta["label"] = "b"
    b.metrics["elapsed"] = value(5)
    with pytest.raises(DuplicateObservation):
        compare([a, b])


def test_distinct_fast_runs_have_distinct_ids(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    runs = [run_command([sys.executable, "-c", "pass"], echo=False) for _ in range(2)]
    assert runs[0].meta["execution_id"] != runs[1].meta["execution_id"]
    compare(runs)  # no DuplicateObservation, even with identical rounded timings


def test_wrapper_and_plugin_share_one_observation():
    parent = fp("wrapper", hardware__arch="arm64")
    parent.meta["execution_id"] = "outer"
    child = fp("pytest", hardware__arch="arm64")
    child.run = {"exit_code": 0, "parent_run_id": "outer"}
    with pytest.raises(DuplicateObservation):
        compare([parent, child])


@pytest.mark.parametrize("run", [
    {"exit_code": 0, "drift_observed": False},
    {"exit_code": 0, "case_coverage": {"state": "incomplete", "expected": ["missing"], "missing": ["missing"]}},
    {"exit_code": 0, "case_coverage": {"state": "sufficient", "expected": ["missing"]}},
])
def test_unavailable_required_evidence_cannot_be_certified(run):
    runs = [fp(label, hardware__arch="arm64") for label in ("a", "b")]
    for r in runs:
        r.run = copy.deepcopy(run)
    report = compare(runs)
    assert report.exit_code == 2
    assert "verdict=indeterminate" in certificate.issue(report)


def test_certificate_binds_coverage_and_identity():
    runs = [fp(label, hardware__arch="arm64") for label in ("a", "b")]
    for i, r in enumerate(runs):
        r.meta["execution_id"] = str(i)
        r.run = {"exit_code": 0, "case_coverage": {"expected": [], "state": "incomplete"}}
    line = certificate.issue(compare(runs))
    runs[0].run["case_coverage"]["expected"] = ["missing"]
    assert not certificate.verify(line, compare(runs)).integrity_verified


@pytest.mark.parametrize("raw", [
    {"fields": {"cpu": {"s": "value"}}},
    {"fields": {}, "run": {"exit_code": "183"}},
    {"fields": {}, "run": {"exit_code": False}},
    {"fields": {}, "run": []},
    {"fields": {}, "metrics": []},
    {"fields": {}, "meta": {"schema_version": 999}},
])
def test_malformed_imports_fail_before_comparison(raw):
    with pytest.raises(ValueError):
        Fingerprint.from_json(raw)


def test_library_records_also_validate_exit_codes():
    runs = [fp(label, cpu="same") for label in ("a", "b")]
    for r in runs:
        r.run = {"exit_code": "183"}
    with pytest.raises(ValueError, match="integer exit_code"):
        compare(runs)


def test_missing_measurements_do_not_disappear_from_signal():
    runs = []
    for variant, measurement in [("a", 1), ("b", 2)]:
        for i in range(4):
            r = fp(f"{variant}{i}", build__variant=variant)
            r.metrics = {"elapsed": value(measurement) if i < 3 else unknown("missing export")}
            runs.append(r)
    report = compare(runs, vary=["build.variant"], require_signal=True)
    assert report.exit_code == 4
    assert not report.noise[0].assessed
    assert "1 of 4" in report.noise[0].reason


def test_spool_bounds_a_single_line_and_counts_actual_bytes():
    spool = _Spool(64)
    spool.add("é" * 10000)
    assert len(spool._tail) == 64
    assert spool.total == 20000
    assert spool.dropped == 19936
    assert spool.text() == "é" * 32


def test_long_line_is_streamed_and_recorded_without_losing_tail(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    record = run_command([sys.executable, "-c", "import sys; sys.stdout.write('x' * 1000000 + 'END')"], echo=False)
    assert record.run["output"].endswith("END")
    assert record.run["output_bytes_total"] == 1000003
    assert record.run["output_bytes_dropped"] == 1000003 - 65536


def test_stale_invalid_ingest_cannot_certify(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    export = tmp_path / "old.json"
    export.write_text(json.dumps({"benchmarks": [
        {"name": "ok", "real_time": 1, "time_unit": "ns"},
        {"name": "bad", "error_occurred": True}]}))
    records = [run_command([sys.executable, "-c", "pass"],
                          ingest=[f"{export}:gbench"], echo=False) for _ in range(2)]
    assert all(r.run["exports"][0]["validity"] == "unavailable" for r in records)
    assert compare(records).exit_code != 0


def test_fresh_ingest_keeps_harness_failure(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    content = json.dumps({"benchmarks": [
        {"name": "ok", "real_time": 1, "time_unit": "ns"},
        {"name": "bad", "error_occurred": True}]})
    cmd = [sys.executable, "-c", f"from pathlib import Path; Path('export.json').write_text({content!r})"]
    records = [run_command(cmd, ingest=["export.json:gbench"], echo=False) for _ in range(2)]
    assert all(r.run["exports"][0]["validity"] == "invalid" for r in records)
    assert all("gbench.ok.real_time_ns" in r.metrics for r in records)
    assert compare(records).exit_code != 0


def test_bundle_cannot_certify_empty_evidence_or_claimed_availability(tmp_path, capsys):
    from ceteris import bundle
    from ceteris.protocol.encoding import digest
    plan = {"kind": "ceteris.plan", "schema_version": 1}
    report = {"plan_digest": digest(plan), "dimensions": {"acceptance": "passed"}}
    receipt = bundle.write(tmp_path, plan=plan, report=report, records=[], level="reproduction_ready")
    assert main(["bundle", "verify", str(tmp_path), str(receipt), "--require-pass",
                 "--require-level", "reproduction_ready", "--json"]) != 0
    result = json.loads(capsys.readouterr().out)
    assert result["integrity"] is True
    assert result["acceptance"] is None
    assert result["supported_semantics"] is False
    assert result["availability_level"] == "records_only"


@pytest.mark.parametrize("member", ["records", "manifest.json"])
def test_bundle_refuses_symlinked_ancestors_and_manifest(tmp_path, member):
    from ceteris import bundle
    from ceteris.protocol.encoding import digest
    root = tmp_path / "bundle"
    plan = {"kind": "ceteris.plan"}
    receipt = bundle.write(root, plan=plan, report={"plan_digest": digest(plan)},
                            records=[{"run_id": "one"}])
    outside = tmp_path / "outside"
    (root / member).rename(outside)
    (root / member).symlink_to(outside, target_is_directory=member == "records")
    result = bundle.verify(root, str(receipt))
    assert not result.integrity
    assert any("symlink" in p for p in result.problems)


def test_bundle_checks_member_limits_before_reading(tmp_path, monkeypatch):
    from ceteris import bundle
    from ceteris.protocol.encoding import digest
    plan = {"kind": "ceteris.plan"}
    receipt = bundle.write(tmp_path, plan=plan, report={"plan_digest": digest(plan)},
                            records=[], evidence=[("large", b"x" * 1024)])
    monkeypatch.setattr(bundle, "MAX_EVIDENCE_BYTES", 512)
    result = bundle.verify(tmp_path, str(receipt))
    assert not result.integrity
    assert any("oversized" in p for p in result.problems)


def test_bundle_rejects_non_object_manifest_without_traceback(tmp_path):
    from ceteris import bundle
    from ceteris.protocol.encoding import digest
    (tmp_path / "manifest.json").write_text("[]")
    result = bundle.verify(tmp_path, str(bundle.Receipt(digest([]))))
    assert not result.integrity


def test_plan_views_cannot_mutate_its_identity():
    from ceteris.experiment import ResolvedPlan
    plan = ResolvedPlan({"policy": {"vary": ["source.commit"]},
                         "schedule": [{"slot": "first"}], "metrics": [{"primary": True}],
                         "analysis_origin": "prospective"})
    original = plan.digest
    plan.to_json()["policy"]["vary"].append("*")
    plan.body["policy"]["vary"].append("*")
    plan.schedule[0]["slot"] = "changed"
    plan.primary_metrics[0]["primary"] = False
    assert plan.digest == original
    assert plan.body["policy"]["vary"] == ["source.commit"]


def test_plan_cannot_silently_substitute_profile(tmp_path):
    from test_cli_protocol import experiment_file
    with pytest.raises(SystemExit) as exc:
        main(["plan", experiment_file(tmp_path), "-o", str(tmp_path / "plan.json")])
    assert exc.value.code == 3
    assert not (tmp_path / "plan.json").exists()


def test_plan_requires_full_commits_and_matching_profile():
    from ceteris.experiment import resolve, AuthoringError
    from test_experiment import authored, PROFILE
    with pytest.raises(AuthoringError, match="immutable commit"):
        resolve(authored(), profile=PROFILE)
    with pytest.raises(AuthoringError, match="supplied"):
        resolve(authored(), profile={"id": "diagnostic", "version": 1},
                revisions={"base": "a" * 40, "candidate": "b" * 40})


def test_actual_action_comparison_uses_frozen_policy(tmp_path):
    import os
    import subprocess
    import yaml
    from ceteris.config import Config
    from ceteris.store import save

    for variant in ("base", "candidate"):
        save(fp(variant, hardware__cpu_model=variant, hardware__arch="arm64"), tmp_path / "runs")
    frozen = tmp_path / "trusted.json"
    frozen.write_text(json.dumps(Config.load().freeze()))
    (tmp_path / "ceteris.json").write_text(json.dumps({"severity": {"hardware.cpu_model": "informational"}}))
    script = next(s["run"] for s in yaml.safe_load(
        (Path(__file__).parent.parent / "action.yml").read_text())["runs"]["steps"]
        if s.get("name") == "Compare")
    env = dict(os.environ, CETERIS_STORE=str(tmp_path / "runs"), CETERIS_CONFIG=str(frozen),
               EXTRA_VARY="", REQUIRE_SIGNAL="false", REPORT_PATH=str(tmp_path / "report.txt"),
               GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"))
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]
    result = subprocess.run(["bash", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "verdict=confounded" in result.stdout


def test_frozen_config_does_not_reactivate_candidate_packs(tmp_path, monkeypatch):
    from ceteris.config import Config
    frozen = Config.load().freeze()
    path = tmp_path / "frozen.json"
    path.write_text(json.dumps(frozen))
    monkeypatch.setattr(Config, "activate_packs", lambda *args: pytest.fail("candidate pack discovery"))
    assert Config.load(path).freeze() == frozen


def test_release_requires_matrix_and_excludes_floating_tag():
    import yaml
    root = Path(__file__).parent.parent
    release = yaml.safe_load((root / ".github/workflows/release.yml").read_text())
    ci = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
    assert release["jobs"]["build"]["needs"] == "validate"
    assert release["jobs"]["validate"]["uses"] == "./.github/workflows/ci.yml"
    assert "workflow_call" in ci.get("on", ci.get(True))
    assert release.get("on", release.get(True))["push"]["tags"] == ["v[0-9]+.[0-9]+.[0-9]+"]


def test_experimental_v2_fails_before_any_setup(tmp_path):
    import subprocess
    import yaml
    action = yaml.safe_load((Path(__file__).parent.parent / "v2/action.yml").read_text())
    step = action["runs"]["steps"][0]
    result = subprocess.run(["bash", "-c", step["run"]], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 2
    assert "experimental" in result.stderr
    assert not list(tmp_path.iterdir())

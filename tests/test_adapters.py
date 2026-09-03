"""Harness adapters.

hyperfine, Google Benchmark and pytest-benchmark fixtures are recorded from
real runs on the machine this was written on. JMH, criterion, OSU, nccl-tests
and MLPerf fixtures are reconstructed from each tool's documented format --
they test the parser against my reading of the docs, not against a file
those tools produced.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from ceteris import adapters
from ceteris.model import State

FX = Path(__file__).parent / "fixtures" / "adapters"


def collect(adapter, output=None, stdout="", cwd=None):
    plan = adapters.Plan(adapter.name, [], str(output) if output else None)
    return adapter.collect(plan, stdout, cwd or str(FX), 0)


def test_hyperfine_real_fixture():
    out = collect(adapters.Hyperfine(), FX / "hyperfine.json")
    # two commands in this export -> numbered; names never contain the command
    assert set(out) == {"hyperfine.1.median_s", "hyperfine.1.min_s", "hyperfine.2.median_s", "hyperfine.2.min_s"}
    assert "sleep 0.01" in out["hyperfine.1.median_s"].provenance
    assert all(f.state is State.VALUE for f in out.values())


def test_google_benchmark_real_fixture():
    out = collect(adapters.GoogleBenchmark(), FX / "google_benchmark.json")
    assert "gbench.BM_sort/1024.real_time_ns" in out
    assert out["gbench.BM_sort/8192.real_time_ns"].value > out["gbench.BM_sort/1024.real_time_ns"].value


def test_pytest_benchmark_real_fixture():
    out = collect(adapters.PytestBenchmark(), FX / "pytest_benchmark.json")
    assert out["pytest.test_join.median_s"].value > 0


def test_jmh_reconstructed_fixture():
    out = collect(adapters.JMH(), FX / "jmh.json")
    assert out["jmh.MyBench.parse.avgt_us_op"].value == 12.345


def test_criterion_reconstructed_fixture(tmp_path):
    shutil.copytree(FX / "criterion", tmp_path / "target" / "criterion")
    plan = adapters.Plan("criterion", [])
    out = adapters.Criterion().collect(plan, "", str(tmp_path), 0)
    assert out["criterion.fib_20.median_ns"].value == 25001.0


def test_osu_reconstructed_fixture():
    out = collect(adapters.OSU(), stdout=(FX / "osu_bw.txt").read_text())
    assert out["osu.Bandwidth_MB_s.1048576B"].value == 12210.03


def test_nccl_reconstructed_fixture():
    out = collect(adapters.NCCLTests(), stdout=(FX / "nccl_tests.txt").read_text())
    assert out["nccl.busbw_GBps.134217728B"].value == 209.44
    assert out["nccl.avg_busbw_GBps"].value == 126.71


def test_mlperf_reconstructed_fixture(tmp_path):
    shutil.copy(FX / "mlperf_log_summary.txt", tmp_path / "mlperf_log_summary.txt")
    out = adapters.MLPerf().collect(adapters.Plan("mlperf", []), "", str(tmp_path), 0)
    assert out["mlperf.samples_per_second"].value == 1234.56
    assert out["mlperf.result"].value == "VALID"


def test_a_missing_output_file_is_unknown_not_empty():
    out = collect(adapters.Hyperfine(), "/nonexistent.json")
    assert out["hyperfine._adapter"].state is State.UNKNOWN


def test_detection_by_command_line():
    assert adapters.detect(["hyperfine", "ls"]).name == "hyperfine"
    assert adapters.detect(["./bench", "--benchmark_min_time=0.1s"]).name == "gbench"
    assert adapters.detect(["pytest", "--benchmark-only"]).name == "pytest"
    assert adapters.detect(["java", "-jar", "b.jar", "-rf", "json"]).name == "jmh"
    assert adapters.detect(["cargo", "bench"]).name == "criterion"
    assert adapters.detect(["mpirun", "-n", "2", "./osu_bw"]).name == "osu"
    assert adapters.detect(["./all_reduce_perf", "-b", "8"]).name == "nccl"
    assert adapters.detect(["python", "-c", "pass"]) is None


def test_hyperfine_plan_injects_export_when_absent(tmp_path):
    plan = adapters.Hyperfine().plan(["hyperfine", "ls"], str(tmp_path))
    assert plan.added_output and "--export-json" in plan.argv
    assert not plan.output.startswith(str(tmp_path)), "injected exports must not land in the working tree"
    os.unlink(plan.output)
    given = adapters.Hyperfine().plan(["hyperfine", "--export-json", "x.json", "ls"], str(tmp_path))
    assert not given.added_output and given.output.endswith("x.json")


def test_ingest_autodetects_format():
    assert "hyperfine.1.median_s" in adapters.ingest(str(FX / "hyperfine.json"))
    assert "gbench.BM_sort/1024.real_time_ns" in adapters.ingest(str(FX / "google_benchmark.json"))
    assert "pytest.test_join.median_s" in adapters.ingest(str(FX / "pytest_benchmark.json"))
    assert "jmh.MyBench.parse.avgt_us_op" in adapters.ingest(str(FX / "jmh.json"))


@pytest.mark.skipif(shutil.which("hyperfine") is None, reason="hyperfine not installed")
def test_end_to_end_hyperfine_zero_config(cfg, tmp_path, monkeypatch):
    """The promise: ceteris run -- hyperfine ... needs no --metric."""
    from ceteris.runner import run_command
    monkeypatch.chdir(tmp_path)
    rec = run_command(["hyperfine", "-N", "--runs", "3", "--warmup", "1", "true"], cfg=cfg, echo=False, label="hf")
    assert rec.meta["adapter"] == "hyperfine"
    assert "hyperfine.median_s" in rec.metrics, rec.metrics  # single command: stable name
    assert rec.fields["execution.command"].value == "hyperfine -N --runs 3 --warmup 1 true"  # original, not augmented
    assert not list(tmp_path.glob("ceteris-hyperfine-*"))  # injected export cleaned up


FAKE_HYPERFINE = """#!/bin/sh
out=""
while [ $# -gt 0 ]; do
  if [ "$1" = "--export-json" ]; then out="$2"; shift; fi
  shift
done
echo "Benchmark 1: fake"
[ -n "$out" ] && printf '{"results":[{"command":"fake","median":0.1,"min":0.09}]}' > "$out"
exit 0
"""


@pytest.mark.skipif(sys.platform == "win32", reason="shell script fake")
def test_a_zero_config_harness_run_in_a_clean_repo_does_not_drift(cfg, tmp_path, monkeypatch):
    """The export file the adapter injects used to be created in the
    working tree, so the after-capture saw an untracked file, source.dirty
    flipped, and the run was reported as drifted."""
    import subprocess
    from ceteris.runner import run_command

    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x"], cwd=repo, check=True)
    fake = tmp_path / "bin"; fake.mkdir()
    (fake / "hyperfine").write_text(FAKE_HYPERFINE); (fake / "hyperfine").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.chdir(repo)
    rec = run_command(["hyperfine", "-N", "true"], cfg=cfg, echo=False, label="hf")
    assert rec.fields["source.dirty"].value is False
    assert rec.run["drift"] == []
    assert rec.metrics["hyperfine.median_s"].value == 0.1
    assert not list(repo.glob("ceteris-*"))

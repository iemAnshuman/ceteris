"""`ceteris run` is the command that makes the tool solve the problem.

These are slower than the rest of the suite because each one performs two real
captures. That is the point of the command.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from ceteris.compare import EXIT_INDETERMINATE, compare
from ceteris.model import State
from ceteris.runner import run_command

PRINTER = "print('size 1024 bytes  bandwidth 57.440 GB/s')"


def test_exit_code_is_passed_through(cfg):
    """Wrapping a benchmark in ceteris must not change how a surrounding
    script behaves."""
    ok = run_command([sys.executable, "-c", "pass"], cfg=cfg, echo=False)
    assert ok.run["exit_code"] == 0
    bad = run_command([sys.executable, "-c", "raise SystemExit(3)"], cfg=cfg, echo=False)
    assert bad.run["exit_code"] == 3


def test_output_is_captured_and_metrics_extracted(cfg):
    record = run_command(
        [sys.executable, "-c", PRINTER],
        cfg=cfg,
        echo=False,
        metric_patterns={"bandwidth_gbs": r"bandwidth ([0-9.]+) GB/s"},
        label="demo",
    )
    assert "57.440" in record.run["output"]
    assert record.metrics["bandwidth_gbs"].value == 57.440
    assert record.run["duration_s"] >= 0


def test_the_launcher_command_line_is_a_comparable_field(cfg):
    """`mpirun -n 16 --bind-to core` is where rank count and binding intent
    actually live. A standalone capture cannot see it."""
    record = run_command([sys.executable, "-c", "pass"], cfg=cfg, echo=False)
    field = record.fields["execution.command"]
    assert field.state is State.VALUE
    assert "-c" in field.value
    assert cfg.severity_of("execution.command") == "critical"


def test_two_runs_of_different_commands_do_not_certify(cfg):
    a = run_command([sys.executable, "-c", "pass"], cfg=cfg, echo=False, label="a")
    b = run_command([sys.executable, "-c", "x = 1"], cfg=cfg, echo=False, label="b")
    report = compare([a, b], cfg=cfg)
    assert report.exit_code != 0
    assert any(r.path == "execution.command" for r in report.violations)


def test_mid_run_environment_change_is_detected(cfg, tmp_path):
    """A rebuild into the same tree, a module swap, a file written into the
    source repo -- the run then has no single well-defined identity."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("hello")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    dirtier = f"open({str(tmp_path / 'b.txt')!r}, 'w').write('x')"
    record = run_command(
        [sys.executable, "-c", dirtier],
        cfg=cfg,
        echo=False,
        repo=str(tmp_path),
        label="dirties-the-tree",
    )
    paths = [c["path"] for c in record.drift]
    assert "source.dirty" in paths

    # Isolate drift: an otherwise identical run that did not drift. Comparing
    # against a differently-invoked run would exit 1 on execution.command
    # instead, since a violation outranks an indeterminate.
    import copy

    steady = copy.deepcopy(record)
    steady.meta["label"] = "steady"
    steady.run["drift"] = []
    report = compare([record, steady], cfg=cfg)
    assert report.drifted and [f.label for f in report.drifted] == ["dirties-the-tree"]
    assert report.exit_code == EXIT_INDETERMINATE


def test_a_command_that_cannot_launch_is_a_clean_error(cfg):
    with pytest.raises(ValueError, match="could not launch"):
        run_command(["definitely-not-a-real-binary-xyz"], cfg=cfg, echo=False)

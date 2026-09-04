"""The wrapped command line, structured so its parts gate independently."""

from __future__ import annotations

import sys

from ceteris import execution
from ceteris.compare import EXIT_OK, EXIT_UNDECLARED, compare
from ceteris.model import State
from ceteris.runner import run_command


def test_mpirun_is_split_into_launcher_and_program():
    launcher, largs, program, pargs = execution.split(
        ["mpirun", "-n", "16", "--bind-to", "core", "./bench", "--size", "4096"]
    )
    assert (launcher, program) == ("mpirun", "./bench")
    assert largs == ["-n", "16", "--bind-to", "core"]
    assert pargs == ["--size", "4096"]


def test_two_valued_mca_options_are_kept_with_the_launcher():
    _, largs, program, _ = execution.split(
        ["mpirun", "--mca", "pml", "ucx", "-np", "4", "./a.out"]
    )
    assert largs == ["--mca", "pml", "ucx", "-np", "4"]
    assert program == "./a.out"


def test_srun_with_equals_options():
    _, largs, program, pargs = execution.split(
        ["srun", "--ntasks=256", "--cpu-bind=cores", "./bench", "1"]
    )
    assert largs == ["--ntasks=256", "--cpu-bind=cores"]
    assert (program, pargs) == ("./bench", ["1"])


def test_a_bare_program_has_no_launcher():
    launcher, largs, program, pargs = execution.split(["./bench", "--size", "1"])
    assert launcher is None and largs == []
    assert (program, pargs) == ("./bench", ["--size", "1"])


def test_program_binary_is_hashed(tmp_path):
    exe = tmp_path / "bench"
    exe.write_bytes(b"#!/bin/sh\necho hi\n")
    fields = execution.collect([str(exe)])
    assert fields["execution.program_sha256"].state is State.VALUE
    assert len(fields["execution.program_sha256"].value) == 64


def test_a_missing_program_hash_is_unknown_not_skipped():
    fields = execution.collect(["mpirun", "-n", "2", "/nonexistent/bench"])
    assert fields["execution.program_sha256"].state is State.UNKNOWN


def test_a_rebuilt_binary_is_caught_even_when_git_is_clean(tmp_path, cfg):
    """The most common invalid comparison: same commit, stale build."""
    exe = tmp_path / "bench"
    exe.write_text("#!/bin/sh\necho v1\n"); exe.chmod(0o755)
    a = run_command([str(exe)], cfg=cfg, echo=False, label="a")
    exe.write_text("#!/bin/sh\necho v2\n")
    b = run_command([str(exe)], cfg=cfg, echo=False, label="b")
    report = compare([a, b], cfg=cfg)
    assert report.exit_code == EXIT_UNDECLARED
    assert {r.path for r in report.violations} == {"execution.program_sha256"}


def test_program_args_can_vary_while_launcher_args_still_gate(tmp_path, cfg):
    """Sweeping a message size must not also waive a rank-count change."""
    exe = tmp_path / "bench"
    exe.write_text("#!/bin/sh\n"); exe.chmod(0o755)
    a = run_command([str(exe), "1024"], cfg=cfg, echo=False, label="a")
    b = run_command([str(exe), "4096"], cfg=cfg, echo=False, label="b")
    assert compare([a, b], vary=["execution.program_args"], cfg=cfg).exit_code == EXIT_OK

    fields = dict(b.fields)
    fields["execution.launcher_args"] = execution.value(["-n", "32"])
    a.fields["execution.launcher_args"] = execution.value(["-n", "16"])
    from ceteris.model import Fingerprint
    c = Fingerprint(fields, {"label": "c"})
    report = compare([a, c], vary=["execution.program_args"], cfg=cfg)
    assert report.exit_code == EXIT_UNDECLARED
    assert any(r.path == "execution.launcher_args" for r in report.violations)


def test_hyperfine_subjects_are_the_timed_commands():
    from ceteris.adapters import Hyperfine

    argv = ["hyperfine", "-N", "--warmup", "1", "--runs", "5", "-L", "n", "1,6",
            "gzip -{n} -c f", "--export-json", "x.json", "--style=basic", "sleep 0.1"]
    assert Hyperfine().subject(argv) == ["gzip -{n} -c f", "sleep 0.1"]


def test_a_script_argument_is_hashed_like_a_binary(tmp_path, monkeypatch, cfg):
    """`python bench.py`: hashing python never sees a changed bench.py."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "bench.py").write_text("x = 1\n")
    from ceteris.model import Fingerprint
    a = Fingerprint(execution.collect([sys.executable, "bench.py"]), {"label": "a"})
    assert a.fields["execution.program_scripts_sha256"].value.keys() == {"bench.py"}
    (tmp_path / "bench.py").write_text("x = 2\n")
    b = Fingerprint(execution.collect([sys.executable, "bench.py"]), {"label": "b"})
    report = compare([a, b], cfg=cfg)
    assert {r.path for r in report.violations} == {"execution.program_scripts_sha256"}

"""The wrapped command line, structured so its parts gate independently."""

from __future__ import annotations

import sys

import pytest

from ceteris import execution
from ceteris.compare import EXIT_INDETERMINATE, EXIT_OK, EXIT_UNDECLARED, compare
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


def test_subjects_are_hashed_and_leave_the_harness_options_behind(tmp_path, monkeypatch):
    exe = tmp_path / "bench"
    exe.write_text("#!/bin/sh\necho v1\n"); exe.chmod(0o755)
    argv = ["hyperfine", "-N", "--runs", "5", f"{exe} --size 1", "sleep 0.1"]
    fields = execution.collect(argv, subjects=[f"{exe} --size 1", "sleep 0.1"])
    assert fields["execution.program"].value == "hyperfine"
    assert fields["execution.program_args"].value == ["-N", "--runs", "5"]
    assert fields["execution.subject"].value == [f"{exe} --size 1", "sleep 0.1"]
    hashes = fields["execution.subject_sha256"].value
    assert set(hashes) == {str(exe), "sleep"} and all(len(h) == 64 for h in hashes.values())


def test_subject_hashes_are_keyed_by_executable_so_arguments_can_vary_alone(cfg):
    """`gzip -6` against `gzip -1` is one binary; declaring that the subject
    varies must be enough."""
    from ceteris.model import Fingerprint
    # sys.executable stands in for the harness binary: the runners have no
    # hyperfine, and an unhashable harness would make the comparison
    # indeterminate for a reason unrelated to what this test is about.
    harness = sys.executable
    a = Fingerprint(execution.collect([harness, "gzip -6 -c f"], subjects=["gzip -6 -c f"]), {"label": "a"})
    b = Fingerprint(execution.collect([harness, "gzip -1 -c f"], subjects=["gzip -1 -c f"]), {"label": "b"})
    assert a.fields["execution.subject_sha256"].value == b.fields["execution.subject_sha256"].value
    assert compare([a, b], vary=["execution.subject"], cfg=cfg).exit_code == EXIT_OK


def test_a_subject_that_cannot_be_found_is_unknown():
    fields = execution.collect(["hyperfine", "/nonexistent/bench 1"], subjects=["/nonexistent/bench 1"])
    assert fields["execution.subject_sha256"].state is State.UNKNOWN
    assert "not found" in fields["execution.subject_sha256"].detail


def test_without_a_harness_the_subject_fields_say_so():
    fields = execution.collect([sys.executable, "-c", "pass"])
    assert fields["execution.subject"].state is State.NOT_APPLICABLE
    assert fields["execution.subject_sha256"].state is State.NOT_APPLICABLE


def test_a_rebuilt_subject_is_caught_although_the_harness_did_not_change(tmp_path, cfg):
    """The flagship case: `hyperfine 'target/release/tool'` hashed hyperfine,
    so a stale or freshly rebuilt tool was invisible."""
    exe = tmp_path / "tool"
    exe.write_text("#!/bin/sh\necho v1\n"); exe.chmod(0o755)
    from ceteris.model import Fingerprint
    harness = sys.executable
    a = Fingerprint(execution.collect([harness, "-N", str(exe)], subjects=[str(exe)]), {"label": "a"})
    exe.write_text("#!/bin/sh\necho v2\n")
    b = Fingerprint(execution.collect([harness, "-N", str(exe)], subjects=[str(exe)]), {"label": "b"})
    report = compare([a, b], cfg=cfg)
    assert report.exit_code == EXIT_UNDECLARED
    assert {r.path for r in report.violations} == {"execution.subject_sha256"}


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
    # and inside a harness subject
    c = execution.collect(["hyperfine", f"{sys.executable} bench.py"], subjects=[f"{sys.executable} bench.py"])
    assert c["execution.subject_scripts_sha256"].value.keys() == {"bench.py"}


def test_the_verbatim_command_keeps_its_quoting():
    fields = execution.collect(["hyperfine", "-N", "gzip -6 -c f"])
    assert fields["execution.command"].value == "hyperfine -N 'gzip -6 -c f'"


# --- F02: token order and launcher grammars -----------------------------------


def test_exclusive_is_a_bare_slurm_flag_not_a_valued_option():
    """It was in the shared valued-option table, so it swallowed the program."""
    _, largs, program, pargs = execution.split(
        ["srun", "--exclusive", "-N", "2", "./bench", "4096"])
    assert largs == ["--exclusive", "-N", "2"]
    assert (program, pargs) == ("./bench", ["4096"])


def test_c_means_different_things_to_srun_and_mpirun():
    """One shared option table cannot be right for both."""
    _, largs, program, _ = execution.split(["srun", "-c", "8", "./bench"])
    assert largs == ["-c", "8"] and program == "./bench"
    _, largs, program, _ = execution.split(["mpirun", "-c", "4", "./bench"])
    assert largs == ["-c", "4"] and program == "./bench"


def test_a_double_dash_ends_the_launcher_arguments():
    _, largs, program, pargs = execution.split(
        ["mpirun", "-n", "2", "--", "./bench", "-n", "99"])
    assert largs == ["-n", "2"]
    assert (program, pargs) == ("./bench", ["-n", "99"])


def test_an_unknown_launcher_option_is_opaque_not_guessed():
    """Guessing whether the next token is a value or the program is how a
    command line silently decomposes into the wrong thing."""
    with pytest.raises(execution.AmbiguousCommand):
        execution.split(["srun", "--brand-new-option", "value", "./bench"])

    fields = execution.collect(["srun", "--brand-new-option", "value", "./bench"])
    assert fields["execution.command"].state is State.VALUE      # ground truth kept
    for name in ("program", "program_sha256", "launcher_args"):
        assert fields[f"execution.{name}"].state is State.UNKNOWN
        assert "--brand-new-option" in fields[f"execution.{name}"].detail


def test_two_unknown_commands_do_not_compare_as_agreeing(cfg):
    from ceteris.model import Fingerprint
    a = Fingerprint(execution.collect(["srun", "--odd", "x", "./one"]), {"label": "a"})
    b = Fingerprint(execution.collect(["srun", "--odd", "y", "./two"]), {"label": "b"})
    assert compare([a, b], cfg=cfg).exit_code == EXIT_INDETERMINATE

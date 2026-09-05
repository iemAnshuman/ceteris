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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_a_signal_killed_benchmark_is_not_reported_as_success(cfg):
    """Popen reports a signal death as a negative code; taking the maximum
    over repeats turned that into 0 and a crashed run passed through."""
    from ceteris.cli import main

    killed = run_command(
        [sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"],
        cfg=cfg, echo=False,
    )
    assert killed.run["exit_code"] == 128 + 15
    assert killed.run["signal"] == 15
    assert main(["run", "--no-store", "-q", "--", sys.executable, "-c",
                 "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"]) == 143


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
    assert "-c" in record.fields["execution.command"].value
    assert record.fields["execution.program_args"].value == ["-c", "pass"]
    assert cfg.severity_of("execution.program_args") == "critical"
    assert cfg.severity_of("execution.launcher_args") == "critical"


def test_two_runs_of_different_commands_do_not_certify(cfg):
    a = run_command([sys.executable, "-c", "pass"], cfg=cfg, echo=False, label="a")
    b = run_command([sys.executable, "-c", "x = 1"], cfg=cfg, echo=False, label="b")
    report = compare([a, b], cfg=cfg)
    assert report.exit_code != 0
    assert any(r.path == "execution.program_args" for r in report.violations)


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


def test_informational_fields_moving_mid_run_are_not_drift(cfg, monkeypatch):
    """Load average changes between any two captures. That is not the
    environment changing, and must not make every run uncertifiable."""
    from ceteris import runner
    from ceteris.model import value

    before = {"system.load_1m": value(1.0), "source.commit": value("abc")}
    after = {"system.load_1m": value(7.5), "source.commit": value("abc")}
    assert runner._drift(before, after, cfg) == []
    after["source.commit"] = value("def")
    assert [c["path"] for c in runner._drift(before, after, cfg)] == ["source.commit"]


def test_non_utf8_output_does_not_lose_the_record(cfg):
    record = run_command(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'bandwidth 12.5 GB/s \\xff\\n')"],
        cfg=cfg, echo=False, metric_patterns={"bw": r"bandwidth ([0-9.]+) GB/s"},
    )
    assert record.run["exit_code"] == 0
    assert record.metrics["bw"].value == 12.5


def test_a_tool_banner_outside_utf8_is_still_read():
    from ceteris.collectors._run import run

    res = run([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'tool 1.2.3 \\xff')"])
    assert res.ok and "1.2.3" in res.stdout


def test_ctrl_c_terminates_the_whole_process_group(cfg, monkeypatch):
    """A wrapper that dies on Ctrl-C and leaves a job running is worse than
    no wrapper, and signalling only the immediate process leaves whatever a
    launcher started behind. See design F10."""
    import ceteris.runner as runner_mod

    events = []

    class FakeProc:
        pid = 4321
        def __init__(self, *a, **k):
            self.stdout = self
        def __iter__(self):
            events.append("reading")
            raise KeyboardInterrupt
        def terminate(self):
            events.append("terminate")
        def wait(self, timeout=None):
            events.append("wait")
            return 143
        def kill(self):
            events.append("kill")

    monkeypatch.setattr(runner_mod.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(runner_mod.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(runner_mod.os, "killpg", lambda pgid, sig: events.append(f"killpg {pgid} {sig}"))
    with pytest.raises(KeyboardInterrupt):
        run_command([sys.executable, "-c", "pass"], cfg=cfg, echo=False)
    assert events[0] == "reading"
    assert f"killpg 4321 {int(runner_mod.signal.SIGTERM)}" in events
    assert "wait" in events


def test_an_unkillable_child_is_killed_after_the_grace_period(cfg, monkeypatch):
    import ceteris.runner as runner_mod

    events = []

    class Stubborn:
        pid = 99
        def __init__(self, *a, **k):
            self.stdout = self
        def __iter__(self):
            raise KeyboardInterrupt
        def wait(self, timeout=None):
            if timeout is not None:
                raise runner_mod.subprocess.TimeoutExpired("cmd", timeout)
            events.append("reaped")
            return -9
        def terminate(self): pass
        def kill(self): events.append("kill")

    monkeypatch.setattr(runner_mod.subprocess, "Popen", Stubborn)
    monkeypatch.setattr(runner_mod.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(runner_mod.os, "killpg", lambda pgid, sig: events.append(f"sig {int(sig)}"))
    with pytest.raises(KeyboardInterrupt):
        run_command([sys.executable, "-c", "pass"], cfg=cfg, echo=False)
    assert events == [f"sig {int(runner_mod.signal.SIGTERM)}",
                      f"sig {int(runner_mod.signal.SIGKILL)}", "reaped"]


def test_a_noisy_benchmark_does_not_accumulate_all_of_its_output(cfg):
    """Only the last 64 KiB was ever saved, but every line was held in memory
    to get there."""
    from ceteris.runner import MAX_OUTPUT

    record = run_command(
        [sys.executable, "-c",
         "print('x' * 200 + '\\n', end='') if False else [print('y' * 200) for _ in range(3000)]"],
        cfg=cfg, echo=False,
    )
    assert len(record.run["output"]) <= MAX_OUTPUT
    assert record.run["output_truncated"] is True
    assert record.run["output_bytes_total"] > MAX_OUTPUT
    assert record.run["output_bytes_dropped"] > 0
    # the tail is kept, not the head
    assert record.run["output"].rstrip().endswith("y" * 200)


def test_short_output_is_not_reported_as_truncated(cfg):
    record = run_command([sys.executable, "-c", "print('small')"], cfg=cfg, echo=False)
    assert record.run["output_truncated"] is False
    assert record.run["output_bytes_dropped"] == 0


# --- F03: the subject is identified before it runs ----------------------------

SELF_REWRITE = """#!/bin/sh
echo "value 1"
printf '#!/bin/sh\\necho "value 2"\\n' > "$0"
"""


@pytest.mark.skipif(sys.platform == "win32", reason="shell script fixture")
def test_a_self_rewriting_program_cannot_look_unchanged(cfg, tmp_path, monkeypatch):
    """Identity used to be collected after the command finished, so it
    described whatever the filesystem held once the run was over. A script
    that replaced itself was recorded as the thing it became, identically on
    both runs, with no drift, and the two runs compared as one subject."""
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "selfrewrite.sh"
    script.write_text(SELF_REWRITE); script.chmod(0o755)

    a = run_command(["./selfrewrite.sh"], cfg=cfg, echo=False, label="a")
    b = run_command(["./selfrewrite.sh"], cfg=cfg, echo=False, label="b")

    assert "value 1" in a.run["output"] and "value 2" in b.run["output"]
    assert a.fields["execution.program_sha256"].value != b.fields["execution.program_sha256"].value
    # The run that rewrote itself says so.
    assert "execution.program_sha256" in [d["path"] for d in a.run["drift"]]
    assert compare([a, b], cfg=cfg).exit_code != 0


@pytest.mark.skipif(sys.platform == "win32", reason="shell script fixture")
def test_a_writable_output_file_is_not_input_drift(cfg, tmp_path, monkeypatch):
    """Only the subject and its script arguments are immutable inputs. A
    benchmark writing its own results must not read as a changed subject."""
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "bench.sh"
    script.write_text('#!/bin/sh\necho "result 1" > out.txt\necho done\n'); script.chmod(0o755)
    rec = run_command(["./bench.sh"], cfg=cfg, echo=False, label="a")
    assert (tmp_path / "out.txt").exists()
    assert [d["path"] for d in rec.run["drift"]] == []


def test_a_file_changing_while_it_is_hashed_is_unknown(tmp_path, monkeypatch):
    """Hashing narrows the race, it does not close it, so the case where the
    file moves under the read has to be stated rather than answered."""
    from ceteris import execution

    target = tmp_path / "moving"
    target.write_bytes(b"a" * 4096)
    real_stat = execution.os.stat
    calls = {"n": 0}

    def shifting_stat(path, *a, **kw):
        result = real_stat(path, *a, **kw)
        calls["n"] += 1
        if calls["n"] > 1 and str(path) == str(target):
            target.write_bytes(b"b" * 8192)
            return real_stat(path, *a, **kw)
        return result

    monkeypatch.setattr(execution.os, "stat", shifting_stat)
    with pytest.raises(execution.FileChangedWhileReading):
        execution._sha256(str(target))


# --- F09: a completed run survives the next one --------------------------------


def test_interrupting_a_later_repeat_keeps_the_earlier_records(tmp_path, monkeypatch, cfg):
    """Repeat one had already run: the machine was occupied and the numbers
    existed. Building the whole list before returning threw them away."""
    import ceteris.runner as runner_mod
    from ceteris.cli import main
    from ceteris import store as store_mod

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CETERIS_STORE", str(tmp_path / "runs"))
    real = runner_mod.run_command
    calls = {"n": 0}

    def interrupt_on_third(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 3:
            raise KeyboardInterrupt
        return real(*a, **kw)

    monkeypatch.setattr(runner_mod, "run_command", interrupt_on_third)
    with pytest.raises(SystemExit) as exc:
        main(["run", "--label", "rep", "-q", "--repeats", "5", "--",
              sys.executable, "-c", "print('bw 5')"])
    assert exc.value.code == 130
    saved = store_mod.all_runs(tmp_path / "runs")
    assert len(saved) == 2, "the two completed runs must still be on disk"
    for path in saved:
        assert store_mod.load(path).run["exit_code"] == 0


def test_run_records_yields_before_the_next_run_starts(cfg):
    """The property the CLI relies on, stated directly."""
    from ceteris.runner import run_records

    seen = []
    for record in run_records([sys.executable, "-c", "pass"], 3, cfg=cfg, echo=False, label="x"):
        seen.append(record.meta["repeat"])
    assert seen == [1, 2, 3]


def test_run_repeated_still_returns_a_list(cfg):
    from ceteris.runner import run_repeated

    records = run_repeated([sys.executable, "-c", "pass"], 2, cfg=cfg, echo=False, label="x")
    assert isinstance(records, list) and len(records) == 2


def test_a_record_is_written_whole_or_not_at_all(tmp_path, cfg, monkeypatch):
    """A crash mid-write must not leave a half-serialised observation."""
    from ceteris import store as store_mod

    record = run_command([sys.executable, "-c", "pass"], cfg=cfg, echo=False, label="x")
    real_replace = store_mod.os.replace

    def fail_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(store_mod.os, "replace", fail_replace)
    with pytest.raises(OSError):
        store_mod.save(record, tmp_path / "runs")
    monkeypatch.setattr(store_mod.os, "replace", real_replace)
    assert store_mod.all_runs(tmp_path / "runs") == [], "no partial record is readable"

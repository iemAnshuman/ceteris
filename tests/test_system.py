"""System state. Linux paths are driven from a fake sysfs tree because this
cannot execute on macOS; CI on Ubuntu runs the real thing."""

from __future__ import annotations

import os
import sys

import pytest

from ceteris.collectors import Context
from ceteris.collectors import system as sys_col
from ceteris.model import State


def _fake_fs(tmp_path, files: dict[str, str]):
    """Redirect the collector's path reads into tmp_path."""
    for rel, content in files.items():
        p = tmp_path / rel.lstrip("/")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    real_exists, real_open, real_isdir, real_listdir = os.path.exists, open, os.path.isdir, os.listdir
    def redirect(p):
        return str(tmp_path / str(p).lstrip("/")) if str(p).startswith(("/sys", "/proc", "/.dockerenv")) else p
    return redirect, real_exists, real_open, real_isdir, real_listdir


@pytest.fixture
def linux_fs(tmp_path, monkeypatch):
    def install(files):
        redirect, ex, op, isd, ls = _fake_fs(tmp_path, files)
        monkeypatch.setattr(sys_col.os.path, "exists", lambda p: ex(redirect(p)))
        monkeypatch.setattr(sys_col.os.path, "isdir", lambda p: isd(redirect(p)))
        monkeypatch.setattr(sys_col.os, "listdir", lambda p: ls(redirect(p)))
        monkeypatch.setattr("builtins.open", lambda p, *a, **k: op(redirect(p), *a, **k))
        monkeypatch.setattr(sys_col, "run", lambda argv, **k: sys_col.run.__wrapped__(argv) if False else _missing(argv))
    return install


def _missing(argv):
    from ceteris.collectors._run import CmdResult
    return CmdResult(argv=argv, ok=False, missing=True, detail=f"{argv[0]} not on PATH")


TUNED = {
    "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor": "performance\n",
    "/sys/devices/system/cpu/intel_pstate/no_turbo": "1\n",
    "/sys/devices/system/cpu/smt/control": "off\n",
    "/proc/sys/kernel/randomize_va_space": "0\n",
    "/sys/kernel/mm/transparent_hugepage/enabled": "always [madvise] never\n",
    "/proc/swaps": "Filename Type Size Used Priority\n",
    "/proc/meminfo": "MemTotal: 100 kB\nMemAvailable: 204800 kB\n",
    "/proc/1/cgroup": "0::/init.scope\n",
}


def test_tuned_linux_box_reads_as_tuned(linux_fs):
    linux_fs(TUNED)
    out = {}
    sys_col._linux(out)
    assert out["system.cpu_governor"].value == "performance"
    assert out["system.turbo"].value == "off"
    assert out["system.smt"].value == "off"
    assert out["system.aslr"].value == "0"
    assert out["system.transparent_hugepages"].value == "madvise"
    assert out["system.swap"].value == "disabled"
    assert out["system.mem_available_mb"].value == 200
    assert out["system.container"].value == "no"


def test_untuned_box_differs_from_tuned_box(linux_fs, cfg):
    """The pyperf/Google Benchmark checklist, as a comparison: same code,
    one box tuned, one not. Must not certify."""
    from ceteris.compare import EXIT_UNDECLARED, compare
    from ceteris.model import Fingerprint
    linux_fs(TUNED); a = {}; sys_col._linux(a)
    untuned = dict(TUNED, **{
        "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor": "powersave\n",
        "/sys/devices/system/cpu/intel_pstate/no_turbo": "0\n",
    })
    linux_fs(untuned); b = {}; sys_col._linux(b)
    report = compare([Fingerprint(a, {"label": "tuned"}), Fingerprint(b, {"label": "untuned"})], cfg=cfg)
    assert report.exit_code == EXIT_UNDECLARED
    assert {r.path for r in report.violations} == {"system.cpu_governor", "system.turbo"}


def test_absent_sysfs_node_is_not_applicable(linux_fs):
    linux_fs({k: v for k, v in TUNED.items() if "smt" not in k})
    out = {}; sys_col._linux(out)
    assert out["system.smt"].state is State.NOT_APPLICABLE


def test_container_is_detected_from_cgroup(linux_fs):
    linux_fs(dict(TUNED, **{"/proc/1/cgroup": "0::/system.slice/docker-abc.scope\n"}))
    out = {}; sys_col._linux(out)
    assert out["system.container"].value == "yes"


def test_load_above_cpu_count_is_flagged_in_detail(monkeypatch, cfg):
    monkeypatch.setattr(sys_col.os, "getloadavg", lambda: (99.0, 1.0, 1.0))
    out = sys_col.collect(Context(cfg=cfg))
    assert "exceeds" in (out["system.load_1m"].detail or "")
    assert cfg.severity_of("system.load_1m") == "informational"


@pytest.mark.skipif(sys.platform != "darwin", reason="real darwin probes")
def test_darwin_probes_produce_values(cfg):
    out = sys_col.collect(Context(cfg=cfg))
    assert out["system.power_source"].value in ("ac", "battery")
    assert out["system.smt"].value in ("on", "off")
    assert out["system.virtualization"].state is State.VALUE


@pytest.mark.skipif(sys.platform != "linux", reason="real linux sysfs")
def test_linux_probes_produce_values_on_linux(cfg):
    out = sys_col.collect(Context(cfg=cfg))
    assert out["system.aslr"].state is State.VALUE
    assert out["system.container"].state is State.VALUE
    assert not [k for k, f in out.items() if f.state is State.ERROR]

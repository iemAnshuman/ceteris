"""Capture must degrade gracefully, and degrade into the *right* state.

The Linux, Slurm and CUDA branches cannot execute on a macOS laptop, so they
are driven from captured command output instead. That tests the parsers against
a recorded reality rather than against nothing, which is the honest limit of
what is checkable here.
"""

from __future__ import annotations

import json
import sys

import pytest

from ceteris.capture import capture
from ceteris.collectors import Context, _run, run_all
from ceteris.collectors import build as build_col
from ceteris.collectors import hardware as hw_col
from ceteris.collectors import runtime as rt_col
from ceteris.collectors import scheduler as sched_col
from ceteris.collectors import source as src_col
from ceteris.config import Config
from ceteris.model import Fingerprint, State


@pytest.fixture
def ctx(cfg: Config) -> Context:
    return Context(cfg=cfg)


def missing(argv, **kw):
    return _run.CmdResult(argv=argv, ok=False, missing=True, detail=f"{argv[0]} not on PATH")


def failing(detail="exit 1"):
    def _f(argv, **kw):
        return _run.CmdResult(argv=argv, ok=False, missing=False, detail=detail)

    return _f


def succeeding(stdout):
    def _f(argv, **kw):
        return _run.CmdResult(argv=argv, ok=True, missing=False, stdout=stdout)

    return _f


# --- the whole point: absent tool vs broken tool ----------------------------


def test_absent_gpu_is_not_applicable_not_unknown(monkeypatch, ctx):
    """No query tool AND no loaded driver means no GPU, which is a fact, not a
    gap. If this were UNKNOWN, every laptop-to-laptop comparison would be
    uncertifiable."""
    monkeypatch.setattr(hw_col, "run", missing)
    monkeypatch.setattr(hw_col, "_gpu_driver_evidence", lambda: [])
    out = hw_col.collect(ctx)
    for key in ("gpu_models", "gpu_count", "gpu_driver", "cuda_runtime"):
        assert out[f"hardware.{key}"].state is State.NOT_APPLICABLE


def test_a_loaded_gpu_driver_without_a_query_tool_is_unknown(monkeypatch, ctx):
    """An AMD box with no rocm-smi installed still has GPUs. Reporting
    not_applicable would let two different AMD machines compare as agreeing
    about their accelerators, which is a silent false certification."""
    monkeypatch.setattr(hw_col, "run", missing)
    monkeypatch.setattr(hw_col, "_gpu_driver_evidence", lambda: ["AMD compute device /dev/kfd"])
    out = {}
    hw_col._gpu(out)
    for key in ("gpu_vendor", "gpu_models", "gpu_count", "gpu_driver"):
        assert out[f"hardware.{key}"].state is State.UNKNOWN
        assert "/dev/kfd" in out[f"hardware.{key}"].detail


def test_two_amd_machines_do_not_compare_as_agreeing(monkeypatch, ctx, cfg):
    from ceteris.compare import EXIT_INDETERMINATE, compare
    from ceteris.model import Fingerprint

    monkeypatch.setattr(hw_col, "run", missing)
    monkeypatch.setattr(hw_col, "_gpu_driver_evidence", lambda: ["amdgpu kernel module"])
    a, b = {}, {}
    hw_col._gpu(a); hw_col._gpu(b)
    report = compare([Fingerprint(a, {"label": "n1"}), Fingerprint(b, {"label": "n2"})], cfg=cfg)
    assert report.exit_code == EXIT_INDETERMINATE


def test_rocm_is_read_when_nvidia_smi_is_absent(monkeypatch, ctx):
    """Fixture shape from rocm-smi documentation, not from a machine here."""
    csv = ("device,Card series,Card model,Card vendor\n"
           "card0,Instinct MI250X,0x0b0c,Advanced Micro Devices Inc.\n"
           "card1,Instinct MI250X,0x0b0c,Advanced Micro Devices Inc.\n"
           "name,value\n"
           "Driver version,6.0.5\n")

    def only_rocm(argv, **kw):
        if argv[0] == "rocm-smi":
            return _run.CmdResult(argv=argv, ok=True, missing=False, stdout=csv)
        return missing(argv)

    monkeypatch.setattr(hw_col, "run", only_rocm)
    out = {}
    hw_col._gpu(out)
    assert out["hardware.gpu_vendor"].value == "amd"
    assert out["hardware.gpu_count"].value == 2
    assert out["hardware.gpu_driver"].value == "6.0.5"


def test_unparseable_rocm_output_is_unknown_not_a_guess(monkeypatch, ctx):
    def only_rocm(argv, **kw):
        if argv[0] == "rocm-smi":
            return _run.CmdResult(argv=argv, ok=True, missing=False, stdout="unexpected banner\n")
        return missing(argv)

    monkeypatch.setattr(hw_col, "run", only_rocm)
    out = {}
    hw_col._gpu(out)
    assert out["hardware.gpu_models"].state is State.UNKNOWN
    assert out["hardware.gpu_driver"].state is State.UNKNOWN


def test_broken_gpu_tool_is_unknown_not_not_applicable(monkeypatch, ctx):
    """nvidia-smi present but hanging means we do not know. Fail closed."""
    monkeypatch.setattr(hw_col, "run", failing("timed out after 10.0s"))
    out = hw_col.collect(ctx)
    assert out["hardware.gpu_driver"].state is State.UNKNOWN
    assert "timed out" in out["hardware.gpu_driver"].detail


def test_absent_mpi_is_not_applicable(monkeypatch, ctx):
    monkeypatch.setattr(rt_col, "run", missing)
    out = rt_col.collect(ctx)
    assert out["runtime.mpi_implementation"].state is State.NOT_APPLICABLE


# --- parsers, driven from real command output -------------------------------


@pytest.mark.parametrize(
    "banner,impl,version",
    [
        ("mpirun (Open MPI) 5.0.9\n\nReport bugs to ...", "Open MPI", "5.0.9"),
        ("HYDRA build details:\n    Version: 4.2.1\nmpich", "MPICH", "4.2.1"),
        ("Intel(R) MPI Library for Linux OS, Version 2021.11", "Intel MPI", "2021.11"),
    ],
)
def test_mpi_banner_parsing(banner, impl, version):
    assert rt_col._parse_mpi(banner) == (impl, version)


@pytest.mark.parametrize(
    "banner,ident,version",
    [
        ("Homebrew clang version 22.1.8\nTarget: arm64-apple-darwin24.6.0", "clang", "22.1.8"),
        ("Apple clang version 17.0.0 (clang-1700.0.13.5)", "apple-clang", "17.0.0"),
        (
            "g++ (Ubuntu 11.4.0-1ubuntu1~22.04) 11.4.0\n"
            "Copyright (C) 2021 Free Software Foundation, Inc.",
            "gcc",
            "11.4.0",
        ),
    ],
)
def test_compiler_banner_parsing(banner, ident, version):
    assert build_col._parse_compiler(banner) == (ident, version)


def test_linux_cpu_parsing_from_recorded_proc_cpuinfo(monkeypatch, ctx, tmp_path):
    """Rostam-shaped /proc/cpuinfo. This path cannot run on darwin."""
    cpuinfo = tmp_path / "cpuinfo"
    body = []
    for i in range(4):
        body.append(
            f"processor\t: {i}\n"
            "model name\t: Intel(R) Xeon(R) Gold 6148 CPU @ 2.40GHz\n"
            f"physical id\t: {i // 2}\n"
            "cpu cores\t: 2\n"
        )
    cpuinfo.write_text("\n".join(body))

    real_open = open
    monkeypatch.setattr(
        "builtins.open",
        lambda p, *a, **k: real_open(cpuinfo, *a, **k)
        if p == "/proc/cpuinfo"
        else real_open(p, *a, **k),
    )
    monkeypatch.setattr(hw_col.glob, "glob", lambda p: ["node0", "node1"])
    out: dict = {}
    hw_col._cpu_linux(out)
    assert out["hardware.cpu_model"].value == "Intel(R) Xeon(R) Gold 6148 CPU @ 2.40GHz"
    assert out["hardware.cpu_cores_logical"].value == 4
    assert out["hardware.cpu_cores_physical"].value == 4  # 2 cores x 2 sockets
    assert out["hardware.numa_nodes"].value == 2


def test_gpu_parsing_from_recorded_nvidia_smi(monkeypatch, ctx):
    monkeypatch.setattr(
        hw_col,
        "run",
        succeeding("NVIDIA A100-SXM4-40GB, 550.54.15\nNVIDIA A100-SXM4-40GB, 550.54.15\n"),
    )
    out: dict = {}
    hw_col._gpu(out)
    assert out["hardware.gpu_count"].value == 2
    assert out["hardware.gpu_driver"].value == "550.54.15"
    assert out["hardware.gpu_models"].value == [
        "NVIDIA A100-SXM4-40GB",
        "NVIDIA A100-SXM4-40GB",
    ]


def test_mismatched_gpu_drivers_are_unknown_not_a_guess(monkeypatch, ctx):
    """Two drivers on one node is a broken node. Picking one would be a guess."""
    monkeypatch.setattr(
        hw_col, "run", succeeding("A100, 550.54.15\nA100, 535.104.05\n")
    )
    out: dict = {}
    hw_col._gpu(out)
    assert out["hardware.gpu_driver"].state is State.UNKNOWN


def test_slurm_fields_populate_under_a_recorded_allocation(monkeypatch, ctx):
    monkeypatch.setenv("SLURM_JOB_ID", "184023")
    monkeypatch.setenv("SLURM_JOB_NUM_NODES", "16")
    monkeypatch.setenv("SLURM_NTASKS", "256")
    monkeypatch.setenv("SLURM_JOB_PARTITION", "buran")
    out = sched_col.collect(ctx)
    assert out["scheduler.job_id"].value == "184023"
    assert out["scheduler.nnodes"].value == "16"
    assert out["scheduler.partition"].value == "buran"
    # Present in the allocation but unset: distinguishable from off-cluster.
    assert out["scheduler.gpus"].state is State.NOT_APPLICABLE
    assert "unset" in out["scheduler.gpus"].detail


def test_slurm_fields_are_not_applicable_off_cluster(monkeypatch, ctx):
    for var in list(sched_col._VARS.values()):
        monkeypatch.delenv(var, raising=False)
    out = sched_col.collect(ctx)
    assert all(f.state is State.NOT_APPLICABLE for f in out.values())
    assert "not running under Slurm" in out["scheduler.job_id"].detail


# --- environment allowlist, the highest-value part of the fingerprint --------


def test_unset_tuning_variable_is_recorded_not_skipped(monkeypatch, ctx):
    """A tuned run and a default run must differ visibly. If the unset side
    were simply absent, the 8 KB default would silently compare equal to a
    tuned 73728."""
    monkeypatch.delenv("LCI_ATTR_PACKET_SIZE", raising=False)
    out = rt_col.collect(ctx)
    field = out["runtime.env.LCI_ATTR_PACKET_SIZE"]
    assert field.state is State.NOT_APPLICABLE
    assert field.detail == "unset"

    monkeypatch.setenv("LCI_ATTR_PACKET_SIZE", "73728")
    out = rt_col.collect(ctx)
    assert out["runtime.env.LCI_ATTR_PACKET_SIZE"].value == "73728"


# --- source -----------------------------------------------------------------


def test_non_git_directory_degrades(ctx, tmp_path):
    ctx.repo = str(tmp_path)
    out = src_col.collect(ctx)
    assert out["source.commit"].state is State.NOT_APPLICABLE
    assert "not inside a git repository" in out["source.commit"].detail


def test_cmake_cache_is_parsed(ctx, tmp_path):
    cache = tmp_path / "CMakeCache.txt"
    cache.write_text(
        "// comment\n"
        "CMAKE_BUILD_TYPE:STRING=Release\n"
        "CMAKE_CXX_FLAGS:STRING=-O3 -march=native\n"
        "HPX_WITH_PARCELPORT_LCI:BOOL=ON\n"
    )
    ctx.cmake_cache = str(tmp_path)
    out = build_col.collect(ctx)
    assert out["build.cmake.CMAKE_BUILD_TYPE"].value == "Release"
    assert out["build.cmake.HPX_WITH_PARCELPORT_LCI"].value == "ON"
    assert out["build.type"].value == "Release"
    assert out["build.cxx_flags"].value == "-O3 -march=native"


def test_missing_cmake_key_is_distinguishable_from_no_cache(ctx, tmp_path):
    cache = tmp_path / "CMakeCache.txt"
    cache.write_text("CMAKE_BUILD_TYPE:STRING=Release\n")
    ctx.cmake_cache = str(cache)
    out = build_col.collect(ctx)
    assert "not present in CMakeCache.txt" in out["build.cmake.CMAKE_CXX_STANDARD"].detail


# --- collector isolation ----------------------------------------------------


def test_a_crashing_collector_does_not_abort_capture(monkeypatch, ctx):
    import ceteris.collectors as collectors

    def boom(_ctx):
        raise RuntimeError("simulated collector failure")

    monkeypatch.setattr(
        collectors,
        "registry",
        lambda: {"hardware": boom, "scheduler": sched_col.collect},
    )
    fields = run_all(ctx)
    assert fields["hardware._collector"].state is State.ERROR
    assert "scheduler.job_id" in fields  # the other collectors still ran


# --- end to end on whatever machine is running the tests --------------------


def test_capture_here_is_valid_serialisable_json(cfg):
    fingerprint = capture(cfg=cfg, label="self-test")
    text = fingerprint.dumps()
    reloaded = Fingerprint.from_json(json.loads(text))
    assert reloaded.content_hash() == fingerprint.content_hash()
    assert not [
        path
        for path, f in fingerprint.fields.items()
        if f.state is State.ERROR
    ], "no collector should error on a healthy machine"


def test_missing_git_is_unknown_not_not_applicable(monkeypatch, ctx, tmp_path):
    """Absence of a tool implies absence of the thing only when the tool IS the
    thing. No nvidia-smi means no NVIDIA stack. No git does not mean no commit
    -- the repository may be right there, unreadable. If this returned
    not_applicable, two runs that both lack git would compare as agreeing on
    their source commit, which is the worst possible failure for this tool."""
    monkeypatch.setattr(src_col, "run", missing)
    ctx.repo = str(tmp_path)
    out = src_col.collect(ctx)
    for name in ("commit", "branch", "dirty", "submodules"):
        assert out[f"source.{name}"].state is State.UNKNOWN


def test_two_runs_without_git_do_not_match_on_commit(monkeypatch, ctx, tmp_path):
    from ceteris.compare import EXIT_INDETERMINATE, compare
    from ceteris.model import Fingerprint

    monkeypatch.setattr(src_col, "run", missing)
    ctx.repo = str(tmp_path)
    fields = src_col.collect(ctx)
    a = Fingerprint(dict(fields), {"label": "run-a"})
    b = Fingerprint(dict(fields), {"label": "run-b"})
    assert compare([a, b], cfg=ctx.cfg).exit_code == EXIT_INDETERMINATE


@pytest.mark.skipif(sys.platform != "linux", reason="exercises the real linux CPU path")
def test_linux_cpu_fields_are_real_values_on_linux(cfg):
    """On CI this is the first time the linux collector runs against a real
    /proc/cpuinfo rather than a fixture."""
    out = hw_col.collect(Context(cfg=cfg))
    assert out["hardware.cpu_model"].state is State.VALUE
    assert out["hardware.cpu_cores_logical"].state is State.VALUE
    assert out["hardware.numa_nodes"].state in (State.VALUE, State.NOT_APPLICABLE)
    assert out["hardware.gpu_models"].state is State.NOT_APPLICABLE

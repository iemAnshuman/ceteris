"""Ecosystem packs activate from what is in the tree and on PATH."""

from __future__ import annotations

import os

from ceteris import packs
from ceteris.collectors import Context, deps
from ceteris.config import Config
from ceteris.model import State


def test_every_pack_file_parses():
    p = packs.available()
    assert {"hpc", "cuda", "rocm", "python", "rust", "jvm", "go", "node"} <= set(p)


def test_rust_pack_activates_on_cargo_toml(tmp_path, monkeypatch):
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n")
    (tmp_path / "Cargo.lock").write_text("# lock v1\n")
    monkeypatch.setattr(packs, "_which", lambda t: None)
    chosen = packs.select(str(tmp_path))
    assert "rust" in chosen and "Cargo.toml" in chosen["rust"][1]
    assert "node" not in chosen


def test_pack_env_vars_merge_into_the_allowlist(tmp_path, monkeypatch):
    (tmp_path / "go.mod").write_text("module x\n")
    monkeypatch.setattr(packs, "_which", lambda t: None)
    cfg = Config.load(tree=str(tmp_path))
    assert "GOMAXPROCS" in cfg.env_allowlist
    assert "LCI_ATTR_PACKET_SIZE" not in cfg.env_allowlist  # hpc pack not active here


def test_forced_pack_and_unknown_pack(tmp_path, monkeypatch):
    monkeypatch.setattr(packs, "_which", lambda t: None)
    assert "cuda" in packs.select(str(tmp_path), ["cuda"])
    import pytest
    with pytest.raises(ValueError, match="unknown pack"):
        packs.select(str(tmp_path), ["ruby"])


def test_lockfile_hash_changes_when_the_lockfile_changes(tmp_path, monkeypatch):
    (tmp_path / "Cargo.toml").write_text("[package]\n")
    (tmp_path / "Cargo.lock").write_text("a = 1\n")
    monkeypatch.setattr(packs, "_which", lambda t: None)
    cfg = Config.load(tree=str(tmp_path))
    ctx = Context(cfg=cfg, repo=str(tmp_path))
    first = deps.collect(ctx)["deps.Cargo.lock"]
    assert first.state is State.VALUE and cfg.severity_of("deps.Cargo.lock") == "critical"
    (tmp_path / "Cargo.lock").write_text("a = 2\n")
    assert deps.collect(ctx)["deps.Cargo.lock"].value != first.value
    assert deps.collect(ctx)["deps.rust-toolchain"].state is State.NOT_APPLICABLE


def test_toolchain_version_is_read_for_the_active_pack(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    monkeypatch.setattr(packs, "_which", lambda t: None)
    cfg = Config.load(tree=str(tmp_path))
    out = deps.collect(Context(cfg=cfg, repo=str(tmp_path)))
    assert out["toolchain.python"].state is State.VALUE
    assert out["packs.active"].value == ["python"]


def test_rocm_pack_activates_on_an_amd_machine(tmp_path, monkeypatch):
    """Rostam's kamand1 has rocm-smi and no nvidia-smi; AMD has its own tuning
    surface (HSA_*, HIP_*, RCCL_*) that the cuda pack does not cover."""
    monkeypatch.setattr(packs, "_which", lambda t: "/usr/bin/rocm-smi" if t == "rocm-smi" else None)
    chosen = packs.select(str(tmp_path))
    assert "rocm" in chosen and "cuda" not in chosen
    cfg = Config.load(tree=str(tmp_path))
    assert "HSA_OVERRIDE_GFX_VERSION" in cfg.env_allowlist
    assert "RCCL_DEBUG" in cfg.env_allowlist


def test_a_version_printed_to_stderr_is_still_captured(tmp_path, monkeypatch):
    """`java -version` writes to stderr and exits 0. Reading only stdout left
    toolchain.java permanently unknown, so no Java project could ever record
    which JDK produced its numbers."""
    from ceteris.collectors import _run

    (tmp_path / "pom.xml").write_text("<project/>")
    monkeypatch.setattr(packs, "_which", lambda t: None)
    cfg = Config.load(tree=str(tmp_path))

    def stderr_only(argv, **kw):
        if argv[0] == "java":
            return _run.CmdResult(argv=argv, ok=True, missing=False, stdout="",
                                  stderr='openjdk version "21.0.5" 2024-10-15 LTS\n')
        return _run.CmdResult(argv=argv, ok=False, missing=True, detail="absent")

    monkeypatch.setattr(deps, "run", stderr_only)
    out = deps.collect(Context(cfg=cfg, repo=str(tmp_path)))
    assert out["toolchain.java"].state is State.VALUE
    assert out["toolchain.java"].value == "21.0.5"

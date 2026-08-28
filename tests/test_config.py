"""Which env vars and build keys matter differs per project, so it is data."""

from __future__ import annotations

import json
import sys

import pytest

from ceteris.config import Config


def test_defaults_load():
    cfg = Config.load()
    assert "LCI_ATTR_PACKET_SIZE" in cfg.env_allowlist
    assert "CMAKE_BUILD_TYPE" in cfg.cmake_keys


def test_longest_glob_wins():
    cfg = Config.load()
    assert cfg.severity_of("hardware.hostnames") == "informational"
    assert cfg.severity_of("hardware.cpu_model") == "material"


def test_unlisted_field_defaults_to_gating():
    assert Config.load().severity_of("some.brand.new.field") == "material"


requires_toml = pytest.mark.skipif(
    sys.version_info < (3, 11), reason="TOML user configs need tomllib (3.11+); JSON works everywhere"
)


@requires_toml
def test_user_config_extends_the_env_allowlist(tmp_path):
    user = tmp_path / "ceteris.toml"
    user.write_text(
        '[capture]\nenv_allowlist = ["MY_PROJECT_TUNABLE"]\n'
        '[severity]\n"hardware.hostnames" = "critical"\n'
    )
    cfg = Config.load(user)
    assert "MY_PROJECT_TUNABLE" in cfg.env_allowlist
    assert "LCI_ATTR_PACKET_SIZE" in cfg.env_allowlist  # defaults are kept
    assert cfg.severity_of("hardware.hostnames") == "critical"


def test_json_config_is_accepted_for_old_interpreters(tmp_path):
    """tomllib needs 3.11. A cluster on an older interpreter should still be
    able to configure the tool without the package taking a TOML dependency."""
    user = tmp_path / "ceteris.json"
    user.write_text(json.dumps({"capture": {"env_allowlist": ["FROM_JSON"]}}))
    assert "FROM_JSON" in Config.load(user).env_allowlist


def test_invalid_severity_is_rejected_loudly(tmp_path):
    user = tmp_path / "bad.json"
    user.write_text(json.dumps({"severity": {"a.b": "extremely-critical"}}))
    with pytest.raises(ValueError, match="expected one of"):
        Config.load(user)


@requires_toml
def test_project_config_in_cwd_is_discovered(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ceteris.toml").write_text('[metrics]\nbw = "x ([0-9]+)"\n')
    assert Config.load().metrics == {"bw": "x ([0-9]+)"}
    monkeypatch.chdir(tmp_path.parent)


def test_a_json_project_config_is_discovered_on_any_interpreter(tmp_path, monkeypatch):
    """The shipped defaults are JSON precisely so that no interpreter is shut
    out. A project config must work the same way."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ceteris.json").write_text(json.dumps({"metrics": {"bw": "x ([0-9]+)"}}))
    assert Config.load().metrics == {"bw": "x ([0-9]+)"}


@pytest.mark.skipif(sys.version_info >= (3, 11), reason="only interpreters without tomllib")
def test_a_toml_config_explains_itself_when_tomllib_is_missing(tmp_path):
    bad = tmp_path / "ceteris.toml"
    bad.write_text("[metrics]\n")
    with pytest.raises(RuntimeError, match="3.11"):
        Config.load(bad)


def test_shipped_defaults_need_no_toml_parser():
    from ceteris import config as cfg_mod
    assert cfg_mod.DEFAULTS_PATH.suffix == ".json"
    from ceteris import packs
    assert packs.available() and all(p.suffix == ".json" for p in packs.PACK_DIR.glob("*.json"))

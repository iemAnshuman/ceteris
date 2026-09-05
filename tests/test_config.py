"""Which env vars and build keys matter differs per project, so it is data."""

from __future__ import annotations

import json
import sys

import pytest

from ceteris import packs
from ceteris.config import Config


def test_defaults_load():
    cfg = Config.load()
    assert "OMP_NUM_THREADS" in cfg.env_allowlist
    assert "CMAKE_BUILD_TYPE" in cfg.cmake_keys


def test_hpc_pack_supplies_the_tuning_variables_the_defaults_do_not(monkeypatch):
    """The HPC knobs live in the `hpc` pack, not in the defaults, so a project
    outside HPC is not asked to carry them.

    `hpc` auto-activates on mpirun/mpiexec/srun being on PATH, so the ambient
    environment decides what Config.load() returns. That is precisely why the
    four tests this one replaces passed on a laptop with MPI installed and
    failed on a clean runner: they asserted a default that was really a pack.
    Pin the PATH probe so this test answers the same on both."""
    monkeypatch.setattr(packs, "_which", lambda t: None)

    base = Config.load()
    assert "LCI_ATTR_PACKET_SIZE" not in base.env_allowlist
    assert "HPX_WITH_PARCELPORT_LCI" not in base.cmake_keys

    hpc = Config.load(packs=["hpc"])
    assert "LCI_ATTR_PACKET_SIZE" in hpc.env_allowlist
    assert "HPX_WITH_PARCELPORT_LCI" in hpc.cmake_keys


def test_longest_glob_wins():
    cfg = Config.load()
    assert cfg.severity_of("hardware.hostnames") == "informational"
    assert cfg.severity_of("hardware.cpu_model") == "material"


def test_where_a_job_landed_does_not_gate():
    """Two jobs on the same partition draw different nodes every time; the
    node list gating meant no two submissions ever compared, and repeats
    across submissions never folded into one configuration. Same for the
    absolute path of a CMake cache: the build tree's location is not the
    build."""
    cfg = Config.load()
    assert cfg.severity_of("scheduler.nodelist") == "informational"
    assert cfg.severity_of("build.cmake_cache_path") == "informational"
    assert cfg.severity_of("scheduler.partition") == "material"
    assert cfg.severity_of("hardware.node_count") == "material"
    assert cfg.severity_of("build.cmake.CMAKE_CXX_FLAGS") == "critical"


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
    assert "OMP_NUM_THREADS" in cfg.env_allowlist  # defaults are kept
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


# --- F08: a policy that has not said what it means ----------------------------

TIED = [("runtime.env.*_SIZE", "critical"), ("runtime.*.LCI_SIZE", "informational")]


def test_equally_specific_rules_that_disagree_are_refused():
    """Which one won depended on the order they were written in, while the
    policy digest, which sorts, stayed identical. A field gated under one
    ordering and not the other, and nothing could tell."""
    from ceteris.config import AmbiguousPolicy

    cfg = Config.load()
    cfg.severity = dict(TIED)
    cfg._severity_cache.clear()
    with pytest.raises(AmbiguousPolicy) as exc:
        cfg.severity_of("runtime.env.LCI_SIZE")
    assert "runtime.env.*_SIZE" in str(exc.value) and "runtime.*.LCI_SIZE" in str(exc.value)


def test_permuting_the_source_order_never_changes_a_valid_policy():
    import itertools

    rules = {"hardware.*": "material", "hardware.gpu_models": "critical",
             "system.*": "material", "system.load_1m": "informational"}
    paths = ["hardware.gpu_models", "hardware.cpu_model", "system.load_1m", "system.turbo"]
    answers = set()
    for order in itertools.permutations(rules.items()):
        cfg = Config.load()
        cfg.severity = dict(order)
        cfg._severity_cache.clear()
        answers.add(tuple(cfg.severity_of(p) for p in paths))
    assert len(answers) == 1


def test_equally_specific_rules_that_agree_are_fine():
    cfg = Config.load()
    cfg.severity = {"runtime.env.*_SIZE": "critical", "runtime.*.LCI_SIZE": "critical"}
    cfg._severity_cache.clear()
    assert cfg.severity_of("runtime.env.LCI_SIZE") == "critical"


def test_a_comparator_tie_is_treated_the_same_as_a_severity_tie():
    from ceteris.config import AmbiguousPolicy

    cfg = Config.load()
    cfg.comparators = {"build.cxx_*": "tokens", "*.cxx_flags": "scalar"}
    cfg._comparator_cache.clear()
    with pytest.raises(AmbiguousPolicy):
        cfg.comparator_of("build.cxx_flags")


def test_the_shipped_defaults_resolve_every_captured_path_unambiguously():
    from ceteris.capture import capture

    cfg = Config.load()
    for path in sorted(capture(cfg=cfg, label="tie-check").fields):
        cfg.severity_of(path)
        cfg.comparator_of(path)


def test_the_policy_identity_names_the_engine_that_read_it():
    """A digest of the rule text says nothing about how ties were decided."""
    import json

    from ceteris.compare import _config_digest
    from ceteris.config import POLICY_ENGINE

    cfg = Config.load()
    before = _config_digest(cfg)
    assert POLICY_ENGINE in json.dumps({"engine": POLICY_ENGINE})
    cfg.severity["a.brand.new.path"] = "critical"
    cfg._severity_cache.clear()
    assert _config_digest(cfg) != before

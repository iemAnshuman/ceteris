"""Container identity.

Almost every HPC site ships software as an Apptainer image. A different image
is a different compiler, a different MPI and a different set of libraries, so
"which image" is as load-bearing as "which commit".
"""

from __future__ import annotations

import os

import pytest

from ceteris.collectors import Context, deps
from ceteris.compare import EXIT_INDETERMINATE, EXIT_UNDECLARED, compare
from ceteris.config import Config
from ceteris.model import Fingerprint, State


@pytest.fixture
def ctx(cfg: Config) -> Context:
    return Context(cfg=cfg)


def clear(monkeypatch):
    for var in deps._IMAGE_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(deps.os.path, "exists", lambda p: False)


def test_outside_a_container_is_not_applicable(monkeypatch):
    clear(monkeypatch)
    out = deps._container()
    assert out["deps.container_runtime"].state is State.NOT_APPLICABLE
    assert out["deps.container_image"].state is State.NOT_APPLICABLE


def test_inside_apptainer_without_an_image_variable_is_unknown(monkeypatch):
    """The silent-match case: two runs in different images both recorded
    not_applicable and compared as equal."""
    clear(monkeypatch)
    monkeypatch.setattr(deps.os.path, "exists", lambda p: p == "/.singularity.d")
    out = deps._container()
    assert out["deps.container_runtime"].value == "apptainer/singularity"
    assert out["deps.container_image"].state is State.UNKNOWN


def test_two_unidentified_containers_do_not_certify(monkeypatch, cfg):
    clear(monkeypatch)
    monkeypatch.setattr(deps.os.path, "exists", lambda p: p == "/.singularity.d")
    a, b = deps._container(), deps._container()
    report = compare([Fingerprint(a, {"label": "a"}), Fingerprint(b, {"label": "b"})], cfg=cfg)
    assert report.exit_code == EXIT_INDETERMINATE


def test_two_different_images_differ(monkeypatch, cfg):
    clear(monkeypatch)
    monkeypatch.setenv("APPTAINER_CONTAINER", "/images/hpx-2026-08.sif")
    a = deps._container()
    monkeypatch.setenv("APPTAINER_CONTAINER", "/images/hpx-2026-07.sif")
    b = deps._container()
    report = compare([Fingerprint(a, {"label": "a"}), Fingerprint(b, {"label": "b"})], cfg=cfg)
    assert report.exit_code == EXIT_UNDECLARED
    assert any(r.path == "deps.container_image" for r in report.violations)
    assert cfg.severity_of("deps.container_image") == "critical"


def test_a_readable_image_file_is_hashed(monkeypatch, tmp_path, cfg):
    clear(monkeypatch)
    img = tmp_path / "hpx.sif"
    img.write_bytes(b"image v1")
    monkeypatch.setattr(deps.os.path, "exists", os.path.exists)
    monkeypatch.setenv("APPTAINER_CONTAINER", str(img))
    first = deps._container()["deps.container_image_sha256"]
    assert first.state is State.VALUE

    # Same name, different build: the name matches, the hash does not.
    img.write_bytes(b"image v2")
    second = deps._container()["deps.container_image_sha256"]
    assert second.value != first.value
    report = compare(
        [Fingerprint({"deps.container_image_sha256": first}, {"label": "a"}),
         Fingerprint({"deps.container_image_sha256": second}, {"label": "b"})], cfg=cfg,
    )
    assert report.exit_code == EXIT_UNDECLARED


def test_docker_is_recognised(monkeypatch):
    clear(monkeypatch)
    monkeypatch.setattr(deps.os.path, "exists", lambda p: p == "/.dockerenv")
    assert deps._container()["deps.container_runtime"].value == "docker"

"""Toolchain versions and dependency identity, driven by the active packs.

'Different library version' is the ML world's LCI_ATTR_PACKET_SIZE: the code
is the same, the numbers move, and nothing says why. Lockfiles are hashed
rather than parsed, so any change in resolved dependencies is a difference
without ceteris knowing the format. Container image identity is recorded
where the runtime exposes it.
"""

from __future__ import annotations

import hashlib
import os
import re

from ..model import Field, not_applicable, unknown, value
from ._run import run


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _version(text: str) -> str | None:
    m = re.search(r"(\d+\.\d+(?:\.\d+)?(?:[-+._a-zA-Z0-9]*)?)", text)
    return m.group(1) if m else None


def collect(ctx) -> dict[str, Field]:
    out: dict[str, Field] = {}
    tree = os.path.abspath(os.path.expanduser(ctx.repo or os.getcwd()))
    packs = getattr(ctx.cfg, "active_packs", {})
    out["packs.active"] = value(sorted(packs), provenance="pack activation") if packs else not_applicable(
        "no ecosystem pack activated", provenance="pack activation")

    for name, (pack, _why) in sorted(packs.items()):
        for tool, argv in pack.get("toolchain", {}).items():
            res = run(list(argv))
            key = f"toolchain.{tool}"
            if res.missing:
                out[key] = not_applicable(res.detail, provenance=res.provenance)
            elif not res.ok and not res.stdout.strip():
                # java -version prints to stderr and exits 0; other tools may
                # exit non-zero yet print a banner. Only a silent failure is unknown.
                out[key] = unknown(res.detail, provenance=res.provenance)
            else:
                text = res.stdout.strip() or res.detail
                ver = _version(text)
                out[key] = value(ver, provenance=res.provenance) if ver else unknown(
                    f"no version in: {text[:80]}", provenance=res.provenance)
        for rel in pack.get("lockfiles", {}).get("files", []):
            path = os.path.join(tree, rel)
            key = f"deps.{rel}"
            if not os.path.isfile(path):
                out[key] = not_applicable("not present in tree", provenance=path)
                continue
            try:
                out[key] = value(_sha256(path), provenance=f"sha256 {path}")
            except OSError as exc:
                out[key] = unknown(str(exc), provenance=path)

    out.update(_container())
    return out


# Files that exist only inside a container runtime. Apptainer/Singularity is
# how most HPC sites ship software, so "which image" is as load-bearing as
# "which commit".
_RUNTIME_MARKERS = (
    ("/.singularity.d", "apptainer/singularity"),
    ("/singularity", "singularity"),
    ("/.dockerenv", "docker"),
    ("/run/.containerenv", "podman"),
)

_IMAGE_VARS = (
    "APPTAINER_CONTAINER", "SINGULARITY_CONTAINER", "APPTAINER_NAME",
    "SINGULARITY_NAME", "CONTAINER_IMAGE", "SLURM_CONTAINER", "CHARLIECLOUD_IMAGE",
)


def _container() -> dict[str, Field]:
    """Container identity.

    Reading only an environment variable meant that two runs inside completely
    different images recorded not_applicable and compared as equal, which is a
    silent false certification: a different image is a different compiler, a
    different MPI and a different set of libraries.

    Inside a container with no identifying variable, the runtime is recorded
    and the image is unknown -- not absent.
    """
    out: dict[str, Field] = {}
    runtime = next((name for path, name in _RUNTIME_MARKERS if os.path.exists(path)), None)
    image, var = None, None
    for name in _IMAGE_VARS:
        if os.environ.get(name):
            image, var = os.environ[name], name
            break

    if runtime is None and image is None:
        out["deps.container_runtime"] = not_applicable(
            "not running inside a container", provenance="/.singularity.d, /.dockerenv, /run/.containerenv"
        )
        out["deps.container_image"] = not_applicable(
            "not running inside a container", provenance="container image variables"
        )
        return out

    out["deps.container_runtime"] = value(
        runtime or "unknown runtime", provenance=f"${var}" if runtime is None else "runtime marker file"
    )
    if image is None:
        out["deps.container_image"] = unknown(
            f"inside a {runtime} container but no image variable is set "
            f"(looked for {', '.join('$' + v for v in _IMAGE_VARS[:4])})",
            provenance="container image variables",
        )
        return out

    out["deps.container_image"] = value(image, provenance=f"${var}")
    # The variable often names a path to the image file. Hash it when it is
    # readable: two sites can use the same name for different builds.
    if os.path.isfile(image):
        try:
            out["deps.container_image_sha256"] = value(_sha256(image), provenance=f"sha256 {image}")
        except OSError as exc:
            out["deps.container_image_sha256"] = unknown(str(exc), provenance=f"sha256 {image}")
    else:
        out["deps.container_image_sha256"] = not_applicable(
            "image is not a readable file from inside the container", provenance=f"${var}"
        )
    return out

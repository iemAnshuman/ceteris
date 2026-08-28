"""Container detection, in one place.

Two collectors used to answer this question separately: system.container
looked for /.dockerenv and docker-shaped cgroup lines, while deps looked for
runtime marker files. Inside a real Apptainer image on Rostam they disagreed
-- deps said apptainer, system said no -- because Apptainer creates neither
of the things system was looking for. A fingerprint that contradicts itself
is worse than one that says nothing, so both now call this.
"""

from __future__ import annotations

import os
import re

# Marker files a runtime leaves inside the container.
RUNTIME_MARKERS = (
    ("/.singularity.d", "apptainer/singularity"),
    ("/singularity", "singularity"),
    ("/.dockerenv", "docker"),
    ("/run/.containerenv", "podman"),
)

# Variables naming the image. Apptainer sets several of these.
IMAGE_VARS = (
    "APPTAINER_CONTAINER", "SINGULARITY_CONTAINER", "APPTAINER_NAME",
    "SINGULARITY_NAME", "CONTAINER_IMAGE", "SLURM_CONTAINER", "CHARLIECLOUD_IMAGE",
)

_CGROUP_RE = re.compile(r"docker|containerd|podman|kubepods|lxc")


def runtime() -> str | None:
    """Name of the container runtime we are inside, or None."""
    for path, name in RUNTIME_MARKERS:
        if os.path.exists(path):
            return name
    for var in IMAGE_VARS:
        if os.environ.get(var):
            return "unknown runtime"
    try:
        with open("/proc/1/cgroup", encoding="utf-8", errors="replace") as handle:
            if _CGROUP_RE.search(handle.read()):
                return "cgroup-detected"
    except OSError:
        pass
    return None


def image() -> tuple[str, str] | None:
    """(image, variable that named it), or None."""
    for var in IMAGE_VARS:
        if os.environ.get(var):
            return os.environ[var], var
    return None

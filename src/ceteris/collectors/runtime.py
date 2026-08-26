"""MPI/LCI runtime identity and tuning environment.

Deliberately NOT captured: the transport actually negotiated at run time.

`mpirun --version` and `ompi_info` report what is *available*, not what got
selected; UCX picks transports during init inside the job. Any value written
here would be a guess presented as a measurement, which is the precise class of
error this tool exists to catch. What is captured instead is the transport
*configuration* visible in the environment, which is a real observation.

The environment allowlist is the highest-value thing in the whole fingerprint.
An unset variable is captured as NOT_APPLICABLE rather than skipped, so a tuned
run and a default run differ visibly instead of both being silently absent.
"""

from __future__ import annotations

import os
import re

from ..model import Field, not_applicable, unknown, value
from ._run import run

_TRANSPORT_VARS = (
    "OMPI_MCA_pml",
    "OMPI_MCA_btl",
    "UCX_TLS",
    "LCI_SERVER",
    "HPX_PARCEL_LCI_ENABLE",
    "HPX_PARCEL_MPI_ENABLE",
    "HPX_PARCEL_TCP_ENABLE",
    "MPICH_NEMESIS_NETMOD",
    "I_MPI_FABRICS",
)


def _parse_mpi(text: str) -> tuple[str | None, str | None]:
    head = text.strip().splitlines()
    if not head:
        return None, None
    first = head[0].strip()
    # MPICH prints "Version: 4.2.1" on a later line of the HYDRA banner, so an
    # explicit Version label anywhere wins over a number on the first line.
    match = re.search(r"version:?\s*(\d+(?:\.\d+)+)", text, re.I) or re.search(
        r"(\d+\.\d+(?:\.\d+)?)", first
    )
    version = match.group(1) if match else None
    lowered = text.lower()
    if "open mpi" in lowered or "openrte" in lowered:
        impl = "Open MPI"
    elif "mpich" in lowered:
        impl = "MPICH"
    elif "intel" in lowered:
        impl = "Intel MPI"
    elif "mvapich" in lowered:
        impl = "MVAPICH"
    else:
        impl = first or None
    return impl, version


def collect(ctx) -> dict[str, Field]:
    out: dict[str, Field] = {}

    res = run(["mpirun", "--version"])
    if res.missing:
        for key in ("mpi_implementation", "mpi_version", "mpi_launcher"):
            out[f"runtime.{key}"] = not_applicable(res.detail, provenance="mpirun")
    elif not res.ok:
        for key in ("mpi_implementation", "mpi_version", "mpi_launcher"):
            out[f"runtime.{key}"] = unknown(res.detail, provenance=res.provenance)
    else:
        impl, version = _parse_mpi(res.stdout)
        out["runtime.mpi_implementation"] = (
            value(impl, provenance=res.provenance)
            if impl
            else unknown("could not parse mpirun --version", provenance=res.provenance)
        )
        out["runtime.mpi_version"] = (
            value(version, provenance=res.provenance)
            if version
            else unknown("no version in mpirun --version", provenance=res.provenance)
        )
        import shutil

        out["runtime.mpi_launcher"] = value(
            shutil.which("mpirun"), provenance="shutil.which('mpirun')"
        )

    configured = {n: os.environ[n] for n in _TRANSPORT_VARS if n in os.environ}
    out["runtime.transport_configured"] = (
        value(configured, provenance="environment")
        if configured
        else not_applicable(
            "no transport-selecting variable set", provenance="environment"
        )
    )

    for name in ctx.cfg.env_allowlist:
        raw = os.environ.get(name)
        out[f"runtime.env.{name}"] = (
            value(raw, provenance=f"${name}")
            if raw is not None
            else not_applicable("unset", provenance=f"${name}")
        )
    return out

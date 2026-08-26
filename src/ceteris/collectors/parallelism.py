"""Rank/thread counts and binding intent.

Deliberately NOT captured: per-rank observed CPU affinity.

Observing where each rank of a 16-node job actually landed requires code
running inside every rank and a reduction step -- a different architecture, not
another field. The tempting alternative is to emit the field permanently as
UNKNOWN, but that would make every comparison uncertifiable and the tool would
be switched off within a week. Emitting it as NOT_APPLICABLE would be worse:
two runs that both failed to observe binding would compare as agreeing.

So the gap is left open and documented rather than papered over. What IS
captured is binding *intent* (the environment variables that decide binding)
plus the capturing process's own affinity mask where the OS exposes one.
"""

from __future__ import annotations

import os

from ..model import Field, not_applicable, value

_RANK_VARS = ("SLURM_NTASKS", "PMI_SIZE", "OMPI_COMM_WORLD_SIZE", "MV2_COMM_WORLD_SIZE")
_THREAD_VARS = ("OMP_NUM_THREADS", "HPX_NUM_THREADS")
_BINDING_VARS = (
    "OMP_PROC_BIND",
    "OMP_PLACES",
    "SLURM_CPU_BIND",
    "SLURM_CPU_BIND_TYPE",
    "I_MPI_PIN",
    "I_MPI_PIN_DOMAIN",
    "GOMP_CPU_AFFINITY",
    "KMP_AFFINITY",
    "HPX_THREAD_BINDING",
)


def _first_set(names) -> tuple[str | None, str | None]:
    for name in names:
        raw = os.environ.get(name)
        if raw is not None:
            return raw, name
    return None, None


def collect(ctx) -> dict[str, Field]:
    out: dict[str, Field] = {}

    raw, src = _first_set(_RANK_VARS)
    out["parallelism.ranks"] = (
        value(raw, provenance=f"${src}")
        if raw is not None
        else not_applicable(
            "no rank-count variable set (" + ", ".join(_RANK_VARS) + ")"
        )
    )

    raw, src = _first_set(_THREAD_VARS)
    out["parallelism.threads"] = (
        value(raw, provenance=f"${src}")
        if raw is not None
        else not_applicable(
            "no thread-count variable set (" + ", ".join(_THREAD_VARS) + ")"
        )
    )

    intent = {n: os.environ[n] for n in _BINDING_VARS if n in os.environ}
    out["parallelism.binding_intent"] = (
        value(intent, provenance="environment")
        if intent
        else not_applicable("no binding variables set", provenance="environment")
    )

    getaffinity = getattr(os, "sched_getaffinity", None)
    if getaffinity is None:
        out["parallelism.capture_process_affinity"] = not_applicable(
            f"{os.uname().sysname} exposes no CPU affinity API",
            provenance="os.sched_getaffinity",
        )
    else:
        cpus = sorted(getaffinity(0))
        out["parallelism.capture_process_affinity"] = value(
            _ranges(cpus), provenance="os.sched_getaffinity(0)"
        )
    return out


def _ranges(cpus: list[int]) -> str:
    if not cpus:
        return ""
    parts, start, prev = [], cpus[0], cpus[0]
    for cpu in cpus[1:] + [None]:
        if cpu is not None and cpu == prev + 1:
            prev = cpu
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        if cpu is not None:
            start = prev = cpu
    return ",".join(parts)

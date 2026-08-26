"""Slurm allocation identity. Everything is not_applicable off a cluster."""

from __future__ import annotations

import os

from ..model import Field, not_applicable, value

_VARS = {
    "job_id": "SLURM_JOB_ID",
    "job_name": "SLURM_JOB_NAME",
    "partition": "SLURM_JOB_PARTITION",
    "nnodes": "SLURM_JOB_NUM_NODES",
    "ntasks": "SLURM_NTASKS",
    "ntasks_per_node": "SLURM_NTASKS_PER_NODE",
    "cpus_per_task": "SLURM_CPUS_PER_TASK",
    "nodelist": "SLURM_JOB_NODELIST",
    "gpus": "SLURM_GPUS_ON_NODE",
    "submit_dir": "SLURM_SUBMIT_DIR",
}


def collect(ctx) -> dict[str, Field]:
    under_slurm = "SLURM_JOB_ID" in os.environ
    out: dict[str, Field] = {}
    for name, var in _VARS.items():
        raw = os.environ.get(var)
        if raw is not None:
            out[f"scheduler.{name}"] = value(raw, provenance=f"${var}")
        else:
            detail = (
                f"${var} unset" if under_slurm else "not running under Slurm"
            )
            out[f"scheduler.{name}"] = not_applicable(detail, provenance=f"${var}")
    return out

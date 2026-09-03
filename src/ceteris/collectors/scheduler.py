"""Batch scheduler allocation identity.

Slurm is not the only scheduler. Reading only SLURM_* meant that on a PBS,
LSF, Flux or Grid Engine cluster every field came back not_applicable with
the detail "not running under Slurm" -- so two completely different
allocations compared as agreeing about their shape. Same failure as reading a
missing nvidia-smi as "no GPU": the absence of the thing I know how to read
is not the absence of the thing.

Each family maps its own variables onto one canonical set of fields, so a
comparison between two PBS jobs works the same way as between two Slurm jobs.
A field a family does not expose is not_applicable for that family, which is
true; a family we do not recognise leaves scheduler.system unknown rather
than claiming there is no scheduler.
"""

from __future__ import annotations

import os

from ..model import Field, not_applicable, unknown, value

FIELDS = (
    "job_id", "job_name", "partition", "nnodes", "ntasks",
    "ntasks_per_node", "cpus_per_task", "nodelist", "gpus", "submit_dir",
)

# (name, marker variable, {canonical field: environment variable})
FAMILIES = (
    ("slurm", "SLURM_JOB_ID", {
        "job_id": "SLURM_JOB_ID", "job_name": "SLURM_JOB_NAME",
        "partition": "SLURM_JOB_PARTITION", "nnodes": "SLURM_JOB_NUM_NODES",
        "ntasks": "SLURM_NTASKS", "ntasks_per_node": "SLURM_NTASKS_PER_NODE",
        "cpus_per_task": "SLURM_CPUS_PER_TASK", "nodelist": "SLURM_JOB_NODELIST",
        "gpus": "SLURM_GPUS_ON_NODE", "submit_dir": "SLURM_SUBMIT_DIR",
    }),
    ("pbs", "PBS_JOBID", {
        "job_id": "PBS_JOBID", "job_name": "PBS_JOBNAME", "partition": "PBS_QUEUE",
        "nnodes": "PBS_NUM_NODES", "ntasks": "PBS_NP",
        "ntasks_per_node": "PBS_NUM_PPN", "nodelist": "PBS_NODEFILE",
        "gpus": "PBS_GPUFILE", "submit_dir": "PBS_O_WORKDIR",
    }),
    ("lsf", "LSB_JOBID", {
        "job_id": "LSB_JOBID", "job_name": "LSB_JOBNAME", "partition": "LSB_QUEUE",
        "ntasks": "LSB_DJOB_NUMPROC",
        "nodelist": "LSB_HOSTS", "submit_dir": "LS_SUBCWD",
    }),
    ("flux", "FLUX_JOB_ID", {
        "job_id": "FLUX_JOB_ID", "nnodes": "FLUX_JOB_NNODES",
        "ntasks": "FLUX_JOB_SIZE", "ntasks_per_node": "FLUX_TASKS_PER_NODE",
    }),
    ("sge", "JOB_ID", {
        "job_id": "JOB_ID", "job_name": "JOB_NAME", "partition": "QUEUE",
        "ntasks": "NSLOTS", "nodelist": "PE_HOSTFILE", "submit_dir": "SGE_O_WORKDIR",
    }),
)

# Variables that mean "some batch scheduler is here" without telling us which.
_GENERIC_MARKERS = ("BATCH_JOBID", "JOB_ID", "COBALT_JOBID", "OAR_JOB_ID", "PJM_JOBID")


def detect() -> tuple[str, dict[str, str]] | None:
    for name, marker, mapping in FAMILIES:
        if os.environ.get(marker):
            return name, mapping
    return None


def collect(ctx) -> dict[str, Field]:
    out: dict[str, Field] = {}
    found = detect()

    if found is None:
        unrecognised = [v for v in _GENERIC_MARKERS if os.environ.get(v)]
        if unrecognised:
            # Something scheduled this. Claiming otherwise would let two
            # different allocations match on every field.
            out["scheduler.system"] = unknown(
                "a batch scheduler is present (" + ", ".join(f"${v}" for v in unrecognised)
                + ") but is not one of " + ", ".join(n for n, _, _ in FAMILIES),
                provenance="environment",
            )
            for name in FIELDS:
                out[f"scheduler.{name}"] = unknown(
                    "unrecognised batch scheduler", provenance="environment"
                )
            return out
        known = ", ".join(n for n, _, _ in FAMILIES)
        out["scheduler.system"] = not_applicable(
            f"no batch scheduler in the environment (checked {known})", provenance="environment"
        )
        for name in FIELDS:
            out[f"scheduler.{name}"] = not_applicable(
                "not running under a batch scheduler", provenance="environment"
            )
        return out

    system, mapping = found
    out["scheduler.system"] = value(system, provenance=f"${mapping['job_id']} set")
    for name in FIELDS:
        var = mapping.get(name)
        if system == "lsf" and name == "nnodes":
            # LSF exposes no node count; LSB_MAX_NUM_PROCESSORS is a slot
            # count and once stood in here, so a 40-slot single-node job read
            # as a 40-node allocation. LSB_HOSTS lists one host per slot.
            hosts = os.environ.get("LSB_HOSTS", "").split()
            out["scheduler.nnodes"] = (
                value(len(set(hosts)), provenance="distinct hosts in $LSB_HOSTS")
                if hosts else not_applicable("$LSB_HOSTS unset", provenance="$LSB_HOSTS")
            )
            continue
        if var is None:
            out[f"scheduler.{name}"] = not_applicable(
                f"{system} does not expose this", provenance=f"{system} environment"
            )
            continue
        raw = os.environ.get(var)
        out[f"scheduler.{name}"] = (
            value(raw, provenance=f"${var}") if raw is not None
            else not_applicable(f"${var} unset", provenance=f"${var}")
        )
    return out

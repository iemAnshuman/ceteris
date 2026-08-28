"""`ceteris doctor` -- what did the capture actually manage to see?

A fingerprint is 150 fields. Reading it by eye to decide whether the tool
understood the machine does not scale, and it is exactly what somebody has to
do on a cluster the author cannot log in to.

Doctor answers three questions:

  what could not be read          every unknown and error, with its reason
  what looks wrong                a claim contradicted by other evidence
  what is fine but worth knowing  tuning that will widen the noise floor

The middle group is the important one. "No GPU" is a normal answer on a
laptop and a suspicious one on a machine with /dev/kfd, and only the second
case is worth a human's attention.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .model import Fingerprint, State

OK, NOTE, SUSPECT, BLIND = "ok", "note", "suspect", "blind"


@dataclass
class Finding:
    level: str
    field: str
    message: str


def _v(fp: Fingerprint, path: str):
    f = fp.fields.get(path)
    return f.value if f is not None and f.state is State.VALUE else None


def _state(fp: Fingerprint, path: str) -> str | None:
    f = fp.fields.get(path)
    return f.state.value if f is not None else None


def _gpu_contradiction(fp: Fingerprint, local: bool) -> Finding | None:
    """The check that would have caught the AMD bug."""
    if _state(fp, "hardware.gpu_models") != "not_applicable":
        return None
    if not local:
        return None
    present = [p for p in ("/dev/kfd", "/proc/driver/nvidia/version",
                           "/sys/module/amdgpu", "/sys/module/nvidia") if os.path.exists(p)]
    if present:
        return Finding(
            SUSPECT, "hardware.gpu_models",
            "reported as absent, but this machine has " + ", ".join(present)
            + " -- a GPU driver is loaded and was not identified",
        )
    return None


def _scheduler_contradiction(fp: Fingerprint, local: bool) -> Finding | None:
    if _state(fp, "scheduler.system") != "not_applicable" or not local:
        return None
    hints = [v for v in ("PBS_JOBID", "LSB_JOBID", "FLUX_JOB_ID", "JOB_ID",
                         "COBALT_JOBID", "OAR_JOB_ID", "PJM_JOBID") if os.environ.get(v)]
    if hints:
        return Finding(SUSPECT, "scheduler.system",
                       "reported as absent, but " + ", ".join("$" + h for h in hints) + " is set")
    return None


def _container_contradiction(fp: Fingerprint, local: bool) -> Finding | None:
    if _state(fp, "deps.container_runtime") != "not_applicable" or not local:
        return None
    markers = [p for p in ("/.singularity.d", "/singularity", "/.dockerenv",
                           "/run/.containerenv") if os.path.exists(p)]
    if markers:
        return Finding(SUSPECT, "deps.container_runtime",
                       "reported as absent, but " + ", ".join(markers) + " exists")
    return None


def diagnose(fp: Fingerprint, local: bool = True) -> list[Finding]:
    """local=False when inspecting a record captured on another machine, where
    checking this machine's filesystem would be meaningless."""
    findings: list[Finding] = []

    for path in sorted(fp.fields):
        f = fp.fields[path]
        if f.state is State.ERROR:
            findings.append(Finding(BLIND, path, f"collector failed: {f.detail}"))
        elif f.state is State.UNKNOWN:
            findings.append(Finding(BLIND, path, f.detail or "could not be read"))

    for check in (_gpu_contradiction, _scheduler_contradiction, _container_contradiction):
        found = check(fp, local)
        if found:
            findings.append(found)

    # Tuning that widens the noise floor. Not errors -- things that make the
    # numbers move, which is worth knowing before blaming a code change.
    for path, bad, why in (
        ("system.cpu_governor", ("powersave", "ondemand", "schedutil", "conservative"),
         "a scaling governor changes clock speed under load"),
        ("system.turbo", ("on",), "turbo is not a sustainable clock; the first run of a pair often wins"),
        ("system.power_source", ("battery",), "on battery the CPU is throttled"),
        ("system.thermal_throttle", None, "the machine is thermally throttled"),
    ):
        val = _v(fp, path)
        if val is None:
            continue
        hit = (val in bad) if bad else (str(val) not in ("none", "0"))
        if hit:
            findings.append(Finding(NOTE, path, f"{val}: {why}"))

    load = _v(fp, "system.load_1m")
    cpus = _v(fp, "hardware.cpu_cores_logical")
    if isinstance(load, (int, float)) and isinstance(cpus, int) and load > cpus * 0.5:
        findings.append(Finding(NOTE, "system.load_1m",
                                f"{load} on {cpus} cpus: the machine was busy during capture"))

    if _state(fp, "source.dirty") == "value" and _v(fp, "source.dirty"):
        findings.append(Finding(NOTE, "source.dirty",
                                "the working tree had uncommitted changes; the commit does not describe the code"))
    return findings


def render(fp: Fingerprint, findings: list[Finding]) -> str:
    counts = {s: 0 for s in (State.VALUE, State.NOT_APPLICABLE, State.UNKNOWN, State.ERROR)}
    for f in fp.fields.values():
        counts[f.state] = counts.get(f.state, 0) + 1
    out = [
        f"{fp.label}: {len(fp.fields)} fields "
        f"({counts[State.VALUE]} captured, {counts[State.NOT_APPLICABLE]} not applicable, "
        f"{counts[State.UNKNOWN]} unknown, {counts[State.ERROR]} error)",
        "",
    ]
    groups = [
        (SUSPECT, "LOOKS WRONG (a claim contradicted by this machine):"),
        (BLIND, "COULD NOT BE READ (these block certification):"),
        (NOTE, "WORTH KNOWING (will widen the noise floor):"),
    ]
    for level, heading in groups:
        rows = [f for f in findings if f.level == level]
        if not rows:
            continue
        out.append(heading)
        width = min(max(len(r.field) for r in rows), 34)
        for r in rows:
            out.append(f"  {r.field.ljust(width)}  {r.message}")
        out.append("")

    if not findings:
        out.append("Nothing to report: every field was either captured or is genuinely absent.")
    else:
        packs = _v(fp, "packs.active")
        if packs:
            out.append(f"Active ecosystem packs: {', '.join(packs)}")
    return "\n".join(out).rstrip() + "\n"


def exit_code(findings: list[Finding]) -> int:
    if any(f.level == SUSPECT for f in findings):
        return 1
    if any(f.level == BLIND for f in findings):
        return 2
    return 0

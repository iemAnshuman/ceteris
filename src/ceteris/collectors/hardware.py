"""Node identity: OS, CPU, NUMA, GPU."""

from __future__ import annotations

import glob
import os
import platform
import re

from ..model import Field, not_applicable, unknown, value
from ._run import run


def _sysctl(key: str) -> tuple[str | None, str]:
    res = run(["sysctl", "-n", key])
    if res.ok:
        return res.stdout.strip(), res.provenance
    return None, res.provenance


def _cpu_darwin(out: dict[str, Field]) -> None:
    brand, prov = _sysctl("machdep.cpu.brand_string")
    out["hardware.cpu_model"] = (
        value(brand, provenance=prov) if brand else unknown("sysctl failed", prov)
    )
    for path, key in (
        ("hw.physicalcpu", "cpu_cores_physical"),
        ("hw.logicalcpu", "cpu_cores_logical"),
    ):
        raw, prov = _sysctl(path)
        out[f"hardware.{key}"] = (
            value(int(raw), provenance=prov) if raw else unknown("sysctl failed", prov)
        )
    out["hardware.numa_nodes"] = not_applicable(
        "darwin exposes no NUMA topology", provenance="sysctl"
    )


def _cpu_linux(out: dict[str, Field]) -> None:
    prov = "/proc/cpuinfo"
    try:
        text = open(prov, encoding="utf-8", errors="replace").read()
    except OSError as exc:
        for key in ("cpu_model", "cpu_cores_physical", "cpu_cores_logical"):
            out[f"hardware.{key}"] = unknown(str(exc), provenance=prov)
    else:
        model = re.search(r"^model name\s*:\s*(.+)$", text, re.M)
        if model is None:
            model = re.search(r"^Model\s*:\s*(.+)$", text, re.M)
        out["hardware.cpu_model"] = (
            value(model.group(1).strip(), provenance=prov)
            if model
            else unknown("no model name line in /proc/cpuinfo", provenance=prov)
        )
        logical = len(re.findall(r"^processor\s*:", text, re.M))
        out["hardware.cpu_cores_logical"] = (
            value(logical, provenance=prov)
            if logical
            else unknown("no processor lines", provenance=prov)
        )
        cores = re.search(r"^cpu cores\s*:\s*(\d+)$", text, re.M)
        sockets = len(set(re.findall(r"^physical id\s*:\s*(\d+)$", text, re.M)))
        if cores and sockets:
            out["hardware.cpu_cores_physical"] = value(
                int(cores.group(1)) * sockets, provenance=prov
            )
        else:
            out["hardware.cpu_cores_physical"] = unknown(
                "no 'cpu cores'/'physical id' lines", provenance=prov
            )

    nodes = glob.glob("/sys/devices/system/node/node[0-9]*")
    node_prov = "/sys/devices/system/node/node*"
    out["hardware.numa_nodes"] = (
        value(len(nodes), provenance=node_prov)
        if nodes
        else not_applicable("no NUMA nodes exposed in sysfs", provenance=node_prov)
    )


def _gpu(out: dict[str, Field]) -> None:
    res = run(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version",
            "--format=csv,noheader",
        ],
        timeout=10,
    )
    if res.missing:
        for key in ("gpu_models", "gpu_count", "gpu_driver"):
            out[f"hardware.{key}"] = not_applicable(res.detail, provenance="nvidia-smi")
    elif not res.ok:
        for key in ("gpu_models", "gpu_count", "gpu_driver"):
            out[f"hardware.{key}"] = unknown(res.detail, provenance=res.provenance)
    else:
        rows = [r.strip() for r in res.stdout.splitlines() if r.strip()]
        models, drivers = [], set()
        for row in rows:
            parts = [p.strip() for p in row.split(",")]
            models.append(parts[0])
            if len(parts) > 1:
                drivers.add(parts[1])
        out["hardware.gpu_models"] = value(sorted(models), provenance=res.provenance)
        out["hardware.gpu_count"] = value(len(models), provenance=res.provenance)
        out["hardware.gpu_driver"] = (
            value(sorted(drivers)[0], provenance=res.provenance)
            if len(drivers) == 1
            else unknown(
                f"GPUs report differing driver versions: {sorted(drivers)}",
                provenance=res.provenance,
            )
        )

    nvcc = run(["nvcc", "--version"])
    if nvcc.missing:
        out["hardware.cuda_runtime"] = not_applicable(nvcc.detail, provenance="nvcc")
    elif not nvcc.ok:
        out["hardware.cuda_runtime"] = unknown(nvcc.detail, provenance=nvcc.provenance)
    else:
        match = re.search(r"release\s+([0-9.]+)", nvcc.stdout)
        out["hardware.cuda_runtime"] = (
            value(match.group(1), provenance=nvcc.provenance)
            if match
            else unknown("could not parse nvcc --version", provenance=nvcc.provenance)
        )


def collect(ctx) -> dict[str, Field]:
    uname = platform.uname()
    out: dict[str, Field] = {
        "hardware.hostname": value(uname.node, provenance="platform.uname().node"),
        "hardware.os": value(uname.system, provenance="platform.uname().system"),
        "hardware.os_version": value(
            platform.mac_ver()[0] or uname.release, provenance="platform"
        ),
        "hardware.kernel": value(uname.release, provenance="platform.uname().release"),
        "hardware.arch": value(uname.machine, provenance="platform.uname().machine"),
    }
    if uname.system == "Darwin":
        _cpu_darwin(out)
    elif uname.system == "Linux":
        _cpu_linux(out)
    else:
        for key in ("cpu_model", "cpu_cores_physical", "cpu_cores_logical", "numa_nodes"):
            out[f"hardware.{key}"] = unknown(
                f"no CPU collector for {uname.system}", provenance="platform.uname()"
            )
    _gpu(out)
    return out

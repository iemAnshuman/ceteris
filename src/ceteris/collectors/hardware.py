"""Node identity: OS, CPU, NUMA, GPU."""

from __future__ import annotations

import glob
import json
import os
import platform
import re

from ..model import Field, State, not_applicable, unknown, value
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


# Signals that a compute GPU driver stack is loaded, used when no vendor query
# tool is on PATH. Deliberately narrow: /sys/class/drm/card* exists on any box
# with integrated graphics and would make ordinary login nodes uncertifiable.
_GPU_DRIVER_SIGNALS = (
    ("/dev/kfd", "AMD compute device /dev/kfd"),
    ("/proc/driver/nvidia/version", "NVIDIA kernel driver"),
    ("/sys/module/amdgpu", "amdgpu kernel module"),
    ("/sys/module/nvidia", "nvidia kernel module"),
)

_GPU_FIELDS = ("gpu_vendor", "gpu_models", "gpu_count", "gpu_driver")


def _gpu_driver_evidence() -> list[str]:
    return [why for path, why in _GPU_DRIVER_SIGNALS if os.path.exists(path)]


def _nvidia(out: dict[str, Field]) -> str:
    """One of: "missing" (no nvidia-smi), "hung" (timed out), "failed"
    (exited non-zero with a driver loaded), "absent" (no GPU, definitively),
    "data"."""
    res = run(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"], timeout=10)
    if res.missing:
        return "missing"
    if not res.ok:
        # Clusters ship nvidia-smi in a shared image, so it exists on GPU-less
        # login nodes and exits non-zero because no driver is loaded. Treating
        # that as unknown made every login-node comparison uncertifiable. With
        # no driver loaded either, the honest answer is that there is no GPU.
        # A hang tells us nothing either way, so it stays unknown. A clean
        # non-zero exit with no driver loaded is a real answer: no GPU.
        if not res.timed_out and not _gpu_driver_evidence():
            for key in _GPU_FIELDS:
                out[f"hardware.{key}"] = not_applicable(
                    f"nvidia-smi failed ({res.detail}) and no GPU driver is loaded",
                    provenance=res.provenance,
                )
            return "absent"
        detail = res.detail
        if "No devices were found" in (res.stderr or "") + (res.stdout or ""):
            # Seen on Rostam's cuda-V100 partition: the driver is loaded but
            # the job asked for no GPU, so the cgroup shows it none. The
            # record is right to be unknown; the reader deserves the reason.
            detail = (
                "nvidia-smi found no devices although the NVIDIA driver is loaded; "
                "under a scheduler this usually means the job was allocated no GPU "
                "(Slurm: --gres=gpu:N)"
            )
        for key in _GPU_FIELDS:
            out[f"hardware.{key}"] = unknown(detail, provenance=res.provenance)
        return "hung" if res.timed_out else "failed"
    rows = [r.strip() for r in res.stdout.splitlines() if r.strip()]
    models, drivers = [], set()
    for row in rows:
        parts = [p.strip() for p in row.split(",")]
        models.append(parts[0])
        if len(parts) > 1:
            drivers.add(parts[1])
    out["hardware.gpu_vendor"] = value("nvidia", provenance=res.provenance)
    out["hardware.gpu_models"] = value(sorted(models), provenance=res.provenance)
    out["hardware.gpu_count"] = value(len(models), provenance=res.provenance)
    out["hardware.gpu_driver"] = (
        value(sorted(drivers)[0], provenance=res.provenance)
        if len(drivers) == 1
        else unknown(f"GPUs report differing driver versions: {sorted(drivers)}", provenance=res.provenance)
    )
    return "data"


def _rocm_json(argv: list[str]):
    """rocm-smi --json for one query. Returns (parsed, CmdResult).

    Each query is issued on its own: asking for two things at once
    (--showproductname --showdriverversion) makes rocm-smi emit only the last
    table, which silently dropped every card row. Verified against ROCm-SMI
    3.0.0 on an MI100 node.
    """
    res = run([*argv, "--json"], timeout=15)
    if not res.ok:
        return None, res
    try:
        return json.loads(res.stdout), res
    except ValueError:
        return None, res


def _amd(out: dict[str, Field]) -> bool:
    """True when rocm-smi answered, either with data or with a real failure."""
    products, res = _rocm_json(["rocm-smi", "--showproductname"])
    if res.missing:
        return False
    if not res.ok:
        for key in _GPU_FIELDS:
            out[f"hardware.{key}"] = unknown(res.detail, provenance=res.provenance)
        return True

    out["hardware.gpu_vendor"] = value("amd", provenance=res.provenance)
    models = []
    if isinstance(products, dict):
        for card in sorted(products):
            entry = products[card]
            if isinstance(entry, dict):
                name = entry.get("Card Series") or entry.get("Card Model") or entry.get("Device Name")
                if name:
                    models.append(str(name))
    if models:
        out["hardware.gpu_models"] = value(sorted(models), provenance=res.provenance)
        out["hardware.gpu_count"] = value(len(models), provenance=res.provenance)
    else:
        for key in ("gpu_models", "gpu_count"):
            out[f"hardware.{key}"] = unknown(
                "no card entries in rocm-smi --showproductname --json", provenance=res.provenance
            )

    driver, dres = _rocm_json(["rocm-smi", "--showdriverversion"])
    versions = set()
    if isinstance(driver, dict):
        for entry in driver.values():
            if isinstance(entry, dict):
                for key, val in entry.items():
                    if "driver" in key.lower() and "version" in key.lower():
                        versions.add(str(val))
    if len(versions) == 1:
        out["hardware.gpu_driver"] = value(versions.pop(), provenance=dres.provenance)
    elif versions:
        out["hardware.gpu_driver"] = unknown(
            f"GPUs report differing driver versions: {sorted(versions)}", provenance=dres.provenance
        )
    else:
        out["hardware.gpu_driver"] = unknown(
            "no driver version in rocm-smi --showdriverversion --json", provenance=dres.provenance
        )
    return True


def _gpu(out: dict[str, Field]) -> None:
    """A missing vendor tool proves the absence of that vendor's stack, not the
    absence of a GPU. Before concluding there is no accelerator, look for a
    loaded driver: an AMD box has no nvidia-smi, and reporting not_applicable
    there would let two different AMD machines compare as agreeing about their
    GPUs.

    A failing nvidia-smi does not settle the question either. Clusters ship
    it in a shared image, so an MI100 node can have nvidia-smi exiting 9,
    /dev/kfd present, and rocm-smi answering perfectly well; letting the
    NVIDIA probe claim the answer left such nodes unknown for good.
    """
    nv: dict[str, Field] = {}
    status = _nvidia(nv)
    if status in ("data", "absent", "hung"):
        # Data, a definitive no, or a hang that says nothing either way.
        out.update(nv)
        _cuda(out)
        return
    amd: dict[str, Field] = {}
    amd_answered = _amd(amd)
    if amd_answered and amd["hardware.gpu_vendor"].state is State.VALUE:
        out.update(amd)
    elif status == "failed":
        out.update(nv)
    elif amd_answered:
        out.update(amd)
    else:
        evidence = _gpu_driver_evidence()
        if evidence:
            for key in _GPU_FIELDS:
                out[f"hardware.{key}"] = unknown(
                    "a GPU driver is loaded (" + "; ".join(evidence) + ") but neither "
                    "nvidia-smi nor rocm-smi is on PATH",
                    provenance="/dev/kfd, /proc/driver/nvidia, /sys/module/*",
                )
        else:
            for key in _GPU_FIELDS:
                out[f"hardware.{key}"] = not_applicable(
                    "no GPU query tool and no loaded GPU driver", provenance="nvidia-smi, rocm-smi"
                )
    _cuda(out)


def _cuda(out: dict[str, Field]) -> None:

    nvcc = run(["nvcc", "--version"])
    if nvcc.missing:
        out["hardware.cuda_runtime"] = not_applicable(nvcc.detail, provenance="nvcc")
    elif not nvcc.ok:
        out["hardware.cuda_runtime"] = unknown(nvcc.detail, provenance=nvcc.provenance)
    else:
        match = re.search(r"release\s+([0-9.]+)", nvcc.stdout)
        out["hardware.cuda_runtime"] = (
            value(match.group(1), provenance=nvcc.provenance)
            if match else unknown("could not parse nvcc --version", provenance=nvcc.provenance)
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

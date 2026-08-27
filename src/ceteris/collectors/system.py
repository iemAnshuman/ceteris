"""System state: the confounds every benchmarking guide tells the user to
handle and no tool captures.

CPU frequency governor, turbo boost, SMT, ASLR, transparent huge pages,
power source, thermal throttling, load, memory pressure, virtualisation,
containers. pyperf's tuning page and Google Benchmark's reducing_variance.md
list these as user obligations. They apply to a Rust microbenchmark on a
laptop as much as to a 16-node job, which is why they live in their own
namespace rather than under hardware.

The rule is unchanged: a sysfs node that does not exist is not_applicable
(this kernel does not expose it); one that exists and cannot be read is
unknown.
"""

from __future__ import annotations

import os
import platform
import re

from ..model import Field, not_applicable, unknown, value
from ._run import run


def _read(path: str) -> tuple[str | None, str | None]:
    """(content, detail). content None when absent or unreadable."""
    if not os.path.exists(path):
        return None, "absent"
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read().strip(), None
    except OSError as exc:
        return None, f"unreadable: {exc.strerror or exc}"


def _sysfs(out: dict[str, Field], key: str, path: str, transform=lambda s: s) -> None:
    content, detail = _read(path)
    if content is not None:
        out[key] = value(transform(content), provenance=path)
    elif detail == "absent":
        out[key] = not_applicable("not exposed by this kernel", provenance=path)
    else:
        out[key] = unknown(detail or "unreadable", provenance=path)


def _bracketed(s: str) -> str:
    """'always [madvise] never' -> 'madvise'."""
    match = re.search(r"\[([^\]]+)\]", s)
    return match.group(1) if match else s


def _linux(out: dict[str, Field]) -> None:
    _sysfs(out, "system.cpu_governor",
           "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    # Two different knobs depending on driver; report whichever exists.
    if os.path.exists("/sys/devices/system/cpu/intel_pstate/no_turbo"):
        _sysfs(out, "system.turbo", "/sys/devices/system/cpu/intel_pstate/no_turbo",
               lambda s: "off" if s.strip() == "1" else "on")
    else:
        _sysfs(out, "system.turbo", "/sys/devices/system/cpu/cpufreq/boost",
               lambda s: "on" if s.strip() == "1" else "off")
    _sysfs(out, "system.smt", "/sys/devices/system/cpu/smt/control")
    _sysfs(out, "system.aslr", "/proc/sys/kernel/randomize_va_space")
    _sysfs(out, "system.transparent_hugepages",
           "/sys/kernel/mm/transparent_hugepage/enabled", _bracketed)

    content, _ = _read("/proc/swaps")
    if content is None:
        out["system.swap"] = not_applicable("/proc/swaps absent", provenance="/proc/swaps")
    else:
        out["system.swap"] = value(
            "enabled" if len(content.splitlines()) > 1 else "disabled", provenance="/proc/swaps"
        )

    content, _ = _read("/proc/meminfo")
    match = re.search(r"^MemAvailable:\s+(\d+) kB", content or "", re.M)
    out["system.mem_available_mb"] = (
        value(int(match.group(1)) // 1024, provenance="/proc/meminfo")
        if match else unknown("no MemAvailable line", provenance="/proc/meminfo")
    )

    # Throttling: any thermal zone reporting a tripped cooling state.
    zones = []
    base = "/sys/class/thermal"
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            if name.startswith("cooling_device"):
                cur, _ = _read(f"{base}/{name}/cur_state")
                typ, _ = _read(f"{base}/{name}/type")
                if cur and cur.strip() not in ("0", "") and typ and "Processor" in typ:
                    zones.append(name)
        out["system.thermal_throttle"] = value(
            "active" if zones else "none", provenance=f"{base}/cooling_device*/cur_state"
        )
    else:
        out["system.thermal_throttle"] = not_applicable("no thermal class", provenance=base)

    cgroup, _ = _read("/proc/1/cgroup")
    if os.path.exists("/.dockerenv") or (cgroup and re.search(r"docker|containerd|podman|kubepods", cgroup)):
        out["system.container"] = value("yes", provenance="/.dockerenv or /proc/1/cgroup")
    elif cgroup is None:
        out["system.container"] = unknown("cannot read /proc/1/cgroup", provenance="/proc/1/cgroup")
    else:
        out["system.container"] = value("no", provenance="/.dockerenv or /proc/1/cgroup")

    product, _ = _read("/sys/class/dmi/id/product_name")
    res = run(["systemd-detect-virt"])
    if res.ok or (not res.missing and res.stdout.strip()):
        out["system.virtualization"] = value(res.stdout.strip() or "none", provenance=res.provenance)
    elif product is not None:
        out["system.virtualization"] = value(product, provenance="/sys/class/dmi/id/product_name")
    else:
        out["system.virtualization"] = not_applicable("no detector available", provenance="systemd-detect-virt")

    out["system.power_source"] = not_applicable("not tracked on linux in this version", provenance="pmset")


def _darwin(out: dict[str, Field]) -> None:
    for key in ("cpu_governor", "turbo", "transparent_hugepages"):
        out[f"system.{key}"] = not_applicable("darwin does not expose this", provenance="sysfs")
    out["system.aslr"] = value("always-on", provenance="darwin policy")

    phys = run(["sysctl", "-n", "hw.physicalcpu"]); logi = run(["sysctl", "-n", "hw.logicalcpu"])
    if phys.ok and logi.ok:
        out["system.smt"] = value("on" if int(logi.stdout) > int(phys.stdout) else "off",
                                  provenance="sysctl hw.logicalcpu vs hw.physicalcpu")
    else:
        out["system.smt"] = unknown("sysctl failed", provenance="sysctl")

    batt = run(["pmset", "-g", "batt"])
    if batt.missing:
        out["system.power_source"] = not_applicable(batt.detail, provenance="pmset -g batt")
    elif not batt.ok:
        out["system.power_source"] = unknown(batt.detail, provenance=batt.provenance)
    else:
        first = batt.stdout.splitlines()[0] if batt.stdout.strip() else ""
        if "AC Power" in first:
            out["system.power_source"] = value("ac", provenance=batt.provenance)
        elif "Battery Power" in first:
            out["system.power_source"] = value("battery", provenance=batt.provenance)
        else:
            out["system.power_source"] = unknown(f"unrecognised: {first[:60]}", provenance=batt.provenance)

    therm = run(["pmset", "-g", "therm"])
    if not therm.ok:
        out["system.thermal_throttle"] = (not_applicable if therm.missing else unknown)(
            therm.detail, provenance="pmset -g therm")
    else:
        m = re.search(r"CPU_Speed_Limit\s*=\s*(\d+)", therm.stdout)
        if m:
            out["system.thermal_throttle"] = value(
                "none" if m.group(1) == "100" else f"cpu_speed_limit={m.group(1)}",
                provenance=therm.provenance)
        else:
            out["system.thermal_throttle"] = value("none", provenance=therm.provenance)

    vmm = run(["sysctl", "-n", "kern.hv_vmm_present"])
    out["system.virtualization"] = (
        value("vm" if vmm.stdout.strip() == "1" else "none", provenance=vmm.provenance)
        if vmm.ok else unknown(vmm.detail, provenance="sysctl kern.hv_vmm_present"))

    swap = run(["sysctl", "-n", "vm.swapusage"])
    m = re.search(r"used = ([\d.]+)M", swap.stdout) if swap.ok else None
    out["system.swap"] = (
        value("in-use" if m and float(m.group(1)) > 0 else "idle", provenance=swap.provenance)
        if swap.ok else unknown(swap.detail, provenance="sysctl vm.swapusage"))
    out["system.mem_available_mb"] = not_applicable("not tracked on darwin in this version", provenance="sysctl")
    out["system.container"] = value("no", provenance="darwin")


def collect(ctx) -> dict[str, Field]:
    out: dict[str, Field] = {}
    system = platform.system()
    if system == "Linux":
        _linux(out)
    elif system == "Darwin":
        _darwin(out)
    else:
        out["system._collector"] = not_applicable(f"no system collector for {system}")
    try:
        load1 = os.getloadavg()[0]
        ncpu = os.cpu_count() or 1
        f = value(round(load1, 2), provenance="os.getloadavg()[0]")
        if load1 > ncpu:
            f = Field(f.state, f.value, f.provenance, detail=f"load exceeds {ncpu} cpus")
        out["system.load_1m"] = f
    except (OSError, AttributeError):
        out["system.load_1m"] = not_applicable("no loadavg on this platform", provenance="os.getloadavg")
    return out

"""Harness adapters: read the numbers the benchmark already produces.

`ceteris run -- hyperfine ...` should need no --metric. Each adapter knows
one harness: how to recognise it on the command line, how to make it write
machine-readable output if it was not going to, and how to turn that output
into metrics. The metric values are the harness's own statistics; ceteris
adds nothing to them.

The harness stays in charge of measurement. ceteris only asks where the
result went.

Three fixture formats (hyperfine, Google Benchmark, pytest-benchmark) are
recorded from real runs. The others were reconstructed from documentation
and are labelled as such in their tests; a real file from any of them is a
welcome contribution.
"""

from __future__ import annotations

import glob
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from statistics import median
from typing import Any, Callable

from ..model import Field, unknown, value


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._/-]+", "_", text).strip("_")[:60]


def _arg_value(argv: list[str], *names: str) -> str | None:
    for i, a in enumerate(argv):
        for n in names:
            if a == n and i + 1 < len(argv):
                return argv[i + 1]
            if a.startswith(n + "="):
                return a[len(n) + 1 :]
    return None


def _scratch(prefix: str) -> str:
    """A path for an export file the adapter injects.

    In the system temp directory, never the working tree: the run's
    after-capture happens while the file exists, and an untracked file in a
    clean repository flipped source.dirty, which counted as drift and made
    every zero-config harness run uncertifiable.
    """
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".json")
    os.close(fd)
    return path


def _num(x: Any) -> Any:
    try:
        return float(x)
    except (TypeError, ValueError):
        return x


@dataclass
class Plan:
    """What the adapter decided before the run."""

    adapter: str
    argv: list[str]                 # possibly augmented command to actually run
    output: str | None = None       # file to read afterwards, if any
    added_output: bool = False      # we injected the export flag ourselves


class Adapter:
    name = "base"

    def detect(self, argv: list[str]) -> bool:  # pragma: no cover - interface
        return False

    def plan(self, argv: list[str], cwd: str) -> Plan:
        return Plan(self.name, list(argv))

    def collect(self, plan: Plan, stdout: str, cwd: str, started: float) -> dict[str, Field]:  # pragma: no cover
        return {}

    def subject(self, argv: list[str]) -> list[str] | None:
        """The command strings the harness itself times, when the harness is
        a wrapper around them (hyperfine); None when the program on the
        command line is the thing being measured."""
        return None

    # -- helpers -------------------------------------------------------------
    def _read_json(self, path: str | None) -> tuple[Any, str | None]:
        if not path:
            return None, "no output file"
        try:
            with open(path, encoding="utf-8") as h:
                return json.load(h), None
        except OSError as exc:
            return None, f"cannot read {path}: {exc.strerror or exc}"
        except ValueError as exc:
            return None, f"{path} is not valid JSON: {exc}"

    def _failed(self, why: str) -> dict[str, Field]:
        return {f"{self.name}._adapter": unknown(why, provenance=self.name)}


def _basename(argv: list[str]) -> str:
    return os.path.basename(argv[0]) if argv else ""


# hyperfine 1.20: options that consume the next argument(s). Anything else
# starting with a dash is a flag, and everything else is a command to time.
_HYPERFINE_VALUED = {
    "-w", "--warmup", "-m", "--min-runs", "-M", "--max-runs", "-r", "--runs",
    "-s", "--setup", "--reference", "--reference-name", "-p", "--prepare",
    "-C", "--conclude", "-c", "--cleanup", "-D", "--parameter-step-size",
    "-S", "--shell", "--style", "--sort", "-u", "--time-unit",
    "--export-asciidoc", "--export-csv", "--export-json", "--export-markdown",
    "--export-orgmode", "--output", "--input", "-n", "--command-name",
    "--min-benchmarking-time",
}
_HYPERFINE_MULTI = {"-P": 3, "--parameter-scan": 3, "-L": 2, "--parameter-list": 2}


class Hyperfine(Adapter):
    name = "hyperfine"

    def detect(self, argv):
        return _basename(argv) == "hyperfine"

    def subject(self, argv):
        out: list[str] = []
        i = 1
        while i < len(argv):
            a = argv[i]
            if a == "--":
                out.extend(argv[i + 1:])
                break
            if a.startswith("-") and len(a) > 1:
                if a.startswith("--") and "=" in a:
                    i += 1
                    continue
                i += 1 + _HYPERFINE_MULTI.get(a, 1 if a in _HYPERFINE_VALUED else 0)
                continue
            out.append(a)
            i += 1
        return out

    def plan(self, argv, cwd):
        out = _arg_value(argv, "--export-json")
        if out:
            return Plan(self.name, list(argv), os.path.join(cwd, out))
        path = _scratch("ceteris-hyperfine-")
        return Plan(self.name, list(argv) + ["--export-json", path], path, added_output=True)

    def collect(self, plan, stdout, cwd, started):
        data, err = self._read_json(plan.output)
        if err:
            return self._failed(err)
        out: dict[str, Field] = {}
        prov = f"hyperfine --export-json ({'injected' if plan.added_output else 'given'})"
        results = data.get("results", [])
        # Metric names must be stable across configurations, or the noise
        # floor cannot compare them. The command is the thing that varies
        # between configurations, so it must not be in the name; a single
        # command is 'hyperfine.median_s', several are numbered in order.
        for i, r in enumerate(results, 1):
            key = "hyperfine" if len(results) == 1 else f"hyperfine.{i}"
            for stat in ("median", "min"):
                if stat in r:
                    out[f"{key}.{stat}_s"] = value(_num(r[stat]), provenance=f"{prov}; command: {r.get('command', '?')}")
        return out or self._failed("no results in export")


class GoogleBenchmark(Adapter):
    name = "gbench"

    def detect(self, argv):
        return any(a.startswith("--benchmark_") for a in argv[1:])

    def plan(self, argv, cwd):
        out = _arg_value(argv, "--benchmark_out")
        if out:
            return Plan(self.name, list(argv), os.path.join(cwd, out))
        path = _scratch("ceteris-gbench-")
        return Plan(self.name, list(argv) + [f"--benchmark_out={path}", "--benchmark_out_format=json"], path, True)

    def collect(self, plan, stdout, cwd, started):
        data, err = self._read_json(plan.output)
        if err:
            return self._failed(err)
        # --benchmark_repetitions=N writes N iteration entries per name and
        # then the aggregates. Keying by name overwrote each with the next,
        # so only the last repetition survived. Take the median across them.
        runs: dict[str, list] = {}
        for b in data.get("benchmarks", []):
            if b.get("run_type") == "aggregate":
                continue
            unit = b.get("time_unit", "ns")
            runs.setdefault(f"gbench.{b.get('name', '?')}.real_time_{unit}", []).append(_num(b.get("real_time")))
        out: dict[str, Field] = {}
        for key, xs in runs.items():
            nums = [x for x in xs if isinstance(x, float)]
            if len(nums) > 1:
                out[key] = value(median(nums), provenance=f"--benchmark_out json, median of {len(nums)} repetitions")
            else:
                out[key] = value(xs[0], provenance="--benchmark_out json")
        return out or self._failed("no benchmarks in output")


class PytestBenchmark(Adapter):
    name = "pytest"

    def detect(self, argv):
        return any(a.startswith("--benchmark") for a in argv[1:]) and (
            _basename(argv) in ("pytest", "py.test") or "pytest" in argv[:3]
        )

    def plan(self, argv, cwd):
        out = _arg_value(argv, "--benchmark-json")
        if out:
            return Plan(self.name, list(argv), os.path.join(cwd, out))
        path = _scratch("ceteris-pytest-")
        return Plan(self.name, list(argv) + [f"--benchmark-json={path}"], path, True)

    def collect(self, plan, stdout, cwd, started):
        data, err = self._read_json(plan.output)
        if err:
            return self._failed(err)
        out: dict[str, Field] = {}
        for b in data.get("benchmarks", []):
            st = b.get("stats", {})
            out[f"pytest.{b.get('name', '?')}.median_s"] = value(_num(st.get("median")), provenance="--benchmark-json")
        return out or self._failed("no benchmarks in output")


class JMH(Adapter):
    name = "jmh"

    def detect(self, argv):
        return "-rf" in argv and _arg_value(argv, "-rf") == "json"

    def plan(self, argv, cwd):
        out = _arg_value(argv, "-rff") or "jmh-result.json"
        return Plan(self.name, list(argv), os.path.join(cwd, out))

    def collect(self, plan, stdout, cwd, started):
        data, err = self._read_json(plan.output)
        if err:
            return self._failed(err)
        out: dict[str, Field] = {}
        for b in data if isinstance(data, list) else []:
            name = b.get("benchmark", "?").split(".")[-2:]
            pm = b.get("primaryMetric", {})
            unit = _slug(pm.get("scoreUnit", "")).replace("/", "_")
            out[f"jmh.{'.'.join(name)}.{b.get('mode', 'score')}_{unit}"] = value(_num(pm.get("score")), provenance="jmh -rf json")
        return out or self._failed("no benchmarks in output")


class Criterion(Adapter):
    name = "criterion"

    def detect(self, argv):
        return _basename(argv) == "cargo" and "bench" in argv[1:3]

    def collect(self, plan, stdout, cwd, started):
        out: dict[str, Field] = {}
        for path in glob.glob(os.path.join(cwd, "target", "criterion", "**", "new", "estimates.json"), recursive=True):
            if os.path.getmtime(path) < started - 1:
                continue
            data, err = self._read_json(path)
            if err:
                continue
            bench = os.path.relpath(os.path.dirname(os.path.dirname(path)), os.path.join(cwd, "target", "criterion"))
            out[f"criterion.{_slug(bench)}.median_ns"] = value(_num(data.get("median", {}).get("point_estimate")), provenance=path)
        return out or self._failed("no fresh target/criterion/*/new/estimates.json")


class OSU(Adapter):
    name = "osu"

    def detect(self, argv):
        return any(os.path.basename(a).startswith("osu_") for a in argv)

    def collect(self, plan, stdout, cwd, started):
        out: dict[str, Field] = {}
        unit = "value"
        for line in stdout.splitlines():
            m = re.match(r"^#\s*Size\s+(.+?)\s*$", line)
            if m:
                unit = re.sub(r"[^A-Za-z0-9]+", "_", m.group(1)).strip("_")
                continue
            m = re.match(r"^\s*(\d+)\s+([0-9.]+)\s*$", line)
            if m:
                out[f"osu.{unit}.{m.group(1)}B"] = value(float(m.group(2)), provenance="osu stdout table")
        return out or self._failed("no size/value rows in stdout")


class NCCLTests(Adapter):
    name = "nccl"

    def detect(self, argv):
        return any(os.path.basename(a).endswith("_perf") for a in argv)

    def collect(self, plan, stdout, cwd, started):
        out: dict[str, Field] = {}
        for line in stdout.splitlines():
            m = re.match(r"^\s*(\d+)\s+\d+\s+\S+\s+\S+\s+\S+\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)", line)
            if m:
                out[f"nccl.busbw_GBps.{m.group(1)}B"] = value(float(m.group(4)), provenance="nccl-tests stdout (out-of-place busbw)")
        m = re.search(r"Avg bus bandwidth\s*:\s*([0-9.]+)", stdout)
        if m:
            out["nccl.avg_busbw_GBps"] = value(float(m.group(1)), provenance="nccl-tests stdout")
        return out or self._failed("no result rows in stdout")


class MLPerf(Adapter):
    name = "mlperf"

    def detect(self, argv):
        return any("mlperf" in a.lower() or "loadgen" in a.lower() for a in argv)

    def collect(self, plan, stdout, cwd, started):
        candidates = [p for p in glob.glob(os.path.join(cwd, "**", "mlperf_log_summary.txt"), recursive=True)
                      if os.path.getmtime(p) >= started - 1]
        if not candidates:
            return self._failed("no fresh mlperf_log_summary.txt under the working directory")
        path = max(candidates, key=os.path.getmtime)
        try:
            text = open(path, encoding="utf-8").read()
        except OSError as exc:
            return self._failed(str(exc))
        out: dict[str, Field] = {}
        for label, key in (("Samples per second", "samples_per_second"), ("QPS w/ loadgen overhead", "qps"),
                           ("90th percentile latency \\(ns\\)", "p90_latency_ns"), ("Completed samples per second", "completed_samples_per_second")):
            m = re.search(rf"{label}\s*:\s*([0-9.]+)", text)
            if m:
                out[f"mlperf.{key}"] = value(float(m.group(1)), provenance=path)
        m = re.search(r"Result is\s*:\s*(\w+)", text)
        if m:
            out["mlperf.result"] = value(m.group(1), provenance=path)
        return out or self._failed(f"no recognised fields in {path}")


ADAPTERS: list[Adapter] = [Hyperfine(), GoogleBenchmark(), PytestBenchmark(), JMH(), Criterion(), OSU(), NCCLTests(), MLPerf()]
BY_NAME = {a.name: a for a in ADAPTERS}


def detect(argv: list[str]) -> Adapter | None:
    for adapter in ADAPTERS:
        if adapter.detect(argv):
            return adapter
    return None


def ingest(path: str, fmt: str | None = None) -> dict[str, Field]:
    """Explicit --ingest FILE[:format]: parse an output file without running."""
    if fmt is None:
        base = os.path.basename(path).lower()
        fmt = "mlperf" if "mlperf" in base else "jmh" if "jmh" in base else None
        if fmt is None:
            data, err = Adapter()._read_json(path)
            if isinstance(data, dict) and "results" in data:
                fmt = "hyperfine"
            elif isinstance(data, dict) and "benchmarks" in data:
                fmt = "gbench" if data["benchmarks"] and "real_time" in data["benchmarks"][0] else "pytest"
            elif isinstance(data, list):
                fmt = "jmh"
    adapter = BY_NAME.get(fmt or "")
    if adapter is None:
        return {"ingest._adapter": unknown(f"cannot determine format of {path}; pass FILE:format", provenance="--ingest")}
    plan = Plan(adapter.name, [], path)
    return adapter.collect(plan, "", os.path.dirname(os.path.abspath(path)), 0)

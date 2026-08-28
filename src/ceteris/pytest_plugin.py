"""pytest plugin: `pytest --ceteris` records the session as a ceteris run.

Works with pytest-benchmark when it is installed: its results are read from
the in-memory session. Without it, the session still gets a fingerprint and
its exit code, which is enough to gate on environment validity.

Registered through the pytest11 entry point, so it is available as soon as
ceteris is installed; it does nothing unless --ceteris is passed.
"""

from __future__ import annotations

import sys
import time

import pytest


def pytest_addoption(parser):
    group = parser.getgroup("ceteris")
    group.addoption("--ceteris", action="store_true", default=False,
                    help="record this session as a ceteris run (fingerprint + benchmark results)")
    group.addoption("--ceteris-label", default=None, help="label for the recorded run")
    group.addoption("--ceteris-store", default=None, help="run store directory")


def pytest_configure(config):
    if not config.getoption("--ceteris"):
        return
    config._ceteris = {"started": time.time()}


def _benchmark_metrics(config):
    """Read pytest-benchmark's results in memory.

    Not by injecting --benchmark-json: that option's type changed from
    argparse.FileType to pathlib.Path between pytest-benchmark 5.2 and 5.3, so
    writing a value into it couples this plugin to a version range. The
    in-memory session object exposes the same attributes on both.
    """
    session = getattr(config, "_benchmarksession", None)
    if session is None:
        return {}
    from .model import unknown, value

    metrics = {}
    for bench in getattr(session, "benchmarks", []) or []:
        name = getattr(bench, "name", None) or getattr(bench, "fullname", "benchmark")
        stats = getattr(bench, "stats", None)
        stats = getattr(stats, "stats", stats)
        median = getattr(stats, "median", None)
        key = f"pytest.{name}.median_s"
        metrics[key] = (
            value(float(median), provenance="pytest-benchmark session")
            if isinstance(median, (int, float))
            else unknown("no median in the benchmark stats", provenance="pytest-benchmark session")
        )
    return metrics


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    state = getattr(config, "_ceteris", None)
    if state is None:
        return
    from . import execution, store
    from .capture import capture
    from .config import Config
    from .model import Fingerprint

    cfg = Config.load()
    fp = capture(label=config.getoption("--ceteris-label") or "pytest", cfg=cfg)
    fields = dict(fp.fields)
    fields.update(execution.collect([sys.executable, "-m", "pytest", *config.invocation_params.args]))
    started = state["started"]
    record = Fingerprint(
        fields=fields,
        meta=dict(fp.meta, kind="run", adapter="pytest"),
        run={
            "exit_code": int(exitstatus),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(started)),
            "duration_s": round(time.time() - started, 3),
            "output": "",
            "output_truncated": False,
            "drift": [],
        },
        metrics=_benchmark_metrics(config),
    )
    saved = store.save(record, store.store_path(config.getoption("--ceteris-store")))
    sys.stderr.write(f"ceteris: recorded {saved}\n")

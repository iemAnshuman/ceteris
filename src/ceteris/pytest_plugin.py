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


# Design section 15.2. A wrapper that already owns this execution passes its
# run ID down, so `ceteris run -- pytest ...` and this plugin do not record
# one session twice as two independent measurements. It is coordination
# metadata, never a comparable tuning variable, so it is not captured as one.
PARENT_RUN_ID_ENV = "CETERIS_PARENT_RUN_ID"


def parent_run_id():
    import os

    return os.environ.get(PARENT_RUN_ID_ENV) or None


def session_outcome(exitstatus: int, session) -> dict:
    """What the session itself did, beside whatever numbers came out of it.

    A test failure is failed correctness for its scope. A session that could
    not even collect has no measurements to report, and another benchmark
    producing numbers does not cover for it.
    """
    status = int(exitstatus)
    collected = len(getattr(session, "items", []) or [])
    outcomes = {
        0: ("passed", "every selected test passed"),
        1: ("failed", "at least one test failed"),
        2: ("interrupted", "the session was interrupted"),
        3: ("failed", "an internal error stopped the session"),
        4: ("failed", "pytest usage error"),
        5: ("empty", "no tests were collected"),
    }
    state, detail = outcomes.get(status, ("failed", f"pytest exited {status}"))
    return {
        "exit_status": status,
        "state": state,
        "detail": detail,
        "collected": collected,
        # A required case that was never collected is missing evidence, not
        # an absent requirement.
        "correctness": {0: "validated", 5: "unverified"}.get(status, "failed"),
    }


def expected_case_coverage(expected, observed) -> dict:
    """Cases the plan required against cases this session actually produced."""
    expected, observed = list(expected), set(observed)
    missing = [case for case in expected if case not in observed]
    return {
        "state": "sufficient" if expected and not missing else "incomplete",
        "expected": expected,
        "observed": sorted(observed),
        "missing": missing,
        "unexpected": sorted(observed - set(expected)),
    }


def pytest_addoption(parser):
    group = parser.getgroup("ceteris")
    group.addoption("--ceteris", action="store_true", default=False,
                    help="record this session as a ceteris run (fingerprint + benchmark results)")
    group.addoption("--ceteris-label", default=None, help="label for the recorded run")
    group.addoption("--ceteris-store", default=None, help="run store directory")
    group.addoption("--ceteris-expect-case", action="append", default=[],
                    metavar="CASE",
                    help="a benchmark case this session must produce. Repeatable. "
                         "A missing one is incomplete evidence, not an absent "
                         "requirement.")


def pytest_configure(config):
    if not config.getoption("--ceteris"):
        return
    config._ceteris = {"started": time.time(), "before": None}


def pytest_sessionstart(session):
    """Capture before the tests run.

    The plugin used to capture only at session finish and write an empty
    drift list, which claims the environment held still across a session it
    never watched. See design F11.
    """
    state = getattr(session.config, "_ceteris", None)
    if state is None:
        return
    from .capture import capture
    from .config import Config

    try:
        state["before"] = capture(label="pytest", cfg=Config.load())
    except Exception:  # noqa: BLE001 - a capture failure must not stop the tests
        state["before"] = None


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


def _pytest_version() -> str:
    return getattr(pytest, "__version__", "unknown")


def _plugin_versions(config) -> dict:
    """Which plugins shaped this session, and at what version."""
    found: dict = {}
    manager = getattr(config, "pluginmanager", None)
    if manager is None:
        return found
    for name, plugin in manager.list_name_plugin():
        module = getattr(plugin, "__module__", "") or ""
        root = module.split(".")[0]
        if root in ("pytest_benchmark", "ceteris", "xdist", "pytest_xdist"):
            found[root] = getattr(
                __import__(root) if root != "ceteris" else __import__("ceteris"),
                "__version__", "unknown")
    return found


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    state = getattr(config, "_ceteris", None)
    if state is None:
        return
    from . import execution, store
    from .capture import capture
    from .config import Config
    from .model import Fingerprint

    from .runner import _drift

    cfg = Config.load()
    outcome = session_outcome(exitstatus, session)
    parent = parent_run_id()
    metrics = _benchmark_metrics(config)
    coverage = expected_case_coverage(
        config.getoption("--ceteris-expect-case"), sorted(metrics))
    fp = capture(label=config.getoption("--ceteris-label") or "pytest", cfg=cfg)
    fields = dict(fp.fields)
    before = state.get("before")
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
            "drift": _drift(before.fields, fp.fields, cfg) if before is not None else [],
            # Without a before-capture there is nothing to compare against,
            # and an empty list would claim the environment held still.
            "drift_observed": before is not None,
            # One pytest process is one outer execution. Twenty pairs means
            # twenty independent sessions per variant, never twenty inner
            # rounds inside one session.
            "sampling_unit": "process_execution",
            "session": outcome,
            "case_coverage": coverage,
            "parent_run_id": parent,
            "pytest": {
                "version": _pytest_version(),
                "plugins": _plugin_versions(config),
            },
        },
        metrics=metrics,
    )
    saved = store.save(record, store.store_path(config.getoption("--ceteris-store")))
    sys.stderr.write(f"ceteris: recorded {saved}\n")
    if record.run.get("session", {}).get("state") not in ("passed", None):
        sys.stderr.write(
            f"ceteris: the session itself {record.run['session']['detail']}; "
            f"correctness for this record is "
            f"{record.run['session']['correctness']}\n")
    coverage = record.run.get("case_coverage")
    if coverage and coverage["state"] == "incomplete":
        sys.stderr.write(
            f"ceteris: expected case(s) not produced: "
            f"{', '.join(coverage['missing'])}\n")

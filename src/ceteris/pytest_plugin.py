"""pytest plugin: `pytest --ceteris` records the session as a ceteris run.

Works with pytest-benchmark when it is installed: the benchmark JSON is read
through the pytest adapter. Without it, the session still gets a fingerprint
and its wall time, which is enough to gate on environment validity.

Registered through the pytest11 entry point, so it is available as soon as
ceteris is installed; it does nothing unless --ceteris is passed.
"""

from __future__ import annotations

import os
import sys
import tempfile
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
    state = {"started": time.time(), "json": None, "injected": False}
    # If pytest-benchmark is present and no JSON export was requested, ask for one.
    if config.pluginmanager.hasplugin("benchmark"):
        current = getattr(config.option, "benchmark_json", None)
        if not current:
            path = tempfile.mktemp(prefix="ceteris-pytest-", suffix=".json")
            config.option.benchmark_json = path
            state["json"], state["injected"] = path, True
        else:
            state["json"] = getattr(current, "name", None) or str(current)
    config._ceteris = state


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    state = getattr(config, "_ceteris", None)
    if state is None:
        return
    from . import adapters, execution, store
    from .capture import capture
    from .config import Config
    from .model import Fingerprint, value

    cfg = Config.load()
    fp = capture(label=config.getoption("--ceteris-label") or "pytest", cfg=cfg)
    fields = dict(fp.fields)
    fields.update(execution.collect([sys.executable, "-m", "pytest", *config.invocation_params.args]))
    metrics = {}
    path = state["json"]
    if path and os.path.exists(path):
        metrics = adapters.ingest(path, "pytest")
        if state["injected"]:
            os.unlink(path)
    record = Fingerprint(
        fields=fields,
        meta=dict(fp.meta, kind="run", adapter="pytest"),
        run={"exit_code": int(exitstatus), "started_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(state["started"])),
             "duration_s": round(time.time() - state["started"], 3), "output": "", "output_truncated": False, "drift": []},
        metrics=metrics,
    )
    saved = store.save(record, store.store_path(config.getoption("--ceteris-store")))
    sys.stderr.write(f"ceteris: recorded {saved}\n")

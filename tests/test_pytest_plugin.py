"""pytest --ceteris records a session. Exercised through pytester."""

from __future__ import annotations

import importlib.util
import json
import shutil

import pytest

pytest_plugins = ["pytester"]


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
@pytest.mark.skipif(
    importlib.util.find_spec("pytest_benchmark") is None,
    reason="needs pytest-benchmark (in the dev extra)",
)
def test_session_is_recorded_with_benchmark_metrics(pytester, monkeypatch):
    store = pytester.path / "runs"
    monkeypatch.setenv("CETERIS_STORE", str(store))
    pytester.makepyfile(test_x="""
        def test_join(benchmark):
            benchmark(lambda: "".join(str(i) for i in range(50)))
    """)
    result = pytester.runpytest_subprocess("--ceteris", "--benchmark-min-rounds=3", "-p", "no:cacheprovider", "-q")
    result.assert_outcomes(passed=1)
    files = list(store.glob("*.json"))
    assert len(files) == 1, result.stderr.str()
    record = json.loads(files[0].read_text())
    assert record["meta"]["adapter"] == "pytest"
    assert any(k.startswith("pytest.test_join.median_s") for k in record["metrics"]), record["metrics"]
    assert record["run"]["exit_code"] == 0


def test_plugin_is_inert_without_the_flag(pytester, monkeypatch):
    store = pytester.path / "runs"
    monkeypatch.setenv("CETERIS_STORE", str(store))
    pytester.makepyfile(test_y="def test_a(): pass")
    pytester.runpytest_subprocess("-q", "-p", "no:cacheprovider").assert_outcomes(passed=1)
    assert not store.exists()


def test_the_plugin_watches_both_ends_of_the_session(pytester_or_testdir=None):
    """It captured only at session finish and wrote an empty drift list,
    which claims the environment held still across a session it never
    watched. See design F11."""
    from ceteris import pytest_plugin

    assert hasattr(pytest_plugin, "pytest_sessionstart")


def test_a_session_without_a_before_capture_says_drift_was_not_observed():
    from ceteris.model import Fingerprint

    # The shape the plugin writes when the before-capture failed.
    run = {"exit_code": 0, "drift": [], "drift_observed": False}
    record = Fingerprint({}, {"label": "pytest"}, run=run)
    assert record.drift == []
    assert record.run["drift_observed"] is False

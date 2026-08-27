"""pytest --ceteris records a session. Exercised through pytester."""

from __future__ import annotations

import json
import shutil

import pytest

pytest_plugins = ["pytester"]


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
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

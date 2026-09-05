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


# --- WP13: one session is one execution ---------------------------------------


class FakeSession:
    def __init__(self, collected=3):
        self.items = list(range(collected))


@pytest.mark.parametrize("status, state, correctness", [
    (0, "passed", "validated"),
    (1, "failed", "failed"),
    (2, "interrupted", "failed"),
    (3, "failed", "failed"),
    (4, "failed", "failed"),
    (5, "empty", "unverified"),
])
def test_the_session_outcome_is_recorded_beside_the_numbers(status, state, correctness):
    """A test failure is failed correctness for its scope, and another
    benchmark producing numbers does not cover for it."""
    from ceteris.pytest_plugin import session_outcome

    got = session_outcome(status, FakeSession())
    assert got["state"] == state
    assert got["correctness"] == correctness
    assert got["detail"]


def test_a_session_that_collected_nothing_is_unverified_not_validated():
    from ceteris.pytest_plugin import session_outcome

    got = session_outcome(5, FakeSession(collected=0))
    assert got["correctness"] == "unverified" and got["collected"] == 0


def test_a_wrapper_run_id_is_picked_up_so_one_session_is_not_two_measurements(monkeypatch):
    from ceteris.pytest_plugin import PARENT_RUN_ID_ENV, parent_run_id

    monkeypatch.delenv(PARENT_RUN_ID_ENV, raising=False)
    assert parent_run_id() is None
    monkeypatch.setenv(PARENT_RUN_ID_ENV, "11111111-1111-4111-8111-111111111111")
    assert parent_run_id() == "11111111-1111-4111-8111-111111111111"


def test_the_parent_run_id_is_not_a_comparable_tuning_variable():
    """It is coordination metadata; capturing it as an environment field
    would make two sessions differ for a reason that is not the experiment."""
    from ceteris.config import Config
    from ceteris.pytest_plugin import PARENT_RUN_ID_ENV

    assert PARENT_RUN_ID_ENV not in Config.load().env_allowlist


def test_a_required_case_that_was_never_produced_is_incomplete_evidence():
    from ceteris.pytest_plugin import expected_case_coverage

    got = expected_case_coverage(["pytest.test_a.median_s", "pytest.test_b.median_s"],
                                 ["pytest.test_a.median_s"])
    assert got["state"] == "incomplete"
    assert got["missing"] == ["pytest.test_b.median_s"]


def test_every_expected_case_present_is_sufficient():
    from ceteris.pytest_plugin import expected_case_coverage

    got = expected_case_coverage(["a"], ["a"])
    assert got["state"] == "sufficient" and got["missing"] == []


def test_an_unexpected_case_is_noted_without_failing_coverage():
    from ceteris.pytest_plugin import expected_case_coverage

    got = expected_case_coverage(["a"], ["a", "b"])
    assert got["state"] == "sufficient" and got["unexpected"] == ["b"]


def test_no_expectation_declared_is_incomplete_rather_than_vacuously_sufficient():
    from ceteris.pytest_plugin import expected_case_coverage

    assert expected_case_coverage([], ["a"])["state"] == "incomplete"

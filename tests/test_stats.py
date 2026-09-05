"""The statistical half of validity: repeats, configurations, noise floor."""

from __future__ import annotations

import sys

from pathlib import Path

from ceteris import stats
from ceteris.cli import main
from ceteris.compare import EXIT_OK, EXIT_WITHIN_NOISE, compare
from ceteris.model import State
from ceteris.model import Fingerprint, unknown, value
from ceteris.render import render
from ceteris.runner import run_repeated

from conftest import distinct_meta


def rec(label, commit, bw):
    return Fingerprint({"source.commit": value(commit)}, distinct_meta(label),
                       run={"exit_code": 0}, metrics={"bw": value(bw)})


def test_identical_environments_group_into_one_configuration():
    fps = [rec("a", "x", 1.0), rec("a", "x", 1.1), rec("b", "y", 5.0)]
    groups = stats.group_configs(fps)
    assert [g.n for g in groups] == [2, 1]
    assert groups[0].label == "a"


def test_the_same_configuration_from_a_different_source_is_one_configuration(cfg):
    """compare grouped by canonical value while the table grouped by the
    serialised field, provenance included, so a match in the report could be
    two configurations in the table. Order is significant since F02, so the
    difference under test here is where the value was read from and how it
    was spaced, not how it was ordered."""
    from ceteris.model import Field, State

    def r(flags, prov):
        return Fingerprint({"build.cxx_flags": Field(State.VALUE, flags, provenance=prov)},
                           distinct_meta("x"), metrics={"bw": value(1.0)}, run={"exit_code": 0})

    runs = [r("-O3 -g", "--cxx-flags") for _ in range(3)] + [r("-O3  -g", "$CXXFLAGS") for _ in range(3)]
    report = compare(runs, cfg=cfg)
    assert report.results[0].verdict.value == "match"
    assert len(report.configs) == 1 and report.configs[0].n == 6


def test_folded_labels_are_all_shown(cfg):
    runs = [rec("before", "x", 1.0) for _ in range(3)] + [rec("after", "x", 1.0) for _ in range(3)]
    assert [g.label for g in stats.group_configs(runs, cfg)] == ["before, after"]


def test_spread_is_range_over_median():
    g = stats.ConfigGroup("h", "a", [rec("a", "x", v) for v in (9.0, 10.0, 11.0)])
    st = stats.stats_for(g, "bw")
    assert (st.lo, st.med, st.hi) == (9.0, 10.0, 11.0)
    assert abs(st.spread - 0.2) < 1e-9


def test_unassessed_with_fewer_than_three_repeats(cfg):
    report = compare([rec("a", "x", 1.0), rec("b", "y", 2.0)], vary=["source.commit"], cfg=cfg)
    v = report.noise[0]
    assert not v.assessed and "unassessed" in v.reason
    assert report.exit_code == EXIT_OK


def test_gap_inside_scatter_is_within_noise(cfg):
    a = [rec("a", "x", v) for v in (45.0, 50.0, 53.0)]   # spread 16%
    b = [rec("b", "y", v) for v in (48.0, 52.0, 55.0)]   # medians 50 vs 52: gap 4%
    report = compare(a + b, vary=["source.commit"], cfg=cfg)
    v = report.noise[0]
    assert v.assessed and v.within_noise
    assert report.exit_code == EXIT_OK  # printed, not gating, by default
    strict = compare(a + b, vary=["source.commit"], cfg=cfg, require_signal=True)
    assert strict.exit_code == EXIT_WITHIN_NOISE


def test_require_signal_with_no_metric_at_all_is_not_a_result(cfg):
    """Two captures with no measurement used to pass --require-signal,
    because the noise list was empty and the check only looked inside it."""
    a = Fingerprint({"source.commit": value("x")}, {"label": "a"})
    b = Fingerprint({"source.commit": value("y")}, {"label": "b"})
    report = compare([a, b], vary=["source.commit"], cfg=cfg, require_signal=True)
    assert report.exit_code == EXIT_WITHIN_NOISE
    assert "no metric was measured" in render(report)


def test_gap_above_scatter_is_signal(cfg):
    a = [rec("a", "x", v) for v in (49.0, 50.0, 51.0)]
    b = [rec("b", "y", v) for v in (99.0, 100.0, 101.0)]
    report = compare(a + b, vary=["source.commit"], cfg=cfg, require_signal=True)
    assert report.noise[0].assessed and not report.noise[0].within_noise
    assert report.exit_code == EXIT_OK


def test_unknown_metrics_are_excluded_from_stats_not_zeroed():
    g = stats.ConfigGroup("h", "a", [rec("a", "x", 10.0),
                                     Fingerprint({}, distinct_meta("a"), metrics={"bw": unknown("no match")})])
    assert stats.stats_for(g, "bw").n == 1


def test_run_repeated_shares_a_series_and_a_configuration(cfg):
    records = run_repeated([sys.executable, "-c", "print('bw 5 GB/s')"], 3, cfg=cfg, echo=False,
                           label="rep", metric_patterns={"bw": r"bw (\d+)"})
    assert len({r.meta["series"] for r in records}) == 1
    assert [r.meta["repeat"] for r in records] == [1, 2, 3]
    assert len(stats.group_configs(records, cfg)) == 1


def test_informational_fields_do_not_split_configurations(cfg):
    from ceteris.model import Fingerprint, value
    a = Fingerprint({"source.commit": value("x"), "system.load_1m": value(1.0)}, distinct_meta("a"))
    b = Fingerprint({"source.commit": value("x"), "system.load_1m": value(9.0)}, distinct_meta("a"))
    assert len(stats.group_configs([a, b], cfg)) == 1
    assert a.content_hash() != b.content_hash()  # the artifact hash still sees everything


def test_cli_repeats_and_require_signal(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CETERIS_STORE", str(tmp_path / "runs"))
    main(["run", "--label", "same", "-q", "--repeats", "3", "--metric", "bw=bw (\\d+)",
          "--", sys.executable, "-c", "print('bw 5')"])
    main(["run", "--label", "same2", "-q", "--repeats", "3", "--metric", "bw=bw (\\d+)", "--cxx-flags", "-O1",
          "--", sys.executable, "-c", "print('bw 5')"])
    capsys.readouterr()
    code = main(["compare", "--vary", "build.cxx_flags", "--require-signal"])
    out = capsys.readouterr().out
    assert code == EXIT_WITHIN_NOISE
    assert "NOT A RESULT" in out and "same x3" in out


def test_runs_whose_command_failed_are_never_certified(cfg):
    """Found on Rostam: three runs of an mpirun that exited 183 compared as
    agreeing and were reported valid. A benchmark that crashed produced no
    measurement, and the exit code lives outside the comparable body."""
    from ceteris.compare import EXIT_INDETERMINATE
    from ceteris.model import Fingerprint, unknown, value

    def crashed(label):
        return Fingerprint({"source.commit": value("x")}, distinct_meta(label),
                           run={"exit_code": 183, "output": "mpirun: launch failed\n"},
                           metrics={"bw": unknown("pattern did not match")})

    runs = [crashed("a"), crashed("b"), crashed("c")]
    report = compare(runs, cfg=cfg)
    assert [f.label for f in report.failed_runs] == ["a", "b", "c"]
    assert report.exit_code == EXIT_INDETERMINATE
    assert "THE BENCHMARK FAILED" in render(report)


def test_a_metric_no_run_produced_says_so(cfg):
    from ceteris.model import Fingerprint, unknown, value

    runs = [Fingerprint({"source.commit": value("x")}, distinct_meta(f"r{i}"),
                        run={"exit_code": 0}, metrics={"bw": unknown("no match")}) for i in range(3)]
    verdict = compare(runs, cfg=cfg).noise[0]
    assert "no configuration produced a value" in verdict.reason


def test_a_multi_valued_metric_says_so(cfg):
    """A regex matching every iteration line produced a list, which the
    stats skipped, and the verdict then claimed no run produced a value."""
    from ceteris.metrics import extract

    m = extract("bw 10\nbw 12\nbw 11\n", {"bw": r"bw (\d+)"})
    runs = [Fingerprint({"source.commit": value(c)}, distinct_meta(c), run={"exit_code": 0}, metrics=dict(m))
            for c in ("x", "x", "x", "y", "y", "y")]
    verdict = compare(runs, vary=["source.commit"], cfg=cfg).noise[0]
    assert "multi-valued" in verdict.reason and "3 times" in verdict.reason


def test_a_successful_run_is_unaffected(cfg):
    from ceteris.model import Fingerprint, value

    runs = [Fingerprint({"source.commit": value("x")}, distinct_meta(f"r{i}"),
                        run={"exit_code": 0}, metrics={"bw": value(1.0 + i * 0.01)}) for i in range(3)]
    report = compare(runs, cfg=cfg)
    assert not report.failed_runs and report.exit_code == EXIT_OK


# --- F04: a value that is not a measurement ----------------------------------

import math

import pytest


def _sweep(bad, position):
    """Three samples per configuration with `bad` dropped in at `position`."""
    good_a, good_b = [1.0, 1.01, 1.02], [5.0, 5.01, 5.02]
    good_a = list(good_a); good_a[position] = bad
    return ([rec("a", "x", v) for v in good_a] + [rec("b", "y", v) for v in good_b])


@pytest.mark.parametrize("bad, label", [
    (float("nan"), "NaN"),
    (float("inf"), "positive infinity"),
    (float("-inf"), "negative infinity"),
    (True, "a boolean"),
    ("12.5", "a numeric string"),
])
@pytest.mark.parametrize("position", [0, 1, 2])
def test_an_unusable_sample_never_produces_a_signal(cfg, bad, label, position):
    """Every comparison against NaN is false, so it passed straight through
    min, median and max and satisfied --require-signal."""
    report = compare(_sweep(bad, position), vary=["source.commit"], cfg=cfg, require_signal=True)
    verdict = report.noise[0]
    assert not verdict.assessed, f"{label} at position {position} was assessed"
    assert report.exit_code == EXIT_WITHIN_NOISE


def test_a_zero_sample_makes_the_relative_method_unassessed(cfg):
    """gap and spread are ratios; a zero denominator is not a large number."""
    runs = [rec("a", "x", v) for v in (0.0, 1.0, 1.0)] + [rec("b", "y", v) for v in (5.0, 5.0, 5.0)]
    verdict = compare(runs, vary=["source.commit"], cfg=cfg).noise[0]
    assert not verdict.assessed and "strictly positive" in verdict.reason


def test_a_negative_sample_is_unassessed_not_inverted(cfg):
    runs = [rec("a", "x", v) for v in (-1.0, -1.0, -1.0)] + [rec("b", "y", v) for v in (5.0, 5.0, 5.0)]
    assert not compare(runs, vary=["source.commit"], cfg=cfg).noise[0].assessed


def test_an_overflowing_pattern_match_is_failed_extraction_not_infinity():
    from ceteris.metrics import extract

    got = extract("bandwidth 1e999 GB/s\n", {"bw": r"bandwidth (\S+) GB/s"})
    assert got["bw"].state is State.UNKNOWN
    assert "not measurements" in got["bw"].detail


def test_a_harness_export_of_nan_is_not_recorded_as_a_number():
    from ceteris.adapters import _num

    assert math.isnan(float("nan"))
    assert _num("nan") == "nan"          # kept as evidence of what was exported
    assert _num("inf") == "inf"
    assert _num("12.5") == 12.5


# --- F05: one execution contributes at most once ------------------------------


def test_the_same_record_three_times_is_refused(cfg):
    """Two records passed three times each gave three samples per
    configuration, a zero spread, and a passing signal."""
    from ceteris.compare import DuplicateObservation

    a, b = rec("a", "x", 1.0), rec("b", "y", 5.0)
    with pytest.raises(DuplicateObservation, match="more than once"):
        compare([a, a, a, b, b, b], vary=["source.commit"], cfg=cfg, require_signal=True)


def test_a_copied_record_file_is_refused(cfg, tmp_path):
    """Copying a file does not make a second measurement."""
    from ceteris.compare import DuplicateObservation
    from ceteris.store import load, save

    original = save(rec("a", "x", 1.0), tmp_path / "runs")
    copy = tmp_path / "runs" / "copy.json"
    copy.write_text(original.read_text())
    with pytest.raises(DuplicateObservation):
        compare([load(original), load(copy), rec("b", "y", 5.0)], cfg=cfg)


def test_genuine_repeats_with_equal_measurements_are_kept(cfg):
    """A deterministic benchmark really can produce the same number twice.
    Distinct executions stay distinct; only identical observations collide."""
    runs = [rec("a", "x", 1.0) for _ in range(3)] + [rec("b", "y", 5.0) for _ in range(3)]
    report = compare(runs, vary=["source.commit"], cfg=cfg)
    assert sorted(g.n for g in report.configs) == [3, 3]


@pytest.mark.parametrize("second", ["same", "relative", "symlink"])
def test_naming_one_file_twice_is_a_usage_error(tmp_path, monkeypatch, second):
    from ceteris.cli import main
    from ceteris.compare import EXIT_USAGE
    from ceteris.store import save

    monkeypatch.chdir(tmp_path)
    path = save(rec("a", "x", 1.0), tmp_path / "runs")
    other = save(rec("b", "y", 5.0), tmp_path / "runs")
    if second == "same":
        twin = str(path)
    elif second == "relative":
        twin = str(Path("runs") / path.name)
    else:
        link = tmp_path / "link.json"; link.symlink_to(path); twin = str(link)
    with pytest.raises(SystemExit) as exc:
        main(["compare", str(path), twin, str(other)])
    assert exc.value.code == EXIT_USAGE

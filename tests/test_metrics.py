"""Metrics are the dependent variable. They are displayed, never gated, and
never invented."""

from __future__ import annotations

import pytest

from ceteris.metrics import extract, parse_cli_metrics
from ceteris.model import State

OUTPUT = "size 1048576 bytes  iters 200  bandwidth 57.440 GB/s\n"
PATTERN = r"bandwidth ([0-9.]+) GB/s"


def test_a_matching_pattern_extracts_a_number():
    field = extract(OUTPUT, {"bw": PATTERN})["bw"]
    assert field.state is State.VALUE
    assert field.value == 57.440


def test_a_pattern_that_does_not_match_is_unknown_not_zero():
    """The dangerous alternative is recording 0, or the last number that
    happened to appear, or omitting the metric so nobody notices."""
    field = extract("no numbers here\n", {"bw": PATTERN})["bw"]
    assert field.state is State.UNKNOWN
    assert field.value is None
    assert "did not match" in field.detail


def test_repeated_matches_are_all_kept():
    text = "bandwidth 1.5 GB/s\nbandwidth 2.5 GB/s\n"
    assert extract(text, {"bw": PATTERN})["bw"].value == [1.5, 2.5]


def test_integers_stay_integers():
    assert extract("iters 200\n", {"n": r"iters (\d+)"})["n"].value == 200


def test_a_pattern_without_a_capture_group_is_rejected():
    field = extract(OUTPUT, {"bw": r"bandwidth"})["bw"]
    assert field.state is State.UNKNOWN
    assert "capture group" in field.detail


def test_an_invalid_pattern_does_not_crash_the_run():
    field = extract(OUTPUT, {"bw": r"bandwidth ([0-9.+"})["bw"]
    assert field.state is State.UNKNOWN
    assert "invalid pattern" in field.detail


def test_cli_metric_parsing():
    assert parse_cli_metrics(["bw=x ([0-9]+)"]) == {"bw": r"x ([0-9]+)"}
    with pytest.raises(ValueError, match="NAME=REGEX"):
        parse_cli_metrics(["bandwidth"])


def test_metrics_never_enter_the_comparable_body():
    """If metrics were compared, every real experiment would be flagged."""
    from ceteris.compare import EXIT_OK, compare
    from ceteris.model import Fingerprint, value

    a = Fingerprint({"source.commit": value("x")}, {"label": "a"},
                    metrics={"bw": value(1.0)})
    b = Fingerprint({"source.commit": value("x")}, {"label": "b"},
                    metrics={"bw": value(99.0)})
    assert compare([a, b]).exit_code == EXIT_OK
    assert "bw" not in a.comparable_body()
    assert a.content_hash() == b.content_hash()

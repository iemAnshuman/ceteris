"""Confound detection: an undeclared field that moves in lockstep with the
declared one. The transport x commit case."""

from __future__ import annotations

from ceteris.compare import compare
from ceteris.render import render

from conftest import fp


def test_perfect_confound_is_reported(cfg):
    runs = [
        fp("lci-1", runtime__transport_configured="lci", source__commit="aaa"),
        fp("lci-2", runtime__transport_configured="lci", source__commit="aaa"),
        fp("mpi-1", runtime__transport_configured="mpi", source__commit="bbb"),
        fp("mpi-2", runtime__transport_configured="mpi", source__commit="bbb"),
    ]
    report = compare(runs, vary=["runtime.transport_configured"], cfg=cfg)
    assert report.exit_code == 1
    assert len(report.confounds) == 1
    c = report.confounds[0]
    assert (c.undeclared, c.declared) == ("source.commit", "runtime.transport_configured")
    assert c.table == [("lci", "aaa", 2), ("mpi", "bbb", 2)]
    assert "lockstep" in render(report)


def test_an_unrelated_difference_is_a_plain_violation_not_a_confound(cfg):
    """Commit differs, but not along the transport split: ordinary violation."""
    runs = [
        fp("lci-1", runtime__transport_configured="lci", source__commit="aaa"),
        fp("lci-2", runtime__transport_configured="lci", source__commit="bbb"),
        fp("mpi-1", runtime__transport_configured="mpi", source__commit="aaa"),
        fp("mpi-2", runtime__transport_configured="mpi", source__commit="bbb"),
    ]
    report = compare(runs, vary=["runtime.transport_configured"], cfg=cfg)
    assert report.violations and not report.confounds


def test_repeats_sharing_a_label_are_counted_individually(cfg):
    runs = [fp("lci", runtime__transport_configured="lci", source__commit="aaa") for _ in range(3)]
    runs += [fp("mpi", runtime__transport_configured="mpi", source__commit="bbb") for _ in range(3)]
    c = compare(runs, vary=["runtime.transport_configured"], cfg=cfg).confounds[0]
    assert c.table == [("lci", "aaa", 3), ("mpi", "bbb", 3)]


def test_no_confound_when_nothing_undeclared_differs(cfg):
    runs = [fp("a", runtime__transport_configured="lci"), fp("b", runtime__transport_configured="mpi")]
    assert not compare(runs, vary=["runtime.transport_configured"], cfg=cfg).confounds

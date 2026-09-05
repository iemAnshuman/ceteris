"""The compare engine is the product, so this is the biggest test file."""

from __future__ import annotations

import pytest

from ceteris.compare import (
    EXIT_INDETERMINATE,
    EXIT_OK,
    EXIT_UNDECLARED,
    Classification,
    Verdict,
    compare,
    matches,
)
from ceteris.model import Fingerprint

from conftest import err, fp, na, unk


def paths(results):
    return {r.path for r in results}


def result_for(report, path):
    return next(r for r in report.results if r.path == path)


# --- the basic contract -----------------------------------------------------


def test_identical_runs_are_comparable(cfg):
    a = fp("run-a", source__commit="a1b2c3d", build__cxx_flags="-O3")
    b = fp("run-b", source__commit="a1b2c3d", build__cxx_flags="-O3")
    report = compare([a, b], cfg=cfg)
    assert report.exit_code == EXIT_OK
    assert report.matched_count == 2
    assert not report.violations


def test_undeclared_critical_difference_fails(cfg):
    a = fp("run-a", source__commit="a1b2c3d")
    b = fp("run-b", source__commit="9f8e7d6")
    report = compare([a, b], cfg=cfg)
    assert report.exit_code == EXIT_UNDECLARED
    assert paths(report.violations) == {"source.commit"}


def test_declared_difference_passes(cfg):
    a = fp("run-a", runtime__transport_configured="lci")
    b = fp("run-b", runtime__transport_configured="mpi")
    report = compare([a, b], vary=["runtime.transport_configured"], cfg=cfg)
    assert report.exit_code == EXIT_OK
    assert result_for(report, "runtime.transport_configured").classification is (
        Classification.DECLARED
    )


def test_needs_at_least_two_fingerprints(cfg):
    with pytest.raises(ValueError):
        compare([fp("only")], cfg=cfg)


# --- the four-state model, which is the reason this tool can fail closed ----


def test_not_applicable_on_both_sides_is_a_match(cfg):
    """Two GPU-less laptops genuinely agree about having no GPU."""
    a = fp("run-a", hardware__gpu_driver=na("no nvidia-smi on PATH"))
    b = fp("run-b", hardware__gpu_driver=na("no nvidia-smi on PATH"))
    report = compare([a, b], cfg=cfg)
    assert result_for(report, "hardware.gpu_driver").verdict is Verdict.MATCH
    assert report.exit_code == EXIT_OK


def test_not_applicable_versus_a_value_is_a_difference(cfg):
    """Laptop vs GPU node: absence is itself a hardware difference."""
    a = fp("laptop", hardware__gpu_driver=na("no nvidia-smi on PATH"))
    b = fp("gpu-node", hardware__gpu_driver="550.54.15")
    report = compare([a, b], cfg=cfg)
    result = result_for(report, "hardware.gpu_driver")
    assert result.verdict is Verdict.DIFFER
    assert result.classification is Classification.VIOLATION
    assert report.exit_code == EXIT_UNDECLARED


def test_unknown_is_never_reported_as_matching(cfg):
    """The acceptance criterion: unknown on one side must not read as equal."""
    a = fp("run-a", hardware__gpu_driver="550.54.15")
    b = fp("run-b", hardware__gpu_driver=unk("nvidia-smi timed out"))
    report = compare([a, b], cfg=cfg)
    result = result_for(report, "hardware.gpu_driver")
    assert result.verdict is Verdict.INDETERMINATE
    assert result.classification is Classification.INDETERMINATE
    assert report.exit_code == EXIT_INDETERMINATE
    assert ("run-b", "unknown: nvidia-smi timed out") in result.indeterminate


def test_unknown_on_both_sides_is_still_not_a_match(cfg):
    a = fp("run-a", hardware__gpu_driver=unk("nvidia-smi timed out"))
    b = fp("run-b", hardware__gpu_driver=unk("nvidia-smi timed out"))
    report = compare([a, b], cfg=cfg)
    assert result_for(report, "hardware.gpu_driver").verdict is Verdict.INDETERMINATE
    assert report.exit_code == EXIT_INDETERMINATE


def test_error_state_is_indeterminate(cfg):
    a = fp("run-a", source__commit="a1b2c3d")
    b = fp("run-b", source__commit=err("git returned non-zero"))
    report = compare([a, b], cfg=cfg)
    assert report.exit_code == EXIT_INDETERMINATE


def test_declaring_a_field_does_not_excuse_it_being_unknown(cfg):
    """Declaring intent to vary is not a claim to have measured it."""
    a = fp("run-a", runtime__transport_configured="lci")
    b = fp("run-b", runtime__transport_configured=unk("not readable"))
    report = compare([a, b], vary=["runtime.transport_configured"], cfg=cfg)
    assert report.exit_code == EXIT_INDETERMINATE


def test_field_missing_from_one_fingerprint_is_indeterminate(cfg):
    """A schema mismatch must not silently shrink the checked surface."""
    a = fp("run-a", source__commit="a1b2c3d", hardware__cpu_model="Apple M4")
    b = fp("run-b", source__commit="a1b2c3d")
    report = compare([a, b], cfg=cfg)
    result = result_for(report, "hardware.cpu_model")
    assert result.verdict is Verdict.INDETERMINATE
    assert "schema mismatch" in result.indeterminate[0][1]


# --- severity ---------------------------------------------------------------


def test_informational_difference_does_not_gate(cfg):
    """job_id differs on every pair of runs ever. If it gated, nobody would
    keep the tool switched on."""
    a = fp("run-a", scheduler__job_id="12345")
    b = fp("run-b", scheduler__job_id="12346")
    report = compare([a, b], cfg=cfg)
    assert report.exit_code == EXIT_OK
    assert result_for(report, "scheduler.job_id").classification is (
        Classification.INFORMATIONAL
    )


def test_strict_promotes_informational_to_gating(cfg):
    a = fp("run-a", scheduler__job_id="12345")
    b = fp("run-b", scheduler__job_id="12346")
    report = compare([a, b], cfg=cfg, strict=True)
    assert report.exit_code == EXIT_UNDECLARED


def test_unlisted_field_gates_by_default(cfg):
    """A field added in a later version must not escape the check."""
    a = fp("run-a", brand__new_field="x")
    b = fp("run-b", brand__new_field="y")
    report = compare([a, b], cfg=cfg)
    assert report.exit_code == EXIT_UNDECLARED
    assert result_for(report, "brand.new_field").severity == "material"


# --- declaring intent -------------------------------------------------------


def test_vary_accepts_globs(cfg):
    a = fp("run-a", runtime__env__LCI_ATTR_PACKET_SIZE="73728")
    b = fp("run-b", runtime__env__LCI_ATTR_PACKET_SIZE="8192")
    report = compare([a, b], vary=["runtime.env.LCI_*"], cfg=cfg)
    assert report.exit_code == EXIT_OK


def test_vary_accepts_a_bare_prefix(cfg):
    a = fp("run-a", build__cxx_flags="-O3", build__type="Release")
    b = fp("run-b", build__cxx_flags="-O2", build__type="Debug")
    report = compare([a, b], vary=["build"], cfg=cfg)
    assert report.exit_code == EXIT_OK


def test_prefix_does_not_match_a_similarly_named_sibling(cfg):
    assert matches("build.cxx_flags", "build")
    assert not matches("buildinfo.cxx_flags", "build")


def test_waiver_carries_its_reason(cfg):
    a = fp("run-a", hardware__cpu_model="Xeon 6248")
    b = fp("run-b", hardware__cpu_model="Xeon 6248R")
    report = compare(
        [a, b],
        waive={"hardware.cpu_model": "same partition, different node draw"},
        cfg=cfg,
    )
    assert report.exit_code == EXIT_OK
    result = result_for(report, "hardware.cpu_model")
    assert result.classification is Classification.WAIVED
    assert result.reason == "same partition, different node draw"


def test_waiver_can_cover_an_unknown(cfg):
    a = fp("run-a", hardware__gpu_driver="550.54.15")
    b = fp("run-b", hardware__gpu_driver=unk("nvidia-smi timed out"))
    report = compare([a, b], waive={"hardware.gpu_driver": "known missing"}, cfg=cfg)
    assert report.exit_code == EXIT_OK


def test_declared_but_constant_is_flagged(cfg):
    """You said you swept transport and you did not. The sweep script is the
    likely bug, and nothing else would tell you."""
    a = fp("run-a", runtime__transport_configured="lci")
    b = fp("run-b", runtime__transport_configured="lci")
    report = compare([a, b], vary=["runtime.transport_configured"], cfg=cfg)
    assert report.exit_code == EXIT_OK
    assert report.constant_declarations == ["runtime.transport_configured"]
    strict = compare(
        [a, b], vary=["runtime.transport_configured"], cfg=cfg, strict=True
    )
    assert strict.exit_code == EXIT_UNDECLARED


def test_a_broad_declaration_is_not_flagged_when_something_under_it_varied(cfg):
    """--vary build covering thirty constant CMake entries and three that
    differ has done its job. Listing the thirty would bury the three."""
    a = fp("run-a", build__compiler_id="clang", build__type="Release")
    b = fp("run-b", build__compiler_id="gcc", build__type="Release")
    report = compare([a, b], vary=["build"], cfg=cfg)
    assert report.exit_code == EXIT_OK
    assert report.constant_declarations == []


def test_a_declaration_matching_no_field_is_flagged_as_a_likely_typo(cfg):
    a = fp("run-a", runtime__transport_configured="lci")
    b = fp("run-b", runtime__transport_configured="mpi")
    report = compare([a, b], vary=["runtime.transprot_configured"], cfg=cfg)
    assert report.unmatched_declarations == ["runtime.transprot_configured"]
    # the real field is still undeclared, so the comparison still fails
    assert report.exit_code == EXIT_UNDECLARED


# --- comparators ------------------------------------------------------------


def test_reordered_flags_are_a_difference(cfg):
    """These two probably do build the same binary, and the tool used to say
    so by sorting the tokens. Sorting is what made `-n 2 -N 4` equal to
    `-n 4 -N 2` and `-I a -I b` equal to its reverse, which is a difference
    reported as a match. An extra reported difference is the cheap error;
    the other one is the expensive one. See design F02."""
    a = fp("run-a", build__cxx_flags="-O3 -march=native")
    b = fp("run-b", build__cxx_flags="-march=native -O3")
    assert result_for(compare([a, b], cfg=cfg), "build.cxx_flags").verdict is Verdict.DIFFER


def test_only_whitespace_is_normalised_in_a_flag_string(cfg):
    a = fp("run-a", build__cxx_flags="-O3   -march=native")
    b = fp("run-b", build__cxx_flags=" -O3 -march=native ")
    assert result_for(compare([a, b], cfg=cfg), "build.cxx_flags").verdict is Verdict.MATCH


def test_argument_order_is_a_difference_for_a_launcher(cfg):
    """`-n 2 -N 4` is two tasks on four nodes; the reverse is four on two."""
    a = fp("run-a", execution__launcher_args=["-n", "2", "-N", "4"])
    b = fp("run-b", execution__launcher_args=["-n", "4", "-N", "2"])
    assert result_for(compare([a, b], cfg=cfg), "execution.launcher_args").verdict is Verdict.DIFFER

    inc_a = fp("run-a", execution__launcher_args=["-I", "first", "-I", "second"])
    inc_b = fp("run-b", execution__launcher_args=["-I", "second", "-I", "first"])
    assert result_for(compare([inc_a, inc_b], cfg=cfg), "execution.launcher_args").verdict is Verdict.DIFFER


def test_last_wins_flags_are_not_flattened_by_sorting(cfg):
    """-O2 -O3 builds -O3; -O3 -O2 builds -O2. Same multiset, different binary.
    Reporting these as equal would be the exact error this tool exists to
    prevent, so the comparator must fall back to ordered comparison."""
    a = fp("run-a", build__cxx_flags="-O2 -O3")
    b = fp("run-b", build__cxx_flags="-O3 -O2")
    report = compare([a, b], cfg=cfg)
    assert result_for(report, "build.cxx_flags").verdict is Verdict.DIFFER


# --- n-way ------------------------------------------------------------------


def test_three_runs_group_by_value(cfg):
    a = fp("run-a", source__commit="a1b2c3d")
    b = fp("run-b", source__commit="a1b2c3d")
    c = fp("run-c", source__commit="9f8e7d6")
    report = compare([a, b, c], cfg=cfg)
    result = result_for(report, "source.commit")
    groups = {g.display: g.labels for g in result.groups}
    assert groups == {"a1b2c3d": ["run-a", "run-b"], "9f8e7d6": ["run-c"]}


def test_violation_outranks_indeterminate_in_the_exit_code(cfg):
    a = fp("run-a", source__commit="a1b2c3d", hardware__gpu_driver=unk("x"))
    b = fp("run-b", source__commit="9f8e7d6", hardware__gpu_driver="550.54.15")
    report = compare([a, b], cfg=cfg)
    assert report.violations and report.indeterminates
    assert report.exit_code == EXIT_UNDECLARED

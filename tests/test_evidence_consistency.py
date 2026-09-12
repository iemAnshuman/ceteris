"""Adversarial evidence and invariants at the experimental API boundaries."""

from decimal import Decimal, Inexact, Rounded, localcontext
from itertools import permutations
import json

import pytest

from ceteris import adapters, nodes_evidence as ne
from ceteris.identity import Artifact, compare_snapshots, directory_manifest, observe_all
from ceteris.protocol.encoding import canonical_decimal
from ceteris.protocol.models import convert


def imported(tmp_path, body, fmt=None):
    path = tmp_path / "out.json"
    path.write_text(json.dumps(body))
    return adapters.ingest_evidence(str(path), fmt, ("absent",), 0)


def test_failed_google_case_is_invalid_in_every_position(tmp_path):
    rows = [{"name": "failed", "error_occurred": True},
            {"name": "a", "real_time": 1}, {"name": "b", "real_time": 2}]
    for order in permutations(rows):
        metrics, claim = imported(tmp_path, {"benchmarks": order})
        assert claim["adapter"] == "gbench"
        assert claim["validity"] == "invalid"
        assert all(key.startswith("gbench.") for key in metrics)


@pytest.mark.parametrize("rows", [[], [{}], [None],
    [{"name": "a", "real_time": 1}, {"name": "b", "stats": {"median": 2}}]])
def test_ambiguous_benchmark_exports_are_unavailable(tmp_path, rows):
    _, claim = imported(tmp_path, {"benchmarks": rows})
    assert claim["validity"] == "unavailable"


BAD_NUMBERS = [None, True, False, "broken", [], {}, float("nan"),
               float("inf"), float("-inf"), "NaN", "Infinity", "1e999", 10 ** 400]


@pytest.mark.parametrize("bad", BAD_NUMBERS)
@pytest.mark.parametrize("fmt", ["gbench", "pytest", "hyperfine", "jmh"])
def test_required_export_rejects_unusable_numeric_values(tmp_path, fmt, bad):
    bodies = {
        "gbench": {"benchmarks": [{"name": "a", "real_time": bad}]},
        "pytest": {"benchmarks": [{"name": "a", "stats": {"median": bad}}]},
        "hyperfine": {"results": [{"median": bad, "min": 1}]},
        "jmh": [{"benchmark": "A.a", "primaryMetric": {"score": bad}}],
    }
    metrics, claim = imported(tmp_path, bodies[fmt], fmt)
    assert claim["validity"] == "unavailable"
    assert any(field.is_indeterminate for field in metrics.values())


@pytest.mark.parametrize("bad", [None, True, "broken", "NaN", "Infinity"])
def test_bad_google_repetition_cannot_be_dropped_or_hidden_by_order(tmp_path, bad):
    for order in permutations([1, 3, bad]):
        rows = [{"name": "a", "real_time": number} for number in order]
        metrics, claim = imported(tmp_path, {"benchmarks": rows}, "gbench")
        assert claim["validity"] == "unavailable"
        assert metrics["gbench.a.real_time_ns"].is_indeterminate


@pytest.mark.parametrize("fmt", ["pytest", "jmh"])
def test_duplicate_metric_names_cannot_overwrite_bad_measurements(tmp_path, fmt):
    for order in permutations([None, 1]):
        body = ({"benchmarks": [{"name": "a", "stats": {"median": n}} for n in order]}
                if fmt == "pytest" else
                [{"benchmark": "A.a", "primaryMetric": {"score": n}} for n in order])
        _, claim = imported(tmp_path, body, fmt)
        assert claim["validity"] == "unavailable"


def test_valid_google_repetitions_have_an_order_independent_median(tmp_path):
    for order in permutations([1, "3", 2]):
        metrics, claim = imported(tmp_path, {"benchmarks": [
            {"name": "a", "real_time": n} for n in order]})
        assert claim["validity"] == "valid"
        assert metrics["gbench.a.real_time_ns"].value == 2


@pytest.mark.parametrize("text", ["1.123456789012345678901234567890123456789",
    "123456789012345678901234567890123456789", "0." + "1" * 128,
    "1e308", "1e-308", "-0e-999999999"])
def test_decimal_normalization_is_exact_and_context_independent(text):
    expected = "0" if Decimal(text).is_zero() else format(Decimal(text), "f")
    for precision in (2, 28, 128):
        with localcontext() as context:
            context.prec = precision
            context.Emax, context.Emin = 9, -9
            context.traps[Inexact] = context.traps[Rounded] = True
            assert canonical_decimal(text) == expected
            assert canonical_decimal(canonical_decimal(text)) == expected


def test_decimal_unit_conversion_roundtrips_without_context_rounding():
    number = "1.123456789012345678901234567890123456789"
    for precision in (2, 28, 128):
        with localcontext() as context:
            context.prec = precision
            context.traps[Inexact] = context.traps[Rounded] = True
            converted = convert(number, "s", "ns")
            assert converted == "1123456789.012345678901234567890123456789"
            assert convert(converted, "ns", "s") == number


def test_directory_links_record_link_text_without_following_targets(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    for target in ("A", "B"):
        (tmp_path / target).mkdir()
    link = root / "dataset"
    link.symlink_to("../A", target_is_directory=True)
    declared = [Artifact("data", "root", "input")]
    before = observe_all(declared, tmp_path)
    first = directory_manifest(root)
    assert first["manifest"]["entries"] == [
        {"path": "dataset", "type": "symlink", "link_target": "../A", "bytes": 4}]
    (tmp_path / "A" / "file").write_text("target content is outside this manifest")
    assert directory_manifest(root) == first
    link.unlink()
    link.symlink_to("../B", target_is_directory=True)
    after = observe_all(declared, tmp_path)
    assert before != after
    assert compare_snapshots(before, after, declared)
    link.unlink()
    link.symlink_to(".", target_is_directory=True)
    assert directory_manifest(root)["entry_count"] == 1
    link.unlink()
    link.symlink_to("missing", target_is_directory=True)
    assert directory_manifest(root)["entry_count"] == 1


def node(field, node_id="n1", status="reported"):
    return ne.NodeEvidence(node_id, "before", status,
                           fields={} if field is None else {"gpu": field})


@pytest.mark.parametrize("field", [None, {}, {"state": "unknown"}, {"state": "error"},
    {"state": "value"}, {"state": "unexpected"}, {"state": "unknown", "v": 1}])
def test_incomplete_node_fields_make_the_aggregate_indeterminate(field):
    view = ne.aggregate([node(field)], "gpu")
    assert view["state"] == "unknown"
    assert "n1" in view["reason"]


def test_node_keys_preserve_field_and_response_states():
    variants = [node(None), node({"state": "unknown"}), node({"state": "error"}),
                node({"state": "not_applicable"}), node({"state": "value", "v": "GPU"}),
                node(None, status="missing"), node(None, status="malformed")]
    for key in (ne.multiset_key, ne.placement_key):
        assert len({key([entry], "gpu") for entry in variants}) == len(variants)
        assert key([], "gpu") != key([node(None, status="missing")], "gpu")


def test_node_keys_ignore_order_and_explanations_but_preserve_placement():
    a = node({"state": "unknown", "reason": "timeout"}, "n1")
    b = node({"state": "not_applicable"}, "n2")
    for key in (ne.multiset_key, ne.placement_key):
        assert key([a, b], "gpu") == key([b, a], "gpu")
        changed_reason = node({"state": "unknown", "reason": "another timeout"}, "n1")
        assert key([a, b], "gpu") == key([changed_reason, b], "gpu")
    swapped = [node(b.fields["gpu"], "n1"), node(a.fields["gpu"], "n2")]
    assert ne.multiset_key([a, b], "gpu") == ne.multiset_key(swapped, "gpu")
    assert ne.placement_key([a, b], "gpu") != ne.placement_key(swapped, "gpu")


def test_structural_absence_is_a_known_aggregate_state():
    assert ne.aggregate([node({"state": "not_applicable"})], "gpu")["state"] == "not_applicable"


@pytest.mark.parametrize("bad", BAD_NUMBERS)
@pytest.mark.parametrize("listed_metrics", [False, True])
def test_compare_rechecks_numeric_values_in_required_export_claims(bad, listed_metrics):
    from ceteris.compare import compare
    from ceteris.model import value
    from conftest import fp

    records = [fp(label, hardware__arch="same") for label in ("a", "b")]
    for record in records:
        record.metrics = {"gbench.a.real_time_ns": value(bad)}
        claim = {"adapter": "gbench", "path": "out.json", "validity": "valid"}
        if listed_metrics:
            claim["metrics"] = list(record.metrics)
        record.run = {"exit_code": 0, "exports": [claim]}
    assert compare(records).exit_code == 2


def test_analysis_keeps_threshold_differences_beyond_default_decimal_precision():
    from fractions import Fraction
    from ceteris import analysis

    candidate = "1.00000000000000000000000000001"
    threshold = "0.000000000000000000000000000009"
    for precision in (2, 28, 128):
        with localcontext() as context:
            context.prec = precision
            effect = analysis.pair_effect("1", candidate, "lower")
            assert effect == Fraction(1, 10 ** 29)
            assert analysis.evaluate_predicate("non_regression", threshold, effect, effect) == analysis.FAIL


@pytest.mark.parametrize("fmt,key", [("gbench", "benchmarks"), ("pytest", "benchmarks"),
                                   ("hyperfine", "results"), ("jmh", None)])
@pytest.mark.parametrize("rows", [None, {}, [], [None], [1], ["bad"], [{}]])
def test_malformed_export_rows_are_unavailable_without_parser_crashes(tmp_path, fmt, key, rows):
    _, claim = imported(tmp_path, {key: rows} if key else rows, fmt)
    assert claim["validity"] == "unavailable"


@pytest.mark.parametrize("fmt,key", [("gbench", "benchmarks"), ("pytest", "benchmarks"),
                                   ("hyperfine", "results"), ("jmh", None)])
def test_good_required_exports_accept_real_numbers_and_numeric_text(tmp_path, fmt, key):
    rows = {"gbench": {"name": "a", "real_time": "12.5"},
            "pytest": {"name": "a", "stats": {"median": "12.5"}},
            "hyperfine": {"median": "12.5"},
            "jmh": {"benchmark": "A.a", "primaryMetric": {"score": "12.5"}}}
    body = {key: [rows[fmt]]} if key else [rows[fmt]]
    for explicit in (None, fmt):
        metrics, claim = imported(tmp_path, body, explicit)
        assert claim["adapter"] == fmt
        assert claim["validity"] in ("valid", "unverified")
        assert [f.value for f in metrics.values()] == [12.5]


@pytest.mark.parametrize("names", [None, "metric", 1, [None], [["metric"]]])
def test_malformed_required_metric_lists_are_rejected(names):
    from conftest import fp
    record = fp("bad", cpu="same")
    record.run = {"exit_code": 0, "exports": [{"validity": "valid", "metrics": names}]}
    with pytest.raises(ValueError, match="export.metrics"):
        record.validate()


def test_directory_manifest_is_independent_of_creation_order_and_root(tmp_path):
    manifests = []
    for index, order in enumerate(permutations(["file", "link", "empty"])):
        root = tmp_path / str(index)
        root.mkdir()
        for item in order:
            if item == "file":
                (root / item).write_text("identical content")
            elif item == "link":
                (root / item).symlink_to("empty", target_is_directory=True)
            else:
                (root / item).mkdir()
        manifests.append(directory_manifest(root, include_empty=True))
    assert all(manifest == manifests[0] for manifest in manifests)


def test_node_value_types_and_multiplicity_remain_part_of_identity():
    fields = [{"state": "value", "v": v} for v in (1, "1", True)]
    for key in (ne.multiset_key, ne.placement_key):
        assert len({key([node(field)], "gpu") for field in fields}) == 3
        assert key([node(fields[0])], "gpu") != key([node(fields[0]), node(fields[0])], "gpu")

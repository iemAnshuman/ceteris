"""Authoring and plan resolution. Design section 6."""

from __future__ import annotations

import copy
import hashlib

import pytest

from ceteris import experiment as x

PROFILE = {"id": "native-linux-local", "version": 1, "required_capabilities": []}


def authored(**overrides) -> dict:
    doc = {
        "kind": "ceteris.experiment",
        "schema_version": 1,
        "id": "compression-regression",
        "profile": "native-linux-local@1",
        "variants": [{"id": "base", "revision": "main"},
                     {"id": "candidate", "revision": "HEAD"}],
        "build": {"argv": ["make"], "timeout_s": 900},
        "benchmark": {"adapter": "hyperfine@1", "argv": ["hyperfine", "-N", "./bench"],
                      "timeout_s": 120},
        "artifacts": [{"id": "program", "path": "build/compress", "role": "subject",
                       "mutability": "immutable"}],
        "comparisons": [{"id": "candidate-v-base", "baseline": "base",
                         "candidate": "candidate"}],
        "sampling": {"unit": "process_execution", "pairs": 20,
                     "order": "balanced-random", "seed": "20260905", "retry": "none"},
        "metrics": [{"case_id": "compress/small", "id": "elapsed", "source": "hyperfine.median_s",
                     "unit": "s", "direction": "lower", "domain": "positive",
                     "aggregation": "median", "primary": True,
                     "predicate": {"type": "non_regression", "max_relative_regression": "0.05"}}],
        "analysis": {"method": "paired-median-relative@1", "confidence": "0.95"},
        "policy": {"vary": ["source.commit"]},
    }
    doc.update(overrides)
    return doc


# --- authoring ----------------------------------------------------------------


def test_a_well_formed_experiment_has_no_problems():
    assert x.validate_authored(authored()) == []


def test_a_typo_in_an_authoring_key_is_caught_before_anything_runs():
    problems = x.validate_authored(authored(sampeling={"pairs": 20}))
    assert any("sampeling" in p for p in problems)


def test_a_namespaced_extension_key_is_allowed():
    assert x.validate_authored(authored(**{"acme.example:tuning": {"x": 1}})) == []


def test_a_comparison_must_name_declared_variants():
    doc = authored(comparisons=[{"id": "c", "baseline": "base", "candidate": "ghost"}])
    assert any("ghost" in p for p in x.validate_authored(doc))


def test_a_variant_cannot_be_compared_with_itself():
    doc = authored(comparisons=[{"id": "c", "baseline": "base", "candidate": "base"}])
    assert any("with itself" in p for p in x.validate_authored(doc))


def test_an_experiment_needs_something_to_decide():
    doc = authored()
    doc["metrics"][0]["primary"] = False
    assert any("primary" in p for p in x.validate_authored(doc))


def test_a_randomised_order_needs_a_seed_so_it_can_be_reproduced():
    doc = authored(sampling={"pairs": 20, "order": "balanced-random", "seed": ""})
    assert any("seed" in p for p in x.validate_authored(doc))


@pytest.mark.parametrize("pairs", [0, 3, 8, 21, True])
def test_balanced_random_needs_an_even_count_of_at_least_ten(pairs):
    doc = authored(sampling={"pairs": pairs, "order": "balanced-random", "seed": "s"})
    assert any("balanced-random" in p for p in x.validate_authored(doc))


def test_a_non_decimal_regression_budget_is_caught():
    doc = authored()
    doc["metrics"][0]["predicate"]["max_relative_regression"] = "five percent"
    assert any("regression budget" in p for p in x.validate_authored(doc))


# --- the deterministic schedule -----------------------------------------------


def test_the_schedule_is_balanced():
    blocks = x.block_order("20260905", "c1", 20)
    assert len(blocks) == 20
    assert sum(1 for b in blocks if b["order"] == "AB") == 10
    assert sum(1 for b in blocks if b["order"] == "BA") == 10


def test_the_same_seed_gives_the_same_schedule():
    assert x.block_order("s", "c1", 10) == x.block_order("s", "c1", 10)


def test_a_different_seed_or_comparison_gives_a_different_schedule():
    base = [b["order"] for b in x.block_order("s", "c1", 20)]
    assert [b["order"] for b in x.block_order("t", "c1", 20)] != base
    assert [b["order"] for b in x.block_order("s", "c2", 20)] != base


def test_the_order_comes_from_the_documented_digest_not_a_language_prng():
    """Another implementation reading the plan must schedule identically."""
    seed, comparison, pairs = "20260905", "candidate-v-base", 10
    expected = []
    for label in ("AB", "BA"):
        for index in range(pairs // 2):
            token = f"ceteris-order-v1:{seed}:{comparison}:{label}:{index}"
            expected.append((hashlib.sha256(token.encode()).hexdigest(), label, index))
    expected.sort()
    got = x.block_order(seed, comparison, pairs)
    assert [(b["source_label"], b["source_index"]) for b in got] == \
        [(label, index) for _, label, index in expected]


def test_the_schedule_is_stored_not_merely_its_seed():
    plan = x.resolve(authored(), profile=PROFILE,
                     revisions={"base": "a" * 40, "candidate": "b" * 40})
    assert plan.body["comparisons"][0]["blocks"]
    assert len(plan.schedule) == 40           # two executions per pair


def test_a_block_runs_its_two_slots_in_the_recorded_order():
    ab = x.slots_for({"pair_id": "p1", "order": "AB"}, "base", "candidate")
    ba = x.slots_for({"pair_id": "p1", "order": "BA"}, "base", "candidate")
    assert [s["variant_id"] for s in ab] == ["base", "candidate"]
    assert [s["variant_id"] for s in ba] == ["candidate", "base"]
    assert {s["role"] for s in ab} == {"baseline", "candidate"}


def test_fixed_order_is_available_for_diagnostics():
    blocks = x.fixed_order("c1", 3)
    assert [b["order"] for b in blocks] == ["AB", "AB", "AB"]


# --- resolution ---------------------------------------------------------------


def test_resolution_records_the_full_revision_not_the_authored_name():
    plan = x.resolve(authored(), profile=PROFILE,
                     revisions={"base": "a" * 40, "candidate": "b" * 40})
    variants = {v["id"]: v for v in plan.body["variants"]}
    assert variants["base"]["revision"] == "a" * 40
    assert variants["base"]["authored_revision"] == "main"


def test_the_plan_carries_the_profile_contents_not_just_its_name():
    """A plan that recorded only a name would not say what it required."""
    plan = x.resolve(authored(), profile=PROFILE,
                     revisions={"base": "a" * 40, "candidate": "b" * 40})
    assert plan.body["profile"]["contents"] == PROFILE
    assert plan.body["profile"]["digest"].startswith("sha256:")


def test_the_plan_digest_changes_when_anything_material_changes():
    revisions = {"base": "a" * 40, "candidate": "b" * 40}
    first = x.resolve(authored(), profile=PROFILE, revisions=revisions)
    other = x.resolve(authored(), profile=PROFILE,
                      revisions={**revisions, "candidate": "c" * 40})
    assert first.digest != other.digest
    assert first.digest == x.resolve(authored(), profile=PROFILE, revisions=revisions).digest


def test_a_changed_profile_changes_the_plan_digest():
    revisions = {"base": "a" * 40, "candidate": "b" * 40}
    first = x.resolve(authored(), profile=PROFILE, revisions=revisions)
    stricter = x.resolve(authored(), profile={**PROFILE, "required_capabilities": ["gpu"]},
                         revisions=revisions)
    assert first.digest != stricter.digest


def test_an_invalid_experiment_never_becomes_a_plan():
    with pytest.raises(x.AuthoringError):
        x.resolve(authored(sampling={"pairs": 3, "order": "balanced-random", "seed": "s"}),
                  profile=PROFILE, revisions={"base": "a", "candidate": "b"})


def test_every_planned_execution_is_enumerated_before_anything_runs():
    plan = x.resolve(authored(), profile=PROFILE,
                     revisions={"base": "a" * 40, "candidate": "b" * 40})
    executions = plan.executions()
    assert len(executions) == 40
    assert {e["role"] for e in executions} == {"baseline", "candidate"}
    assert len({e["pair_id"] for e in executions}) == 20


def test_a_resolved_plan_does_not_change_when_its_source_document_does():
    doc = authored()
    plan = x.resolve(doc, profile=PROFILE, revisions={"base": "a" * 40, "candidate": "b" * 40})
    before = plan.digest
    doc["metrics"][0]["predicate"]["max_relative_regression"] = "0.5"
    assert plan.digest == before


# --- amendments ---------------------------------------------------------------


def test_an_amendment_is_a_new_lineage_not_an_edit():
    plan = x.resolve(authored(), profile=PROFILE,
                     revisions={"base": "a" * 40, "candidate": "b" * 40})
    amended = x.amend(plan, {"analysis": {"method": "other@1"}},
                      reason="the first method did not fit the workload")
    assert amended.digest != plan.digest
    assert amended.body["analysis_origin"] == "retrospective"
    assert amended.body["amends"]["plan_digest"] == plan.digest
    assert plan.body["analysis_origin"] == "prospective"


def test_a_retrospective_analysis_says_so_and_cannot_pass_for_prospective():
    plan = x.resolve(authored(), profile=PROFILE,
                     revisions={"base": "a" * 40, "candidate": "b" * 40})
    amended = x.amend(plan, {}, reason="re-read after the fact")
    assert amended.body["analysis_origin"] != plan.body["analysis_origin"]


def test_an_amendment_needs_a_reason():
    plan = x.resolve(authored(), profile=PROFILE,
                     revisions={"base": "a" * 40, "candidate": "b" * 40})
    with pytest.raises(x.AuthoringError, match="reason"):
        x.amend(plan, {}, reason="   ")

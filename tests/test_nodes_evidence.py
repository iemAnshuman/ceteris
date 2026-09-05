"""Per-node evidence. Design section 15.3."""

from __future__ import annotations

import pytest

from ceteris import nodes_evidence as ne

PLAN = "sha256:" + "a" * 64


def response(node_id, cpu="Xeon 6148", plan_digest=PLAN, **extra):
    body = {"node_id": node_id, "plan_digest": plan_digest,
            "fields": {"hardware.cpu_model": {"state": "value", "v": cpu}}}
    body.update(extra)
    return body


# --- collecting ---------------------------------------------------------------


def test_every_expected_node_that_answered_is_reported():
    evidence = ne.collect_responses(["n1", "n2"], [response("n1"), response("n2")],
                                    plan_digest=PLAN)
    assert [e.status for e in evidence] == ["reported", "reported"]


def test_a_node_that_never_answered_is_missing_not_silent():
    """Fifteen of sixteen is not an observation of sixteen."""
    evidence = ne.collect_responses(["n1", "n2"], [response("n1")], plan_digest=PLAN)
    missing = [e for e in evidence if e.status == "missing"]
    assert [e.node_id for e in missing] == ["n2"]
    assert "fifteen of sixteen" in missing[0].reason


def test_two_responses_from_one_node_is_a_duplicate():
    evidence = ne.collect_responses(["n1"], [response("n1"), response("n1")],
                                    plan_digest=PLAN)
    assert "duplicated" in {e.status for e in evidence}


def test_a_response_against_another_plan_is_refused():
    evidence = ne.collect_responses(["n1"], [response("n1", plan_digest="sha256:" + "b" * 64)],
                                    plan_digest=PLAN)
    assert [e.status for e in evidence] == ["wrong_plan", "missing"]


def test_a_response_with_no_field_map_is_malformed():
    evidence = ne.collect_responses(["n1"], [{"node_id": "n1", "plan_digest": PLAN}],
                                    plan_digest=PLAN)
    assert "malformed" in {e.status for e in evidence}


# --- the aggregate is a view, not the storage ---------------------------------


def test_a_homogeneous_allocation_collapses_but_keeps_every_node():
    evidence = ne.collect_responses(["n1", "n2"], [response("n1"), response("n2")],
                                    plan_digest=PLAN)
    view = ne.aggregate(evidence, "hardware.cpu_model")
    assert view["homogeneous"] is True
    assert view["multiset"] == [["Xeon 6148", 2]]
    assert set(view["per_node"]) == {"n1", "n2"}


def test_a_heterogeneous_allocation_says_which_node_had_what():
    """The shipped merge answers what the mix was and loses the placement."""
    evidence = ne.collect_responses(
        ["n1", "n2", "n3"],
        [response("n1", "Xeon 6148"), response("n2", "E5-2660 v3"),
         response("n3", "Xeon 6148")],
        plan_digest=PLAN)
    view = ne.aggregate(evidence, "hardware.cpu_model")
    assert view["homogeneous"] is False
    assert view["multiset"] == [["Xeon 6148", 2], ["E5-2660 v3", 1]]
    assert view["per_node"]["n2"]["v"] == "E5-2660 v3"


def test_any_unusable_node_makes_the_aggregate_unknown():
    evidence = ne.collect_responses(["n1", "n2"], [response("n1")], plan_digest=PLAN)
    view = ne.aggregate(evidence, "hardware.cpu_model")
    assert view["state"] == "unknown" and "n2" in view["reason"]


def test_grouping_ignores_provenance_wording():
    a = response("n1")
    a["fields"]["hardware.cpu_model"]["provenance"] = {"source_ref": "/proc/cpuinfo"}
    b = response("n2")
    b["fields"]["hardware.cpu_model"]["provenance"] = {"source_ref": "sysctl"}
    view = ne.aggregate(ne.collect_responses(["n1", "n2"], [a, b], plan_digest=PLAN),
                        "hardware.cpu_model")
    assert view["homogeneous"] is True


# --- mix against placement ----------------------------------------------------


def test_the_same_mix_on_different_nodes_has_one_multiset_key_and_two_placements():
    first = ne.collect_responses(["n1", "n2"],
                                 [response("n1", "A"), response("n2", "B")], plan_digest=PLAN)
    swapped = ne.collect_responses(["n1", "n2"],
                                   [response("n1", "B"), response("n2", "A")], plan_digest=PLAN)
    assert ne.multiset_key(first, "hardware.cpu_model") == ne.multiset_key(
        swapped, "hardware.cpu_model")
    assert ne.placement_key(first, "hardware.cpu_model") != ne.placement_key(
        swapped, "hardware.cpu_model")


# --- inventory ----------------------------------------------------------------


def test_the_inventory_names_missing_and_unexpected_nodes():
    evidence = ne.collect_responses(["n1", "n2"], [response("n1"), response("n9")],
                                    plan_digest=PLAN)
    got = ne.inventory(["n1", "n2"], evidence)
    assert got["missing"] == ["n2"] and got["unexpected"] == ["n9"]
    assert got["complete"] is False


def test_a_fully_reported_allocation_is_complete():
    evidence = ne.collect_responses(["n1", "n2"], [response("n1"), response("n2")],
                                    plan_digest=PLAN)
    assert ne.inventory(["n1", "n2"], evidence)["complete"] is True


# --- pseudonyms ---------------------------------------------------------------


def test_node_ids_are_stable_within_a_campaign_and_not_across_them():
    assert ne.pseudonym("c1", "medusa00") == ne.pseudonym("c1", "medusa00")
    assert ne.pseudonym("c1", "medusa00") != ne.pseudonym("c2", "medusa00")
    assert "medusa" not in ne.pseudonym("c1", "medusa00")


def test_a_real_hostname_is_optional_disclosure_not_the_key():
    evidence = ne.collect_responses(
        ["n1"], [response("n1", hostname="medusa00.rostam.cct.lsu.edu")], plan_digest=PLAN)
    body = evidence[0].to_json()
    assert body["node_id"] == "n1"
    assert body["hostname"] == "medusa00.rostam.cct.lsu.edu"
    assert ne.collect_responses(["n1"], [response("n1")],
                                plan_digest=PLAN)[0].to_json().get("hostname") is None


# --- the probe's own affinity -------------------------------------------------


def test_the_probes_affinity_is_never_offered_as_the_benchmarks():
    """A one-task-per-node probe observes the mask that probe was given."""
    got = ne.probe_affinity_is_not_rank_affinity({"state": "value", "v": "0-23"})
    assert got["capability"] == "parallelism.probe_affinity@1"
    assert "separate capability" in got["limitation"]


def test_an_unknown_node_status_is_refused():
    with pytest.raises(ValueError):
        ne.NodeEvidence("n1", "before", "probably-fine")

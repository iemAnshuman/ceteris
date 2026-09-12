"""Per-node evidence, kept per node.

Design section 15.3. The shipped merge flattens a heterogeneous allocation
into `[[value, count], ...]` pairs, which answers "what mix of hardware was
there" and destroys "which node had what". That is enough when the mix is
all a policy cares about, and not enough the moment placement matters or a
reviewer wants to know which node was the odd one.

So both are kept: the raw per-node map, and a deterministic aggregate
derived from it. The aggregate is a view, never the storage.

Node IDs here are campaign-local pseudonyms. Real hostnames are disclosure
metadata a site may choose to include, not the identity the record is
keyed by.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field as dcfield
from typing import Any

from .policy import typed_exact
from .protocol.encoding import canonical_bytes, digest

NODE_ID_PREFIX = "node-"

# Why a node's evidence is not usable.
NODE_STATUSES = ("reported", "missing", "malformed", "duplicated", "wrong_plan")


def pseudonym(campaign_id: str, hostname: str) -> str:
    """A stable campaign-local node ID.

    Stable within one campaign so records can be joined, and meaningless
    outside it so sharing a bundle does not publish a site's host names.
    """
    material = canonical_bytes({"campaign": campaign_id, "host": hostname})
    return NODE_ID_PREFIX + hashlib.sha256(material).hexdigest()[:12]


@dataclass
class NodeEvidence:
    """What one node reported, at one stage."""

    node_id: str
    stage: str
    status: str = "reported"
    fields: dict = dcfield(default_factory=dict)
    hostname: "str | None" = None            # optional disclosure only
    reason: str = ""

    def __post_init__(self) -> None:
        if self.status not in NODE_STATUSES:
            raise ValueError(f"{self.status!r} is not one of {', '.join(NODE_STATUSES)}")

    def to_json(self) -> dict:
        body = {"node_id": self.node_id, "stage": self.stage, "status": self.status,
                "fields": self.fields, "reason": self.reason}
        if self.hostname is not None:
            body["hostname"] = self.hostname
        return body


def collect_responses(expected_node_ids, responses, *, plan_digest: str,
                      stage: str = "before") -> list:
    """Turn raw node responses into evidence, naming every way one can fail.

    A response from a node the plan did not expect, two responses from one
    node, a response against a different plan, and a node that never
    answered are four distinct problems, and none of them is silence.
    """
    expected = list(expected_node_ids)
    seen: dict = {}
    evidence: list = []

    for response in responses:
        node_id = response.get("node_id")
        if response.get("plan_digest") not in (None, plan_digest):
            evidence.append(NodeEvidence(
                node_id or "<unknown>", stage, "wrong_plan",
                reason="this node captured against a different plan"))
            continue
        if not isinstance(response.get("fields"), dict):
            evidence.append(NodeEvidence(
                node_id or "<unknown>", stage, "malformed",
                reason="the response carries no field map"))
            continue
        if node_id in seen:
            evidence.append(NodeEvidence(
                node_id, stage, "duplicated",
                reason="more than one response arrived for this node"))
            continue
        seen[node_id] = response
        evidence.append(NodeEvidence(
            node_id, stage, "reported", fields=response["fields"],
            hostname=response.get("hostname")))

    for node_id in expected:
        if node_id not in seen:
            evidence.append(NodeEvidence(
                node_id, stage, "missing",
                reason="this node never reported; fifteen of sixteen is not an "
                       "observation of sixteen"))
    return sorted(evidence, key=lambda e: (e.node_id, e.stage))


def _field_identity(entry, path):
    """Semantic state and value, excluding diagnostic wording and provenance."""
    if entry.status != "reported":
        return {"node_status": entry.status}
    field = entry.fields.get(path)
    if field is None:
        return {"node_status": "reported", "field": {"state": "missing"}}
    if not isinstance(field, dict):
        return {"node_status": "reported", "field": {"state": "malformed"}}
    state = field.get("state")
    if (state not in ("value", "unknown", "error", "not_applicable") or
            (state == "value") != ("v" in field)):
        return {"node_status": "reported", "field": {"state": "malformed"}}
    semantic = {"state": state}
    if state == "value":
        semantic["v"] = field["v"]
    return {"node_status": "reported", "field": semantic}


def aggregate(evidence, path: str) -> dict:
    """Group by field state and typed value while retaining every node's evidence.

    The existing value-only multiset remains available for fully valued fields.
    ``state_multiset`` also records structural absence and indeterminate states.
    Identity helpers always use the latter semantics.
    """
    evidence = list(evidence)
    groups: dict = {}
    per_node: dict = {}
    incomplete = []
    for entry in evidence:
        per_node[entry.node_id] = entry.fields.get(path)
        semantic = _field_identity(entry, path)
        field = semantic.get("field", {})
        if entry.status != "reported" or field.get("state") not in ("value", "not_applicable"):
            incomplete.append(f"{entry.node_id}: {entry.status if entry.status != 'reported' else field['state']}")
        key = repr(typed_exact(semantic))
        groups.setdefault(key, {"field": semantic, "value": field.get("v"), "nodes": []})
        groups[key]["nodes"].append(entry.node_id)

    ordered = sorted(groups.values(), key=lambda g: (-len(g["nodes"]), repr(typed_exact(g["field"]))))
    for group in ordered:
        group["nodes"].sort()
    state = "unknown" if incomplete or not evidence else (
        "not_applicable" if all(g["field"].get("field", {}).get("state") == "not_applicable"
                                for g in ordered) else "value")
    view = {
        "path": path, "state": state, "homogeneous": len(ordered) == 1,
        "state_multiset": [[group["field"], len(group["nodes"])] for group in ordered],
        "per_node": per_node, "groups": ordered,
    }
    if all(g["field"].get("field", {}).get("state") == "value" for g in ordered) and evidence:
        view["multiset"] = [[group["value"], len(group["nodes"])] for group in ordered]
    if state == "unknown":
        view["reason"] = "; ".join(sorted(incomplete)) or "no node evidence"
    return view


def placement_key(evidence, path: str) -> str:
    """Identity of which node reported which state and value, including failures."""
    placement = sorted((e.node_id, repr(typed_exact(_field_identity(e, path)))) for e in evidence)
    return digest({"path": path, "placement": [list(item) for item in placement]})


def multiset_key(evidence, path: str) -> str:
    """Identity of the state/value mix alone, ignoring node IDs and input order."""
    mix = sorted(repr(typed_exact(_field_identity(e, path))) for e in evidence)
    return digest({"path": path, "multiset": mix})


def inventory(expected_node_ids, evidence) -> dict:
    """Whether the allocation was actually observed."""
    reported = sorted({e.node_id for e in evidence if e.status == "reported"})
    problems = sorted({e.node_id for e in evidence if e.status != "reported"})
    expected = sorted(expected_node_ids)
    return {
        "expected": expected,
        "reported": reported,
        "missing": [n for n in expected if n not in reported],
        "unexpected": [n for n in reported if n not in expected],
        "problem_nodes": problems,
        "complete": expected != [] and reported == expected and not problems,
    }


def probe_affinity_is_not_rank_affinity(probe_field: dict) -> dict:
    """The fan-out probe's own affinity, labelled as exactly that.

    A one-task-per-node probe observes the mask that probe was given. That
    is not the affinity the benchmark's ranks ran under, and recording it as
    though it were is the kind of plausible value this tool exists to
    refuse.
    """
    return {
        "capability": "parallelism.probe_affinity@1",
        "field": probe_field,
        "limitation": (
            "this is the capture probe's own affinity mask. The benchmark's "
            "ranks are a different process set, and their affinity is a "
            "separate capability that this does not establish."),
    }


__all__ = [
    "NODE_ID_PREFIX",
    "NODE_STATUSES",
    "NodeEvidence",
    "aggregate",
    "collect_responses",
    "inventory",
    "multiset_key",
    "placement_key",
    "probe_affinity_is_not_rank_affinity",
    "pseudonym",
]

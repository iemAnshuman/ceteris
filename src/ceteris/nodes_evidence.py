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


def aggregate(evidence, path: str) -> dict:
    """A deterministic view of one field across the allocation.

    Grouping is on the typed canonical value, so provenance wording never
    splits a group. The per-node map stays alongside, because a mix is not
    a placement.
    """
    reported = [e for e in evidence if e.status == "reported"]
    incomplete = [e for e in evidence if e.status != "reported"]
    if incomplete:
        return {
            "path": path,
            "state": "unknown",
            "reason": "; ".join(
                f"{e.node_id}: {e.status}" for e in sorted(incomplete, key=lambda e: e.node_id)),
            "per_node": {e.node_id: None for e in incomplete},
        }

    groups: dict = {}
    per_node: dict = {}
    for entry in reported:
        field = entry.fields.get(path)
        per_node[entry.node_id] = field
        key = repr(typed_exact(None if field is None else field.get("v")))
        groups.setdefault(key, {"value": None if field is None else field.get("v"),
                                "nodes": []})
        groups[key]["nodes"].append(entry.node_id)

    ordered = sorted(groups.values(), key=lambda g: (-len(g["nodes"]), repr(g["value"])))
    for group in ordered:
        group["nodes"].sort()
    return {
        "path": path,
        "state": "value",
        "homogeneous": len(ordered) == 1,
        # The multiset view, for a policy that only cares about the mix.
        "multiset": [[group["value"], len(group["nodes"])] for group in ordered],
        # The placement view, for a policy that cares which node had what.
        "per_node": per_node,
        "groups": ordered,
    }


def placement_key(evidence, path: str) -> str:
    """Identity of *which* node had *what*, for a policy that needs it."""
    per_node = {e.node_id: (e.fields.get(path) or {}).get("v")
                for e in evidence if e.status == "reported"}
    return digest({"path": path, "placement": per_node})


def multiset_key(evidence, path: str) -> str:
    """Identity of the mix alone, ignoring which node had what."""
    view = aggregate(evidence, path)
    return digest({"path": path, "multiset": view.get("multiset")})


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

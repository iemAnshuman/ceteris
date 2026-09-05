"""Authoring an experiment, and freezing it into a resolved plan.

Design section 6. The point of the split between an authored experiment and
a resolved plan is that results must not decide the rules they are judged
by. Everything is expanded, ordered and hashed before a single build runs,
and the plan is immutable from that moment.

Resolution may look at the world: it reads revisions and installed tool
versions. Verification never repeats it, and consumes the frozen plan.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field as dcfield
from typing import Any

from .protocol.encoding import CanonicalError, canonical_decimal, digest

EXPERIMENT_KIND = "ceteris.experiment"
EXPERIMENT_SCHEMA = 1
PLAN_KIND = "ceteris.plan"
PLAN_SCHEMA = 1

ORDER_PREFIX = "ceteris-order-v1"
MIN_PAIRS_BALANCED = 10

SAMPLING_ORDERS = ("balanced-random", "fixed-ab")

# Authoring keys. Anything else is a typo unless it is namespaced, and a
# typo caught here costs nothing while the same typo caught after a campaign
# costs the campaign.
EXPERIMENT_KEYS = {
    "kind", "schema_version", "id", "profile", "variants", "build", "benchmark",
    "artifacts", "correctness", "comparisons", "sampling", "metrics", "analysis",
    "policy", "extensions",
}


class AuthoringError(ValueError):
    """The authored experiment cannot be read as written."""

    code = "invalid_experiment"


class PlanFrozen(Exception):
    """Something tried to change a plan after it was resolved."""

    code = "plan_immutable"


def _require(condition, message, code="invalid_experiment"):
    if not condition:
        err = AuthoringError(message)
        err.code = code
        raise err


# --- deterministic schedule ---------------------------------------------------


def block_order(seed: str, comparison_id: str, pairs: int) -> list:
    """The pair order for `balanced-random`, from design section 6.3.

    Half the blocks run baseline first and half run candidate first, and
    which is which is decided by a digest rather than by a language's
    random number generator, so another implementation reading the same plan
    produces the same schedule.

    Randomising order reduces ordering bias. It does not establish
    independence, and it does not remove thermal or cache carryover.
    """
    _require(isinstance(pairs, int) and not isinstance(pairs, bool) and pairs > 0,
             "pairs must be a positive integer")
    _require(pairs % 2 == 0, f"balanced-random needs an even number of pairs, got {pairs}")
    _require(pairs >= MIN_PAIRS_BALANCED,
             f"balanced-random needs at least {MIN_PAIRS_BALANCED} pairs, got {pairs}")

    entries = []
    for label in ("AB", "BA"):
        for index in range(pairs // 2):
            token = f"{ORDER_PREFIX}:{seed}:{comparison_id}:{label}:{index}"
            entries.append({
                "label": label,
                "index": index,
                "digest": hashlib.sha256(token.encode("utf-8")).hexdigest(),
            })
    entries.sort(key=lambda e: (e["digest"], e["label"], e["index"]))
    return [{"pair_id": f"{comparison_id}/p{position:03d}",
             "order": entry["label"],
             "source_label": entry["label"],
             "source_index": entry["index"]}
            for position, entry in enumerate(entries)]


def fixed_order(comparison_id: str, pairs: int) -> list:
    """Baseline first every time. For diagnostics and reviewed protocols."""
    return [{"pair_id": f"{comparison_id}/p{i:03d}", "order": "AB",
             "source_label": "AB", "source_index": i} for i in range(pairs)]


def slots_for(block: dict, baseline: str, candidate: str) -> list:
    """The two executions of one block, in the order they will run."""
    first, second = ((baseline, candidate) if block["order"] == "AB"
                     else (candidate, baseline))
    return [
        {"pair_id": block["pair_id"], "slot": "first", "variant_id": first,
         "role": "baseline" if first == baseline else "candidate"},
        {"pair_id": block["pair_id"], "slot": "second", "variant_id": second,
         "role": "baseline" if second == baseline else "candidate"},
    ]


# --- authoring ----------------------------------------------------------------


def validate_authored(document: dict) -> list:
    """Problems with the authored experiment, as messages."""
    problems: list = []
    if not isinstance(document, dict):
        return ["an experiment must be an object"]
    if document.get("kind") != EXPERIMENT_KIND:
        problems.append(f"kind must be {EXPERIMENT_KIND!r}")
    if document.get("schema_version") != EXPERIMENT_SCHEMA:
        problems.append(f"schema_version must be {EXPERIMENT_SCHEMA}")

    unknown = sorted(set(document) - EXPERIMENT_KEYS)
    for key in unknown:
        if ":" not in key:
            problems.append(
                f"unknown authoring key {key!r}; a namespaced extension key contains a colon"
            )

    variants = document.get("variants") or []
    if len(variants) < 2:
        problems.append("an experiment needs at least two variants")
    ids = [v.get("id") for v in variants if isinstance(v, dict)]
    if len(set(ids)) != len(ids):
        problems.append("variant ids must be unique")

    for comparison in document.get("comparisons") or []:
        for role in ("baseline", "candidate"):
            if comparison.get(role) not in ids:
                problems.append(
                    f"comparison {comparison.get('id')!r} names {role} "
                    f"{comparison.get(role)!r}, which is not a declared variant")
        if comparison.get("baseline") == comparison.get("candidate"):
            problems.append(
                f"comparison {comparison.get('id')!r} compares a variant with itself")

    sampling = document.get("sampling") or {}
    order = sampling.get("order", "balanced-random")
    if order not in SAMPLING_ORDERS:
        problems.append(f"sampling order {order!r} is not one of {', '.join(SAMPLING_ORDERS)}")
    if order == "balanced-random":
        pairs = sampling.get("pairs")
        if not isinstance(pairs, int) or isinstance(pairs, bool) or pairs % 2 or pairs < MIN_PAIRS_BALANCED:
            problems.append(
                f"balanced-random needs an even pairs count of at least "
                f"{MIN_PAIRS_BALANCED}, got {pairs!r}")
        if not sampling.get("seed"):
            problems.append("a randomised order needs an explicit seed, so it can be reproduced")

    primary = [m for m in document.get("metrics") or [] if m.get("primary")]
    if not primary:
        problems.append("at least one metric must be primary; a comparison needs something to decide")
    for metric in document.get("metrics") or []:
        for key in ("case_id", "id", "unit", "direction", "domain"):
            if not metric.get(key):
                problems.append(f"metric {metric.get('id')!r} is missing {key}")
        predicate = metric.get("predicate") or {}
        if predicate.get("type") == "non_regression":
            try:
                canonical_decimal(predicate.get("max_relative_regression"))
            except CanonicalError:
                problems.append(
                    f"metric {metric.get('id')!r} has a non-decimal regression budget")
    return problems


# --- the resolved plan --------------------------------------------------------


@dataclass(frozen=True)
class ResolvedPlan:
    """A frozen experiment: every default expanded, every order fixed.

    Frozen so that nothing observed later can alter what was required. A
    collector discovering a new field appends an observation; it never edits
    the plan.
    """

    body: dict

    @property
    def digest(self) -> str:
        return digest(self.body)

    @property
    def id(self) -> str:
        return self.body["experiment_id"]

    @property
    def schedule(self) -> list:
        return self.body["schedule"]

    @property
    def primary_metrics(self) -> list:
        return [m for m in self.body["metrics"] if m.get("primary")]

    def executions(self) -> list:
        """Every planned execution, in the order it will run."""
        out = []
        for comparison in self.body["comparisons"]:
            for block in comparison["blocks"]:
                out.extend(slots_for(block, comparison["baseline"], comparison["candidate"]))
        return out

    def to_json(self) -> dict:
        return dict(self.body)


def resolve(document: dict, *, profile: dict, revisions: "dict | None" = None,
            tool_versions: "dict | None" = None) -> ResolvedPlan:
    """Expand an authored experiment into an immutable plan.

    The profile is passed in at its exact contents rather than by name: a
    plan that recorded only a profile's name would not say what it required.
    """
    problems = validate_authored(document)
    _require(not problems, "; ".join(problems))

    revisions = revisions or {}
    sampling = dict(document.get("sampling") or {})
    order = sampling.get("order", "balanced-random")
    seed = str(sampling.get("seed", ""))
    pairs = int(sampling.get("pairs", MIN_PAIRS_BALANCED))

    variants = []
    for variant in document["variants"]:
        resolved_revision = revisions.get(variant["id"], variant.get("revision"))
        _require(resolved_revision is not None,
                 f"variant {variant['id']!r} has no revision")
        variants.append({"id": variant["id"], "revision": resolved_revision,
                         "authored_revision": variant.get("revision")})

    comparisons = []
    for comparison in document.get("comparisons") or []:
        blocks = (block_order(seed, comparison["id"], pairs) if order == "balanced-random"
                  else fixed_order(comparison["id"], pairs))
        comparisons.append({
            "id": comparison["id"],
            "baseline": comparison["baseline"],
            "candidate": comparison["candidate"],
            "blocks": blocks,
        })

    # Deep copies throughout: a plan that shared structure with the document
    # it came from would change when that document was edited, and the whole
    # point of freezing it is that results cannot alter their own rules.
    take = lambda key, default: copy.deepcopy(document.get(key, default))  # noqa: E731

    body = {
        "kind": PLAN_KIND,
        "schema_version": PLAN_SCHEMA,
        "experiment_id": document["id"],
        # The profile's contents, not merely its name.
        "profile": {"id": profile.get("id"), "version": profile.get("version"),
                    "contents": copy.deepcopy(profile), "digest": digest(profile)},
        "variants": variants,
        "build": take("build", None),
        "benchmark": take("benchmark", None),
        "artifacts": take("artifacts", None) or [],
        "correctness": take("correctness", None) or {"mode": "none", "validators": []},
        "comparisons": comparisons,
        "sampling": {"unit": sampling.get("unit", "process_execution"),
                     "pairs": pairs, "order": order, "seed": seed,
                     "retry": sampling.get("retry", "none")},
        "metrics": take("metrics", None) or [],
        "analysis": take("analysis", None) or {},
        "policy": take("policy", None) or {},
        "tool_versions": dict(tool_versions or {}),
        "schedule": [],
        "analysis_origin": "prospective",
    }
    plan = ResolvedPlan(body)
    body["schedule"] = plan.executions()
    return ResolvedPlan(body)


def amend(plan: ResolvedPlan, changes: dict, reason: str) -> ResolvedPlan:
    """A new plan lineage, never an edit of the original.

    Changing a threshold, a waiver, a selected run set or an analysis method
    after the fact produces a retrospective analysis. It is labelled as one,
    it points at what it came from, and it does not satisfy a policy that
    asked for prospective rules.
    """
    _require(bool(reason.strip()), "an amendment needs a reason")
    body = dict(plan.body)
    body.update(changes)
    body["analysis_origin"] = "retrospective"
    body["amends"] = {"plan_digest": plan.digest, "reason": reason}
    return ResolvedPlan(body)


__all__ = [
    "AuthoringError",
    "EXPERIMENT_KIND",
    "EXPERIMENT_SCHEMA",
    "MIN_PAIRS_BALANCED",
    "ORDER_PREFIX",
    "PLAN_KIND",
    "ResolvedPlan",
    "amend",
    "block_order",
    "fixed_order",
    "resolve",
    "slots_for",
    "validate_authored",
]

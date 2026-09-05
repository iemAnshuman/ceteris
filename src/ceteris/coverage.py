"""Expected evidence against observed evidence.

Design section 7.2. Coverage answers one question: were the observations the
plan required actually available? It is deliberately separate from whether
they matched, because "the machines agreed" and "we looked" are different
claims and a waiver can only ever touch the second.

The expected set comes from the resolved plan. It never comes from the
records that arrived, since a requirement nobody managed to observe would
then quietly cease to be a requirement.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dcfield
from typing import Any

# Three-valued, because "we could not tell" is not "no".
TRUE, FALSE, UNRESOLVED = True, False, None

SCOPE_SELECTORS = ("controller", "subject", "execution", "campaign", "all_allocated_nodes")

RESULTS = ("satisfied", "incomplete", "unresolved")


class ConditionError(ValueError):
    """A `when` expression that is not in the closed grammar."""

    code = "invalid_condition"


@dataclass(frozen=True)
class Requirement:
    """One capability the plan says must be evidenced."""

    id: str
    capability: str
    scope_selector: Any = "subject"          # a selector name or an explicit list
    stages: tuple = ("before", "after")
    allow_not_applicable: bool = False
    when: "dict | None" = None

    def scopes(self, allocated_nodes=()) -> list:
        """Concrete scopes this requirement expands to."""
        selector = self.scope_selector
        if isinstance(selector, (list, tuple)):
            return list(selector)
        if selector == "all_allocated_nodes":
            return [f"node/{node}" for node in allocated_nodes]
        return [selector]

    def to_json(self) -> dict:
        return {"id": self.id, "capability": self.capability,
                "scope_selector": self.scope_selector, "stages": list(self.stages),
                "allow_not_applicable": self.allow_not_applicable, "when": self.when}


# --- the `when` grammar -------------------------------------------------------


def evaluate_condition(expression, lookup) -> "bool | None":
    """Three-valued evaluation of the closed `when` grammar.

    `{"all": [...]}`, `{"any": [...]}`, `{"equals": {"ref": ..., "value": ...}}`,
    exactly one operator per object. False dominates `all`, true dominates
    `any`, and an unresolved operand otherwise keeps the whole thing
    unresolved. An input nobody could read never silently becomes false.
    """
    if expression is None:
        return TRUE
    if not isinstance(expression, dict) or len(expression) != 1:
        raise ConditionError(
            "a condition is one object with exactly one of all, any or equals"
        )
    operator, operand = next(iter(expression.items()))

    if operator in ("all", "any"):
        if not isinstance(operand, list) or not operand:
            raise ConditionError(f"{operator!r} needs a non-empty list of conditions")
        results = [evaluate_condition(item, lookup) for item in operand]
        if operator == "all":
            if FALSE in results:
                return FALSE
            return UNRESOLVED if UNRESOLVED in results else TRUE
        if TRUE in results:
            return TRUE
        return UNRESOLVED if UNRESOLVED in results else FALSE

    if operator == "equals":
        if not isinstance(operand, dict) or "ref" not in operand or "value" not in operand:
            raise ConditionError("equals needs a ref and a value")
        found, known = lookup(operand["ref"])
        if not known:
            return UNRESOLVED
        # Typed equality: 1 and "1" are different answers.
        return (type(found) is type(operand["value"]) and found == operand["value"])

    raise ConditionError(f"{operator!r} is not one of all, any, equals")


def reference_lookup(fields: dict, parameters: dict):
    """Resolve `field:<scope>:<path>` and `parameter:<name>` references."""

    def lookup(ref: str):
        if not isinstance(ref, str):
            raise ConditionError("a reference must be a string")
        if ref.startswith("parameter:"):
            name = ref[len("parameter:"):]
            return (parameters.get(name), name in parameters)
        if ref.startswith("field:"):
            rest = ref[len("field:"):]
            scope, _, path = rest.partition(":")
            if not path:
                raise ConditionError(f"{ref!r} needs field:<scope>:<path>")
            entry = (fields.get(scope) or {}).get(path)
            if entry is None or entry.get("state") != "value":
                return (None, False)
            return (entry.get("v"), True)
        raise ConditionError(f"{ref!r} is not a field: or parameter: reference")

    return lookup


# --- evaluation ---------------------------------------------------------------


@dataclass
class CoverageResult:
    """What became of one requirement, at one scope and stage."""

    requirement_id: str
    capability: str
    scope: str
    stage: str
    result: str
    reason: str = ""

    def to_json(self) -> dict:
        return {"requirement_id": self.requirement_id, "capability": self.capability,
                "scope": self.scope, "stage": self.stage, "result": self.result,
                "reason": self.reason}


def _entry_for(capabilities, capability, scope, stage):
    for entry in capabilities:
        if (entry.get("capability") == capability and entry.get("scope") == scope
                and entry.get("stage") == stage):
            return entry
    return None


def evaluate_requirement(requirement, capabilities, fields=None, parameters=None,
                         allocated_nodes=()) -> list:
    """Expand one requirement and judge each scope and stage."""
    fields = fields or {}
    parameters = parameters or {}
    try:
        applicable = evaluate_condition(
            requirement.when, reference_lookup(fields, parameters))
    except ConditionError as exc:
        return [CoverageResult(requirement.id, requirement.capability, "*", "*",
                               "unresolved", str(exc))]
    if applicable is FALSE:
        return []
    if applicable is UNRESOLVED:
        return [CoverageResult(
            requirement.id, requirement.capability, "*", "*", "unresolved",
            "the condition deciding whether this applies could not be evaluated")]

    results = []
    scopes = requirement.scopes(allocated_nodes)
    if requirement.scope_selector == "all_allocated_nodes" and not allocated_nodes:
        return [CoverageResult(
            requirement.id, requirement.capability, "all_allocated_nodes", "*",
            "unresolved", "the plan requires every allocated node and none is named")]
    for scope in scopes:
        for stage in requirement.stages:
            entry = _entry_for(capabilities, requirement.capability, scope, stage)
            results.append(_judge(requirement, entry, scope, stage))
    return results


def _judge(requirement, entry, scope, stage) -> CoverageResult:
    make = lambda result, reason: CoverageResult(  # noqa: E731
        requirement.id, requirement.capability, scope, stage, result, reason)
    if entry is None:
        return make("incomplete", f"no evidence for {requirement.capability} at {scope}/{stage}")
    status = entry.get("status")
    if status == "observed":
        # A required field that is unknown inside a capability calling itself
        # observed is a contradiction, and the record should say so.
        bad = [f for f, state in (entry.get("field_states") or {}).items()
               if state in ("unknown", "error")]
        if bad:
            return make("incomplete",
                        f"reported observed while {', '.join(sorted(bad))} could not be "
                        f"read; the capability metadata contradicts its fields")
        return make("satisfied", "")
    if status == "not_applicable":
        if not requirement.allow_not_applicable:
            return make("incomplete",
                        "structurally absent, and this requirement does not accept absence")
        if not entry.get("reason"):
            return make("incomplete", "absence was claimed without applicability evidence")
        return make("satisfied", "")
    return make("incomplete", entry.get("reason") or f"capability status {status}")


def evaluate(requirements, capabilities, *, fields=None, parameters=None,
             allocated_nodes=(), expected_nodes=()) -> dict:
    """Coverage over every requirement.

    Node-scoped evidence needs every expected node present exactly once. A
    count is not enough: fifteen reports from fourteen nodes is not a
    fingerprint of fifteen.
    """
    results = []
    for requirement in requirements:
        results.extend(evaluate_requirement(
            requirement, capabilities, fields, parameters, allocated_nodes))

    node_issues = _node_inventory(capabilities, expected_nodes)
    sufficient = (not node_issues
                  and all(r.result == "satisfied" for r in results))
    return {
        "state": "sufficient" if sufficient else "incomplete",
        "results": [r.to_json() for r in results],
        "incomplete": [r.to_json() for r in results if r.result == "incomplete"],
        "unresolved": [r.to_json() for r in results if r.result == "unresolved"],
        "node_issues": node_issues,
    }


def _node_inventory(capabilities, expected_nodes) -> list:
    if not expected_nodes:
        return []
    issues = []
    seen: dict = {}
    for entry in capabilities:
        scope = entry.get("scope", "")
        if scope.startswith("node/"):
            seen.setdefault(scope[len("node/"):], 0)
            seen[scope[len("node/"):]] += 1
    for node in expected_nodes:
        if node not in seen:
            issues.append({"node": node, "problem": "no evidence from this node"})
    for node in sorted(set(seen) - set(expected_nodes)):
        issues.append({"node": node, "problem": "evidence from a node the plan did not expect"})
    return issues


__all__ = [
    "ConditionError",
    "CoverageResult",
    "RESULTS",
    "Requirement",
    "SCOPE_SELECTORS",
    "evaluate",
    "evaluate_condition",
    "evaluate_requirement",
    "reference_lookup",
]

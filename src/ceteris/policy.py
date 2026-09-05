"""Field rules, comparators, waivers, and the aggregate decision.

Design sections 7.3 to 7.6 and 12.2. Pure: nothing here reads the machine.

Two properties this module is built around. Precedence is explicit, so the
same policy written in a different order always decides the same way, and a
tie that would need an arbitrary winner is an error instead. And a waiver
accepts a specific known difference; it never converts one into a match, and
there is a fixed list of things it cannot touch at all.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field as dcfield
from typing import Any

from .protocol.encoding import canonical_decimal, digest

POLICY_ENGINE = "ceteris-policy@1"

SEVERITIES = ("critical", "material", "informational")
GATING = ("critical", "material")
DEFAULT_SEVERITY = "material"
DEFAULT_COMPARATOR = "typed-exact@1"

# Design section 7.5. These are properties of the evidence itself; a waiver
# is a statement about an accepted difference, not permission to believe a
# record that does not hold together.
UNWAIVABLE = (
    "malformed_record",
    "duplicate_observation",
    "harness_invalid",
    "correctness_failed",
    "receipt_integrity",
    "unsupported_required_semantics",
)

ACCEPTANCE_STATES = ("passed", "passed_with_waivers", "failed", "inconclusive", "not_evaluated")


class AmbiguousPolicy(ValueError):
    """Two rules of equal priority disagree about the same path."""

    code = "ambiguous_policy_rule"


class UnwaivableObligation(ValueError):
    """A waiver aimed at something a waiver cannot reach."""

    code = "unwaivable_obligation"


# --- comparators --------------------------------------------------------------


def typed_exact(value: Any) -> Any:
    """`typed-exact@1`: JSON type, recursive structure and array order.

    Integer 1, string "1" and boolean true are three different observations.
    A comparator that folded them together would report a changed
    configuration as unchanged.
    """
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int):
        return ("int", value)
    if isinstance(value, str):
        return ("str", value)
    if value is None:
        return ("null",)
    if isinstance(value, (list, tuple)):
        return ("array",) + tuple(typed_exact(v) for v in value)
    if isinstance(value, dict):
        return ("object",) + tuple(
            (k, typed_exact(value[k])) for k in sorted(value)
        )
    return ("str", str(value))


def multiset(value: Any) -> Any:
    """`multiset@1`: order-insensitive, duplicate-preserving.

    For genuinely unordered collections only. Duplicates are kept, because
    two of a thing is not one of a thing.
    """
    if not isinstance(value, (list, tuple)):
        return typed_exact(value)
    return ("multiset",) + tuple(sorted(
        (repr(typed_exact(v)) for v in value)
    ))


def decimal_value(value: Any) -> Any:
    """For registry-declared decimal observations only."""
    return ("decimal", canonical_decimal(value))


def logical_path_value(value: Any) -> Any:
    """Exact case, no symlink resolution, no normalisation of case."""
    return ("path", str(value))


COMPARATORS = {
    "typed-exact@1": typed_exact,
    "multiset@1": multiset,
    "decimal@1": decimal_value,
    "logical-path@1": logical_path_value,
}


def comparator(name: str):
    try:
        return COMPARATORS[name]
    except KeyError:
        raise ValueError(
            f"unknown comparator {name!r}; known: {', '.join(sorted(COMPARATORS))}"
        ) from None


# --- rules --------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """One field rule. Priority is explicit; there is no insertion order."""

    id: str
    pattern: str
    priority: int = 0
    severity: str = DEFAULT_SEVERITY
    comparator: str = DEFAULT_COMPARATOR
    scope: str = "*"

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"severity {self.severity!r} is not one of {', '.join(SEVERITIES)}")
        comparator(self.comparator)
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise ValueError("priority must be an integer")

    def matches(self, path: str, scope: str = "subject") -> bool:
        if self.scope != "*" and self.scope != scope:
            return False
        return fnmatch.fnmatchcase(path, self.pattern)

    def to_json(self) -> dict:
        return {"id": self.id, "pattern": self.pattern, "priority": self.priority,
                "severity": self.severity, "comparator": self.comparator, "scope": self.scope}


def expand_prefix(pattern: str) -> str:
    """A bare prefix from the command line becomes an explicit glob.

    Expanded before the plan is hashed, so the stored plan says exactly what
    it meant and two spellings of one intent hash the same.
    """
    if any(ch in pattern for ch in "*?["):
        return pattern
    return pattern + ".*"


@dataclass
class FieldPolicy:
    """The resolved field rules, and how they decide."""

    rules: tuple = ()
    engine: str = POLICY_ENGINE

    def __post_init__(self) -> None:
        self._cache: dict = {}

    def _winner(self, path: str, scope: str) -> "Rule | None":
        matching = [r for r in self.rules if r.matches(path, scope)]
        if not matching:
            return None
        top = max(r.priority for r in matching)
        best = [r for r in matching if r.priority == top]
        distinct = {(r.severity, r.comparator) for r in best}
        if len(distinct) > 1:
            shown = "; ".join(
                f"{r.id!r} ({r.pattern!r}) says {r.severity}/{r.comparator}"
                for r in sorted(best, key=lambda r: r.id)
            )
            raise AmbiguousPolicy(
                f"{path!r} at scope {scope!r} matches rules of equal priority "
                f"{top} that disagree: {shown}. Give one a higher priority, or "
                f"an exact-path rule of its own."
            )
        # Equivalent duplicates collapse; their source IDs stay for explanation.
        return sorted(best, key=lambda r: r.id)[0]

    def decide(self, path: str, scope: str = "subject") -> dict:
        key = (path, scope)
        if key not in self._cache:
            rule = self._winner(path, scope)
            self._cache[key] = {
                "severity": rule.severity if rule else DEFAULT_SEVERITY,
                "comparator": rule.comparator if rule else DEFAULT_COMPARATOR,
                "rule_id": rule.id if rule else None,
                "matched_by": [r.id for r in sorted(self.rules, key=lambda r: r.id)
                               if rule and r.matches(path, scope)
                               and r.priority == rule.priority
                               and (r.severity, r.comparator) == (rule.severity, rule.comparator)],
            }
        return self._cache[key]

    def severity_of(self, path: str, scope: str = "subject") -> str:
        return self.decide(path, scope)["severity"]

    def comparator_of(self, path: str, scope: str = "subject") -> str:
        return self.decide(path, scope)["comparator"]

    def gates(self, path: str, scope: str = "subject") -> bool:
        return self.severity_of(path, scope) in GATING

    def canonical_key(self, path: str, value: Any, scope: str = "subject") -> Any:
        return comparator(self.comparator_of(path, scope))(value)

    @property
    def identity(self) -> str:
        """Digest over the effective rules and the engine that reads them.

        The rules alone are not the policy: how ties and precedence resolve
        is part of what a verdict meant.
        """
        return digest({"engine": self.engine,
                       "rules": sorted((r.to_json() for r in self.rules),
                                       key=lambda r: (r["priority"], r["id"]))})


# --- waivers ------------------------------------------------------------------


@dataclass(frozen=True)
class Waiver:
    """An accepted, specific, attributed exception."""

    id: str
    target: str
    reason: str
    reference: str
    kind: str = "field"                     # field or capability
    comparisons: tuple = ()                 # empty means every comparison
    expires: "str | None" = None            # RFC 3339 date

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError(f"waiver {self.id!r} needs a reason")
        if not self.reference.strip():
            raise ValueError(
                f"waiver {self.id!r} needs a reference: who accepted this, and where"
            )
        if self.kind not in ("field", "capability"):
            raise ValueError("waiver kind is field or capability")

    def covers(self, target: str, comparison: "str | None" = None) -> bool:
        if self.comparisons and comparison is not None and comparison not in self.comparisons:
            return False
        return fnmatch.fnmatchcase(target, self.target)

    def expired_at(self, campaign_start: "str | None") -> bool:
        """Expiry is judged against the campaign, not against now.

        Re-reading an old report must not change what it decided.
        """
        if not self.expires or not campaign_start:
            return False
        return campaign_start[:10] > self.expires[:10]

    def to_json(self) -> dict:
        return {"id": self.id, "target": self.target, "kind": self.kind,
                "reason": self.reason, "reference": self.reference,
                "comparisons": list(self.comparisons), "expires": self.expires}


def check_waivable(obligation_code: str) -> None:
    """Refuse a waiver aimed at something no waiver can reach."""
    if obligation_code in UNWAIVABLE:
        raise UnwaivableObligation(
            f"{obligation_code} cannot be waived. A waiver accepts a known "
            f"difference or a missing observation; it cannot make a malformed "
            f"record well formed, a failed check passed, or a broken receipt "
            f"whole."
        )


# --- declared variation -------------------------------------------------------


@dataclass
class Variation:
    """What the experiment said would differ, and where.

    `vary` permits a difference between the named variants. It does not
    permit one between repeats of a single variant, nor drift inside one
    execution, nor a missing value: those are not the change that was
    intended, and reading them as permitted is how an accident becomes a
    result.
    """

    patterns: tuple = ()
    across_variants: tuple = ()
    require_observed_change: tuple = ()

    def permits(self, path: str, variants_involved) -> bool:
        involved = set(variants_involved)
        if len(involved) < 2:
            return False                      # repeats of one variant
        if self.across_variants and not involved.issubset(set(self.across_variants)):
            return False
        return any(fnmatch.fnmatchcase(path, p) for p in self.patterns)

    def unmet_assertions(self, changed_paths) -> list:
        """Declared changes that did not actually happen.

        An experiment whose intended change never took effect is a broken
        experiment, even if the two builds happen to measure the same.
        """
        changed = set(changed_paths)
        return [p for p in self.require_observed_change
                if not any(fnmatch.fnmatchcase(c, p) for c in changed)]


# --- the aggregate decision ---------------------------------------------------


@dataclass
class Obligation:
    """One requirement, and what became of it."""

    id: str
    kind: str                                # coverage, comparability, correctness,
                                             # execution, measurement, assertion
    state: str                               # satisfied, violated, unresolved, waived
    detail: str = ""
    waiver_id: "str | None" = None

    def to_json(self) -> dict:
        return {"id": self.id, "kind": self.kind, "state": self.state,
                "detail": self.detail, "waiver_id": self.waiver_id}


@dataclass
class Decision:
    """The dimensions of design section 12.1, and the acceptance they imply."""

    execution: str = "passed"                # passed, failed, incomplete
    correctness: str = "unverified"          # validated, failed, unverified
    coverage: str = "sufficient"             # sufficient, incomplete
    comparability: str = "compatible"        # compatible, incompatible, indeterminate
    measurement: str = "assessed"            # assessed, inconclusive, unavailable
    obligations: list = dcfield(default_factory=list)
    diagnostic: bool = False

    def acceptance(self) -> str:
        """Design section 12.2, in order. Every reason is kept even once an
        earlier one has decided the outcome."""
        if self.diagnostic:
            return "not_evaluated"
        if self.execution == "failed" or self.correctness == "failed":
            return "failed"
        if self.comparability == "incompatible":
            return "failed"
        if any(o.state == "violated" for o in self.obligations):
            return "failed"
        if (self.coverage == "incomplete" or self.execution == "incomplete"
                or self.comparability == "indeterminate"
                or self.measurement == "unavailable"
                or any(o.state == "unresolved" for o in self.obligations)):
            return "inconclusive"
        if self.measurement == "inconclusive":
            return "inconclusive"
        if any(o.state == "waived" for o in self.obligations):
            return "passed_with_waivers"
        return "passed"

    @property
    def eligible_for_acceptance(self) -> bool:
        """Inference may still be computed for diagnostics on evidence that
        cannot support acceptance; it just cannot drive a passing policy."""
        return self.acceptance() in ("passed", "passed_with_waivers")

    def to_json(self) -> dict:
        return {
            "execution": self.execution,
            "correctness": self.correctness,
            "coverage": self.coverage,
            "comparability": self.comparability,
            "measurement": self.measurement,
            "acceptance": self.acceptance(),
            "obligations": [o.to_json() for o in self.obligations],
        }


__all__ = [
    "ACCEPTANCE_STATES",
    "AmbiguousPolicy",
    "COMPARATORS",
    "DEFAULT_COMPARATOR",
    "DEFAULT_SEVERITY",
    "Decision",
    "FieldPolicy",
    "GATING",
    "Obligation",
    "POLICY_ENGINE",
    "Rule",
    "SEVERITIES",
    "UNWAIVABLE",
    "UnwaivableObligation",
    "Variation",
    "Waiver",
    "check_waivable",
    "comparator",
    "expand_prefix",
    "multiset",
    "typed_exact",
]

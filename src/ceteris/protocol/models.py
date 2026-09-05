"""Immutable protocol-facing types: fields, capabilities, metric observations.

These are the schema 4 shapes from design sections 5.5 and 5.6. They are
deliberately separate from `ceteris.model.Field`, which is the shipped
schema 3 type: the two coexist while the migration runs, and conflating them
is how a legacy record would silently acquire evidence it never carried.

Nothing here touches the machine. A type either describes an observation
somebody made, or it refuses to be constructed.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dcfield
from typing import Any

from .encoding import CanonicalError, canonical_decimal, is_digest

# --- registries ---------------------------------------------------------------

FIELD_STATES = ("value", "not_applicable", "unknown", "error")

CAPABILITY_STATUSES = ("observed", "not_applicable", "unavailable", "unsupported", "excluded")

CAPABILITY_STAGES = ("resolution", "before", "after", "validation")

# Units the first release knows. Anything else is a namespaced custom unit
# and must match exactly, because guessing that two unfamiliar units are
# compatible is how a comparison silently changes what it measured.
UNITS = ("s", "ns", "us", "ms", "B", "B/s", "count", "count/s", "ratio")

# Exact powers of ten only. Bytes and bits are not interchangeable, and
# neither are decimal and binary prefixes.
_TIME_IN_SECONDS = {"s": 0, "ms": -3, "us": -6, "ns": -9}

DIRECTIONS = ("lower", "higher", "none")

DOMAINS = ("positive", "nonnegative", "real")

SAMPLING_UNITS = ("process_execution", "harness_iteration", "aggregate_report")


class ProtocolError(ValueError):
    """A protocol object that cannot be constructed as described."""

    code = "invalid_protocol_object"


def _require(condition: bool, message: str, code: str = "invalid_protocol_object") -> None:
    if not condition:
        err = ProtocolError(message)
        err.code = code
        raise err


# --- provenance ---------------------------------------------------------------


@dataclass(frozen=True)
class Provenance:
    """How an observation was obtained.

    Structured rather than a prose sentence, so a reader can group by
    collector and version instead of matching strings, and so a wording
    change is not mistaken for the environment changing.
    """

    collector_id: str
    collector_version: str
    source_kind: str          # command, file, environment, api, derived
    source_ref: str
    detail: "str | None" = None

    SOURCE_KINDS = ("command", "file", "environment", "api", "derived")

    def __post_init__(self) -> None:
        _require(bool(self.collector_id), "provenance needs a collector_id")
        _require(self.source_kind in self.SOURCE_KINDS,
                 f"source_kind {self.source_kind!r} is not one of {', '.join(self.SOURCE_KINDS)}")

    def to_json(self) -> dict:
        out = {
            "collector_id": self.collector_id,
            "collector_version": self.collector_version,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
        }
        if self.detail is not None:
            out["detail"] = self.detail
        return out


# --- fields -------------------------------------------------------------------


@dataclass(frozen=True)
class Field:
    """One observation, in one of the four states.

    `value` carries `v`; the other three must not, because a field that is
    both unknown and has a value is two claims at once and a reader would be
    entitled to believe either.
    """

    state: str
    v: Any = None
    provenance: "Provenance | None" = None
    reason: "str | None" = None
    evidence_refs: tuple = ()

    def __post_init__(self) -> None:
        _require(self.state in FIELD_STATES,
                 f"field state {self.state!r} is not one of {', '.join(FIELD_STATES)}",
                 "unknown_enum_value")
        if self.state == "value":
            _require(self.v is not None, "a value field must carry v", "missing_value")
        else:
            _require(self.v is None,
                     f"a {self.state} field must not carry a value", "value_on_non_value_state")
        if self.state == "not_applicable":
            _require(bool(self.reason),
                     "not_applicable needs an applicability reason: why the thing is "
                     "structurally absent here", "missing_applicability_reason")
            _require("not implemented" not in (self.reason or "").lower(),
                     "'not implemented' is not an applicability reason; the thing may "
                     "well be present and simply was not looked for",
                     "missing_applicability_reason")
        if self.state in ("unknown", "error"):
            _require(bool(self.reason), f"{self.state} needs a reason", "missing_reason")
        for ref in self.evidence_refs:
            _require(is_digest(ref), f"evidence reference {ref!r} is not a digest")

    def to_json(self) -> dict:
        out: dict = {"state": self.state}
        if self.state == "value":
            out["v"] = self.v
        if self.provenance is not None:
            out["provenance"] = self.provenance.to_json()
        if self.reason is not None:
            out["reason"] = self.reason
        if self.evidence_refs:
            out["evidence_refs"] = list(self.evidence_refs)
        return out


# --- capability evidence ------------------------------------------------------


def valid_scope(scope: str) -> bool:
    """`controller`, `subject`, `node/<id>`, `execution`, `campaign`,
    `validator/<id>`. Scope says whose machine an observation describes; the
    capturing process's environment is never silently attributed to a remote
    rank or a container."""
    if scope in ("controller", "subject", "execution", "campaign"):
        return True
    for prefix in ("node/", "validator/"):
        if scope.startswith(prefix) and len(scope) > len(prefix):
            return True
    return False


@dataclass(frozen=True)
class Capability:
    """Whether a required observation was actually available, and where."""

    capability: str
    version: int
    scope: str
    stage: str
    status: str
    fields: tuple = ()
    reason: "str | None" = None
    evidence_refs: tuple = ()

    def __post_init__(self) -> None:
        _require(self.status in CAPABILITY_STATUSES,
                 f"capability status {self.status!r} is not one of "
                 f"{', '.join(CAPABILITY_STATUSES)}", "unknown_enum_value")
        _require(self.stage in CAPABILITY_STAGES,
                 f"capability stage {self.stage!r} is not one of "
                 f"{', '.join(CAPABILITY_STAGES)}", "unknown_enum_value")
        _require(valid_scope(self.scope), f"scope {self.scope!r} is not a known scope")
        _require(isinstance(self.version, int) and self.version >= 1,
                 "capability version must be a positive integer")
        if self.status != "observed":
            _require(bool(self.reason),
                     f"a {self.status} capability must say why", "missing_reason")

    @property
    def satisfies_requirement(self) -> bool:
        """Only an actual observation, or a structural absence, answers a
        requirement. Unavailable, unsupported and excluded do not, whatever
        a policy later decides to waive."""
        return self.status in ("observed", "not_applicable")

    def to_json(self) -> dict:
        return {
            "capability": self.capability,
            "version": self.version,
            "scope": self.scope,
            "stage": self.stage,
            "status": self.status,
            "fields": list(self.fields),
            "reason": self.reason,
            "evidence_refs": list(self.evidence_refs),
        }


# --- metric observations ------------------------------------------------------


def convert(estimate: str, unit: str, to_unit: str) -> str:
    """Convert between compatible units by an exact power of ten.

    Only within the time family. Bytes are not bits, and a decimal prefix is
    not a binary one; a conversion that is not exact is refused rather than
    rounded, because the rounding would end up inside a policy decision.
    """
    if unit == to_unit:
        return canonical_decimal(estimate)
    _require(unit in _TIME_IN_SECONDS and to_unit in _TIME_IN_SECONDS,
             f"no exact conversion from {unit!r} to {to_unit!r}", "incompatible_units")
    from decimal import Decimal

    shift = _TIME_IN_SECONDS[unit] - _TIME_IN_SECONDS[to_unit]
    return canonical_decimal(Decimal(canonical_decimal(estimate)).scaleb(shift))


@dataclass(frozen=True)
class Metric:
    """One measured quantity, with everything a policy needs to read it.

    A number without its unit, direction and domain is not a measurement a
    rule can be written against: `lower` and `higher` decide what an
    improvement is, and the domain decides whether a relative method applies
    at all.
    """

    case_id: str
    metric_id: str
    unit: str
    direction: str
    domain: str
    state: str = "value"
    estimate: "str | None" = None
    aggregation: "str | None" = None
    sampling_unit: str = "process_execution"
    raw_samples: tuple = ()
    inner_sample_count: "int | None" = None
    source: dict = dcfield(default_factory=dict)
    reason: "str | None" = None

    def __post_init__(self) -> None:
        _require(self.state in FIELD_STATES,
                 f"metric state {self.state!r} is not one of {', '.join(FIELD_STATES)}",
                 "unknown_enum_value")
        _require(self.unit in UNITS or ":" in self.unit,
                 f"unit {self.unit!r} is not a registry unit ({', '.join(UNITS)}); "
                 f"a custom unit uses a namespaced identifier", "unknown_unit")
        _require(self.direction in DIRECTIONS,
                 f"direction {self.direction!r} is not one of {', '.join(DIRECTIONS)}",
                 "unknown_enum_value")
        _require(self.domain in DOMAINS,
                 f"domain {self.domain!r} is not one of {', '.join(DOMAINS)}",
                 "unknown_enum_value")
        _require(self.sampling_unit in SAMPLING_UNITS,
                 f"sampling_unit {self.sampling_unit!r} is not one of "
                 f"{', '.join(SAMPLING_UNITS)}", "unknown_enum_value")
        if self.state == "value":
            _require(self.estimate is not None,
                     "a value metric must carry an estimate", "missing_value")
            canonical_decimal(self.estimate)          # raises if not canonical
            self._check_domain(self.estimate)
        else:
            _require(self.estimate is None,
                     f"a {self.state} metric must not carry an estimate",
                     "value_on_non_value_state")
            _require(bool(self.reason),
                     f"a {self.state} metric must say why", "missing_reason")
        for sample in self.raw_samples:
            canonical_decimal(sample)
            self._check_domain(sample)
        if self.inner_sample_count is not None:
            _require(isinstance(self.inner_sample_count, int) and self.inner_sample_count >= 0,
                     "inner_sample_count must be a nonnegative integer")

    def _check_domain(self, text: str) -> None:
        from decimal import Decimal

        value = Decimal(canonical_decimal(text))
        if self.domain == "positive":
            _require(value > 0,
                     f"{text} is outside the declared domain 'positive' for "
                     f"{self.metric_id}", "domain_violation")
        elif self.domain == "nonnegative":
            _require(value >= 0,
                     f"{text} is outside the declared domain 'nonnegative' for "
                     f"{self.metric_id}", "domain_violation")

    @property
    def identity(self) -> tuple:
        """Two observations of this identity in one run is a duplicate,
        unless they are explicitly parameterised cases."""
        return (self.case_id, self.metric_id)

    @property
    def eligible_for_directional_predicate(self) -> bool:
        """A metric with no direction can be shown but cannot decide whether
        a change was an improvement."""
        return self.state == "value" and self.direction in ("lower", "higher")

    def to_json(self) -> dict:
        return {
            "case_id": self.case_id,
            "metric_id": self.metric_id,
            "unit": self.unit,
            "direction": self.direction,
            "domain": self.domain,
            "state": self.state,
            "estimate": self.estimate,
            "aggregation": self.aggregation,
            "sampling_unit": self.sampling_unit,
            "raw_samples": list(self.raw_samples),
            "inner_sample_count": self.inner_sample_count,
            "source": dict(self.source),
            "reason": self.reason,
        }


__all__ = [
    "CAPABILITY_STAGES",
    "CAPABILITY_STATUSES",
    "Capability",
    "DIRECTIONS",
    "DOMAINS",
    "FIELD_STATES",
    "Field",
    "Metric",
    "ProtocolError",
    "Provenance",
    "SAMPLING_UNITS",
    "UNITS",
    "CanonicalError",
    "convert",
    "valid_scope",
]

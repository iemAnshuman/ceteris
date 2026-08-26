"""Core data model: four-valued fields and the fingerprint container.

The four states are the reason this tool can fail closed correctly. The
distinction that matters most is UNKNOWN vs NOT_APPLICABLE:

    NOT_APPLICABLE  the thing is structurally absent (no GPU in this machine)
    UNKNOWN         the thing may exist but we could not read it (nvidia-smi hung)

Two GPU-less laptops both report NOT_APPLICABLE for gpu.driver_version and that
is a genuine match. A laptop compared against a GPU node reports
NOT_APPLICABLE vs a real version string, which is a genuine hardware
difference. Collapsing those two states into one gets one of those cases
wrong no matter which way you collapse them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field as dcfield
from enum import Enum
from typing import Any

SCHEMA_VERSION = 1


class State(str, Enum):
    VALUE = "value"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    ERROR = "error"


@dataclass(frozen=True)
class Field:
    """One captured field.

    provenance records how the value was obtained -- the literal command or
    source. When compare reports a difference the immediate next question is
    "how did you determine that", and the answer should be in the artifact
    rather than in the documentation.
    """

    state: State
    value: Any = None
    provenance: str | None = None
    detail: str | None = None

    @property
    def is_known(self) -> bool:
        return self.state is State.VALUE

    @property
    def is_indeterminate(self) -> bool:
        return self.state in (State.UNKNOWN, State.ERROR)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"s": self.state.value}
        if self.state is State.VALUE:
            out["v"] = self.value
        if self.provenance:
            out["p"] = self.provenance
        if self.detail:
            out["d"] = self.detail
        return out

    @classmethod
    def from_json(cls, raw: Any) -> "Field":
        if not isinstance(raw, dict) or "s" not in raw:
            raise ValueError(f"malformed field: {raw!r}")
        try:
            state = State(raw["s"])
        except ValueError as exc:
            raise ValueError(f"unknown field state: {raw['s']!r}") from exc
        return cls(
            state=state,
            value=raw.get("v"),
            provenance=raw.get("p"),
            detail=raw.get("d"),
        )


def value(v: Any, provenance: str | None = None) -> Field:
    return Field(State.VALUE, value=v, provenance=provenance)


def unknown(detail: str, provenance: str | None = None) -> Field:
    return Field(State.UNKNOWN, provenance=provenance, detail=detail)


def not_applicable(detail: str, provenance: str | None = None) -> Field:
    return Field(State.NOT_APPLICABLE, provenance=provenance, detail=detail)


def error(detail: str, provenance: str | None = None) -> Field:
    return Field(State.ERROR, provenance=provenance, detail=detail)


@dataclass
class Fingerprint:
    """A captured environment.

    `fields` is flat and keyed by dotted path ("source.commit"). Flat keys make
    globbing, severity lookup and diffing straightforward; the grouping in the
    brief is presentational and is recovered at render time by splitting on the
    first dot.

    `meta` holds everything that must NOT participate in comparison --
    captured_at above all. It is excluded from the content hash by
    construction, so two captures of an identical environment hash identically.
    """

    fields: dict[str, Field]
    meta: dict[str, Any]
    # Set when the fingerprint came from `ceteris run`. Non-comparable
    # execution facts: exit code, timing, mid-run drift, output tail.
    run: dict[str, Any] = dcfield(default_factory=dict)
    # The dependent variable. Metrics are excluded from the comparable body BY
    # CONSTRUCTION: they are what you are measuring, so they are supposed to
    # differ. Gating on them would flag every real experiment.
    metrics: dict[str, Field] = dcfield(default_factory=dict)

    @property
    def label(self) -> str:
        return str(self.meta.get("label") or "unnamed")

    @property
    def drift(self) -> list[dict[str, Any]]:
        return list(self.run.get("drift") or [])

    def comparable_body(self) -> dict[str, Any]:
        return {k: self.fields[k].to_json() for k in sorted(self.fields)}

    def content_hash(self) -> str:
        blob = json.dumps(
            self.comparable_body(), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def to_json(self) -> dict[str, Any]:
        meta = dict(self.meta)
        meta["schema_version"] = SCHEMA_VERSION
        meta["content_hash"] = self.content_hash()
        out: dict[str, Any] = {"meta": meta, "fields": self.comparable_body()}
        if self.run:
            out["run"] = self.run
        if self.metrics:
            out["metrics"] = {
                k: self.metrics[k].to_json() for k in sorted(self.metrics)
            }
        return out

    def dumps(self) -> str:
        return json.dumps(self.to_json(), sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_json(cls, raw: Any) -> "Fingerprint":
        if not isinstance(raw, dict) or "fields" not in raw:
            raise ValueError("not a ceteris fingerprint: missing 'fields'")
        fields_raw = raw["fields"]
        if not isinstance(fields_raw, dict):
            raise ValueError("not a ceteris fingerprint: 'fields' is not an object")
        fields = {k: Field.from_json(v) for k, v in fields_raw.items()}
        meta = raw.get("meta") or {}
        if not isinstance(meta, dict):
            raise ValueError("not a ceteris fingerprint: 'meta' is not an object")
        metrics_raw = raw.get("metrics") or {}
        metrics = {k: Field.from_json(v) for k, v in metrics_raw.items()}
        return cls(
            fields=fields,
            meta=dict(meta),
            run=dict(raw.get("run") or {}),
            metrics=metrics,
        )

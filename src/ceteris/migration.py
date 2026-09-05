"""Reading old records without pretending they say more than they do.

Design section 16.2. Migration normalises a schema 2 or 3 record into the
schema 4 shape so it can be viewed and compared diagnostically. It never
repairs an omission: a record captured without a pre-run subject hash does
not acquire one by being converted, and a record with no correctness
evidence is `unverified` afterwards exactly as it was before.

The original is never rewritten. A migrated record is a derivative, carries
`migration` provenance, and points at the digest of what it came from.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field as dcfield
from typing import Any

from .protocol.encoding import canonical_bytes

MIGRATION_ID = "legacy-to-schema4@1"
SUPPORTED_SOURCE_SCHEMAS = (2, 3)

# What a legacy record cannot tell us, whatever we do to it.
LIMITATION_CODES = (
    "no_execution_identity",
    "no_prospective_plan",
    "no_capability_manifest",
    "ambiguous_not_applicable",
    "no_correctness_evidence",
    "no_pre_execution_identity",
    "no_raw_samples",
    "no_drift_observation",
)


@dataclass
class Limitation:
    """One thing the source record could not say."""

    code: str
    detail: str

    def to_json(self) -> dict:
        return {"code": self.code, "detail": self.detail}


@dataclass
class Migrated:
    """A derivative record, and an honest account of what it lacks."""

    record: dict
    limitations: list = dcfield(default_factory=list)

    @property
    def codes(self) -> set:
        return {limitation.code for limitation in self.limitations}

    def to_json(self) -> dict:
        return dict(self.record)


def source_digest(record: dict) -> str:
    """A digest over a legacy record, on its own terms.

    Schema 2 and 3 records carry fractional JSON numbers, which the schema 4
    canonical encoding refuses precisely because two parsers can disagree
    about them. So the source is hashed the way it was written, with sorted
    keys, and the result is labelled as a legacy digest rather than being
    passed off as a canonical one.
    """
    import json

    blob = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256-legacy:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def source_observation_id(payload: dict, selector: str = "") -> str:
    """A stable identity derived from the source, not a fresh UUID.

    Importing the same file twice must not look like two executions. This
    identifies the observation; it establishes nothing about whether the
    original executions were independent.
    """
    material = canonical_bytes({"payload": source_digest(payload), "selector": selector})
    return "obs-" + hashlib.sha256(material).hexdigest()[:32]


def migrate(record: dict, *, producer_hint: "dict | None" = None) -> Migrated:
    """Normalise a legacy record into the schema 4 shape.

    Every gap in the source becomes a named limitation rather than a
    plausible default.
    """
    version = record.get("meta", {}).get("schema_version", 1)
    if version not in SUPPORTED_SOURCE_SCHEMAS:
        raise ValueError(
            f"schema {version} is not a legacy schema this build migrates "
            f"({', '.join(str(v) for v in SUPPORTED_SOURCE_SCHEMAS)})")

    meta = record.get("meta") or {}
    fields = record.get("fields") or {}
    run = record.get("run") or {}
    metrics = record.get("metrics") or {}

    limitations: list = [
        Limitation("no_execution_identity",
                   "the source has no run ID; an import identity derived from its "
                   "payload stands in, and independence remains unestablished"),
        Limitation("no_prospective_plan",
                   "no plan was frozen before these runs, so any analysis over them "
                   "is retrospective"),
        Limitation("no_capability_manifest",
                   "only the observations actually present are represented; expected "
                   "coverage cannot be inferred from them"),
    ]

    scopes: dict = {"subject": {}}
    ambiguous_absence = 0
    for path, entry in fields.items():
        state = entry.get("s")
        converted: dict = {"state": state}
        if state == "value":
            converted["v"] = entry.get("v")
        if entry.get("d"):
            converted["reason"] = entry["d"]
        if entry.get("p"):
            converted["provenance"] = {"collector_id": "legacy",
                                       "collector_version": str(version),
                                       "source_kind": "derived",
                                       "source_ref": entry["p"]}
        if state == "not_applicable":
            ambiguous_absence += 1
        scopes["subject"][path] = converted
    if ambiguous_absence:
        limitations.append(Limitation(
            "ambiguous_not_applicable",
            f"{ambiguous_absence} field(s) are not_applicable in a schema where that "
            f"could mean structurally absent or simply not captured; the distinction "
            f"cannot be recovered"))

    if not record.get("correctness"):
        limitations.append(Limitation(
            "no_correctness_evidence",
            "the source carries no validator claim, so correctness is unverified"))

    limitations.append(Limitation(
        "no_pre_execution_identity",
        "the source records identity after the run only, so pre-execution subject "
        "identity is unavailable"))

    # Only an explicit claim counts. An empty drift list in a schema that
    # had no way to say "I did not look" is not evidence that nothing moved.
    if not run.get("drift_observed", False):
        limitations.append(Limitation(
            "no_drift_observation",
            "the source does not say whether it watched for drift, so an empty list "
            "cannot be read as none"))

    converted_metrics = []
    for name, entry in sorted(metrics.items()):
        observation = {
            "case_id": "legacy",
            "metric_id": name,
            "unit": "ceteris.legacy:unspecified",
            "direction": "none",
            "domain": "real",
            "state": entry.get("s", "unknown"),
            "aggregation": None,
            "sampling_unit": "aggregate_report",
            "raw_samples": [],
            "inner_sample_count": None,
            "source": {"adapter": meta.get("adapter"), "selector": name},
        }
        if entry.get("s") == "value":
            observation["estimate"] = str(entry.get("v"))
        else:
            observation["reason"] = entry.get("d") or "not recorded"
        converted_metrics.append(observation)
    if converted_metrics:
        limitations.append(Limitation(
            "no_raw_samples",
            "the source reports aggregates only; inner samples are not invented"))

    exit_code = run.get("exit_code")
    outcome = "completed" if isinstance(exit_code, int) else "abandoned"

    migrated = {
        "kind": "ceteris.run",
        "schema_version": 4,
        "producer": {
            "name": (producer_hint or {}).get("name", meta.get("tool", "unknown")),
            "version": (producer_hint or {}).get("version", meta.get("tool_version", "unknown")),
            # Not a claim of fresh capture. This record was converted.
            "record_semantics": f"ceteris.run@4 via {MIGRATION_ID}",
        },
        "run_id": None,
        "source_observation_id": source_observation_id(record),
        "campaign_id": None,
        "experiment_id": "legacy-import",
        "variant_id": None,
        "plan_digest": None,
        "assignment": None,
        "timestamps": {"start": meta.get("captured_at"), "end": None,
                       "duration_s": (str(run["duration_s"]) if "duration_s" in run else None)},
        "execution": {
            "requested_argv": (fields.get("execution.command", {}).get("v", "") or "").split(),
            "effective_argv": (fields.get("execution.command", {}).get("v", "") or "").split(),
            "outcome": outcome,
            "exit_code": exit_code if isinstance(exit_code, int) else None,
            "signal": run.get("signal"),
        },
        "observations": {
            "before": {"status": "unavailable",
                       "reason": "the source captured identity after the run only"},
            "after": {"status": "observed", "scopes": scopes},
        },
        "capabilities": [],
        "metrics": converted_metrics,
        "correctness": [],
        "drift": ({"status": "observed", "changes": run.get("drift") or [], "issues": []}
                  if run.get("drift_observed") else
                  {"status": "unavailable", "changes": [], "issues": []}),
        "issues": [],
        "requires": [],
        "migration": {
            "migration_id": MIGRATION_ID,
            "source_schema_version": version,
            "source_digest": source_digest(record),
            "analysis_origin": "retrospective",
            "limitations": [limitation.to_json() for limitation in limitations],
        },
    }
    return Migrated(migrated, limitations)


def qualifies_for(migrated: Migrated, required_capabilities) -> dict:
    """Whether a migrated record can satisfy a policy, and why not.

    A source omission is not repairable by conversion. The only way to get a
    missing observation is to capture it.
    """
    missing = sorted(set(required_capabilities))
    return {
        "qualifies": not missing,
        "missing_capabilities": missing,
        "reason": (
            "" if not missing else
            "a legacy record cannot acquire an observation it never made; recapture "
            "is the only way to satisfy these"),
        "limitations": [limitation.to_json() for limitation in migrated.limitations],
    }


__all__ = [
    "LIMITATION_CODES",
    "MIGRATION_ID",
    "Limitation",
    "Migrated",
    "SUPPORTED_SOURCE_SCHEMAS",
    "migrate",
    "qualifies_for",
    "source_digest",
    "source_observation_id",
]

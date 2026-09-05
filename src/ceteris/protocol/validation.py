"""Structural validation of schema 4 objects, and the limits that bound them.

Design section 5.7. Two rules shape this module:

Validate before comparing. A comparator handed a malformed record produces
a comparison of nonsense, and a traceback is not a verdict. Every problem
here is a structured issue with a stable code, so a report can name it and a
caller can branch on it.

Limits are refused, never trimmed. A record over a limit is rejected with
the limit named; silently truncating it would make the evidence disagree
with what the producer wrote.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from .encoding import CanonicalError, canonical_bytes, is_digest, loads
from .models import (
    CAPABILITY_STAGES,
    CAPABILITY_STATUSES,
    FIELD_STATES,
    valid_scope,
)

SCHEMA_VERSION = 4
RUN_KIND = "ceteris.run"

# Design section 5.7. Component maxima are checked as well as the file size,
# because each can be individually valid while the whole is not.
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_FIELD_ENTRIES = 100_000
MAX_METRIC_ENTRIES = 10_000
MAX_RAW_SAMPLES = 1_000_000
MAX_STRING_CHARS = 1_000_000

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$"
)

LIFECYCLE_OUTCOMES = ("completed", "failed", "timed_out", "cancelled", "abandoned")
DRIFT_STATUSES = ("observed", "unavailable")


@dataclass(frozen=True)
class Issue:
    """A structured validation failure. `code` is a stable API value."""

    code: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message} [{self.code}]"


class Validator:
    def __init__(self) -> None:
        self.issues: list = []

    def fail(self, code: str, path: str, message: str) -> None:
        self.issues.append(Issue(code, path, message))

    # -- primitives ------------------------------------------------------------

    def identifier(self, value, path: str, *, allow_none: bool = False) -> None:
        if value is None and allow_none:
            return
        if not isinstance(value, str) or not _IDENTIFIER.match(value):
            self.fail("invalid_identifier", path,
                      "must be 1 to 128 characters of [A-Za-z0-9._/-] starting "
                      "alphanumerically")
            return
        if ".." in value:
            # Path-like IDs are names, not filesystem paths.
            self.fail("invalid_identifier", path,
                      "must not contain '..'; an identifier is a name, not a path")

    def uuid4(self, value, path: str, *, allow_none: bool = False) -> None:
        if value is None and allow_none:
            return
        if not isinstance(value, str):
            self.fail("invalid_uuid", path, "must be a UUID string")
            return
        try:
            parsed = uuid.UUID(value)
        except ValueError:
            self.fail("invalid_uuid", path, f"{value!r} is not a UUID")
            return
        if str(parsed) != value:
            self.fail("invalid_uuid", path, "must be the lowercase canonical form")

    def digest_ref(self, value, path: str, *, allow_none: bool = False) -> None:
        if value is None and allow_none:
            return
        if not is_digest(value):
            self.fail("invalid_digest", path,
                      "must be 'sha256:' followed by 64 lowercase hex characters")

    def timestamp(self, value, path: str, *, allow_none: bool = False) -> None:
        if value is None and allow_none:
            return
        if not isinstance(value, str) or not _RFC3339.match(value):
            self.fail("invalid_timestamp", path, "must be an RFC 3339 UTC timestamp")

    def enum(self, value, allowed, path: str) -> None:
        if value not in allowed:
            self.fail("unknown_enum_value", path,
                      f"{value!r} is not one of {', '.join(allowed)}")

    # -- envelope --------------------------------------------------------------

    def run(self, obj) -> list:
        """Validate a schema 4 run envelope. Returns the issues found."""
        if not isinstance(obj, dict):
            self.fail("invalid_structure", "$", "a run record must be an object")
            return self.issues

        if obj.get("kind") != RUN_KIND:
            self.fail("invalid_structure", "$.kind", f"must be {RUN_KIND!r}")
        version = obj.get("schema_version")
        if version != SCHEMA_VERSION:
            self.fail("unsupported_version", "$.schema_version",
                      f"this validator implements schema {SCHEMA_VERSION}, the record "
                      f"declares {version!r}")
            # Nothing below is meaningful under another schema.
            return self.issues

        self._producer(obj.get("producer"), "$.producer")
        self.uuid4(obj.get("run_id"), "$.run_id")
        self.uuid4(obj.get("campaign_id"), "$.campaign_id", allow_none=True)
        self.identifier(obj.get("experiment_id"), "$.experiment_id")
        self.identifier(obj.get("variant_id"), "$.variant_id", allow_none=True)
        self.digest_ref(obj.get("plan_digest"), "$.plan_digest", allow_none=True)
        self._assignment(obj.get("assignment"), "$.assignment")
        self._timestamps(obj.get("timestamps"), "$.timestamps")
        outcome = self._execution(obj.get("execution"), "$.execution")
        self._observations(obj.get("observations"), "$.observations")
        self._capabilities(obj.get("capabilities"), "$.capabilities")
        self._metrics(obj.get("metrics"), "$.metrics")
        self._drift(obj.get("drift"), "$.drift")
        self._requires(obj.get("requires"), "$.requires")
        self._completeness(obj, outcome)
        return self.issues

    def _producer(self, producer, path: str) -> None:
        if not isinstance(producer, dict):
            self.fail("invalid_structure", path, "must be an object")
            return
        for key in ("name", "version", "record_semantics"):
            if not isinstance(producer.get(key), str) or not producer.get(key):
                self.fail("invalid_structure", f"{path}.{key}", "must be a non-empty string")

    def _assignment(self, assignment, path: str) -> None:
        if assignment is None:
            return                                    # an unpaired diagnostic
        if not isinstance(assignment, dict):
            self.fail("invalid_structure", path, "must be an object or null")
            return
        self.identifier(assignment.get("comparison_id"), f"{path}.comparison_id")
        self.identifier(assignment.get("pair_id"), f"{path}.pair_id")
        attempt = assignment.get("attempt")
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            self.fail("invalid_structure", f"{path}.attempt", "must be a positive integer")

    def _timestamps(self, timestamps, path: str) -> None:
        if not isinstance(timestamps, dict):
            self.fail("invalid_structure", path, "must be an object")
            return
        self.timestamp(timestamps.get("start"), f"{path}.start", allow_none=True)
        self.timestamp(timestamps.get("end"), f"{path}.end", allow_none=True)
        duration = timestamps.get("duration_s")
        if duration is not None:
            try:
                from decimal import Decimal

                from .encoding import canonical_decimal

                if Decimal(canonical_decimal(duration)) < 0:
                    self.fail("invalid_structure", f"{path}.duration_s",
                              "a duration cannot be negative")
            except CanonicalError as exc:
                self.fail("invalid_structure", f"{path}.duration_s", str(exc))

    def _execution(self, execution, path: str):
        if not isinstance(execution, dict):
            self.fail("invalid_structure", path, "must be an object")
            return None
        outcome = execution.get("outcome")
        self.enum(outcome, LIFECYCLE_OUTCOMES, f"{path}.outcome")
        for key in ("requested_argv", "effective_argv"):
            argv = execution.get(key)
            if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
                self.fail("invalid_structure", f"{path}.{key}", "must be an array of strings")
        code, signal = execution.get("exit_code"), execution.get("signal")
        if code is not None and (not isinstance(code, int) or isinstance(code, bool)):
            self.fail("malformed_exit_code", f"{path}.exit_code",
                      "must be an integer or null")
        if signal is not None and (not isinstance(signal, int) or isinstance(signal, bool)
                                   or signal < 1):
            self.fail("malformed_exit_code", f"{path}.signal",
                      "must be a positive integer or null")
        if outcome == "completed" and code is None:
            self.fail("missing_value", f"{path}.exit_code",
                      "a completed execution has an exit status")
        return outcome

    def _observations(self, observations, path: str) -> None:
        if not isinstance(observations, dict):
            self.fail("invalid_structure", path, "must be an object")
            return
        total = 0
        for stage in ("before", "after"):
            snapshot = observations.get(stage)
            if snapshot is None:
                self.fail("missing_value", f"{path}.{stage}",
                          "a snapshot may be unavailable, but it must say so explicitly "
                          "rather than be absent")
                continue
            if not isinstance(snapshot, dict):
                self.fail("invalid_structure", f"{path}.{stage}", "must be an object")
                continue
            if snapshot.get("status") == "unavailable":
                if not snapshot.get("reason"):
                    self.fail("missing_reason", f"{path}.{stage}.reason",
                              "an unavailable snapshot must say why")
                continue
            for scope, fields in (snapshot.get("scopes") or {}).items():
                if not valid_scope(scope):
                    self.fail("invalid_scope", f"{path}.{stage}.scopes.{scope}",
                              "not a known observation scope")
                if not isinstance(fields, dict):
                    self.fail("invalid_structure", f"{path}.{stage}.scopes.{scope}",
                              "must be a map of field path to field")
                    continue
                total += len(fields)
                for name, entry in fields.items():
                    self._field(entry, f"{path}.{stage}.scopes.{scope}.{name}")
        if total > MAX_FIELD_ENTRIES:
            self.fail("limit_exceeded", path,
                      f"{total} field entries exceeds the limit of {MAX_FIELD_ENTRIES}")

    def _field(self, entry, path: str) -> None:
        if not isinstance(entry, dict):
            self.fail("invalid_structure", path, "must be an object")
            return
        state = entry.get("state")
        self.enum(state, FIELD_STATES, f"{path}.state")
        has_value = "v" in entry
        if state == "value" and not has_value:
            self.fail("missing_value", path, "a value field must carry v")
        if state in ("not_applicable", "unknown", "error") and has_value:
            self.fail("value_on_non_value_state", path,
                      f"a {state} field must not carry a value")
        if state == "not_applicable" and not entry.get("reason"):
            self.fail("missing_applicability_reason", path,
                      "not_applicable must say why the thing is structurally absent")
        if state in ("unknown", "error") and not entry.get("reason"):
            self.fail("missing_reason", path, f"{state} must say why")
        for ref in entry.get("evidence_refs") or []:
            self.digest_ref(ref, f"{path}.evidence_refs")

    def _capabilities(self, capabilities, path: str) -> None:
        if capabilities is None:
            return
        if not isinstance(capabilities, list):
            self.fail("invalid_structure", path, "must be an array")
            return
        seen = set()
        for i, entry in enumerate(capabilities):
            here = f"{path}[{i}]"
            if not isinstance(entry, dict):
                self.fail("invalid_structure", here, "must be an object")
                continue
            self.identifier(entry.get("capability"), f"{here}.capability")
            self.enum(entry.get("status"), CAPABILITY_STATUSES, f"{here}.status")
            self.enum(entry.get("stage"), CAPABILITY_STAGES, f"{here}.stage")
            scope = entry.get("scope")
            if not isinstance(scope, str) or not valid_scope(scope):
                self.fail("invalid_scope", f"{here}.scope", f"{scope!r} is not a known scope")
            if entry.get("status") != "observed" and not entry.get("reason"):
                self.fail("missing_reason", f"{here}.reason",
                          f"a {entry.get('status')} capability must say why")
            identity = (entry.get("capability"), scope, entry.get("stage"))
            if identity in seen:
                self.fail("duplicate_capability", here,
                          f"{identity} appears more than once; one capability has one "
                          f"status per scope and stage")
            seen.add(identity)

    def _metrics(self, metrics, path: str) -> None:
        if metrics is None:
            return
        if not isinstance(metrics, list):
            self.fail("invalid_structure", path, "must be an array")
            return
        if len(metrics) > MAX_METRIC_ENTRIES:
            self.fail("limit_exceeded", path,
                      f"{len(metrics)} metric entries exceeds the limit of "
                      f"{MAX_METRIC_ENTRIES}")
        raw_total = 0
        seen = set()
        for i, entry in enumerate(metrics):
            here = f"{path}[{i}]"
            if not isinstance(entry, dict):
                self.fail("invalid_structure", here, "must be an object")
                continue
            identity = (entry.get("case_id"), entry.get("metric_id"))
            if identity in seen:
                self.fail("duplicate_metric_identity", here,
                          f"{identity[1]!r} for case {identity[0]!r} appears more than "
                          f"once; distinct measurements need distinct parameterised cases")
            seen.add(identity)
            raw_total += len(entry.get("raw_samples") or [])
        if raw_total > MAX_RAW_SAMPLES:
            self.fail("limit_exceeded", path,
                      f"{raw_total} raw samples exceeds the limit of {MAX_RAW_SAMPLES}; "
                      f"large sample arrays belong in a digest-referenced artifact")

    def _drift(self, drift, path: str) -> None:
        if not isinstance(drift, dict):
            self.fail("invalid_structure", path,
                      "must be an object saying whether drift was observed")
            return
        status = drift.get("status")
        self.enum(status, DRIFT_STATUSES, f"{path}.status")
        if status == "unavailable" and drift.get("changes"):
            self.fail("invalid_structure", f"{path}.changes",
                      "drift that was not observed cannot list changes")

    def _requires(self, requires, path: str) -> None:
        if requires is None:
            return
        if not isinstance(requires, list) or not all(isinstance(r, str) for r in requires):
            self.fail("invalid_structure", path, "must be an array of strings")

    def _completeness(self, obj, outcome) -> None:
        """A record may be missing observations; it may not then claim the
        execution completed."""
        if outcome != "completed":
            return
        observations = obj.get("observations") or {}
        for stage in ("before", "after"):
            snapshot = observations.get(stage) or {}
            if isinstance(snapshot, dict) and snapshot.get("status") == "unavailable":
                # Legal, and it means the record is incomplete, not that it failed.
                self.fail("incomplete_observation", f"$.observations.{stage}",
                          "a completed execution with an unavailable snapshot is "
                          "incomplete evidence; the outcome stands but coverage does not")


def validate_run(obj) -> list:
    """Structural issues in a schema 4 run record. Empty means valid."""
    return Validator().run(obj)


def load_run(data) -> tuple:
    """Read and validate a run record. Returns (object, issues).

    Size is checked before parsing, because a limit enforced after the parse
    has already paid the cost it exists to bound.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    if isinstance(data, (bytes, bytearray)) and len(data) > MAX_FILE_BYTES:
        return None, [Issue("limit_exceeded", "$",
                            f"{len(data)} bytes exceeds the {MAX_FILE_BYTES} byte limit")]
    try:
        obj = loads(data)
    except CanonicalError as exc:
        return None, [Issue(getattr(exc, "code", "canonical_encoding_error"), "$", str(exc))]
    return obj, validate_run(obj)


def check_limits(obj) -> list:
    """Limits that apply to any protocol object, whatever its kind."""
    issues: list = []
    try:
        size = len(canonical_bytes(obj))
    except CanonicalError as exc:
        return [Issue(getattr(exc, "code", "canonical_encoding_error"), "$", str(exc))]
    if size > MAX_FILE_BYTES:
        issues.append(Issue("limit_exceeded", "$",
                            f"{size} canonical bytes exceeds the {MAX_FILE_BYTES} byte limit"))

    def walk(node, path):
        if isinstance(node, str) and len(node) > MAX_STRING_CHARS:
            issues.append(Issue("limit_exceeded", path,
                                f"{len(node)} characters exceeds the {MAX_STRING_CHARS} limit"))
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")
        elif isinstance(node, dict):
            for key, item in node.items():
                walk(item, f"{path}.{key}")

    walk(obj, "$")
    return issues


__all__ = [
    "Issue",
    "MAX_FIELD_ENTRIES",
    "MAX_FILE_BYTES",
    "MAX_METRIC_ENTRIES",
    "MAX_RAW_SAMPLES",
    "MAX_STRING_CHARS",
    "RUN_KIND",
    "SCHEMA_VERSION",
    "Validator",
    "check_limits",
    "load_run",
    "validate_run",
]

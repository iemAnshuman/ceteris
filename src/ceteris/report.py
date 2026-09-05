"""Deterministic assembly of a semantic report.

Design section 12. One report object serves text, JSON and HTML, because a
renderer that computed anything would be a second decision procedure nobody
tested. Renderers read; only this module decides.

Every dimension is kept even after one of them has settled the outcome, so
missing evidence is never hidden behind the first violation that happened to
be found.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dcfield
from typing import Any

from . import analysis as analysis_mod
from .policy import Decision, Obligation
from .protocol.encoding import digest

REPORT_KIND = "ceteris.report"
REPORT_SCHEMA = 1

# Stable issue codes. These are API: a caller may branch on them, and they
# outlive any wording change in the message beside them.
ISSUE_CODES = (
    "duplicate_observation", "stale_export", "harness_invalid", "metric_nonfinite",
    "required_capability_missing", "subject_changed_during_run", "ambiguous_policy_rule",
    "unsupported_method", "unstable_artifact", "incomplete_observation",
    "associated_difference", "undeclared_difference", "assertion_unmet",
    "correctness_failed", "execution_failed", "coverage_incomplete",
)

SEVERITIES = ("blocking", "advisory")


@dataclass
class Issue:
    """One structured finding. Remediation is data, never a command to run."""

    code: str
    severity: str
    stage: str
    message: str
    run_id: "str | None" = None
    case_id: "str | None" = None
    field: "str | None" = None
    capability: "str | None" = None
    evidence_refs: tuple = ()
    remediation: "str | None" = None

    def to_json(self) -> dict:
        return {
            "code": self.code, "severity": self.severity, "stage": self.stage,
            "message": self.message, "run_id": self.run_id, "case_id": self.case_id,
            "field": self.field, "capability": self.capability,
            "evidence_refs": list(self.evidence_refs), "remediation": self.remediation,
        }


@dataclass
class Report:
    """The whole semantic result of one evaluation."""

    plan_digest: str
    comparison_id: str
    decision: Decision
    coverage: dict = dcfield(default_factory=dict)
    field_results: list = dcfield(default_factory=list)
    metric_results: list = dcfield(default_factory=list)
    selected_records: list = dcfield(default_factory=list)
    issues: list = dcfield(default_factory=list)
    waivers_applied: list = dcfield(default_factory=list)
    associated_differences: list = dcfield(default_factory=list)
    analysis_origin: str = "prospective"
    policy_identity: str = ""
    producer: dict = dcfield(default_factory=dict)

    def to_json(self) -> dict:
        """Canonical, ordered, and free of anything locale-specific."""
        return {
            "kind": REPORT_KIND,
            "schema_version": REPORT_SCHEMA,
            "plan_digest": self.plan_digest,
            "comparison_id": self.comparison_id,
            "analysis_origin": self.analysis_origin,
            "policy_identity": self.policy_identity,
            "producer": dict(self.producer),
            "dimensions": self.decision.to_json(),
            "coverage": self.coverage,
            # Sorted by assignment identity, so the same evaluation always
            # produces the same bytes.
            "selected_records": sorted(self.selected_records,
                                       key=lambda r: (r.get("pair_id", ""),
                                                      r.get("slot", ""),
                                                      r.get("run_id", ""))),
            "field_results": sorted(self.field_results, key=lambda f: f.get("path", "")),
            "metric_results": sorted(self.metric_results,
                                     key=lambda m: (m.get("case_id", ""),
                                                    m.get("metric_id", ""))),
            "associated_differences": sorted(
                self.associated_differences,
                key=lambda d: (d.get("declared", ""), d.get("undeclared", ""))),
            "waivers_applied": sorted(self.waivers_applied, key=lambda w: w.get("id", "")),
            "issues": sorted((i.to_json() for i in self.issues),
                             key=lambda i: (i["code"], i["message"])),
        }

    @property
    def digest(self) -> str:
        """Over the semantic content, never over rendered text."""
        return digest(self.to_json())

    @property
    def acceptance(self) -> str:
        return self.decision.acceptance()

    @property
    def blocking(self) -> list:
        return [i for i in self.issues if i.severity == "blocking"]

    def exit_code(self) -> int:
        """Design section 12.4, in its documented precedence."""
        if any(i.code in ("ambiguous_policy_rule", "duplicate_observation") for i in self.issues):
            return 3
        state = self.acceptance
        if state == "failed":
            return 1
        if state == "inconclusive":
            if self.decision.measurement == "inconclusive" and self.decision.coverage == "sufficient":
                return 4
            return 2
        return 0


def build(*, plan_digest: str, comparison_id: str, coverage: dict, field_results,
          metric_results, selected_records, issues=(), waivers_applied=(),
          associated_differences=(), execution: str = "passed",
          correctness: str = "unverified", diagnostic: bool = False,
          analysis_origin: str = "prospective", policy_identity: str = "",
          producer: "dict | None" = None) -> Report:
    """Assemble the report, deriving every dimension from the evidence.

    This is the only place a dimension is decided. A renderer that wanted to
    show something different would have to change the report, which is the
    point.
    """
    obligations: list = []

    coverage_state = coverage.get("state", "sufficient")
    for entry in coverage.get("incomplete", []):
        obligations.append(Obligation(
            entry["requirement_id"], "coverage", "violated"
            if entry.get("blocking") else "unresolved",
            entry.get("reason", "")))
    for entry in coverage.get("unresolved", []):
        obligations.append(Obligation(entry["requirement_id"], "coverage", "unresolved",
                                      entry.get("reason", "")))

    comparability = "compatible"
    for result in field_results:
        state = result.get("classification")
        if state == "undeclared_difference":
            comparability = "incompatible"
            obligations.append(Obligation(
                result["path"], "comparability", "violated",
                "differs and was not declared"))
        elif state == "indeterminate":
            if comparability == "compatible":
                comparability = "indeterminate"
            obligations.append(Obligation(
                result["path"], "comparability", "unresolved",
                result.get("reason", "could not be read")))
        elif state == "waived":
            obligations.append(Obligation(
                result["path"], "comparability", "waived",
                result.get("reason", ""), result.get("waiver_id")))

    for waiver in waivers_applied:
        if not any(o.waiver_id == waiver.get("id") for o in obligations):
            obligations.append(Obligation(waiver.get("id", "waiver"), "coverage", "waived",
                                          waiver.get("reason", ""), waiver.get("id")))

    measurement = "assessed"
    eligible = [m for m in metric_results if m.get("primary")]
    if not eligible:
        measurement = "unavailable"
    else:
        outcome = analysis_mod.combine_primary(eligible)
        if any(m.get("status") in ("unavailable", None) for m in eligible):
            measurement = "unavailable"
        elif outcome == analysis_mod.INCONCLUSIVE:
            measurement = "inconclusive"
        if outcome == analysis_mod.FAIL:
            measurement = "assessed"
            for metric in eligible:
                if metric.get("predicate", {}).get("result") == analysis_mod.FAIL:
                    obligations.append(Obligation(
                        f"{metric.get('case_id')}/{metric.get('metric_id')}",
                        "measurement", "violated",
                        "the measured effect is beyond the declared budget"))

    return Report(
        plan_digest=plan_digest,
        comparison_id=comparison_id,
        decision=Decision(
            execution=execution,
            correctness=correctness,
            coverage=coverage_state,
            comparability=comparability,
            measurement=measurement,
            obligations=obligations,
            diagnostic=diagnostic,
        ),
        coverage=coverage,
        field_results=list(field_results),
        metric_results=list(metric_results),
        selected_records=list(selected_records),
        issues=list(issues),
        waivers_applied=list(waivers_applied),
        associated_differences=list(associated_differences),
        analysis_origin=analysis_origin,
        policy_identity=policy_identity,
        producer=dict(producer or {}),
    )


def headline(report: Report) -> str:
    """The first line: what was asked, and the answer, in that order."""
    state = report.acceptance.replace("_", " ").upper()
    blocking = report.blocking
    reason = blocking[0].message if blocking else _first_reason(report)
    return f"{report.comparison_id} — {state}" + (f": {reason}" if reason else "")


def _first_reason(report: Report) -> str:
    decision = report.decision
    if decision.correctness == "failed":
        return "a required correctness check failed"
    if decision.execution == "failed":
        return "an execution failed"
    if decision.comparability == "incompatible":
        violated = [o for o in decision.obligations
                    if o.kind == "comparability" and o.state == "violated"]
        if violated:
            return f"{violated[0].id} differs and was not declared"
    if decision.coverage == "incomplete":
        missing = report.coverage.get("incomplete") or []
        if missing:
            return (f"required evidence was not observed: "
                    f"{missing[0].get('capability', missing[0].get('requirement_id'))}")
        return "required evidence was not observed"
    if decision.measurement == "inconclusive":
        return "the measured interval does not resolve against the declared threshold"
    if decision.measurement == "unavailable":
        return "no eligible primary measurement"
    return ""


__all__ = ["ISSUE_CODES", "Issue", "REPORT_KIND", "REPORT_SCHEMA", "Report", "build", "headline"]

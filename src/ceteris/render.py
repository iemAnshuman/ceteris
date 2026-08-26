"""Human-readable report rendering.

Short and scannable. The sections are ordered by what the reader has to act on:
things that invalidate the comparison first, things that merely need noting
last.
"""

from __future__ import annotations

from typing import Any, Sequence

from .compare import Classification, FieldResult, Report
from .model import Fingerprint, State

MAX_VALUE = 46


def _clip(text: str, width: int = MAX_VALUE) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _groups_line(result: FieldResult) -> str:
    parts = []
    for group in result.groups:
        who = ", ".join(group.labels)
        parts.append(f"{_clip(group.display)} ({who})")
    return "  vs  ".join(parts)


def _field_lines(results: list[FieldResult], width: int) -> list[str]:
    lines = []
    for result in results:
        lines.append(f"  {result.path.ljust(width)}  {_groups_line(result)}")
        if result.reason:
            lines.append(f"  {' ' * width}  reason: {result.reason}")
        if result.note:
            lines.append(f"  {' ' * width}  note: {result.note}")
    return lines


def _metric_cell(field) -> str:
    if field is None:
        return "-"
    if field.state is not State.VALUE:
        return f"<{field.state.value}>"
    val = field.value
    if isinstance(val, list):
        return f"[{len(val)} values]"
    return str(val)


def _results_table(sources: Sequence[Fingerprint]) -> list[str]:
    """Measurements next to the verdict. Metrics are never gated -- they are
    the dependent variable and are supposed to differ."""
    runs = [f for f in sources if f.run or f.metrics]
    if not runs:
        return []
    names: list[str] = []
    for fingerprint in runs:
        for name in sorted(fingerprint.metrics):
            if name not in names:
                names.append(name)
    label_w = max(len(f.label) for f in runs)
    header = "  " + "run".ljust(label_w)
    widths = [max(len(n), 9) for n in names]
    for name, w in zip(names, widths):
        header += "  " + name.rjust(w)
    header += "  " + "exit".rjust(4) + "  " + "wall".rjust(8)
    lines = ["MEASUREMENTS:", header]
    for fingerprint in runs:
        row = "  " + fingerprint.label.ljust(label_w)
        for name, w in zip(names, widths):
            row += "  " + _metric_cell(fingerprint.metrics.get(name)).rjust(w)
        code = fingerprint.run.get("exit_code")
        secs = fingerprint.run.get("duration_s")
        row += "  " + ("-" if code is None else str(code)).rjust(4)
        row += "  " + ("-" if secs is None else f"{secs:.2f}s").rjust(8)
        lines.append(row)
    lines.append("")
    return lines


def render_listing(runs: Sequence[Fingerprint], store) -> str:
    names: list[str] = []
    for fingerprint in runs:
        for name in sorted(fingerprint.metrics):
            if name not in names:
                names.append(name)
    label_w = max([len(f.label) for f in runs] + [3])
    lines = [f"{len(runs)} runs in {store}", ""]
    header = "  " + "run".ljust(label_w) + "  " + "when".ljust(20)
    for name in names:
        header += "  " + name.rjust(max(len(name), 9))
    header += "  " + "exit".rjust(4)
    lines.append(header)
    for fingerprint in runs:
        when = str(fingerprint.meta.get("captured_at", ""))[:19]
        row = "  " + fingerprint.label.ljust(label_w) + "  " + when.ljust(20)
        for name in names:
            row += "  " + _metric_cell(fingerprint.metrics.get(name)).rjust(
                max(len(name), 9)
            )
        code = fingerprint.run.get("exit_code")
        row += "  " + ("-" if code is None else str(code)).rjust(4)
        if fingerprint.drift:
            row += "   DRIFT"
        lines.append(row)
    return "\n".join(lines) + "\n"


def render(report: Report) -> str:
    out: list[str] = []
    n = len(report.labels)
    declared = ", ".join(report.declared) if report.declared else "nothing"
    out.append(f"{n} runs compared. Declared varying: {declared}")
    out.append("")

    violations = report.violations
    indeterminates = report.indeterminates
    waived = report.by_class(Classification.WAIVED)
    declared_ok = report.by_class(Classification.DECLARED)
    informational = report.by_class(Classification.INFORMATIONAL)

    interesting = violations + indeterminates + waived + declared_ok + informational
    width = max((len(r.path) for r in interesting), default=20)
    width = min(width, 34)

    out.extend(_results_table(report.sources))

    if report.drifted:
        out.append("ENVIRONMENT CHANGED DURING THE RUN (not certifiable):")
        for fingerprint in report.drifted:
            out.append(f"  {fingerprint.label}")
            for change in fingerprint.drift[:6]:
                out.append(
                    f"      {change['path']}: "
                    f"{_clip(change['before'], 22)} -> {_clip(change['after'], 22)}"
                )
            if len(fingerprint.drift) > 6:
                out.append(f"      ... and {len(fingerprint.drift) - 6} more")
        out.append("")

    if violations:
        out.append("UNDECLARED DIFFERENCES (comparison is not valid):")
        out.extend(_field_lines(violations, width))
        out.append("")

    if indeterminates:
        out.append("UNKNOWN (could not be captured -- comparison is not certified):")
        for result in indeterminates:
            out.append(f"  {result.path}")
            for label, why in result.indeterminate:
                out.append(f"      {label}: {why}")
            for group in result.groups:
                who = ", ".join(group.labels)
                out.append(f"      {who}: known, {_clip(group.display)}")
        out.append("")

    if report.unmatched_declarations:
        out.append("DECLARED BUT NO SUCH FIELD (typo?):")
        for pattern in report.unmatched_declarations:
            out.append(f"  --vary {pattern}")
        out.append("")

    if report.constant_declarations:
        out.append("DECLARED BUT DID NOT VARY (did the sweep actually apply?):")
        for pattern in report.constant_declarations:
            out.append(f"  --vary {pattern}")
        out.append("")

    if declared_ok:
        out.append("DECLARED VARYING (expected):")
        out.extend(_field_lines(declared_ok, width))
        out.append("")

    if waived:
        out.append("WAIVED:")
        out.extend(_field_lines(waived, width))
        out.append("")

    if informational:
        out.append("DIFFERS, NOT GATING (informational severity):")
        out.extend(_field_lines(informational, width))
        out.append("")

    out.append(f"Matched on {report.matched_count} other fields.")

    if report.exit_code == 0:
        out.append("")
        out.append("OK: every difference was declared. Comparison is valid.")
    return "\n".join(out) + "\n"


def to_json(report: Report) -> dict[str, Any]:
    return {
        "runs": report.labels,
        "declared": report.declared,
        "waived": report.waived,
        "strict": report.strict,
        "constant_declarations": report.constant_declarations,
        "unmatched_declarations": report.unmatched_declarations,
        "exit_code": report.exit_code,
        "matched": report.matched_count,
        "fields": [
            {
                "path": r.path,
                "verdict": r.verdict.value,
                "classification": r.classification.value,
                "severity": r.severity,
                "reason": r.reason,
                "note": r.note,
                "groups": [
                    {"value": g.display, "runs": g.labels} for g in r.groups
                ],
                "indeterminate": [
                    {"run": label, "why": why} for label, why in r.indeterminate
                ],
            }
            for r in report.results
            if r.classification is not Classification.MATCHED
        ],
    }

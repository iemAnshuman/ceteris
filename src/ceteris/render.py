"""Human-readable report rendering.

Short and scannable. The sections are ordered by what the reader has to act on:
things that invalidate the comparison first, things that merely need noting
last.
"""

from __future__ import annotations

from typing import Any, Sequence

from collections import Counter

from . import stats
from .compare import Classification, FieldResult, Report
from .model import Fingerprint, State

MAX_VALUE = 46


def _clip(text: str, width: int = MAX_VALUE) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _who(labels: list[str]) -> str:
    """Repeats share a label; show 'tuned-O3 x5' rather than five copies."""
    counts = Counter(labels)
    return ", ".join(f"{k} x{n}" if n > 1 else k for k, n in counts.items())


def _groups_line(result: FieldResult) -> str:
    parts = []
    for group in result.groups:
        parts.append(f"{_clip(group.display)} ({_who(group.labels)})")
    return "  vs  ".join(parts)


def _summary_line(result: FieldResult) -> str | None:
    """Many distinct values (load average across 40 runs): summarise."""
    if len(result.groups) <= 3:
        return None
    runs = sum(len(g.labels) for g in result.groups)
    nums = []
    for g in result.groups:
        try:
            nums.append(float(g.display))
        except ValueError:
            return f"{len(result.groups)} distinct values across {runs} runs"
    return f"{len(result.groups)} distinct values across {runs} runs (range {min(nums):g} to {max(nums):g})"


def _field_lines(results: list[FieldResult], width: int) -> list[str]:
    lines = []
    for result in results:
        shown = _summary_line(result) if result.classification is Classification.INFORMATIONAL else None
        lines.append(f"  {result.path.ljust(width)}  {shown or _groups_line(result)}")
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


def _fmt(x: float) -> str:
    return f"{x:.4g}"


def _results_table(report: Report) -> list[str]:
    """Measurements per configuration. Metrics are never gated -- they are
    the dependent variable. Configurations are records with identical
    comparable bodies, so repeats fold together without any bookkeeping."""
    configs = [g for g in report.configs if any(fp.run or fp.metrics for fp in g.members)]
    if not configs:
        return []
    names = stats.metric_names(configs)
    lines = ["MEASUREMENTS (per configuration):"]
    if not names:
        for g in configs:
            codes = {fp.run.get("exit_code") for fp in g.members}
            lines.append(f"  {g.label:<14} n={g.n:<3} exit={','.join(str(c) for c in sorted(codes, key=str))}")
        lines.append("")
        return lines
    w = max(len(g.label) for g in configs)
    lines.append(f"  {'configuration':<{w}}  {'n':>3}  {'metric':<16} {'min':>10} {'median':>10} {'max':>10} {'spread':>7}")
    for g in configs:
        for name in names:
            st = stats.stats_for(g, name)
            if st is None:
                bad = next((fp.metrics.get(name) for fp in g.members if fp.metrics.get(name)), None)
                why = f"<{bad.state.value}>" if bad else "-"
                lines.append(f"  {g.label:<{w}}  {g.n:>3}  {name:<16} {why:>10}")
                continue
            lines.append(
                f"  {g.label:<{w}}  {st.n:>3}  {name:<16} {_fmt(st.lo):>10} {_fmt(st.med):>10} {_fmt(st.hi):>10} {st.spread:>6.0%}"
            )
    lines.append("")
    return lines


def _noise_section(report: Report) -> list[str]:
    if not report.noise:
        return []
    lines = ["NOISE FLOOR:"]
    for v in report.noise:
        tag = "unassessed" if not v.assessed else ("WITHIN NOISE" if v.within_noise else "signal")
        lines.append(f"  {v.metric:<16} {tag:<13} {v.reason}")
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

    for w in report.warnings:
        out.append(f"WARNING: {w}")
    if report.warnings:
        out.append("")
    out.extend(_results_table(report))
    out.extend(_noise_section(report))

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

    if report.confounds:
        out.append("CONFOUNDED WITH A DECLARED VARIABLE (re-run; do not waive):")
        for c in report.confounds:
            out.append(f"  {c.undeclared} moves in lockstep with {c.declared}:")
            for d_val, u_val, n in c.table:
                out.append(f"      {c.declared} = {_clip(d_val, 24)}  ->  {c.undeclared} = {_clip(u_val, 24)}  ({n} run{'s' if n != 1 else ''})")
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
                out.append(f"      {_who(group.labels)}: known, {_clip(group.display)}")
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

    code = report.exit_code
    if code == 0:
        out.append("")
        if any(v.assessed and v.within_noise for v in report.noise):
            out.append("OK: every difference was declared -- but see NOISE FLOOR: the measured gap is not a result.")
        else:
            out.append("OK: every difference was declared. Comparison is valid.")
    elif code == 4:
        out.append("")
        out.append("NOT A RESULT: the comparison is valid but no metric shows a gap above the noise floor.")
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
        "warnings": report.warnings,
        "confounds": [
            {"undeclared": c.undeclared, "declared": c.declared,
             "table": [{"declared_value": a, "undeclared_value": b, "runs": n} for a, b, n in c.table]}
            for c in report.confounds
        ],
        "configurations": [
            {"label": g.label, "content_hash": g.content_hash, "n": g.n,
             "runs": [fp.label for fp in g.members],
             "metrics": {m: (lambda st: st and {"n": st.n, "min": st.lo, "median": st.med, "max": st.hi, "spread": st.spread})(stats.stats_for(g, m))
                         for m in stats.metric_names(report.configs)}}
            for g in report.configs
        ],
        "noise": [
            {"metric": v.metric, "assessed": v.assessed, "within_noise": v.within_noise,
             "gap": v.gap, "noise": v.noise, "reason": v.reason}
            for v in report.noise
        ],
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

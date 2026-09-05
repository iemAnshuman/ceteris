"""A static HTML report that opens offline and decides nothing.

Design section 14.5. Local assets only, no network, no script that computes
a verdict. Everything shown comes from the semantic report handed to it, and
every string that came from a user or a harness is escaped.

Colour is never the only signal: each state carries a word. The
execution-order plot is inline SVG with a table of the same numbers beside
it, because a picture nobody can read with a screen reader is not a report.
"""

from __future__ import annotations

import html as html_escape
from typing import Any

STATE_WORDS = {
    "passed": ("PASSED", "#1a7f37"),
    "passed_with_waivers": ("PASSED WITH WAIVERS", "#9a6700"),
    "failed": ("FAILED", "#cf222e"),
    "inconclusive": ("INCONCLUSIVE", "#9a6700"),
    "not_evaluated": ("NOT EVALUATED", "#57606a"),
}

_CSS = """
:root { color-scheme: light dark; --fg:#1f2328; --bg:#ffffff; --muted:#57606a;
        --line:#d0d7de; --panel:#f6f8fa; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e6edf3; --bg:#0d1117; --muted:#9198a1; --line:#30363d; --panel:#161b22; }
}
body { margin:0; padding:2rem 1.25rem; background:var(--bg); color:var(--fg);
       font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }
main { max-width: 60rem; margin: 0 auto; }
h1 { font-size:1.35rem; margin:0 0 .25rem; }
h2 { font-size:1rem; margin:2rem 0 .5rem; padding-bottom:.25rem;
     border-bottom:1px solid var(--line); }
.state { font-weight:700; letter-spacing:.02em; }
.reason { color:var(--muted); margin:.25rem 0 1.25rem; }
table { border-collapse:collapse; width:100%; margin:.5rem 0 1rem; font-variant-numeric:tabular-nums; }
caption { text-align:left; color:var(--muted); padding-bottom:.35rem; }
th,td { text-align:left; padding:.35rem .6rem; border-bottom:1px solid var(--line); }
th { font-weight:600; }
.dims { display:flex; flex-wrap:wrap; gap:.5rem 1.5rem; padding:.75rem 1rem;
        background:var(--panel); border:1px solid var(--line); border-radius:6px; }
.dims div { min-width:11rem; }
.dims span { display:block; color:var(--muted); font-size:.8rem; }
.limit { background:var(--panel); border-left:3px solid var(--line); padding:.6rem .9rem;
         margin:.5rem 0; }
figure { margin:.5rem 0; }
svg { max-width:100%; height:auto; border:1px solid var(--line); border-radius:6px; }
footer { color:var(--muted); margin-top:2.5rem; font-size:.85rem; }
code { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.9em; }
"""


def esc(value: Any) -> str:
    """Every user- and harness-supplied string goes through here."""
    return html_escape.escape("" if value is None else str(value), quote=True)


def _row(cells, header=False) -> str:
    tag = "th" if header else "td"
    return "<tr>" + "".join(f"<{tag}>{cell}</{tag}>" for cell in cells) + "</tr>"


def _dimensions(dimensions: dict) -> str:
    order = ("execution", "correctness", "coverage", "comparability", "measurement")
    cells = "".join(
        f"<div><span>{esc(name.capitalize())}</span>{esc(dimensions.get(name, 'unknown'))}</div>"
        for name in order)
    return f'<div class="dims">{cells}</div>'


def _order_plot(pairs) -> str:
    """Baseline and candidate values against execution order.

    Inline SVG with no script. The same numbers follow in a table, so the
    figure is an aid rather than the only way to read the data.
    """
    if not pairs:
        return ""
    values = [v for pair in pairs for v in (pair.get("baseline"), pair.get("candidate"))
              if isinstance(v, (int, float))]
    if len(values) < 2:
        return ""
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    width, height, pad = 640, 200, 28

    def point(index, value, total):
        x = pad + (width - 2 * pad) * (index / max(total - 1, 1))
        y = height - pad - (height - 2 * pad) * ((value - low) / span)
        return f"{x:.1f},{y:.1f}"

    marks = []
    for role, colour in (("baseline", "#57606a"), ("candidate", "#0969da")):
        series = [pair.get(role) for pair in pairs]
        usable = [(i, v) for i, v in enumerate(series) if isinstance(v, (int, float))]
        if len(usable) < 2:
            continue
        path = " ".join(point(i, v, len(series)) for i, v in usable)
        marks.append(f'<polyline fill="none" stroke="{colour}" stroke-width="2" points="{path}"/>')
        for i, v in usable:
            cx, cy = point(i, v, len(series)).split(",")
            marks.append(f'<circle cx="{cx}" cy="{cy}" r="2.5" fill="{colour}"/>')
    legend = ('<text x="28" y="16" font-size="11" fill="#57606a">baseline</text>'
              '<text x="92" y="16" font-size="11" fill="#0969da">candidate</text>')
    return (
        f'<figure><svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Baseline and candidate values in execution order. '
        f'The same values are listed in the table below.">'
        f'{legend}{"".join(marks)}</svg>'
        f'<figcaption class="reason">Values in execution order. '
        f'The table below carries the same numbers.</figcaption></figure>')


def render(report: dict, *, receipt: "str | None" = None, pairs=()) -> str:
    """One self-contained page. No network, no verdict computed here."""
    dimensions = report.get("dimensions") or {}
    acceptance = dimensions.get("acceptance", "not_evaluated")
    word, colour = STATE_WORDS.get(acceptance, (esc(acceptance).upper(), "#57606a"))

    parts = [
        "<!-- Generated by ceteris. This page displays a semantic report; it "
        "computes no verdict of its own. -->",
        f"<style>{_CSS}</style>",
        "<main>",
        f"<h1>{esc(report.get('comparison_id', 'comparison'))}</h1>",
        f'<p class="state" style="color:{colour}">{word}</p>',
    ]

    reason = report.get("headline_reason")
    if reason:
        parts.append(f'<p class="reason">{esc(reason)}</p>')

    parts.append(_dimensions(dimensions))

    metrics = report.get("metric_results") or []
    if metrics:
        parts.append("<h2>Primary metrics</h2><table>")
        parts.append("<caption>Each metric's estimate, interval and decision. "
                     "Percentages are display values; the decision used exact "
                     "rationals.</caption>")
        parts.append(_row(["Case", "Metric", "Effect", "Interval", "Predicate", "Decision"],
                          header=True))
        for metric in metrics:
            interval = metric.get("interval_display") or [None, None]
            predicate = metric.get("predicate") or {}
            parts.append(_row([
                esc(metric.get("case_id")), esc(metric.get("metric_id")),
                esc(metric.get("estimate_display")),
                esc(f"{interval[0]} to {interval[1]}" if interval[0] else "not resolved"),
                esc(f"{predicate.get('type')} ≤ {predicate.get('threshold')}"
                    if predicate else "none"),
                esc(predicate.get("result", "none")),
            ]))
        parts.append("</table>")

    if pairs:
        parts.append("<h2>Execution order</h2>")
        parts.append(_order_plot(pairs))
        parts.append("<table><caption>Every pair, in the order it ran.</caption>")
        parts.append(_row(["Pair", "Baseline", "Candidate"], header=True))
        for pair in pairs:
            parts.append(_row([esc(pair.get("pair_id")), esc(pair.get("baseline")),
                               esc(pair.get("candidate"))]))
        parts.append("</table>")

    differing = [f for f in report.get("field_results") or []
                 if f.get("classification") != "matched"]
    if differing:
        parts.append("<h2>Field differences</h2><table>")
        parts.append(_row(["Field", "Classification", "Detail"], header=True))
        for field in differing:
            parts.append(_row([esc(field.get("path")), esc(field.get("classification")),
                               esc(field.get("reason", ""))]))
        parts.append("</table>")

    incomplete = (report.get("coverage") or {}).get("incomplete") or []
    if incomplete:
        parts.append("<h2>Evidence that was not observed</h2><table>")
        parts.append(_row(["Capability", "Scope", "Stage", "Reason"], header=True))
        for entry in incomplete:
            parts.append(_row([esc(entry.get("capability")), esc(entry.get("scope")),
                               esc(entry.get("stage")), esc(entry.get("reason"))]))
        parts.append("</table>")

    waivers = report.get("waivers_applied") or []
    if waivers:
        parts.append("<h2>Waivers</h2><table>")
        parts.append("<caption>Accepted exceptions. The underlying difference or "
                     "gap is unchanged and still listed above.</caption>")
        parts.append(_row(["Waiver", "Target", "Reason", "Reference"], header=True))
        for waiver in waivers:
            parts.append(_row([esc(waiver.get("id")), esc(waiver.get("target")),
                               esc(waiver.get("reason")), esc(waiver.get("reference"))]))
        parts.append("</table>")

    issues = report.get("issues") or []
    if issues:
        parts.append("<h2>Issues</h2><table>")
        parts.append(_row(["Code", "Severity", "Message"], header=True))
        for issue in issues:
            parts.append(_row([f"<code>{esc(issue.get('code'))}</code>",
                               esc(issue.get("severity")), esc(issue.get("message"))]))
        parts.append("</table>")

    assumptions = [a for metric in metrics for a in (metric.get("assumptions") or [])]
    if assumptions:
        parts.append("<h2>What this result assumes</h2>")
        for assumption in dict.fromkeys(assumptions):
            parts.append(f'<p class="limit">{esc(assumption)}</p>')

    parts.append("<footer>")
    parts.append(f"<p>Plan <code>{esc(report.get('plan_digest'))}</code>, "
                 f"analysis origin {esc(report.get('analysis_origin', 'prospective'))}.</p>")
    if receipt:
        parts.append(f"<p>Receipt <code>{esc(receipt)}</code></p>")
    parts.append("<p>This page displays a report; it does not compute one. "
                 "Digests detect changed content against a known receipt. They do "
                 "not prove the recorded experiment was run honestly.</p>")
    parts.append("</footer></main>")
    return "\n".join(parts)


__all__ = ["STATE_WORDS", "esc", "render"]

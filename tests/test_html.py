"""The static HTML report. Design section 14.5."""

from __future__ import annotations

import re

import pytest

from ceteris import html


def a_report(**overrides) -> dict:
    body = {
        "kind": "ceteris.report", "schema_version": 1,
        "plan_digest": "sha256:" + "a" * 64,
        "comparison_id": "candidate-v-base",
        "analysis_origin": "prospective",
        "dimensions": {"acceptance": "passed", "execution": "passed",
                       "correctness": "validated", "coverage": "sufficient",
                       "comparability": "compatible", "measurement": "assessed"},
        "coverage": {"state": "sufficient", "incomplete": []},
        "metric_results": [{
            "case_id": "compress/small", "metric_id": "elapsed",
            "estimate_display": "2.00%", "interval_display": ["1.50%", "2.50%"],
            "predicate": {"type": "non_regression", "threshold": "0.05", "result": "pass"},
            "assumptions": ["pairs are independent and sample a common effect distribution"],
        }],
        "field_results": [], "issues": [], "waivers_applied": [],
    }
    body.update(overrides)
    return body


PAIRS = [{"pair_id": f"c1/p{i:03d}", "baseline": 1.0 + i * 0.01,
          "candidate": 1.02 + i * 0.01} for i in range(10)]


# --- offline and self-contained -----------------------------------------------


def test_the_page_loads_nothing_from_the_network():
    page = html.render(a_report(), pairs=PAIRS)
    for pattern in ("http://", "https://", "<script", "src=", "@import", "cdn"):
        assert pattern not in page.lower(), f"the page references {pattern}"


def test_the_page_computes_no_verdict_of_its_own():
    page = html.render(a_report())
    assert "<script" not in page.lower()
    assert "does not compute one" in page


def test_the_plot_is_inline_svg_with_no_script():
    page = html.render(a_report(), pairs=PAIRS)
    assert "<svg" in page and "polyline" in page
    assert "<script" not in page.lower()


# --- escaping -----------------------------------------------------------------


@pytest.mark.parametrize("hostile", [
    "<script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    "a & b < c > d",
    "'; DROP TABLE runs; --",
])
def test_every_supplied_string_is_escaped(hostile):
    """Command lines and harness output land in this page verbatim."""
    report = a_report(comparison_id=hostile)
    report["issues"] = [{"code": "harness_invalid", "severity": "blocking",
                         "message": hostile}]
    report["field_results"] = [{"path": hostile, "classification": "undeclared_difference",
                                "reason": hostile}]
    page = html.render(report)
    # What matters is that nothing hostile survives as markup. The escaped
    # text may well contain the characters of an attack; inert is the point.
    assert "<img" not in page
    assert "<script>alert" not in page
    assert html.esc(hostile) in page
    # And the only tags on the page are the ones this module emits.
    emitted = set(re.findall(r"<([a-zA-Z][a-zA-Z0-9]*)", page))
    assert emitted <= {"style", "main", "h1", "h2", "p", "div", "span", "table",
                       "caption", "tr", "th", "td", "figure", "figcaption", "svg",
                       "polyline", "circle", "text", "footer", "code"}


def test_escaping_covers_attribute_context():
    assert '"' not in html.esc('a "quoted" value').replace("&quot;", "")


# --- the content ---------------------------------------------------------------


def test_colour_is_never_the_only_signal():
    """A state is a word first."""
    for state, (word, _) in html.STATE_WORDS.items():
        page = html.render(a_report(dimensions={"acceptance": state}))
        assert word in page


def test_the_acceptance_state_and_reason_lead_the_page():
    report = a_report()
    report["dimensions"]["acceptance"] = "inconclusive"
    report["headline_reason"] = "required subject affinity was not observed"
    page = html.render(report)
    assert page.index("INCONCLUSIVE") < page.index("Primary metrics")
    assert "required subject affinity was not observed" in page


def test_every_dimension_is_shown_not_just_the_verdict():
    page = html.render(a_report())
    for name in ("Execution", "Correctness", "Coverage", "Comparability", "Measurement"):
        assert name in page


def test_the_plot_is_accompanied_by_a_table_of_the_same_numbers():
    page = html.render(a_report(), pairs=PAIRS)
    assert "<svg" in page
    assert page.count("<table") >= 2
    assert "c1/p000" in page and "c1/p009" in page


def test_a_figure_carries_a_text_alternative():
    page = html.render(a_report(), pairs=PAIRS)
    assert 'role="img"' in page and "aria-label=" in page


def test_missing_evidence_is_listed_rather_than_omitted():
    report = a_report()
    report["dimensions"]["coverage"] = "incomplete"
    report["coverage"] = {"state": "incomplete", "incomplete": [
        {"capability": "parallelism.subject_affinity", "scope": "subject",
         "stage": "before", "reason": "no evidence"}]}
    page = html.render(report)
    assert "Evidence that was not observed" in page
    assert "parallelism.subject_affinity" in page


def test_a_waiver_is_shown_and_the_underlying_difference_is_not_erased():
    report = a_report()
    report["waivers_applied"] = [{"id": "w1", "target": "hardware.cpu_model",
                                  "reason": "same partition", "reference": "ticket-7"}]
    report["field_results"] = [{"path": "hardware.cpu_model", "classification": "waived",
                                "reason": "same partition"}]
    page = html.render(report)
    assert "Waivers" in page and "ticket-7" in page
    assert "Field differences" in page and "hardware.cpu_model" in page
    assert "still listed above" in page


def test_the_methods_assumptions_are_on_the_page():
    page = html.render(a_report())
    assert "What this result assumes" in page
    assert "independent" in page


def test_the_receipt_is_shown_when_one_is_given():
    line = "ceteris-receipt v3 manifest=sha256:" + "b" * 64
    page = html.render(a_report(), receipt=line)
    assert line in page
    assert "do not prove" in page


def test_the_page_survives_a_report_with_nothing_in_it():
    page = html.render({"comparison_id": "c1", "dimensions": {}})
    assert "<main>" in page and "</main>" in page


def test_a_metric_with_no_resolved_interval_says_so():
    report = a_report()
    report["metric_results"][0]["interval_display"] = [None, None]
    assert "not resolved" in html.render(report)

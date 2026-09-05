"""Versioned metric analysis methods.

Design section 11. Two methods ship: `descriptive@1`, which counts and
summarises and concludes nothing, and `paired-median-relative@1`, the
reference inferential method.

Everything that touches a decision is exact rational arithmetic. Rounding
exists only for display, and a report digest covers the rationals rather
than the rendered percentages, so two implementations agree on the decision
even when they disagree about how to print it.

`paired-median-relative@1` is experimental until it has independent
methodology review. It estimates the population median of within-pair
relative effects, for these fixed builds on this testbed. It does not
estimate a ratio of global medians, a mean effect, or uncertainty across
rebuilds or machines.
"""

from __future__ import annotations

from fractions import Fraction
from math import comb
from typing import Any

from ..protocol.encoding import canonical_decimal

DESCRIPTIVE = "descriptive@1"
PAIRED_MEDIAN_RELATIVE = "paired-median-relative@1"
LEGACY_RANGE = "legacy-range@1"

METHODS = (DESCRIPTIVE, PAIRED_MEDIAN_RELATIVE, LEGACY_RANGE)

MIN_PAIRS = 10

PREDICATES = ("non_regression", "improvement", "equivalence")

# Interval and predicate outcomes.
PASS, FAIL, INCONCLUSIVE = "pass", "fail", "inconclusive"


class IneligibleInput(ValueError):
    """The selected observations cannot support this method."""

    code = "unsupported_method"


def _fraction(text: Any) -> Fraction:
    """A measurement as an exact rational, via its canonical decimal."""
    return Fraction(canonical_decimal(text))


def as_rational(value: Fraction) -> dict:
    """The protocol's rational encoding: reduced, positive denominator."""
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def to_display(value: "Fraction | None", places: int = 2) -> "str | None":
    """Display only. Round half to even, and never feed this to a decision."""
    if value is None:
        return None
    from decimal import Decimal, ROUND_HALF_EVEN

    scaled = Decimal(value.numerator) / Decimal(value.denominator) * 100
    return str(scaled.quantize(Decimal(10) ** -places, rounding=ROUND_HALF_EVEN)) + "%"


# --- eligibility --------------------------------------------------------------


def check_pairs(pairs, *, min_pairs: int = MIN_PAIRS, planned_pairs: "int | None" = None) -> list:
    """Why these pairs cannot be analysed, or an empty list.

    A missing measurement never shrinks the expected sample set: dropping
    the pairs that failed and analysing the rest answers a question about a
    different experiment.
    """
    problems = []
    if min_pairs < MIN_PAIRS:
        problems.append(
            f"min_pairs is {min_pairs}; this method requires at least {MIN_PAIRS}")
    if planned_pairs is not None and len(pairs) != planned_pairs:
        problems.append(
            f"{len(pairs)} of {planned_pairs} planned pairs carry an eligible "
            f"measurement; a failed slot does not reduce the expected sample set")
    if len(pairs) < max(min_pairs, MIN_PAIRS):
        problems.append(f"{len(pairs)} pairs is fewer than the required {max(min_pairs, MIN_PAIRS)}")

    seen = set()
    for pair in pairs:
        identity = pair.get("pair_id")
        if identity in seen:
            problems.append(f"pair {identity!r} appears more than once")
        seen.add(identity)
        for role in ("baseline", "candidate"):
            value = pair.get(role)
            if isinstance(value, list):
                problems.append(f"pair {identity!r} has a list-valued {role} estimate")
                continue
            try:
                if _fraction(value) <= 0:
                    problems.append(
                        f"pair {identity!r} has a nonpositive {role} value; this method "
                        f"is restricted to positive scalar metrics")
            except Exception:
                problems.append(f"pair {identity!r} has an unusable {role} value {value!r}")
    return problems


# --- pair effects -------------------------------------------------------------


def pair_effect(baseline: Any, candidate: Any, direction: str) -> Fraction:
    """The within-pair relative effect. Positive is worse, always.

    The baseline is the denominator in both directions, deliberately.
    Latency 100 to 106 is +0.06; throughput 100 to 106 is -0.06. Switching
    denominators depending on which number is larger would make the same
    change read differently depending on which way the metric points.
    """
    b, c = _fraction(baseline), _fraction(candidate)
    if b <= 0 or c <= 0:
        raise IneligibleInput("this method needs strictly positive values")
    if direction == "lower":
        return (c - b) / b
    if direction == "higher":
        return (b - c) / b
    raise IneligibleInput(
        f"direction {direction!r} cannot decide whether a change is an improvement")


def median_of(effects) -> Fraction:
    """Exact median. For even counts, the average of the central two."""
    ordered = sorted(effects)
    n = len(ordered)
    if n == 0:
        raise IneligibleInput("no effects to summarise")
    middle = n // 2
    if n % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


# --- the order-statistic interval ---------------------------------------------


def interval_rank(n: int, alpha: Fraction) -> "int | None":
    """The largest k giving a distribution-free interval at level alpha.

    Largest integer k in [1, floor((n+1)/2)] with

        2 * sum(comb(n, j) for j in range(k)) / 2**n  <=  alpha

    None when no such k exists, which means this many pairs cannot resolve
    an interval at this confidence, not that the effect is zero.
    """
    best = None
    for k in range(1, (n + 1) // 2 + 1):
        tail = Fraction(2 * sum(comb(n, j) for j in range(k)), 2 ** n)
        if tail <= alpha:
            best = k
        else:
            break
    return best


def family_alpha(confidence: Any, hypotheses: int) -> Fraction:
    """Bonferroni allocation across the predeclared primary hypotheses.

    Correlated metrics do not need an independence assumption for this
    allocation; they would for a sharper one.
    """
    if hypotheses < 1:
        raise IneligibleInput("a family needs at least one hypothesis")
    return (1 - _fraction(confidence)) / hypotheses


# --- predicates ---------------------------------------------------------------


def evaluate_predicate(kind: str, threshold: Any, low, high) -> str:
    """One primary metric's decision, from the interval alone."""
    if low is None or high is None:
        return INCONCLUSIVE
    t = _fraction(threshold)
    if kind == "non_regression":
        if t < 0:
            raise IneligibleInput("a regression budget cannot be negative")
        if high <= t:
            return PASS
        if low > t:
            return FAIL
        return INCONCLUSIVE
    if kind == "improvement":
        if t < 0:
            raise IneligibleInput("a required improvement cannot be negative")
        if high < -t:
            return PASS
        if low >= -t:
            return FAIL
        return INCONCLUSIVE
    if kind == "equivalence":
        if t <= 0:
            raise IneligibleInput("an equivalence margin must be positive")
        if low >= -t and high <= t:
            return PASS
        if high < -t or low > t:
            return FAIL
        return INCONCLUSIVE
    raise IneligibleInput(f"{kind!r} is not one of {', '.join(PREDICATES)}")


def classify_effect(low, high, margin: Any) -> str:
    """A description of the evidence, beside the predicate's exact rule."""
    if low is None or high is None:
        return "inconclusive"
    e = _fraction(margin)
    if high < -e:
        return "improvement"
    if low > e:
        return "regression"
    if low >= -e and high <= e:
        return "no_material_change"
    return "inconclusive"


# --- the methods --------------------------------------------------------------


def descriptive(samples) -> dict:
    """`descriptive@1`. Counts and summarises; concludes nothing."""
    usable, missing = [], 0
    for value in samples:
        try:
            usable.append(_fraction(value))
        except Exception:
            missing += 1
    body = {"method": DESCRIPTIVE, "n": len(usable), "missing": missing}
    if usable:
        ordered = sorted(usable)
        body.update(
            min=as_rational(ordered[0]),
            median=as_rational(median_of(ordered)),
            max=as_rational(ordered[-1]),
        )
    return body


def paired_median_relative(pairs, *, direction: str, confidence: Any = "0.95",
                           hypotheses: int = 1, predicate: "dict | None" = None,
                           min_pairs: int = MIN_PAIRS,
                           planned_pairs: "int | None" = None,
                           material_margin: Any = None) -> dict:
    """`paired-median-relative@1`.

    Each pair contributes one relative effect. The estimate is their median,
    and the interval is a distribution-free order-statistic interval on that
    median. Everything is exact; the decision never sees a rounded number.
    """
    problems = check_pairs(pairs, min_pairs=min_pairs, planned_pairs=planned_pairs)
    if problems:
        return {
            "method": PAIRED_MEDIAN_RELATIVE,
            "status": "unavailable",
            "eligible": False,
            "reasons": problems,
            "n": len(pairs),
        }

    effects = []
    for pair in pairs:
        effects.append({
            "pair_id": pair.get("pair_id"),
            "effect": pair_effect(pair["baseline"], pair["candidate"], direction),
        })
    ordered = sorted(effects, key=lambda e: e["effect"])
    values = [e["effect"] for e in ordered]
    n = len(values)

    alpha = family_alpha(confidence, hypotheses)
    k = interval_rank(n, alpha)
    if k is None:
        low = high = None
        interval_status = "insufficient_resolution"
    else:
        low, high = values[k - 1], values[n - k]
        interval_status = "resolved"

    estimate = median_of(values)
    ties = n - len({(v.numerator, v.denominator) for v in values})

    body = {
        "method": PAIRED_MEDIAN_RELATIVE,
        "status": "assessed" if interval_status == "resolved" else "inconclusive",
        "eligible": True,
        "n": n,
        "direction": direction,
        "confidence": canonical_decimal(confidence),
        "hypotheses": hypotheses,
        "alpha": as_rational(alpha),
        "interval_status": interval_status,
        "interval_rank_k": k,
        "estimate": as_rational(estimate),
        "estimate_display": to_display(estimate),
        "interval_low": as_rational(low) if low is not None else None,
        "interval_high": as_rational(high) if high is not None else None,
        "interval_display": [to_display(low), to_display(high)],
        "ties": ties,
        "pair_effects": [{"pair_id": e["pair_id"], "effect": as_rational(e["effect"])}
                         for e in ordered],
        "assumptions": [
            "pairs are independent and sample a common effect distribution",
            "the estimand is the median within-pair relative effect for these "
            "fixed builds on this testbed",
            "balanced execution order reduces ordering bias; it does not "
            "establish independence or remove thermal or cache carryover",
        ],
    }

    if predicate:
        kind = predicate.get("type")
        threshold = predicate.get("threshold",
                                  predicate.get("max_relative_regression",
                                                predicate.get("margin", "0")))
        body["predicate"] = {
            "type": kind,
            "threshold": canonical_decimal(threshold),
            "result": evaluate_predicate(kind, threshold, low, high),
        }
        body["effect_class"] = classify_effect(
            low, high, material_margin if material_margin is not None else threshold)
    return body


def minimum_pairs_for(confidence: Any, hypotheses: int, *, limit: int = 4096) -> "int | None":
    """The smallest even n whose interval resolves at this confidence.

    Used at plan resolution to refuse an inferential design that cannot
    produce a finite interval however it runs. Interval existence is not
    statistical power, and this does not pretend to estimate power.
    """
    alpha = family_alpha(confidence, hypotheses)
    n = MIN_PAIRS
    while n <= limit:
        if interval_rank(n, alpha) is not None:
            return n
        n += 2
    return None


def combine_primary(results) -> str:
    """All primary predicates must pass. Any failure fails the policy.

    A signal on one metric never rescues another; they are separate
    questions and the family was declared in advance.
    """
    outcomes = [r.get("predicate", {}).get("result", INCONCLUSIVE) for r in results]
    if not outcomes:
        return INCONCLUSIVE
    if FAIL in outcomes:
        return FAIL
    if INCONCLUSIVE in outcomes:
        return INCONCLUSIVE
    return PASS


__all__ = [
    "DESCRIPTIVE",
    "FAIL",
    "INCONCLUSIVE",
    "IneligibleInput",
    "LEGACY_RANGE",
    "METHODS",
    "MIN_PAIRS",
    "PAIRED_MEDIAN_RELATIVE",
    "PASS",
    "PREDICATES",
    "as_rational",
    "check_pairs",
    "classify_effect",
    "combine_primary",
    "descriptive",
    "evaluate_predicate",
    "family_alpha",
    "interval_rank",
    "median_of",
    "minimum_pairs_for",
    "pair_effect",
    "paired_median_relative",
    "to_display",
]

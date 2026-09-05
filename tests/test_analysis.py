"""Measurement analysis. Design section 11.

Written as conformance tests: the reference values in the design are checked
directly, so another implementation of `paired-median-relative@1` has
something exact to agree with.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from ceteris import analysis as a


def pairs_from(effects, baseline="100"):
    """Pairs whose candidate values realise the given relative effects.

    Measurements are decimal strings, as the protocol carries them, so the
    effects here have to be decimal-representable. An effect like one third
    is a perfectly good rational and not a decimal measurement, which is why
    the exactness test below builds its pair from two plain values instead.
    """
    from decimal import Decimal

    out = []
    for i, effect in enumerate(effects):
        b = Fraction(baseline)
        c = b * (1 + Fraction(effect))
        assert c.denominator in (1, 2, 4, 5, 8, 10, 16, 20, 25, 40, 50, 100, 125, 200), (
            f"{c} is not a decimal measurement; pick another effect")
        out.append({"pair_id": f"p{i:03d}",
                    "baseline": str(Decimal(b.numerator) / Decimal(b.denominator)),
                    "candidate": str(Decimal(c.numerator) / Decimal(c.denominator))})
    return out


# --- the reference values from the design -------------------------------------


@pytest.mark.parametrize("n, hypotheses, expected_k", [
    (10, 1, 2),
    (20, 1, 6),
    (10, 100, None),
])
def test_interval_rank_matches_the_documented_reference_checks(n, hypotheses, expected_k):
    assert a.interval_rank(n, a.family_alpha("0.95", hypotheses)) == expected_k


def test_the_interval_is_the_kth_through_the_n_minus_k_plus_first_order_statistics():
    """n=10, k=2 means the second through the ninth."""
    effects = [Fraction(i, 100) for i in range(10)]
    result = a.paired_median_relative(pairs_from(effects), direction="lower")
    assert result["interval_rank_k"] == 2
    ordered = sorted(effects)
    assert Fraction(int(result["interval_low"]["numerator"]),
                    int(result["interval_low"]["denominator"])) == ordered[1]
    assert Fraction(int(result["interval_high"]["numerator"]),
                    int(result["interval_high"]["denominator"])) == ordered[8]


def test_too_many_hypotheses_gives_no_finite_interval_rather_than_a_guess():
    result = a.paired_median_relative(pairs_from([Fraction(i, 100) for i in range(10)]),
                                      direction="lower", hypotheses=100)
    assert result["interval_status"] == "insufficient_resolution"
    assert result["interval_low"] is None and result["interval_high"] is None
    assert result["status"] == "inconclusive"


# --- pair effects -------------------------------------------------------------


def test_the_baseline_is_the_denominator_in_both_directions():
    """Latency 100 to 106 is +0.06; throughput 100 to 106 is -0.06."""
    assert a.pair_effect("100", "106", "lower") == Fraction(6, 100)
    assert a.pair_effect("100", "106", "higher") == Fraction(-6, 100)


def test_positive_is_always_worse():
    assert a.pair_effect("100", "110", "lower") > 0        # slower latency
    assert a.pair_effect("100", "90", "higher") > 0        # lower throughput
    assert a.pair_effect("100", "100", "lower") == 0


def test_effects_are_exact_not_binary_floats():
    """0.1 and 0.2 are not exactly representable; the arithmetic is rational."""
    effect = a.pair_effect("0.3", "0.1", "lower")
    assert effect == Fraction(-2, 3)


def test_a_direction_of_none_cannot_decide_anything():
    with pytest.raises(a.IneligibleInput, match="improvement"):
        a.pair_effect("1", "2", "none")


def test_a_nonpositive_value_is_refused():
    with pytest.raises(a.IneligibleInput):
        a.pair_effect("0", "1", "lower")


def test_the_median_of_an_even_count_is_the_average_of_the_central_two():
    assert a.median_of([Fraction(1), Fraction(2), Fraction(3), Fraction(4)]) == Fraction(5, 2)
    assert a.median_of([Fraction(1), Fraction(3), Fraction(2)]) == Fraction(2)


# --- eligibility --------------------------------------------------------------


def test_fewer_than_ten_pairs_is_unavailable():
    result = a.paired_median_relative(pairs_from([Fraction(0)] * 8), direction="lower")
    assert result["status"] == "unavailable" and not result["eligible"]


def test_a_failed_slot_does_not_shrink_the_expected_sample_set():
    """Analysing the pairs that survived answers a different question."""
    result = a.paired_median_relative(
        pairs_from([Fraction(1, 100)] * 18), direction="lower", planned_pairs=20)
    assert result["status"] == "unavailable"
    assert any("planned pairs" in r for r in result["reasons"])


def test_a_repeated_pair_id_is_refused():
    pairs = pairs_from([Fraction(1, 100)] * 10)
    pairs[1]["pair_id"] = pairs[0]["pair_id"]
    result = a.paired_median_relative(pairs, direction="lower")
    assert any("more than once" in r for r in result["reasons"])


def test_a_list_valued_estimate_is_refused():
    pairs = pairs_from([Fraction(1, 100)] * 10)
    pairs[0]["candidate"] = ["1", "2"]
    result = a.paired_median_relative(pairs, direction="lower")
    assert any("list-valued" in r for r in result["reasons"])


@pytest.mark.parametrize("bad", ["0", "-1", "nan", "inf"])
def test_values_outside_the_supported_domain_are_refused(bad):
    pairs = pairs_from([Fraction(1, 100)] * 10)
    pairs[0]["candidate"] = bad
    result = a.paired_median_relative(pairs, direction="lower")
    assert not result["eligible"]


def test_a_min_pairs_below_the_method_floor_is_refused():
    result = a.paired_median_relative(pairs_from([Fraction(0)] * 10),
                                      direction="lower", min_pairs=3)
    assert any("at least 10" in r for r in result["reasons"])


# --- predicates ---------------------------------------------------------------


def frac(x):
    return Fraction(x)


@pytest.mark.parametrize("low, high, budget, expected", [
    ("0.01", "0.03", "0.05", a.PASS),           # whole interval inside the budget
    ("0.06", "0.09", "0.05", a.FAIL),           # entirely beyond it
    ("0.01", "0.09", "0.05", a.INCONCLUSIVE),   # straddles the threshold
    ("-0.10", "-0.02", "0.05", a.PASS),         # an improvement passes non-regression
    ("0", "0", "0", a.PASS),                    # exactly unchanged, zero budget
])
def test_non_regression(low, high, budget, expected):
    assert a.evaluate_predicate("non_regression", budget, frac(low), frac(high)) == expected


@pytest.mark.parametrize("low, high, required, expected", [
    ("-0.20", "-0.11", "0.10", a.PASS),
    ("-0.05", "0.02", "0.10", a.FAIL),
    ("-0.20", "-0.05", "0.10", a.INCONCLUSIVE),
])
def test_improvement(low, high, required, expected):
    assert a.evaluate_predicate("improvement", required, frac(low), frac(high)) == expected


@pytest.mark.parametrize("low, high, margin, expected", [
    ("-0.02", "0.03", "0.05", a.PASS),
    ("0.06", "0.09", "0.05", a.FAIL),
    ("-0.09", "-0.06", "0.05", a.FAIL),
    ("-0.02", "0.09", "0.05", a.INCONCLUSIVE),
])
def test_equivalence(low, high, margin, expected):
    assert a.evaluate_predicate("equivalence", margin, frac(low), frac(high)) == expected


def test_an_unresolved_interval_is_inconclusive_for_every_predicate():
    for kind, threshold in (("non_regression", "0.05"), ("improvement", "0.1"),
                            ("equivalence", "0.05")):
        assert a.evaluate_predicate(kind, threshold, None, None) == a.INCONCLUSIVE


def test_no_detectable_difference_can_legitimately_pass_non_regression():
    """The whole interval lying inside the budget is the pass condition,
    not the mere absence of a detected regression."""
    assert a.evaluate_predicate("non_regression", "0.05",
                                frac("-0.01"), frac("0.01")) == a.PASS


def test_a_negative_budget_is_refused():
    with pytest.raises(a.IneligibleInput):
        a.evaluate_predicate("non_regression", "-0.01", frac("0"), frac("0"))
    with pytest.raises(a.IneligibleInput):
        a.evaluate_predicate("equivalence", "0", frac("0"), frac("0"))


# --- practical classification -------------------------------------------------


@pytest.mark.parametrize("low, high, margin, expected", [
    ("-0.20", "-0.11", "0.05", "improvement"),
    ("0.06", "0.20", "0.05", "regression"),
    ("-0.01", "0.02", "0.05", "no_material_change"),
    ("-0.20", "0.20", "0.05", "inconclusive"),
])
def test_effect_classification(low, high, margin, expected):
    assert a.classify_effect(frac(low), frac(high), margin) == expected


# --- combining a family -------------------------------------------------------


def test_every_primary_predicate_must_pass():
    passing = {"predicate": {"result": a.PASS}}
    failing = {"predicate": {"result": a.FAIL}}
    unclear = {"predicate": {"result": a.INCONCLUSIVE}}
    assert a.combine_primary([passing, passing]) == a.PASS
    assert a.combine_primary([passing, failing]) == a.FAIL
    assert a.combine_primary([passing, unclear]) == a.INCONCLUSIVE
    # A signal on one metric never rescues another.
    assert a.combine_primary([failing, passing]) == a.FAIL
    assert a.combine_primary([]) == a.INCONCLUSIVE


# --- determinism and display --------------------------------------------------


def test_the_same_input_always_gives_the_same_answer():
    pairs = pairs_from([Fraction(i, 200) for i in range(-5, 15)])
    first = a.paired_median_relative(pairs, direction="lower")
    second = a.paired_median_relative(list(reversed(pairs)), direction="lower")
    assert first["estimate"] == second["estimate"]
    assert first["interval_low"] == second["interval_low"]


def test_rounding_is_for_display_only_and_the_rationals_stay_exact():
    """The effect here is one third, which no decimal can hold. The
    measurements are decimals; the arithmetic over them is not."""
    pairs = [{"pair_id": f"p{i}", "baseline": "3", "candidate": "4"} for i in range(10)]
    result = a.paired_median_relative(pairs, direction="lower")
    assert result["estimate"] == {"numerator": "1", "denominator": "3"}
    assert result["estimate_display"] == "33.33%"


def test_display_rounds_half_to_even():
    assert a.to_display(Fraction(125, 10000)) == "1.25%"
    assert a.to_display(Fraction(1250001, 100000000)) == "1.25%"
    assert a.to_display(None) is None


def test_ties_are_counted_and_reported():
    result = a.paired_median_relative(pairs_from([Fraction(1, 100)] * 10), direction="lower")
    assert result["ties"] == 9
    assert result["estimate"] == {"numerator": "1", "denominator": "100"}


def test_the_method_states_its_assumptions_in_the_result():
    result = a.paired_median_relative(pairs_from([Fraction(1, 100)] * 10), direction="lower")
    joined = " ".join(result["assumptions"])
    assert "independent" in joined and "fixed builds" in joined


# --- planning -----------------------------------------------------------------


def test_a_plan_that_cannot_resolve_an_interval_is_detectable_before_it_runs():
    assert a.minimum_pairs_for("0.95", 1) == 10
    assert a.minimum_pairs_for("0.95", 100) == 12
    assert a.minimum_pairs_for("0.999999", 10000) is not None


# --- descriptive --------------------------------------------------------------


def test_descriptive_counts_and_concludes_nothing():
    got = a.descriptive(["1", "2", "3"])
    assert got["n"] == 3 and got["missing"] == 0
    assert got["median"] == {"numerator": "2", "denominator": "1"}
    assert "predicate" not in got and "interval_low" not in got


def test_descriptive_counts_what_it_could_not_read():
    got = a.descriptive(["1", "nan", None])
    assert got["n"] == 1 and got["missing"] == 2

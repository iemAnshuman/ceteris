"""`ceteris-json-v1`, checked against frozen byte vectors.

A digest only means something if two implementations agree on the bytes it
was taken over, so these tests are written the way an independent
implementation would have to pass them: exact output, not round-tripping.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ceteris.protocol import encoding as e

VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / "protocol" / "encoding_vectors.json").read_text(
        encoding="utf-8"
    )
)


def ids(entries):
    return [entry["name"] for entry in entries]


# --- the frozen vectors -------------------------------------------------------


@pytest.mark.parametrize("case", VECTORS["vectors"], ids=ids(VECTORS["vectors"]))
def test_canonical_bytes_match_the_frozen_vector(case):
    assert e.canonical_text(case["value"]) == case["canonical"]
    assert len(e.canonical_bytes(case["value"])) == case["utf8_bytes"]


@pytest.mark.parametrize("case", VECTORS["vectors"], ids=ids(VECTORS["vectors"]))
def test_digests_match_the_frozen_vector(case):
    assert e.digest(case["value"]) == case["digest"]
    assert e.is_digest(case["digest"])


@pytest.mark.parametrize("case", VECTORS["vectors"], ids=ids(VECTORS["vectors"]))
def test_canonical_output_reads_back_as_the_same_value(case):
    assert e.loads(case["canonical"]) == case["value"]


@pytest.mark.parametrize("case", VECTORS["decimals"], ids=ids(VECTORS["decimals"]))
def test_decimal_vectors(case):
    assert e.canonical_decimal(case["source"]) == case["canonical"]


@pytest.mark.parametrize("case", VECTORS["rationals"], ids=ids(VECTORS["rationals"]))
def test_rational_vectors(case):
    assert e.rational(case["numerator"], case["denominator"]) == case["canonical"]


# --- the rules the vectors illustrate -----------------------------------------


def test_keys_sort_by_unicode_scalar_value_not_by_utf8_bytes():
    """Sorting encoded bytes and sorting code points agree for ASCII and
    disagree elsewhere; the protocol says code points."""
    assert e.canonical_text({"é": 1, "z": 2}) == '{"z":2,"\\u00e9":1}'


def test_array_order_is_never_sorted():
    assert e.canonical_text([3, 1, 2]) == "[3,1,2]"


def test_pretty_input_canonicalises_to_the_same_digest():
    """A human may format a protocol file; the digest must not care."""
    pretty = '{\n  "b" : 2,\n  "a" : [1,\n   2]\n}\n'
    assert e.digest(e.loads(pretty)) == e.digest({"a": [1, 2], "b": 2})


def test_a_fractional_number_is_refused_on_the_way_in_and_out():
    with pytest.raises(e.CanonicalError, match="fractional"):
        e.canonical_text({"x": 0.1})
    with pytest.raises(e.CanonicalError, match="fractional"):
        e.loads('{"x": 0.1}')


def test_duplicate_object_keys_are_refused():
    """Which one wins is a reader's choice, so the document has no meaning."""
    with pytest.raises(e.CanonicalError, match="duplicate object key"):
        e.loads('{"a": 1, "a": 2}')


def test_integers_beyond_exact_representation_are_refused():
    with pytest.raises(e.NumericLimitExceeded):
        e.canonical_text(e.MAX_SAFE_INT + 1)
    with pytest.raises(e.NumericLimitExceeded):
        e.loads(str(e.MIN_SAFE_INT - 1))
    assert e.canonical_text(e.MAX_SAFE_INT) == str(e.MAX_SAFE_INT)


def test_a_byte_order_mark_is_refused():
    with pytest.raises(e.CanonicalError, match="byte order mark"):
        e.loads(b"\xef\xbb\xbf{}")


def test_invalid_utf8_is_refused():
    with pytest.raises(e.CanonicalError, match="not valid UTF-8"):
        e.loads(b'{"a": "\xff"}')


def test_an_unpaired_surrogate_is_refused_both_ways():
    with pytest.raises(e.CanonicalError, match="surrogate"):
        e.canonical_text("\ud800")
    with pytest.raises(e.CanonicalError, match="surrogate"):
        e.loads('"\\ud800"')


def test_json_constants_python_accepts_are_refused():
    for text in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(e.CanonicalError):
            e.loads(text)


def test_nesting_deeper_than_the_limit_is_refused():
    deep = {}
    node = deep
    for _ in range(e.MAX_DEPTH + 2):
        node["a"] = {}
        node = node["a"]
    with pytest.raises(e.CanonicalError, match="nesting"):
        e.canonical_text(deep)


def test_booleans_are_encoded_as_booleans_not_integers():
    assert e.canonical_text({"t": True, "f": False}) == '{"f":false,"t":true}'
    assert e.canonical_text({"one": 1}) == '{"one":1}'


def test_object_keys_must_be_strings():
    with pytest.raises(e.CanonicalError, match="keys must be strings"):
        e.canonical_text({1: "a"})


def test_an_unencodable_type_is_named():
    with pytest.raises(e.CanonicalError, match="set has no canonical encoding"):
        e.canonical_text({"a"})


# --- decimals -----------------------------------------------------------------


def test_a_binary_float_cannot_become_a_decimal_measurement():
    """It has already lost the precision, and a conversion would invent it."""
    with pytest.raises(e.CanonicalError, match="binary float"):
        e.canonical_decimal(0.1)


def test_limits_are_refused_rather_than_rounded():
    with pytest.raises(e.NumericLimitExceeded):
        e.canonical_decimal("1." + "2" * 200)
    with pytest.raises(e.NumericLimitExceeded):
        e.canonical_decimal("1e400")


def test_a_decimal_survives_a_round_trip_that_a_float_would_not():
    exact = "0.1"
    assert e.canonical_decimal(exact) == exact
    assert e.loads(e.canonical_text({"x": exact}))["x"] == exact


def test_a_zero_denominator_is_not_a_number():
    with pytest.raises(e.CanonicalError, match="zero denominator"):
        e.rational("1", "0")


# --- the digest itself --------------------------------------------------------


def test_digest_form_is_the_documented_string():
    got = e.digest({})
    assert got.startswith("sha256:") and len(got) == 71
    assert got == "sha256:" + __import__("hashlib").sha256(b"{}").hexdigest()


def test_is_digest_rejects_near_misses():
    good = e.digest({})
    assert not e.is_digest(good.upper())
    assert not e.is_digest(good[7:])
    assert not e.is_digest("sha256:" + "g" * 64)
    assert not e.is_digest(None)


def test_a_reordered_object_has_the_same_digest_and_a_changed_one_does_not():
    assert e.digest({"a": 1, "b": 2}) == e.digest({"b": 2, "a": 1})
    assert e.digest({"a": 1, "b": 2}) != e.digest({"a": 1, "b": 3})

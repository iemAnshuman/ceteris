"""The fingerprint must be stable and diffable."""

from __future__ import annotations

import json

import pytest

from ceteris.model import Field, Fingerprint, State, not_applicable, unknown, value

from conftest import fp, na


def test_json_round_trips():
    original = fp("run-a", source__commit="a1b2c3d", hardware__gpu=na("no GPU"))
    reloaded = Fingerprint.from_json(json.loads(original.dumps()))
    assert reloaded.fields == original.fields
    assert reloaded.content_hash() == original.content_hash()


def test_keys_are_sorted_so_the_file_diffs_cleanly():
    text = fp("x", zulu="1", alpha="2", mike="3").dumps()
    body = json.loads(text)["fields"]
    assert list(body) == sorted(body)
    assert text.index('"alpha"') < text.index('"mike"') < text.index('"zulu"')


def test_hash_ignores_meta_so_identical_environments_hash_identically():
    fields = {"source.commit": value("a1b2c3d")}
    a = Fingerprint(fields, {"label": "a", "captured_at": "2026-08-26T10:00:00+00:00"})
    b = Fingerprint(dict(fields), {"label": "b", "captured_at": "2026-08-26T23:59:59+00:00"})
    assert a.content_hash() == b.content_hash()


def test_hash_changes_when_a_field_changes():
    a = Fingerprint({"source.commit": value("a1b2c3d")}, {})
    b = Fingerprint({"source.commit": value("9f8e7d6")}, {})
    assert a.content_hash() != b.content_hash()


def test_unknown_carries_no_value_through_serialisation():
    """An unknown must not round-trip into something that looks like data."""
    text = json.dumps(unknown("nvidia-smi timed out").to_json())
    assert '"v"' not in text
    assert Field.from_json(json.loads(text)).value is None


def test_states_are_distinguishable_after_serialisation():
    for field in (unknown("x"), not_applicable("y"), value(None)):
        reloaded = Field.from_json(json.loads(json.dumps(field.to_json())))
        assert reloaded.state is field.state


@pytest.mark.parametrize(
    "raw", [{"fields": []}, {"nope": 1}, {"fields": {"a": {"s": "bogus"}}}]
)
def test_malformed_input_is_rejected(raw):
    with pytest.raises(ValueError):
        Fingerprint.from_json(raw)

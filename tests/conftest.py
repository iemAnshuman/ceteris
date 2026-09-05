"""Fixture helpers.

These hand-build fingerprints so the compare engine can be tested without any
collector running. That ordering is deliberate: the fixtures define the schema
contract the collectors must then satisfy.
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from ceteris.config import Config
from ceteris.model import Field, Fingerprint, State


_serial = itertools.count(1)


def distinct_meta(label: str) -> dict:
    """Meta for a record that is its own execution.

    Real records carry the moment they were captured, so two runs are never
    byte-identical and duplicate detection can tell a genuine repeat from a
    copied file. Synthetic fixtures have to say the same thing or they look
    like one observation offered twice.
    """
    n = next(_serial)
    return {"label": label, "captured_at": f"2026-01-01T00:00:{n % 60:02d}+00:00", "fixture_seq": n}


def fp(label: str, **fields: Any) -> Fingerprint:
    """Build a fingerprint. Plain values become VALUE fields; pass a Field for
    any other state."""
    built: dict[str, Field] = {}
    for key, val in fields.items():
        path = key.replace("__", ".")
        built[path] = val if isinstance(val, Field) else Field(State.VALUE, val)
    return Fingerprint(fields=built, meta=distinct_meta(label))


def na(detail: str = "structurally absent") -> Field:
    return Field(State.NOT_APPLICABLE, detail=detail)


def unk(detail: str = "could not read") -> Field:
    return Field(State.UNKNOWN, detail=detail)


def err(detail: str = "collector crashed") -> Field:
    return Field(State.ERROR, detail=detail)


@pytest.fixture(scope="session")
def cfg() -> Config:
    return Config.load()

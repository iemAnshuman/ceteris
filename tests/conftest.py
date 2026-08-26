"""Fixture helpers.

These hand-build fingerprints so the compare engine can be tested without any
collector running. That ordering is deliberate: the fixtures define the schema
contract the collectors must then satisfy.
"""

from __future__ import annotations

from typing import Any

import pytest

from ceteris.config import Config
from ceteris.model import Field, Fingerprint, State


def fp(label: str, **fields: Any) -> Fingerprint:
    """Build a fingerprint. Plain values become VALUE fields; pass a Field for
    any other state."""
    built: dict[str, Field] = {}
    for key, val in fields.items():
        path = key.replace("__", ".")
        built[path] = val if isinstance(val, Field) else Field(State.VALUE, val)
    return Fingerprint(fields=built, meta={"label": label})


def na(detail: str = "structurally absent") -> Field:
    return Field(State.NOT_APPLICABLE, detail=detail)


def unk(detail: str = "could not read") -> Field:
    return Field(State.UNKNOWN, detail=detail)


def err(detail: str = "collector crashed") -> Field:
    return Field(State.ERROR, detail=detail)


@pytest.fixture(scope="session")
def cfg() -> Config:
    return Config.load()

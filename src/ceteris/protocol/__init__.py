"""The wire protocol: canonical encoding, digests, typed values, validation.

Nothing in this package touches the machine. Encoding and validation are
pure functions of their input, so a verifier can recompute a decision from
an offline bundle without running anything, and two implementations can be
compared against the same byte vectors.
"""

from .encoding import (
    CanonicalError,
    NumericLimitExceeded,
    canonical_bytes,
    canonical_decimal,
    canonical_text,
    digest,
    is_digest,
    loads,
    rational,
)
from .models import Capability, Field, Metric, ProtocolError, Provenance
from .validation import Issue, SCHEMA_VERSION, load_run, validate_run

__all__ = [
    "Capability",
    "Field",
    "Issue",
    "Metric",
    "ProtocolError",
    "Provenance",
    "SCHEMA_VERSION",
    "load_run",
    "validate_run",
    "CanonicalError",
    "NumericLimitExceeded",
    "canonical_bytes",
    "canonical_decimal",
    "canonical_text",
    "digest",
    "is_digest",
    "loads",
    "rational",
]

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

__all__ = [
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

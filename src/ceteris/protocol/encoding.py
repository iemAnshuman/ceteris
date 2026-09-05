"""`ceteris-json-v1`: the canonical encoding, and the digests taken over it.

A digest is only meaningful if two implementations agree on the bytes it was
taken over. Python's default JSON output does not qualify: it emits binary
floats whose shortest repr differs between versions, it accepts duplicate
object keys and silently keeps the last, and it leaves U+007F unescaped. So
this is a deliberately small encoding with the awkward parts pinned down,
and `tests/fixtures/protocol/encoding_vectors.json` freezes the bytes.

The rules, from design section 5.2:

1. UTF-8 without a BOM. Duplicate object keys and unpaired surrogates are
   rejected rather than resolved.
2. null, booleans, strings, arrays, objects, and integers within the range
   an IEEE double represents exactly. Fractional JSON numbers are not
   permitted; a decimal measurement is a string, so that `0.1` survives a
   round trip through every language's parser.
3. Object keys sort by Unicode scalar value. Array order is significant.
4. Compact, no insignificant whitespace, no trailing newline.
5. Escape `"` and `\\`; `\\b \\t \\n \\f \\r` for those five; everything else
   below U+0020, plus U+007F and every non-ASCII character, as lowercase
   `\\uXXXX`, with surrogate pairs for supplementary characters. `/` is not
   escaped. No Unicode normalization.
6. Integer zero is `0`. Never `-0`, never leading zeros.
7. Pretty-printed input must canonicalize to the same digest.
8. An object never contains its own digest.

This is Ceteris's own encoding. It is not a claim of compliance with any
other canonical JSON specification.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

ENCODING_ID = "ceteris-json-v1"

# The integers an IEEE double represents exactly. Beyond this a JSON reader
# written in a language with one number type would silently round.
MAX_SAFE_INT = 9007199254740991
MIN_SAFE_INT = -9007199254740991

# Import limits for decimals, from design section 5.3.
MAX_SIGNIFICANT_DIGITS = 128
MAX_ABS_EXPONENT = 308
MAX_CANONICAL_DECIMAL_CHARS = 1024

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_DECIMAL_RE = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")

_SHORT_ESCAPES = {
    0x08: "\\b",
    0x09: "\\t",
    0x0A: "\\n",
    0x0C: "\\f",
    0x0D: "\\r",
    0x22: '\\"',
    0x5C: "\\\\",
}


class CanonicalError(ValueError):
    """The value cannot be encoded, or the text cannot be read, canonically."""

    code = "canonical_encoding_error"


class NumericLimitExceeded(CanonicalError):
    """A number outside the range the protocol will represent.

    Its own error rather than a rounding, because quietly rounding a
    measurement is the class of thing this project exists to refuse.
    """

    code = "numeric_limit_exceeded"


# --------------------------------------------------------------------------
# encoding
# --------------------------------------------------------------------------


def _escape(s: str) -> str:
    out = ['"']
    for ch in s:
        point = ord(ch)
        short = _SHORT_ESCAPES.get(point)
        if short is not None:
            out.append(short)
        elif point < 0x20 or point == 0x7F or point > 0x7E:
            if point > 0xFFFF:
                # Supplementary plane: the standard surrogate pair.
                adjusted = point - 0x10000
                high = 0xD800 + (adjusted >> 10)
                low = 0xDC00 + (adjusted & 0x3FF)
                out.append(f"\\u{high:04x}\\u{low:04x}")
            elif 0xD800 <= point <= 0xDFFF:
                raise CanonicalError(
                    f"unpaired surrogate U+{point:04X} in a string; the value is "
                    f"not valid Unicode and cannot be encoded"
                )
            else:
                out.append(f"\\u{point:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _encode(value: Any, out: list, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise CanonicalError(f"nesting deeper than {MAX_DEPTH} levels")
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, int):
        if not MIN_SAFE_INT <= value <= MAX_SAFE_INT:
            raise NumericLimitExceeded(
                f"{value} is outside the exactly representable integer range "
                f"[{MIN_SAFE_INT}, {MAX_SAFE_INT}]; encode it as a decimal string"
            )
        out.append(str(value))
    elif isinstance(value, float):
        raise CanonicalError(
            f"fractional JSON numbers are not permitted ({value!r}); a decimal "
            f"measurement is a string, so it survives every language's parser"
        )
    elif isinstance(value, str):
        out.append(_escape(value))
    elif isinstance(value, (list, tuple)):
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            _encode(item, out, depth + 1)
        out.append("]")
    elif isinstance(value, dict):
        keys = list(value)
        for key in keys:
            if not isinstance(key, str):
                raise CanonicalError(f"object keys must be strings, got {type(key).__name__}")
        out.append("{")
        # Unicode scalar value order, which is what Python's str comparison
        # gives, and what a reader in another language gets by sorting the
        # decoded code points rather than the UTF-8 bytes.
        for i, key in enumerate(sorted(keys)):
            if i:
                out.append(",")
            out.append(_escape(key))
            out.append(":")
            _encode(value[key], out, depth + 1)
        out.append("}")
    elif isinstance(value, Decimal):
        raise CanonicalError(
            "encode a Decimal with canonical_decimal() first; the protocol "
            "carries decimals as strings so their precision is explicit"
        )
    else:
        raise CanonicalError(f"{type(value).__name__} has no canonical encoding")


MAX_DEPTH = 64


def canonical_text(value: Any) -> str:
    out: list = []
    _encode(value, out)
    return "".join(out)


def canonical_bytes(value: Any) -> bytes:
    return canonical_text(value).encode("utf-8")


def digest(value: Any) -> str:
    """`sha256:` and 64 lowercase hex characters, over the canonical bytes."""
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def is_digest(text: Any) -> bool:
    return isinstance(text, str) and bool(_DIGEST_RE.match(text))


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------


def _no_duplicates(pairs):
    seen = {}
    for key, val in pairs:
        if key in seen:
            raise CanonicalError(
                f"duplicate object key {key!r}; which one wins is a reader's "
                f"choice, so the document has no single meaning"
            )
        seen[key] = val
    return seen


def _reject_float(text: str):
    raise CanonicalError(
        f"fractional JSON number {text!r}; the protocol carries decimals as "
        f"strings so that reading and re-encoding cannot change the value"
    )


def loads(text: "str | bytes") -> Any:
    """Read canonical or pretty-printed protocol JSON, strictly.

    Accepts whitespace, so a human-formatted file canonicalizes to the same
    digest, and refuses everything the encoding does not define.
    """
    if isinstance(text, bytes):
        if text.startswith(b"\xef\xbb\xbf"):
            raise CanonicalError("byte order mark; input must be UTF-8 without a BOM")
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CanonicalError(f"input is not valid UTF-8: {exc}") from None
    elif text.startswith("﻿"):
        raise CanonicalError("byte order mark; input must be UTF-8 without a BOM")
    try:
        value = json.loads(
            text, object_pairs_hook=_no_duplicates, parse_float=_reject_float,
            parse_constant=lambda c: (_ for _ in ()).throw(
                CanonicalError(f"{c} is not a JSON value the protocol permits")),
        )
    except CanonicalError:
        raise
    except ValueError as exc:
        raise CanonicalError(f"not readable as JSON: {exc}") from None
    _check_parsed(value, 0)
    return value


def _check_parsed(value: Any, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise CanonicalError(f"nesting deeper than {MAX_DEPTH} levels")
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int):
        if not MIN_SAFE_INT <= value <= MAX_SAFE_INT:
            raise NumericLimitExceeded(
                f"{value} is outside the exactly representable integer range"
            )
    elif isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise CanonicalError("string contains an unpaired surrogate") from None
    elif isinstance(value, list):
        for item in value:
            _check_parsed(item, depth + 1)
    elif isinstance(value, dict):
        for key, item in value.items():
            try:
                key.encode("utf-8")
            except UnicodeEncodeError:
                raise CanonicalError("object key contains an unpaired surrogate") from None
            _check_parsed(item, depth + 1)


# --------------------------------------------------------------------------
# decimals and rationals
# --------------------------------------------------------------------------


def canonical_decimal(source: Any) -> str:
    """The canonical decimal string for a measurement.

    No exponent, no leading plus, no unnecessary leading zeros, no trailing
    fractional zeros, no negative zero. `0.125` stays `0.125` rather than
    becoming a binary approximation of it.
    """
    if isinstance(source, bool):
        raise CanonicalError("a boolean is not a measurement")
    if isinstance(source, float):
        raise CanonicalError(
            f"{source!r} is a binary float; a decimal measurement must come from "
            f"its source text, and a float that has already lost precision "
            f"cannot get it back. Record the precision origin instead."
        )
    text = str(source).strip() if not isinstance(source, Decimal) else str(source)
    if not text:
        raise CanonicalError("empty decimal")
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        raise CanonicalError(f"{text!r} is not a decimal number") from None
    if parsed.is_nan() or parsed.is_infinite():
        raise CanonicalError(f"{text!r} is not a finite decimal")

    sign, digits, exponent = parsed.as_tuple()
    if len(digits) > MAX_SIGNIFICANT_DIGITS:
        raise NumericLimitExceeded(
            f"{len(digits)} significant digits exceeds the limit of "
            f"{MAX_SIGNIFICANT_DIGITS}"
        )
    adjusted = parsed.adjusted()
    if parsed != 0 and abs(adjusted) > MAX_ABS_EXPONENT:
        raise NumericLimitExceeded(
            f"base-10 exponent {adjusted} exceeds the limit of {MAX_ABS_EXPONENT}"
        )

    normalized = parsed.normalize()
    # normalize() turns 100 into 1E+2; expand it back out.
    if normalized == normalized.to_integral_value():
        expanded = normalized.quantize(Decimal(1)) if abs(normalized.as_tuple().exponent) < 30 \
            else Decimal(format(normalized, "f"))
        out = format(expanded, "f")
    else:
        out = format(normalized, "f")
    if out.startswith("-0") and Decimal(out) == 0:
        out = "0"
    if "." in out:
        out = out.rstrip("0").rstrip(".")
    if out in ("", "-"):
        out = "0"
    if len(out) > MAX_CANONICAL_DECIMAL_CHARS:
        raise NumericLimitExceeded(
            f"the expanded decimal is {len(out)} characters, over the "
            f"{MAX_CANONICAL_DECIMAL_CHARS} limit"
        )
    if not _DECIMAL_RE.match(out):  # pragma: no cover - belt and braces
        raise CanonicalError(f"{out!r} is not canonical")
    return out


def rational(numerator: Any, denominator: Any) -> dict:
    """A computed effect, exactly, reduced, with a positive denominator.

    Effects are ratios of measurements, and a ratio rounded for display must
    never be the thing a policy decided on.
    """
    from math import gcd

    num = int(Decimal(canonical_decimal(numerator)))
    den = int(Decimal(canonical_decimal(denominator)))
    if den == 0:
        raise CanonicalError("a rational with a zero denominator is not a number")
    if den < 0:
        num, den = -num, -den
    common = gcd(abs(num), den) or 1
    return {"numerator": str(num // common), "denominator": str(den // common)}

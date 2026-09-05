"""Normalisation used for grouping.

A comparator turns a raw captured value into a canonical key. Runs are grouped
by that key; the value shown to the user is always the raw one.

The point is to avoid crying wolf. "-O3 -march=native" and "-march=native -O3"
are the same build, and a tool that flags them as different trains its user to
stop reading the output. But a false negative is far worse than a false
positive here, so normalisation is deliberately conservative -- see
`flagset` below.
"""

from __future__ import annotations

import posixpath
import re
from typing import Any, Callable, Hashable

# Flags where a later occurrence overrides an earlier one. If any of these
# appears more than once, token order is load-bearing and must NOT be sorted:
# "-O2 -O3" means -O3 while "-O3 -O2" means -O2, yet both sort to the same
# multiset. Sorting those would report two genuinely different builds as
# identical, which is the exact failure this tool exists to prevent.
_OVERRIDE_FAMILIES = (
    re.compile(r"^-O.*$"),
    re.compile(r"^-march=.*$"),
    re.compile(r"^-mtune=.*$"),
    re.compile(r"^-std=.*$"),
    re.compile(r"^-g\d*$"),
    re.compile(r"^-fopenmp.*$"),
)


def _family_of(token: str) -> str | None:
    for pattern in _OVERRIDE_FAMILIES:
        if pattern.match(token):
            return pattern.pattern
    return None


def scalar(v: Any) -> Hashable:
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return tuple(str(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted((str(k), str(x)) for k, x in v.items()))
    return str(v)


def tokens(v: Any) -> Hashable:
    """Ordered token comparison. The conservative default for anything that
    is a command line or a flag string.

    Order is meaning. `-n 2 -N 4` and `-n 4 -N 2` are different jobs, `-I a
    -I b` and `-I b -I a` are different search paths, and `-D X=1 -D X=2`
    resolves differently each way. `flagset` sorted these into equality,
    which is the one error this tool must never make: a difference reported
    as a match. Whitespace in a flag *string* is normalised because it never
    carried meaning; a list is compared exactly as its tokens stand, because
    those boundaries came from argv and are evidence.
    """
    if v is None:
        return None
    if isinstance(v, str):
        return ("tokens",) + tuple(v.split())
    if isinstance(v, (list, tuple)):
        return ("tokens",) + tuple(str(x) for x in v)
    return ("tokens", str(v))


def flagset(v: Any) -> Hashable:
    """Legacy order-insensitive flag comparison. Not for new policy.

    Retained only so records and configurations written against it can still
    be read under an explicitly chosen legacy comparator. It reports two
    different command lines as one whenever their tokens are a permutation,
    which is why `tokens` replaced it as the default. See design F02.
    """
    if v is None:
        return None
    tokens = v.split() if isinstance(v, str) else [str(x) for x in v]
    counts: dict[str, int] = {}
    for token in tokens:
        family = _family_of(token)
        if family:
            counts[family] = counts.get(family, 0) + 1
    if any(n > 1 for n in counts.values()):
        return ("ordered",) + tuple(tokens)
    return ("set",) + tuple(sorted(tokens))


def version(v: Any) -> Hashable:
    """Compare version strings numerically where possible, so 12.3 == 12.3.0."""
    if v is None:
        return None
    text = str(v).strip()
    match = re.search(r"\d+(?:\.\d+)*", text)
    if not match:
        return text
    parts = [int(p) for p in match.group(0).split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    rest = (text[: match.start()] + text[match.end() :]).strip()
    return (rest, tuple(parts))


def path(v: Any) -> Hashable:
    if v is None:
        return None
    return posixpath.normpath(str(v)).rstrip("/")


def as_set(v: Any) -> Hashable:
    if v is None:
        return None
    items = v if isinstance(v, (list, tuple)) else [v]
    return tuple(sorted(str(x) for x in items))


COMPARATORS: dict[str, Callable[[Any], Hashable]] = {
    "scalar": scalar,
    "tokens": tokens,
    # Legacy, kept readable but never a default. See `flagset` above.
    "flagset": flagset,
    "version": version,
    "path": path,
    "set": as_set,
}


def get(name: str) -> Callable[[Any], Hashable]:
    try:
        return COMPARATORS[name]
    except KeyError:
        raise ValueError(
            f"unknown comparator {name!r}; expected one of "
            f"{', '.join(sorted(COMPARATORS))}"
        ) from None

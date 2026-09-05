"""Metric extraction from benchmark output.

Metrics are the dependent variable: they are what you are measuring, so they
are *supposed* to differ between runs. They are therefore held outside the
comparable body entirely and are never gated. Compare displays them next to the
validity verdict, which is the only place the two questions meet -- "what were
the numbers" and "were they comparable".

A pattern that does not match records UNKNOWN. It never records a zero, never
records the last number it happened to see, and never omits the metric so that
its absence goes unnoticed.
"""

from __future__ import annotations

import re

from .model import Field, unknown, value


def extract(text: str, patterns: dict[str, str]) -> dict[str, Field]:
    out: dict[str, Field] = {}
    for name, pattern in patterns.items():
        provenance = f"regex /{pattern}/"
        try:
            compiled = re.compile(pattern, re.M)
        except re.error as exc:
            out[name] = unknown(f"invalid pattern: {exc}", provenance=provenance)
            continue
        if compiled.groups < 1:
            out[name] = unknown(
                "pattern has no capture group; wrap the number in parentheses",
                provenance=provenance,
            )
            continue
        found = [m.group(1) for m in compiled.finditer(text)]
        if not found:
            out[name] = unknown(
                "pattern did not match the run output", provenance=provenance
            )
            continue
        parsed = [_number(x) for x in found]
        bad = [raw for raw, p in zip(found, parsed) if _rejects(p)]
        if bad:
            out[name] = unknown(
                f"the pattern matched values that are not measurements: {', '.join(bad[:3])}",
                provenance=provenance,
            )
            continue
        out[name] = value(
            parsed[0] if len(parsed) == 1 else parsed, provenance=provenance
        )
    return out


def _rejects(v) -> bool:
    """A parsed sample that must not be recorded as a measurement."""
    from .stats import unusable

    return unusable(v) is not None


def _number(raw: str):
    try:
        return float(raw) if any(c in raw for c in ".eE") else int(raw)
    except ValueError:
        return raw


def parse_cli_metrics(items: list[str]) -> dict[str, str]:
    """Parse --metric NAME=REGEX."""
    out: dict[str, str] = {}
    for item in items:
        name, sep, pattern = item.partition("=")
        if not sep or not name.strip() or not pattern:
            raise ValueError(
                f"--metric {item!r} must look like NAME=REGEX, "
                "e.g. --metric 'bandwidth=Bandwidth:\\s+([0-9.]+)'"
            )
        out[name.strip()] = pattern
    return out

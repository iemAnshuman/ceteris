"""The statistical half of validity.

A comparison is valid iff (a) only declared things differ and (b) the
difference exceeds the noise floor. compare.py owns (a). This owns (b), with
deliberately modest tools: median and spread, no distributional assumptions,
no third-party dependency. It answers one question -- is the gap between
configurations bigger than the scatter within them -- and says "unassessed"
rather than guessing when there are too few repeats to know.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median
from typing import Sequence

from . import comparators
from .config import GATING_SEVERITIES, Config
from .model import Fingerprint, State

MIN_REPEATS = 3


def unusable(v) -> str | None:
    """Why this value cannot enter a statistic, or None if it can.

    A NaN propagates through min, median and max and comes out the far side
    as a comparison that satisfied `--require-signal`, because every
    comparison against NaN is false. A bool is an int to Python and a
    category to everyone else. Neither is a measurement.
    """
    if isinstance(v, bool):
        return "boolean, not a measurement"
    if not isinstance(v, (int, float)):
        return f"not a number ({type(v).__name__})"
    if math.isnan(v):
        return "NaN"
    if math.isinf(v):
        return "infinite"
    return None


def config_key(fp: Fingerprint, cfg: Config) -> str:
    """Identity of a configuration: a hash over the gating fields only, each
    reduced to the canonical value compare groups on.

    The record's content hash covers every field, including informational
    ones like the load average that differ between any two moments. Grouping
    on that would make every repeat its own configuration. Hashing the
    serialised field was still too strict: it carried the provenance and the
    raw token order, so the same flags given as `--cxx-flags` on one run and
    `$CXXFLAGS` on the next, or written in another order, compared as a match
    in the report and yet split into two configurations in the table, with
    a noise floor computed between them.
    """
    import hashlib
    import json

    body = []
    for path in sorted(fp.fields):
        if cfg.severity_of(path) not in GATING_SEVERITIES:
            continue
        f = fp.fields[path]
        if f.state is State.VALUE:
            body.append((path, "v", comparators.get(cfg.comparator_of(path))(f.value)))
        else:
            body.append((path, f.state.value))
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


@dataclass
class ConfigGroup:
    """Records whose comparable bodies are identical: one configuration."""

    content_hash: str
    label: str
    members: list[Fingerprint] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.members)

    def samples(self, metric: str) -> list[float]:
        out = []
        for fp in self.members:
            f = fp.metrics.get(metric)
            if f is not None and f.state is State.VALUE and unusable(f.value) is None:
                out.append(float(f.value))
        return out

    def rejected(self, metric: str) -> list[str]:
        """Values present but unusable, with the reason for each."""
        out = []
        for fp in self.members:
            f = fp.metrics.get(metric)
            if f is None or f.state is not State.VALUE:
                continue
            why = unusable(f.value)
            if why is not None and not isinstance(f.value, list):
                out.append(f"{fp.label}: {why}")
        return out


@dataclass
class MetricStats:
    metric: str
    label: str
    n: int
    lo: float
    med: float
    hi: float

    @property
    def spread(self) -> float:
        """(max - min) / median. Zero median is reported as infinite spread."""
        return (self.hi - self.lo) / self.med if self.med else float("inf")


@dataclass
class NoiseVerdict:
    metric: str
    gap: float | None          # (max median - min median) / min median
    noise: float | None        # largest within-config spread
    assessed: bool
    within_noise: bool
    reason: str


def group_configs(fingerprints: Sequence[Fingerprint], cfg: Config | None = None) -> list[ConfigGroup]:
    cfg = cfg or Config.load()
    groups: dict[str, ConfigGroup] = {}
    for fp in fingerprints:
        h = config_key(fp, cfg)
        if h not in groups:
            groups[h] = ConfigGroup(content_hash=h, label=fp.label)
        groups[h].members.append(fp)
    # Runs labelled differently that turn out to be one configuration (a
    # "before" and an "after" with the binary never rebuilt) fold together;
    # the table should say so rather than show one label and hide the other.
    for g in groups.values():
        labels = list(dict.fromkeys(fp.label for fp in g.members))
        g.label = ", ".join(labels)
    return list(groups.values())


def metric_names(groups: Sequence[ConfigGroup]) -> list[str]:
    names: list[str] = []
    for g in groups:
        for fp in g.members:
            for name in sorted(fp.metrics):
                if name not in names:
                    names.append(name)
    return names


def stats_for(group: ConfigGroup, metric: str) -> MetricStats | None:
    xs = group.samples(metric)
    if not xs:
        return None
    return MetricStats(metric, group.label, len(xs), min(xs), median(xs), max(xs))


def noise_verdict(groups: Sequence[ConfigGroup], metric: str) -> NoiseVerdict:
    counts = {
        len(f.value)
        for g in groups
        for f in (fp.metrics.get(metric) for fp in g.members)
        if f is not None and f.state is State.VALUE and isinstance(f.value, list)
    }
    if counts:
        # A pattern that matched several lines. Which of them is the result
        # is not something to guess at; it used to be reported as "no value".
        n = ", ".join(str(c) for c in sorted(counts))
        return NoiseVerdict(metric, None, None, False, False,
                            f"multi-valued: the pattern matched {n} times per run; "
                            "use a pattern that matches once, or a harness adapter")
    bad = [why for g in groups for why in g.rejected(metric)]
    if bad:
        # Present, and not a measurement. Silently dropping these would let
        # the remaining samples answer a question about a different dataset.
        shown = "; ".join(bad[:3]) + (f"; and {len(bad) - 3} more" if len(bad) > 3 else "")
        return NoiseVerdict(metric, None, None, False, False,
                            f"unusable measurements were recorded for this metric ({shown})")
    per = [s for s in (stats_for(g, metric) for g in groups) if s is not None]
    if not per:
        # Every sample was unknown: the pattern did not match, or the harness
        # produced nothing. Saying "fewer than two configurations" here hid
        # the fact that the number was never extracted at all.
        return NoiseVerdict(metric, None, None, False, False,
                            "no configuration produced a value for this metric")
    if len(per) < 2:
        return NoiseVerdict(metric, None, None, False, False, "fewer than two configurations carry this metric")
    thin = [s.label for s in per if s.n < MIN_REPEATS]
    if thin:
        return NoiseVerdict(
            metric, None, None, False, False,
            f"noise floor unassessed: fewer than {MIN_REPEATS} repeats for {', '.join(thin)}",
        )
    non_positive = [s.label for s in per if s.lo <= 0]
    if non_positive:
        # gap and spread are relative, so a zero or negative sample makes the
        # denominator meaningless rather than merely large.
        return NoiseVerdict(
            metric, None, None, False, False,
            "the relative-noise method needs strictly positive samples; "
            f"{', '.join(sorted(set(non_positive)))} recorded zero or negative values",
        )
    meds = [s.med for s in per]
    lo, hi = min(meds), max(meds)
    gap = (hi - lo) / lo if lo else float("inf")
    noise = max(s.spread for s in per)
    within = gap <= noise
    reason = (
        f"gap {gap:.0%} between configuration medians is not larger than the "
        f"{noise:.0%} spread within a single configuration"
        if within else
        f"gap {gap:.0%} exceeds the largest within-configuration spread of {noise:.0%}"
    )
    return NoiseVerdict(metric, gap, noise, True, within, reason)

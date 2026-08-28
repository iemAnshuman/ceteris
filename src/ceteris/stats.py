"""The statistical half of validity.

A comparison is valid iff (a) only declared things differ and (b) the
difference exceeds the noise floor. compare.py owns (a). This owns (b), with
deliberately modest tools: median and spread, no distributional assumptions,
no third-party dependency. It answers one question -- is the gap between
configurations bigger than the scatter within them -- and says "unassessed"
rather than guessing when there are too few repeats to know.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Sequence

from .config import GATING_SEVERITIES, Config
from .model import Fingerprint, State

MIN_REPEATS = 3


def config_key(fp: Fingerprint, cfg: Config) -> str:
    """Identity of a configuration: a hash over the gating fields only.

    The record's content hash covers every field, including informational
    ones like the load average that differ between any two moments. Grouping
    on that would make every repeat its own configuration.
    """
    import hashlib
    import json

    body = {k: fp.fields[k].to_json() for k in sorted(fp.fields) if cfg.severity_of(k) in GATING_SEVERITIES}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


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
            if f is not None and f.state is State.VALUE and isinstance(f.value, (int, float)):
                out.append(float(f.value))
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

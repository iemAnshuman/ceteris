"""The comparison engine.

The whole tool reduces to one set operation:

    actually_varying \\ declared_varying == empty ?

Everything here is the edge cases around that line, and the edge cases are the
product.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Hashable, Iterable, Sequence

from . import comparators, stats
from .config import GATING_SEVERITIES, Config
from .model import Fingerprint, State

EXIT_OK = 0
EXIT_UNDECLARED = 1
EXIT_INDETERMINATE = 2
EXIT_USAGE = 3
EXIT_WITHIN_NOISE = 4
# Digest, bundle membership, or receipt semantic integrity mismatch.
EXIT_INTEGRITY = 5


class Verdict(str, Enum):
    MATCH = "match"
    DIFFER = "differ"
    INDETERMINATE = "indeterminate"


class Classification(str, Enum):
    MATCHED = "matched"
    DECLARED = "declared"
    WAIVED = "waived"
    VIOLATION = "violation"
    INFORMATIONAL = "informational"
    INDETERMINATE = "indeterminate"


ABSENT = "<not applicable>"


def matches(path: str, pattern: str) -> bool:
    """Exact, glob, or prefix match.

    Prefix matching means `--vary build` covers every build.* field, which is
    what people actually mean when they type it.
    """
    if path == pattern:
        return True
    if any(ch in pattern for ch in "*?["):
        return fnmatch.fnmatchcase(path, pattern)
    return path.startswith(pattern + ".")


def _matches_any(path: str, patterns: Iterable[str]) -> str | None:
    for pattern in patterns:
        if matches(path, pattern):
            return pattern
    return None


@dataclass
class Group:
    key: Hashable
    display: str
    labels: list[str] = field(default_factory=list)
    raw_variants: list[str] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)   # positions in the compared sequence


@dataclass
class FieldResult:
    path: str
    verdict: Verdict
    classification: Classification
    severity: str
    groups: list[Group] = field(default_factory=list)
    note: str | None = None
    reason: str | None = None
    matched_pattern: str | None = None
    indeterminate: list[tuple[str, str]] = field(default_factory=list)

    @property
    def is_gating(self) -> bool:
        return self.classification in (
            Classification.VIOLATION,
            Classification.INDETERMINATE,
        )


@dataclass
class Confound:
    """An undeclared field whose value is a function of a declared one.

    Three transports across two commits, with the commit constant inside each
    transport group, is the textbook case: whatever the transport result is,
    it is inseparable from the commit. Detectable from the partition of runs
    each field induces, and reported as its own thing because the fix is
    different from an ordinary violation -- re-run, do not waive.
    """

    undeclared: str
    declared: str
    table: list[tuple[str, str, int]]   # (declared value, undeclared value, count)


@dataclass
class Report:
    labels: list[str]
    declared: list[str]
    waived: dict[str, str]
    strict: bool
    results: list[FieldResult]
    # The runs themselves, so the report can show the measurements alongside
    # the verdict. Seeing "these are the numbers" and "here is why you may not
    # compare them" in one place is the entire point.
    sources: list[Fingerprint] = field(default_factory=list)
    # Warnings about the declarations themselves rather than about any one
    # field. Reported per pattern: "--vary build" that covers thirty constant
    # CMake entries and three that differ has done its job, and listing all
    # thirty as suspicious would bury the three.
    constant_declarations: list[str] = field(default_factory=list)
    unmatched_declarations: list[str] = field(default_factory=list)
    # Statistical half of validity: records grouped into configurations by
    # content hash, and a noise verdict per metric.
    configs: list[stats.ConfigGroup] = field(default_factory=list)
    noise: list[stats.NoiseVerdict] = field(default_factory=list)
    require_signal: bool = False
    warnings: list[str] = field(default_factory=list)
    confounds: list[Confound] = field(default_factory=list)
    # Identity of the severity and comparator maps this ran under. They decide
    # which fields gate, so a verdict is only meaningful together with them.
    config_digest: str = ""

    def by_class(self, *classes: Classification) -> list[FieldResult]:
        wanted = set(classes)
        return [r for r in self.results if r.classification in wanted]

    @property
    def violations(self) -> list[FieldResult]:
        return self.by_class(Classification.VIOLATION)

    @property
    def indeterminates(self) -> list[FieldResult]:
        return self.by_class(Classification.INDETERMINATE)

    @property
    def matched_count(self) -> int:
        return len(self.by_class(Classification.MATCHED))

    @property
    def exit_code(self) -> int:
        if self.violations:
            return EXIT_UNDECLARED
        if self.indeterminates:
            return EXIT_INDETERMINATE
        if self.failed_runs or self.drifted:
            return EXIT_INDETERMINATE
        if self.strict and (self.constant_declarations or self.unmatched_declarations):
            return EXIT_UNDECLARED
        # No metric at all is the strongest form of "nothing beat the noise
        # floor"; it used to pass because the noise list was empty.
        if self.require_signal and not any(v.assessed and not v.within_noise for v in self.noise):
            return EXIT_WITHIN_NOISE
        return EXIT_OK

    @property
    def failed_runs(self) -> list[Fingerprint]:
        """Runs whose wrapped command exited non-zero.

        A benchmark that crashed produced no measurement, so nothing about it
        can be certified. The exit code lives outside the comparable body, so
        without this check a set of runs that all failed identically compared
        as agreeing and was reported valid.
        """
        out = []
        for f in self.sources:
            code = f.run.get("exit_code")
            if isinstance(code, int) and code != 0:
                out.append(f)
        return out

    @property
    def drifted(self) -> list[Fingerprint]:
        """Runs whose environment changed while they were running. Such a run
        has no single well-defined identity, so it cannot be certified."""
        return [f for f in self.sources if f.drift]


def _render_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(x) for x in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in sorted(value.items()))
    return str(value)


def _analyse_field(
    path: str,
    fingerprints: Sequence[Fingerprint],
    cfg: Config,
) -> tuple[Verdict, list[Group], list[tuple[str, str]], str | None]:
    comparator = comparators.get(cfg.comparator_of(path))
    grouped: dict[Hashable, Group] = {}
    indeterminate: list[tuple[str, str]] = []

    for idx, fp in enumerate(fingerprints):
        label = fp.label
        f = fp.fields.get(path)
        if f is None:
            indeterminate.append(
                (label, "field absent from this fingerprint (schema mismatch?)")
            )
            continue
        if f.is_indeterminate:
            reason = f.detail or f.state.value
            indeterminate.append((label, f"{f.state.value}: {reason}"))
            continue
        if f.state is State.NOT_APPLICABLE:
            key: Hashable = ("na",)
            display = ABSENT
            raw = ABSENT
        else:
            key = ("v", comparator(f.value))
            display = _render_value(f.value)
            raw = display
        group = grouped.get(key)
        if group is None:
            group = Group(key=key, display=display)
            grouped[key] = group
        group.labels.append(label)
        group.indices.append(idx)
        if raw not in group.raw_variants:
            group.raw_variants.append(raw)

    if indeterminate:
        return Verdict.INDETERMINATE, list(grouped.values()), indeterminate, None

    groups = list(grouped.values())
    note = None
    if len(groups) == 1 and len(groups[0].raw_variants) > 1:
        note = "same set, different order: " + " | ".join(groups[0].raw_variants)
    verdict = Verdict.MATCH if len(groups) <= 1 else Verdict.DIFFER
    return verdict, groups, [], note


class DuplicateObservation(ValueError):
    """The same execution offered more than once.

    Copying a record, naming it twice, or passing one object three times
    used to produce three samples, a zero spread, and a signal. Invariant 5:
    an execution contributes at most once to a given analysis, and
    relabelling or copying its file does not create a new execution.
    """

    code = "duplicate_observation"


def observation_digest(fp: Fingerprint) -> str:
    """Identity of an observation, for duplicate detection only.

    Everything the producer wrote, minus where the file happens to sit. Two
    genuine repeats differ in `captured_at` and in their measurements; a
    copy is identical in every byte.
    """
    import hashlib
    import json

    body = fp.to_json()
    meta = {k: v for k, v in body.get("meta", {}).items() if k != "source_file"}
    payload = {**body, "meta": meta}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _reject_duplicates(fingerprints: Sequence[Fingerprint]) -> None:
    seen: dict[str, str] = {}
    for fp in fingerprints:
        digest = observation_digest(fp)
        first = seen.get(digest)
        if first is not None:
            where = fp.meta.get("source_file")
            raise DuplicateObservation(
                f"the same observation appears more than once ({first!r} and "
                f"{fp.label!r}"
                + (f", {where}" if where else "")
                + "). Copying a record or naming it twice does not make a "
                "second measurement; record another run instead. If these "
                "really are separate executions, recapture them so each "
                "carries its own timestamp."
            )
        seen[digest] = fp.label


def compare(
    fingerprints: Sequence[Fingerprint],
    vary: Sequence[str] = (),
    waive: dict[str, str] | None = None,
    cfg: Config | None = None,
    strict: bool = False,
    require_signal: bool = False,
) -> Report:
    if len(fingerprints) < 2:
        raise ValueError("compare needs at least two fingerprints")
    _reject_duplicates(fingerprints)
    cfg = cfg or Config.load()
    waive = dict(waive or {})
    vary = list(vary)

    paths: set[str] = set()
    for fp in fingerprints:
        paths.update(fp.fields)

    results: list[FieldResult] = []
    for path in sorted(paths):
        severity = cfg.severity_of(path)
        verdict, groups, indeterminate, note = _analyse_field(path, fingerprints, cfg)
        declared_pattern = _matches_any(path, vary)
        waived_pattern = _matches_any(path, waive)

        if verdict is Verdict.INDETERMINATE:
            # A declared-varying field is still allowed to be unreadable only if
            # it was explicitly waived; otherwise unknown means the comparison
            # cannot be certified, which is the entire point of the tool.
            if waived_pattern is not None:
                classification = Classification.WAIVED
            else:
                classification = Classification.INDETERMINATE
        elif verdict is Verdict.MATCH:
            classification = Classification.MATCHED
        elif declared_pattern is not None:
            classification = Classification.DECLARED
        elif waived_pattern is not None:
            classification = Classification.WAIVED
        elif severity in GATING_SEVERITIES or strict:
            classification = Classification.VIOLATION
        else:
            classification = Classification.INFORMATIONAL

        results.append(
            FieldResult(
                path=path,
                verdict=verdict,
                classification=classification,
                severity=severity,
                groups=groups,
                note=note,
                reason=waive.get(waived_pattern) if waived_pattern else None,
                matched_pattern=declared_pattern or waived_pattern,
                indeterminate=indeterminate,
            )
        )

    # A declaration that matched nothing is almost always a typo, and a
    # declaration under which nothing varied usually means the sweep script
    # never applied the setting. Neither is visible any other way.
    constant, unmatched = [], []
    for pattern in vary:
        covered = [r for r in results if matches(r.path, pattern)]
        if not covered:
            unmatched.append(pattern)
        elif all(r.verdict is Verdict.MATCH for r in covered):
            constant.append(pattern)

    confounds = _confounds(results)
    configs = stats.group_configs(fingerprints, cfg)
    noise = [stats.noise_verdict(configs, m) for m in stats.metric_names(configs)]
    warnings = []
    versions = sorted({fp.schema_version for fp in fingerprints})
    if len(versions) > 1:
        warnings.append(
            f"records use schema versions {versions}; fields added in a newer "
            "version are unknown on the older side and are reported as such"
        )

    return Report(
        labels=[fp.label for fp in fingerprints],
        declared=vary,
        waived=waive,
        strict=strict,
        results=results,
        sources=list(fingerprints),
        constant_declarations=constant,
        unmatched_declarations=unmatched,
        configs=configs,
        noise=noise,
        require_signal=require_signal,
        warnings=warnings,
        confounds=confounds,
        config_digest=_config_digest(cfg),
    )


def _config_digest(cfg: Config) -> str:
    import hashlib
    import json

    payload = {
        "severity": sorted(cfg.severity.items()),
        "comparators": sorted(cfg.comparators.items()),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]


def _confounds(results: list[FieldResult]) -> list[Confound]:
    declared = [r for r in results if r.classification is Classification.DECLARED]
    violations = [r for r in results if r.classification is Classification.VIOLATION]
    found: list[Confound] = []
    for d in declared:
        d_of = {i: g.display for g in d.groups for i in g.indices}
        for u in violations:
            u_of = {i: g.display for g in u.groups for i in g.indices}
            labels = [i for i in d_of if i in u_of]
            if not labels:
                continue
            # u is a function of d: every d-group maps to exactly one u-value.
            mapping: dict[str, set[str]] = {}
            for l in labels:
                mapping.setdefault(d_of[l], set()).add(u_of[l])
            if all(len(v) == 1 for v in mapping.values()) and len({next(iter(v)) for v in mapping.values()}) > 1:
                counts: dict[tuple[str, str], int] = {}
                for l in labels:
                    counts[(d_of[l], u_of[l])] = counts.get((d_of[l], u_of[l]), 0) + 1
                found.append(Confound(u.path, d.path, sorted((a, b, n) for (a, b), n in counts.items())))
    return found

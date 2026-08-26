"""Configuration: shipped defaults plus an optional user file.

TOML is read with the stdlib tomllib (3.11+). JSON is also accepted so a
cluster stuck on an older interpreter can still configure the tool without the
package taking a third-party parser as a dependency.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # pragma: no cover - exercised by whichever interpreter runs the tests
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

DEFAULTS_PATH = Path(__file__).with_name("defaults.toml")

SEVERITIES = ("critical", "material", "informational")
DEFAULT_SEVERITY = "material"
GATING_SEVERITIES = ("critical", "material")


def _load_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    if tomllib is None:
        raise RuntimeError(
            f"cannot read {path}: this interpreter has no tomllib "
            "(Python < 3.11). Supply the config as .json instead."
        )
    return tomllib.loads(text)


@dataclass
class Config:
    env_allowlist: list[str] = field(default_factory=list)
    cmake_keys: list[str] = field(default_factory=list)
    severity: dict[str, str] = field(default_factory=dict)
    comparators: dict[str, str] = field(default_factory=dict)
    # name -> regex with one capture group, applied to `ceteris run` output.
    metrics: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, user_path: str | Path | None = None) -> "Config":
        raw = _load_file(DEFAULTS_PATH)
        cfg = cls(
            env_allowlist=list(raw.get("capture", {}).get("env_allowlist", [])),
            cmake_keys=list(raw.get("capture", {}).get("cmake_keys", [])),
            severity=dict(raw.get("severity", {})),
            comparators=dict(raw.get("comparators", {})),
            metrics=dict(raw.get("metrics", {})),
        )
        if user_path is not None:
            cfg.merge(_load_file(Path(user_path)))
        cfg.validate()
        return cfg

    def merge(self, raw: dict[str, Any]) -> None:
        capture = raw.get("capture", {})
        for name in ("env_allowlist", "cmake_keys"):
            extra = capture.get(name)
            if extra:
                current = getattr(self, name)
                seen = set(current)
                current.extend(x for x in extra if x not in seen and not seen.add(x))
        self.severity.update(raw.get("severity", {}))
        self.comparators.update(raw.get("comparators", {}))
        self.metrics.update(raw.get("metrics", {}))

    def validate(self) -> None:
        for pattern, sev in self.severity.items():
            if sev not in SEVERITIES:
                raise ValueError(
                    f"config: severity for {pattern!r} is {sev!r}, "
                    f"expected one of {', '.join(SEVERITIES)}"
                )

    def severity_of(self, path: str) -> str:
        """Longest matching glob wins, so 'hardware.hostname' beats 'hardware.*'."""
        best: tuple[int, str] | None = None
        for pattern, sev in self.severity.items():
            if fnmatch.fnmatchcase(path, pattern):
                score = len(pattern) - pattern.count("*") * 2
                if best is None or score > best[0]:
                    best = (score, sev)
        return best[1] if best else DEFAULT_SEVERITY

    def comparator_of(self, path: str) -> str:
        best: tuple[int, str] | None = None
        for pattern, name in self.comparators.items():
            if fnmatch.fnmatchcase(path, pattern):
                score = len(pattern) - pattern.count("*") * 2
                if best is None or score > best[0]:
                    best = (score, name)
        return best[1] if best else "scalar"

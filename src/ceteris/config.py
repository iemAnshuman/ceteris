"""Configuration: shipped defaults plus an optional user file.

The shipped defaults and packs are JSON, not TOML, so that starting the tool
needs nothing beyond the standard library on any supported interpreter. Many
clusters still ship Python 3.9 as the system interpreter -- Rostam does -- and
tomllib only arrived in 3.11. A user config may be either TOML or JSON; TOML
requires 3.11 and says so if it cannot be read.
"""

from __future__ import annotations

import fnmatch
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # pragma: no cover - exercised by whichever interpreter runs the tests
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

DEFAULTS_PATH = Path(__file__).with_name("defaults.json")

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
            f"(needs Python 3.11+, running {sys.version_info.major}."
            f"{sys.version_info.minor}). Write the config as JSON instead."
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
    # Packs from config: names to force on. Resolved packs live in active_packs.
    packs: list[str] = field(default_factory=list)
    active_packs: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, user_path: str | Path | None = None, packs: list[str] | None = None,
             tree: str | None = None) -> "Config":
        """Load defaults, then the project config.

        With no explicit path, ./ceteris.toml (or ./ceteris.json) is used if
        present, so a project's metric patterns and tuning variables apply
        without every command repeating --config.
        """
        if user_path is None:
            for candidate in ("ceteris.json", "ceteris.toml"):
                if Path(candidate).is_file():
                    user_path = candidate
                    break
        raw = _load_file(DEFAULTS_PATH)
        cfg = cls(
            env_allowlist=list(raw.get("capture", {}).get("env_allowlist", [])),
            cmake_keys=list(raw.get("capture", {}).get("cmake_keys", [])),
            severity=dict(raw.get("severity", {})),
            comparators=dict(raw.get("comparators", {})),
            metrics=dict(raw.get("metrics", {})),
            packs=list(raw.get("packs", [])),
        )
        if user_path is not None:
            cfg.merge(_load_file(Path(user_path)))
        cfg.validate()
        cfg.activate_packs(list(cfg.packs) + list(packs or []), tree)
        return cfg

    def activate_packs(self, forced: list[str], tree: str | None) -> None:
        """Merge every applicable ecosystem pack into the capture lists."""
        from . import packs as packs_mod

        tree = str(Path(tree or ".").expanduser())
        self.active_packs = packs_mod.select(tree, forced)
        for _name, (pack, _why) in sorted(self.active_packs.items()):
            self.merge({"capture": pack.get("capture", {})})

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
        for name in raw.get("packs", []):
            if name not in self.packs:
                self.packs.append(name)

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

"""Ecosystem packs: per-runtime tuning variables, toolchain versions and
lockfiles. Activated by what is on PATH and what is in the tree, so a Rust
project gets RUSTFLAGS and Cargo.lock without configuration, and an HPC job
gets LCI and UCX without dragging those into a Node project."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

PACK_DIR = Path(__file__).parent
_which = shutil.which  # patched in tests


def available() -> dict[str, dict[str, Any]]:
    packs = {}
    for path in sorted(PACK_DIR.glob("*.toml")):
        if tomllib is None:  # pragma: no cover
            break
        packs[path.stem] = tomllib.loads(path.read_text(encoding="utf-8"))
    return packs


def activates(pack: dict[str, Any], tree: str) -> str | None:
    """Reason the pack activates, or None."""
    act = pack.get("activate", {})
    for tool in act.get("path_tools", []):
        if _which(tool):
            return f"{tool} on PATH"
    for marker in act.get("tree_markers", []):
        if os.path.exists(os.path.join(tree, marker)):
            return f"{marker} in tree"
    for var in act.get("env_any", []):
        if var in os.environ:
            return f"${var} set"
    return None


def select(tree: str, forced: list[str] | None = None) -> dict[str, tuple[dict[str, Any], str]]:
    """{name: (pack, reason)} for every pack that applies."""
    packs = available()
    chosen: dict[str, tuple[dict[str, Any], str]] = {}
    for name in forced or []:
        if name not in packs:
            raise ValueError(f"unknown pack {name!r}; available: {', '.join(sorted(packs))}")
        chosen[name] = (packs[name], "requested")
    for name, pack in packs.items():
        if name in chosen:
            continue
        why = activates(pack, tree)
        if why:
            chosen[name] = (pack, why)
    return chosen

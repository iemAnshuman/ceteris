"""The run store.

A campaign is forty runs, not two. Requiring the user to keep track of forty
JSON files and pass the right ones on the command line reintroduces exactly the
bookkeeping that this tool exists to remove, so runs go into a store by default
and compare can select from it.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .model import Fingerprint

DEFAULT_STORE = ".ceteris/runs"


def store_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("CETERIS_STORE")
    if env:
        return Path(env).expanduser()
    return Path(DEFAULT_STORE)


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "run"


def save(fingerprint: Fingerprint, store: Path) -> Path:
    store.mkdir(parents=True, exist_ok=True)
    stamp = str(fingerprint.meta.get("captured_at", "")).replace(":", "").replace("-", "")
    stamp = stamp.replace("+0000", "Z").replace("T", "-")[:16] or "run"
    path = store / f"{stamp}-{_slug(fingerprint.label)}.json"
    n = 1
    while path.exists():
        n += 1
        path = store / f"{stamp}-{_slug(fingerprint.label)}-{n}.json"
    path.write_text(fingerprint.dumps(), encoding="utf-8")
    return path


def load(path: str | Path) -> Fingerprint:
    fingerprint = Fingerprint.from_json(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )
    if not fingerprint.meta.get("label"):
        fingerprint.meta["label"] = Path(path).stem
    fingerprint.meta.setdefault("source_file", str(path))
    return fingerprint


def all_runs(store: Path) -> list[Path]:
    if not store.is_dir():
        return []
    return sorted(store.glob("*.json"))


def select(
    store: Path, last: int | None = None, labels: list[str] | None = None
) -> list[Path]:
    paths = all_runs(store)
    if labels:
        import fnmatch

        keep = []
        for path in paths:
            label = load(path).label
            if any(fnmatch.fnmatchcase(label, pattern) for pattern in labels):
                keep.append(path)
        paths = keep
    if last:
        paths = paths[-last:]
    return paths

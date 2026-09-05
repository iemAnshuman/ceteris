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


def ensure(store: Path) -> None:
    """Create the store and make it ignore itself.

    The default store lives inside the user's repository. Without this, the
    first run leaves the tree dirty, the second run captures source.dirty as
    True, and the user's very first comparison fails because of the tool that
    is supposed to be checking it. Writing a self-ignoring .gitignore into the
    store directory is what .pytest_cache and .mypy_cache do, and it avoids
    touching the user's own .gitignore.
    """
    store.mkdir(parents=True, exist_ok=True)
    # Only the default layout owns its parent. Any other store called
    # "runs" -- ~/campaigns/runs, say -- used to get the marker written into
    # ~/campaigns, ignoring everything the user kept there.
    if store.name == "runs" and store.parent.name == ".ceteris":
        marker = store.parent / ".gitignore"
    else:
        marker = store / ".gitignore"
    if not marker.exists():
        marker.write_text("# created by ceteris; the run store is not source\n*\n")


def save(fingerprint: Fingerprint, store: Path) -> Path:
    ensure(store)
    stamp = str(fingerprint.meta.get("captured_at", "")).replace(":", "").replace("-", "")
    stamp = stamp.replace("+0000", "Z").replace("T", "-")[:16] or "run"
    path = store / f"{stamp}-{_slug(fingerprint.label)}.json"
    n = 1
    while path.exists():
        n += 1
        path = store / f"{stamp}-{_slug(fingerprint.label)}-{n}.json"
    # Written whole or not at all: a crash between two repeats must not leave
    # a half-serialised record that later reads as a corrupt observation.
    tmp = path.with_name(path.name + ".partial")
    tmp.write_text(fingerprint.dumps(), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load(path: str | Path) -> Fingerprint:
    fingerprint = Fingerprint.from_json(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )
    if not fingerprint.meta.get("label"):
        fingerprint.meta["label"] = Path(path).stem
    fingerprint.meta.setdefault("source_file", str(path))
    return fingerprint


_NAME = re.compile(r"^(\d{8}-\d{6}Z)-(.*?)(?:-(\d+))?\.json$")


def _order(path: Path):
    """Chronological within a second too: `x-2.json` sorts after `x.json`,
    where plain string order put the dash before the dot."""
    m = _NAME.match(path.name)
    if not m:
        return ("", path.name, 0)
    return (m.group(1), m.group(2), int(m.group(3) or 1))


def all_runs(store: Path) -> list[Path]:
    if not store.is_dir():
        return []
    return sorted(store.glob("*.json"), key=_order)


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

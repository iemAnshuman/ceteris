"""Capture orchestration."""

from __future__ import annotations

import datetime as _dt
import platform

from .collectors import Context, run_all
from .config import Config
from .model import Fingerprint


def capture(
    repo: str | None = None,
    cmake_cache: str | None = None,
    compiler: str | None = None,
    cxx_flags: str | None = None,
    build_type: str | None = None,
    label: str | None = None,
    cfg: Config | None = None,
) -> Fingerprint:
    """Collect a fingerprint of the current environment.

    Returns a Fingerprint rather than writing a file so the same call is usable
    from a script, a test, or a future wrapper that captures either side of a
    job.
    """
    from . import __version__

    cfg = cfg or Config.load()
    ctx = Context(
        cfg=cfg,
        repo=repo,
        cmake_cache=cmake_cache,
        compiler=compiler,
        cxx_flags=cxx_flags,
        build_type=build_type,
    )
    fields = run_all(ctx)
    meta = {
        "label": label or platform.uname().node,
        # captured_at lives in meta and never in the comparable body, so two
        # captures of an identical environment produce an identical hash.
        "captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(
            timespec="seconds"
        ),
        "tool": "ceteris",
        "tool_version": __version__,
    }
    return Fingerprint(fields=fields, meta=meta)

"""Collector registry and isolated runner.

Each collector is a function taking a Context and returning {path: Field}.
Collectors are run in isolation: one that raises produces an ERROR marker for
its namespace instead of taking down the capture. That is the same fail-closed
principle applied one level down -- a broken collector must make the
comparison uncertifiable, never make it quietly narrower.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field as dc_field
from typing import Callable

from ..config import Config
from ..model import Field, error


@dataclass
class Context:
    cfg: Config
    repo: str | None = None
    cmake_cache: str | None = None
    compiler: str | None = None
    cxx_flags: str | None = None
    build_type: str | None = None
    extra: dict[str, str] = dc_field(default_factory=dict)


Collector = Callable[[Context], "dict[str, Field]"]


def registry() -> dict[str, Collector]:
    from . import build, hardware, parallelism, runtime, scheduler, source, system

    return {
        "source": source.collect,
        "build": build.collect,
        "runtime": runtime.collect,
        "parallelism": parallelism.collect,
        "hardware": hardware.collect,
        "scheduler": scheduler.collect,
        "system": system.collect,
    }


def run_all(ctx: Context) -> dict[str, Field]:
    fields: dict[str, Field] = {}
    for name, collector in registry().items():
        try:
            fields.update(collector(ctx))
        except Exception:  # noqa: BLE001 - a collector must never abort capture
            fields[f"{name}._collector"] = error(
                "collector raised: "
                + " ".join(traceback.format_exc(limit=1).split())[:300]
            )
    return fields

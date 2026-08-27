"""`ceteris run` -- wrap the benchmark itself.

This is the command that makes the tool solve the problem rather than describe
it. Capturing separately means remembering to capture, naming files
consistently, and pairing them with results by hand -- the same bookkeeping
whose failure produces the invalid comparisons in the first place. A tool you
have to remember to use fails the way the discipline it replaces failed.

Wrapping the run gets three things that a standalone capture cannot have:

1. The fingerprint is taken *in the job's own context*. Run inside an sbatch
   script, it sees the compute node, the allocation and the job environment,
   not the login node you happened to type the command on.
2. The launcher command line is recorded for real, so `mpirun -n 16
   --bind-to core` is captured rather than inferred. That is where binding
   intent actually lives.
3. The environment is captured before *and* after, so a change that happens
   mid-run -- a module swap, a rebuild into the same tree, a filesystem
   remount -- is detected instead of silently splitting the run in half.
"""

from __future__ import annotations

import datetime as _dt
import os
import subprocess
import sys
import time
from typing import Any

from . import execution
from .capture import capture
from .config import GATING_SEVERITIES, Config
from .metrics import extract
from .model import Field, Fingerprint, State, value

MAX_OUTPUT = 64 * 1024


def _display(field: Field) -> str:
    if field.state is State.VALUE:
        return str(field.value)
    return f"<{field.state.value}>"


def _drift(before: dict[str, Field], after: dict[str, Field], cfg: Config) -> list[dict[str, Any]]:
    """Fields that changed between the before and after captures.

    Only gating fields count. Load average and available memory move between
    any two moments; treating that as the environment changing would mark
    every run uncertifiable.
    """
    changed = []
    for path in sorted(set(before) | set(after)):
        if cfg.severity_of(path) not in GATING_SEVERITIES:
            continue
        old, new = before.get(path), after.get(path)
        if old is None or new is None or old != new:
            changed.append(
                {
                    "path": path,
                    "before": _display(old) if old else "<absent>",
                    "after": _display(new) if new else "<absent>",
                }
            )
    return changed


def run_command(
    command: list[str],
    label: str | None = None,
    cfg: Config | None = None,
    repo: str | None = None,
    cmake_cache: str | None = None,
    compiler: str | None = None,
    cxx_flags: str | None = None,
    build_type: str | None = None,
    metric_patterns: dict[str, str] | None = None,
    echo: bool = True,
    series: str | None = None,
    repeat: int | None = None,
) -> Fingerprint:
    """Capture, run the command, capture again, and assemble one record."""
    cfg = cfg or Config.load()
    kwargs = dict(
        repo=repo,
        cmake_cache=cmake_cache,
        compiler=compiler,
        cxx_flags=cxx_flags,
        build_type=build_type,
        cfg=cfg,
    )
    before = capture(label=label, **kwargs)

    started = _dt.datetime.now(_dt.timezone.utc)
    clock = time.monotonic()
    chunks: list[str] = []
    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except (OSError, ValueError) as exc:
        raise ValueError(f"could not launch {command[0]!r}: {exc}") from exc

    assert proc.stdout is not None
    for line in proc.stdout:
        chunks.append(line)
        if echo:
            sys.stdout.write(line)
            sys.stdout.flush()
    exit_code = proc.wait()
    duration = time.monotonic() - clock

    output = "".join(chunks)
    after = capture(label=label, **kwargs)

    fields = dict(before.fields)
    fields.update(execution.collect(command))

    truncated = len(output) > MAX_OUTPUT
    record: dict[str, Any] = {
        "exit_code": exit_code,
        "started_at": started.isoformat(timespec="seconds"),
        "duration_s": round(duration, 3),
        "output": output[-MAX_OUTPUT:],
        "output_truncated": truncated,
        "drift": _drift(before.fields, after.fields, cfg),
    }

    patterns = dict(getattr(cfg, "metrics", {}) or {})
    patterns.update(metric_patterns or {})
    metrics = extract(output, patterns) if patterns else {}

    meta = dict(before.meta)
    meta["kind"] = "run"
    if series:
        meta["series"] = series
    if repeat is not None:
        meta["repeat"] = repeat
    return Fingerprint(fields=fields, meta=meta, run=record, metrics=metrics)


def run_repeated(command: list[str], repeats: int, label: str | None = None, **kwargs) -> list[Fingerprint]:
    """Run the command `repeats` times; one record each, sharing a series id.

    Records that capture an identical environment share a content hash, and
    compare groups by that hash, so repeats need no other bookkeeping. Each
    repeat captures before and after on its own, so drift inside any one of
    them is still detected.
    """
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    out: list[Fingerprint] = []
    series = None
    for i in range(1, repeats + 1):
        record = run_command(command, label=label, series=series, repeat=i, **kwargs)
        if series is None:
            series = f"{record.label}@{record.run['started_at']}"
            record.meta["series"] = series
        out.append(record)
    return out

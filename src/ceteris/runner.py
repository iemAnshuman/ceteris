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
import signal
import subprocess
import sys
import time
from collections import deque
from typing import Any

from . import adapters, execution
from .capture import capture
from .config import GATING_SEVERITIES, Config
from .metrics import extract
from .model import Field, Fingerprint, State, value

MAX_OUTPUT = 64 * 1024
TERMINATE_GRACE_S = 5.0

_POSIX = os.name == "posix"


class _Spool:
    """A bounded tail of the benchmark's output.

    Every line used to be kept in a list and only the last 64 KiB survived
    into the record, so a benchmark printing per-iteration lines for an hour
    was held in memory in full for the sake of its final page. This keeps the
    same tail and counts what it dropped.
    """

    def __init__(self, limit: int = MAX_OUTPUT):
        self.limit = limit
        self._lines: "deque[str]" = deque()
        self._size = 0
        self.total = 0
        self.dropped = 0

    def add(self, line: str) -> None:
        self._lines.append(line)
        self._size += len(line)
        self.total += len(line)
        while self._size > self.limit and len(self._lines) > 1:
            gone = self._lines.popleft()
            self._size -= len(gone)
            self.dropped += len(gone)

    def text(self) -> str:
        return "".join(self._lines)[-self.limit:]

    @property
    def truncated(self) -> bool:
        return self.dropped > 0 or self.total > self.limit


def _terminate(proc) -> None:
    """Stop the benchmark and the children it started, with a bound.

    Signalling only the immediate process leaves a launcher's local children
    running. The group is signalled where the platform has groups. Ranks a
    launcher started on *other* nodes are its business, not ours, and this
    makes no claim about them.
    """
    try:
        if _POSIX:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:                                        # pragma: no cover
            proc.terminate()
    except (ProcessLookupError, PermissionError, OSError):
        proc.terminate()
    try:
        proc.wait(timeout=TERMINATE_GRACE_S)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if _POSIX:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:                                        # pragma: no cover
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()
    proc.wait()


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
    from .compare import field_key

    changed = []
    for path in sorted(set(before) | set(after)):
        if cfg.severity_of(path) not in GATING_SEVERITIES:
            continue
        old, new = before.get(path), after.get(path)
        if field_key(path, old, cfg) == field_key(path, new, cfg):
            continue
        # A field that was readable before and is not readable now says the
        # post-run capture is incomplete, which is a different statement from
        # the environment having changed underneath the run.
        kind = "changed"
        if old is not None and old.state is State.VALUE and (
                new is None or new.state is not State.VALUE):
            kind = "post_capture_unreadable"
        changed.append(
            {
                "path": path,
                "kind": kind,
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
    adapter: str | None = None,
    ingest: list[str] | None = None,
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

    # Harness adapter: recognised on the command line, may add an export flag.
    if adapter == "none":
        chosen = None
    elif adapter:
        chosen = adapters.BY_NAME.get(adapter)
        if chosen is None:
            raise ValueError(f"unknown adapter {adapter!r}; known: {', '.join(sorted(adapters.BY_NAME))}")
    else:
        chosen = adapters.detect(command)
    plan = chosen.plan(command, os.getcwd()) if chosen else adapters.Plan("none", list(command))

    # The identity of what is about to run, taken before it runs. Collecting
    # it afterwards described whatever the filesystem held once the command
    # had finished, so a program that rewrote itself was recorded as the
    # thing it became, identically across runs, with no drift. See design F03.
    subjects = chosen.subject(command) if chosen else None
    execution_before = execution.collect(command, subjects=subjects)

    started = _dt.datetime.now(_dt.timezone.utc)
    wall_started = time.time()
    clock = time.monotonic()
    spool = _Spool()
    try:
        proc = subprocess.Popen(
            plan.argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            # A benchmark that prints one byte outside UTF-8 must not lose
            # its record; the tail of its output is evidence, not data.
            errors="replace",
            bufsize=1,
            # Its own process group, so termination can reach the children a
            # launcher starts rather than only the launcher.
            start_new_session=_POSIX,
        )
    except (OSError, ValueError) as exc:
        raise ValueError(f"could not launch {command[0]!r}: {exc}") from exc

    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            spool.add(line)
            if echo:
                sys.stdout.write(line)
                sys.stdout.flush()
        exit_code = proc.wait()
    except KeyboardInterrupt:
        # Do not leave the benchmark, or anything it started, running behind
        # a dead wrapper.
        _terminate(proc)
        raise
    duration = time.monotonic() - clock
    # A process killed by a signal has a negative return code here. Reported
    # raw, `max()` over repeats turned it into 0 and a crashed benchmark
    # passed through as success. Use the shell's convention instead.
    signal_number = -exit_code if exit_code < 0 else None
    if signal_number:
        exit_code = 128 + signal_number

    output = spool.text()
    after = capture(label=label, **kwargs)
    execution_after = execution.collect(command, subjects=subjects)

    fields = dict(before.fields)
    fields.update(execution_before)

    record: dict[str, Any] = {
        "exit_code": exit_code,
        **({"signal": signal_number} if signal_number else {}),
        "started_at": started.isoformat(timespec="seconds"),
        "duration_s": round(duration, 3),
        "output": output,
        "output_truncated": spool.truncated,
        # What was dropped is itself evidence: a reader must know the tail is
        # not the whole story.
        "output_bytes_total": spool.total,
        "output_bytes_dropped": spool.dropped,
        # The subject's identity is evidence like any other, so it goes
        # through the same drift evaluator as the environment.
        "drift": _drift({**before.fields, **execution_before},
                        {**after.fields, **execution_after}, cfg),
        # This run watched for drift on both sides of the command.
        "drift_observed": True,
    }

    metrics: dict[str, Field] = {}
    if chosen:
        state, detail = chosen.validity(plan, output, os.getcwd(), wall_started)
        record["harness"] = {"adapter": chosen.name, "validity": state, "detail": detail}
        try:
            metrics.update(chosen.collect(plan, output, os.getcwd(), wall_started))
        finally:
            if plan.added_output and plan.output and os.path.exists(plan.output):
                os.unlink(plan.output)
    for item in ingest or []:
        path, _, fmt = item.partition(":")
        metrics.update(adapters.ingest(path, fmt or None))
    patterns = dict(getattr(cfg, "metrics", {}) or {})
    patterns.update(metric_patterns or {})
    if patterns:
        metrics.update(extract(output, patterns))

    meta = dict(before.meta)
    meta["kind"] = "run"
    if chosen:
        meta["adapter"] = chosen.name
    if series:
        meta["series"] = series
    if repeat is not None:
        meta["repeat"] = repeat
    return Fingerprint(fields=fields, meta=meta, run=record, metrics=metrics)


def run_records(command: list[str], repeats: int, label: str | None = None, **kwargs):
    """Yield each record the moment its run is complete.

    A measurement that finished is evidence, and it should survive whatever
    happens to the next one. Building the whole list before returning meant
    that interrupting repeat two threw away repeat one, which had already
    run: the machine had been occupied, the numbers existed, and they were
    discarded on the way out. See design F09.

    Records that capture an identical environment share a content hash, and
    compare groups by that hash, so repeats need no other bookkeeping. Each
    repeat captures before and after on its own, so drift inside any one of
    them is still detected.
    """
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    series = None
    for i in range(1, repeats + 1):
        record = run_command(command, label=label, series=series, repeat=i, **kwargs)
        if series is None:
            series = f"{record.label}@{record.run['started_at']}"
            record.meta["series"] = series
        yield record


def run_repeated(command: list[str], repeats: int, label: str | None = None, **kwargs) -> list[Fingerprint]:
    """The whole campaign as a list. Callers that must not lose a completed
    run on interruption should consume `run_records` instead."""
    return list(run_records(command, repeats, label=label, **kwargs))

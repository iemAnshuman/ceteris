"""Multi-node capture.

A fingerprint taken inside a batch script describes the node the script runs
on. For a 16-node job that is one sixteenth of the hardware, and a node with a
different driver or CPU stepping would compare as a clean match -- a silent
false certification in the tool's primary use case.

Under a multi-node Slurm allocation, capture fans out one trivial task per
node with srun, collects each node's fingerprint, and merges the node-local
fields. The fan-out is one short task per node inside an allocation that
already exists; it submits nothing.

Merge rules, per node-local field:

    identical on every node   -> that value, provenance notes the node count
    differs across nodes      -> sorted [value, count] pairs, so two
                                 allocations with the same hardware mix
                                 compare equal regardless of which hosts
                                 they landed on
    unknown on any node       -> unknown
    a node's capture missing  -> unknown for every node-local field

The last rule is the fail-closed one. Fifteen of sixteen nodes reporting is
not a fingerprint of the allocation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Callable, Sequence

from .model import Field, Fingerprint, State, unknown, value

NODE_MODE_ENV = "CETERIS_NODE_MODE"
FANOUT_TIMEOUT = 120

NODE_LOCAL_PREFIXES = ("hardware.",)
NODE_LOCAL_FIELDS = {"parallelism.capture_process_affinity"}


def is_node_local(path: str) -> bool:
    return path.startswith(NODE_LOCAL_PREFIXES) or path in NODE_LOCAL_FIELDS


def wanted() -> int | None:
    """Node count if a fan-out should happen, else None."""
    if os.environ.get(NODE_MODE_ENV):
        return None  # we are one of the fanned-out tasks
    try:
        n = int(os.environ.get("SLURM_JOB_NUM_NODES", "1"))
    except ValueError:
        return None
    if n <= 1 or shutil.which("srun") is None:
        return None
    return n


# Multi-node fan-out is Slurm-only: it uses srun. Under another scheduler the
# capture is single-node and says so through scheduler.system, rather than
# pretending the whole allocation was fingerprinted.


def _display(f: Field):
    if f.state is State.VALUE:
        return f.value
    return f"<{f.state.value}>"


def _key(f: Field) -> str:
    return json.dumps(f.to_json(), sort_keys=True)


def merge(
    head: Fingerprint,
    per_node: Sequence[tuple[str, Fingerprint | None]],
    expected: int,
) -> Fingerprint:
    """Fold per-node fingerprints into the head fingerprint."""
    fields = dict(head.fields)
    hosts = sorted(h for h, _ in per_node)
    present = [(h, fp) for h, fp in per_node if fp is not None]
    missing = [h for h, fp in per_node if fp is None]
    paths = {p for p in fields if is_node_local(p)}
    for _, fp in present:
        paths.update(p for p in fp.fields if is_node_local(p))

    if missing or len(present) != expected:
        why = (
            f"per-node capture incomplete: {len(present)} of {expected} nodes "
            f"reported" + (f"; missing {', '.join(sorted(missing))}" if missing else "")
        )
        for path in paths:
            if path in ("hardware.hostname",):
                continue
            fields[path] = unknown(why, provenance="srun fan-out")
    else:
        for path in sorted(paths):
            if path == "hardware.hostname":
                continue
            samples = [(h, fp.fields.get(path)) for h, fp in present]
            if any(f is None for _, f in samples):
                fields[path] = unknown(
                    "field absent from some node's capture", provenance="srun fan-out"
                )
                continue
            bad = [h for h, f in samples if f.is_indeterminate]
            if bad:
                fields[path] = unknown(
                    f"{samples[0][1].state.value} on {', '.join(sorted(bad))}",
                    provenance="srun fan-out",
                )
                continue
            distinct: dict[str, list[str]] = {}
            for h, f in samples:
                distinct.setdefault(_key(f), []).append(h)
            if len(distinct) == 1:
                f = samples[0][1]
                fields[path] = Field(
                    f.state, f.value,
                    provenance=f"{f.provenance} (identical on {expected} nodes)",
                    detail=f.detail,
                )
            else:
                pairs = sorted(
                    ([_display(present_field_for(samples, k)), len(hs)] for k, hs in distinct.items()),
                    key=lambda p: (-p[1], str(p[0])),
                )
                fields[path] = Field(
                    State.VALUE, pairs,
                    provenance="srun fan-out",
                    detail=f"heterogeneous across {expected} nodes; [value, node count]",
                )

    fields.pop("hardware.hostname", None)
    fields["hardware.hostnames"] = value(hosts, provenance="srun fan-out")
    fields["hardware.node_count"] = value(expected, provenance="$SLURM_JOB_NUM_NODES")
    return Fingerprint(fields=fields, meta=dict(head.meta), run=head.run, metrics=head.metrics)


def present_field_for(samples, key: str) -> Field:
    for _, f in samples:
        if _key(f) == key:
            return f
    raise KeyError(key)


def fanout_srun(n: int, capture_args: list[str]) -> list[tuple[str, Fingerprint | None]]:
    """Run one capture per node; return (hostname, fingerprint|None) pairs."""
    outdir = tempfile.mkdtemp(prefix="ceteris-nodes-", dir=os.getcwd())
    env = dict(os.environ, **{NODE_MODE_ENV: "1"})
    cmd = [
        "srun", f"--nodes={n}", f"--ntasks={n}", "--ntasks-per-node=1",
        f"--output={outdir}/%N.json", "--error=/dev/null",
        sys.executable, "-m", "ceteris", "capture", *capture_args,
    ]
    try:
        subprocess.run(cmd, env=env, timeout=FANOUT_TIMEOUT, check=False)
    except (subprocess.TimeoutExpired, OSError):
        pass
    results: list[tuple[str, Fingerprint | None]] = []
    try:
        for name in sorted(os.listdir(outdir)):
            host = name[: -len(".json")] if name.endswith(".json") else name
            try:
                raw = json.loads(open(os.path.join(outdir, name), encoding="utf-8").read())
                results.append((host, Fingerprint.from_json(raw)))
            except (OSError, ValueError):
                results.append((host, None))
    finally:
        shutil.rmtree(outdir, ignore_errors=True)
    return results


def apply(
    head: Fingerprint,
    capture_args: list[str],
    fanout: Callable[[int, list[str]], list[tuple[str, Fingerprint | None]]] = fanout_srun,
) -> Fingerprint:
    n = wanted()
    if n is None:
        fields = dict(head.fields)
        host = fields.pop("hardware.hostname", None)
        fields["hardware.hostnames"] = value(
            [host.value] if host and host.state is State.VALUE else [],
            provenance=host.provenance if host else "platform.uname().node",
        )
        fields["hardware.node_count"] = value(1, provenance="single-host capture")
        return Fingerprint(fields, dict(head.meta), run=head.run, metrics=head.metrics)
    per_node = fanout(n, capture_args)
    if len(per_node) < n:
        seen = {h for h, _ in per_node}
        for i in range(n - len(per_node)):
            per_node.append((f"<unreported-{i + 1}>", None))
    return merge(head, per_node, n)

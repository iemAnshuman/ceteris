"""Toolchain versions and dependency identity, driven by the active packs.

'Different library version' is the ML world's LCI_ATTR_PACKET_SIZE: the code
is the same, the numbers move, and nothing says why. Lockfiles are hashed
rather than parsed, so any change in resolved dependencies is a difference
without ceteris knowing the format. Container image identity is recorded
where the runtime exposes it.
"""

from __future__ import annotations

import hashlib
import os
import re

from ..model import Field, not_applicable, unknown, value
from ._run import run


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _version(text: str) -> str | None:
    m = re.search(r"(\d+\.\d+(?:\.\d+)?(?:[-+._a-zA-Z0-9]*)?)", text)
    return m.group(1) if m else None


def collect(ctx) -> dict[str, Field]:
    out: dict[str, Field] = {}
    tree = os.path.abspath(os.path.expanduser(ctx.repo or os.getcwd()))
    packs = getattr(ctx.cfg, "active_packs", {})
    out["packs.active"] = value(sorted(packs), provenance="pack activation") if packs else not_applicable(
        "no ecosystem pack activated", provenance="pack activation")

    for name, (pack, _why) in sorted(packs.items()):
        for tool, argv in pack.get("toolchain", {}).items():
            res = run(list(argv))
            key = f"toolchain.{tool}"
            if res.missing:
                out[key] = not_applicable(res.detail, provenance=res.provenance)
            elif not res.ok and not res.stdout.strip():
                # java -version prints to stderr and exits 0; other tools may
                # exit non-zero yet print a banner. Only a silent failure is unknown.
                out[key] = unknown(res.detail, provenance=res.provenance)
            else:
                text = res.stdout.strip() or res.detail
                ver = _version(text)
                out[key] = value(ver, provenance=res.provenance) if ver else unknown(
                    f"no version in: {text[:80]}", provenance=res.provenance)
        for rel in pack.get("lockfiles", {}).get("files", []):
            path = os.path.join(tree, rel)
            key = f"deps.{rel}"
            if not os.path.isfile(path):
                out[key] = not_applicable("not present in tree", provenance=path)
                continue
            try:
                out[key] = value(_sha256(path), provenance=f"sha256 {path}")
            except OSError as exc:
                out[key] = unknown(str(exc), provenance=path)

    image = os.environ.get("CONTAINER_IMAGE") or os.environ.get("SINGULARITY_CONTAINER") or os.environ.get("APPTAINER_CONTAINER")
    out["deps.container_image"] = value(image, provenance="$CONTAINER_IMAGE / $APPTAINER_CONTAINER") if image else not_applicable(
        "no container image variable set", provenance="$CONTAINER_IMAGE")
    return out

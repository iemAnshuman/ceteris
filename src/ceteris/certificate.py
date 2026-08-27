"""The certificate: one line that says a comparison was valid, and enough to
recompute that claim from the records.

    ceteris-certified v1 configs=2 n=5,5 vary=build.cxx_flags waive= verdict=ok noise=15% sha256:<h>

The hash covers the records' content hashes, the declarations, and the
verdict. `ceteris verify LINE FILES...` re-runs the comparison with the
declarations parsed out of the line and checks the hash. A record edited
after the fact, a declaration quietly widened, or a different set of files
all fail verification.

This is the thing that gets pasted into a README, a PR, or a paper's
artifact appendix, which is how a check turns into a norm.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Sequence

from .compare import Report

VERSION = 1


def _hash(report: Report) -> str:
    payload = {
        "records": sorted(g.content_hash for g in report.configs for _ in g.members),
        "vary": sorted(report.declared),
        "waive": sorted(report.waived.items()),
        "strict": report.strict,
        "exit_code": report.exit_code,
        "noise": [(v.metric, v.assessed, v.within_noise) for v in report.noise],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _noise_summary(report: Report) -> str:
    assessed = [v for v in report.noise if v.assessed]
    if not assessed:
        return "unassessed"
    return f"{max(v.noise for v in assessed):.0%}"


def issue(report: Report) -> str:
    verdict = {0: "ok", 1: "confounded", 2: "indeterminate", 4: "within-noise"}.get(report.exit_code, "invalid")
    n = ",".join(str(g.n) for g in report.configs)
    vary = ",".join(report.declared)
    waive = ";".join(f"{k}:{v}" for k, v in report.waived.items()).replace(" ", "_")
    return (
        f"ceteris-certified v{VERSION} configs={len(report.configs)} n={n} "
        f"vary={vary} waive={waive} strict={'1' if report.strict else '0'} "
        f"verdict={verdict} noise={_noise_summary(report)} sha256:{_hash(report)}"
    )


@dataclass
class Parsed:
    vary: list[str]
    waive: dict[str, str]
    strict: bool
    verdict: str
    digest: str


def parse(line: str) -> Parsed:
    m = re.match(
        r"ceteris-certified v(\d+) configs=\d+ n=[\d,]* vary=(\S*) waive=(\S*) strict=([01]) "
        r"verdict=(\S+) noise=\S+ sha256:([0-9a-f]{64})\s*$",
        line.strip(),
    )
    if not m:
        raise ValueError("not a ceteris certificate line")
    if int(m.group(1)) != VERSION:
        raise ValueError(f"certificate version {m.group(1)} not supported")
    waive = {}
    if m.group(3):
        for item in m.group(3).split(";"):
            k, _, v = item.partition(":")
            waive[k] = v.replace("_", " ")
    return Parsed(
        vary=[v for v in m.group(2).split(",") if v],
        waive=waive,
        strict=m.group(4) == "1",
        verdict=m.group(5),
        digest=m.group(6),
    )


def verify(line: str, report: Report) -> tuple[bool, str]:
    parsed = parse(line)
    actual = _hash(report)
    if actual != parsed.digest:
        return False, "hash mismatch: the records, declarations or verdict differ from what was certified"
    return True, f"verified: {parsed.verdict}"

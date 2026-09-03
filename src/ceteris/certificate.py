"""The certificate: one line that says a comparison was valid, and enough to
recompute that claim from the records.

    ceteris-certified v2 configs=2 n=5,5 vary=build.cxx_flags waive= strict=0 signal=0 verdict=ok noise=15% config=<c> sha256:<h>

The hash covers every record in full (the whole comparable body, the metrics
and the wrapped command's exit code), the declarations, the verdict and the
noise numbers. `ceteris verify LINE FILES...` re-runs the comparison with the
declarations parsed out of the line and checks the hash. A record edited
after the fact, a measurement nudged, a declaration quietly widened, or a
different set of files all fail verification.

Version 1 of the line hashed only the gating fields and a boolean per metric,
so the measurements themselves could be altered without the check noticing.
Those lines are refused rather than verified, because a passing check would
prove less than it claims.

`config=` names the severity and comparator maps the comparison ran under.
They decide which fields gate and therefore what the verdict means, so a
verifier holding a different map is told that, instead of a bare mismatch.

This is the thing that gets pasted into a README, a PR, or a paper's
artifact appendix, which is how a check turns into a norm.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

from .compare import Report
from .model import Fingerprint

VERSION = 2

# Characters allowed to stand for themselves in the declarations. Everything
# else, spaces above all, is percent-encoded so the line stays one token per
# item and round-trips exactly: version 1 wrote spaces as underscores, which
# turned "node_draw" into "node draw" on the way back and failed the check.
_SAFE = "*.?[]!-_"


def record_digest(fp: Fingerprint) -> str:
    """One record, entire: every field (gating or not), the metrics, the
    exit code and any drift. The content hash alone would leave the
    measurements unbound, and the measurements are the point."""
    payload = {
        "fields": fp.content_hash(),
        "metrics": {k: fp.metrics[k].to_json() for k in sorted(fp.metrics)},
        "exit_code": fp.run.get("exit_code"),
        "drift": fp.drift,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _round(x):
    return None if x is None else round(x, 4)


def _hash(report: Report) -> str:
    payload = {
        "version": VERSION,
        "records": sorted(record_digest(fp) for fp in report.sources),
        "vary": sorted(report.declared),
        "waive": sorted(report.waived.items()),
        "strict": report.strict,
        "require_signal": report.require_signal,
        "exit_code": report.exit_code,
        # Sorted, so the line does not depend on the order the files were
        # named in. Gap and noise are included: a verdict of "signal" with a
        # different gap is a different claim.
        "noise": sorted(
            (v.metric, v.assessed, v.within_noise, _round(v.gap), _round(v.noise))
            for v in report.noise
        ),
        "config": report.config_digest,
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
    vary = ",".join(quote(v, safe=_SAFE) for v in report.declared)
    waive = ";".join(
        f"{quote(k, safe=_SAFE)}:{quote(v, safe='')}" for k, v in report.waived.items()
    )
    return (
        f"ceteris-certified v{VERSION} configs={len(report.configs)} n={n} "
        f"vary={vary} waive={waive} strict={'1' if report.strict else '0'} "
        f"signal={'1' if report.require_signal else '0'} "
        f"verdict={verdict} noise={_noise_summary(report)} "
        f"config={report.config_digest} sha256:{_hash(report)}"
    )


@dataclass
class Parsed:
    vary: list[str]
    waive: dict[str, str]
    strict: bool
    require_signal: bool
    verdict: str
    config: str
    digest: str


_V2 = re.compile(
    r"ceteris-certified v2 configs=\d+ n=[\d,]* vary=(\S*) waive=(\S*) strict=([01]) "
    r"signal=([01]) verdict=(\S+) noise=\S+ config=([0-9a-f]{12}) sha256:([0-9a-f]{64})\s*$"
)


def parse(line: str) -> Parsed:
    line = line.strip()
    head = re.match(r"ceteris-certified v(\d+)\b", line)
    if not head:
        raise ValueError("not a ceteris certificate line")
    version = int(head.group(1))
    if version == 1:
        raise ValueError(
            "certificate version 1 is not accepted: it bound only the gating fields "
            "and a verdict per metric, so the measurements could change without "
            "failing the check. Re-issue it with `ceteris compare --certify`."
        )
    if version != VERSION:
        raise ValueError(f"certificate version {version} not supported")
    m = _V2.match(line)
    if not m:
        raise ValueError("malformed version 2 certificate line")
    waive: dict[str, str] = {}
    if m.group(2):
        for item in m.group(2).split(";"):
            k, _, v = item.partition(":")
            waive[unquote(k)] = unquote(v)
    return Parsed(
        vary=[unquote(v) for v in m.group(1).split(",") if v],
        waive=waive,
        strict=m.group(3) == "1",
        require_signal=m.group(4) == "1",
        verdict=m.group(5),
        config=m.group(6),
        digest=m.group(7),
    )


def verify(line: str, report: Report) -> tuple[bool, str]:
    parsed = parse(line)
    if parsed.config != report.config_digest:
        return False, (
            f"configuration mismatch: the certificate was issued under severity/"
            f"comparator configuration {parsed.config}, this check runs under "
            f"{report.config_digest}. Use the same --config (or the same project "
            f"directory, whose ceteris.toml is picked up automatically)."
        )
    if _hash(report) != parsed.digest:
        return False, "hash mismatch: the records, measurements, declarations or verdict differ from what was certified"
    return True, f"verified: {parsed.verdict}"

"""Bundles and receipts: a decision somebody else can check, offline.

Design section 13. The receipt is deliberately tiny:

    ceteris-receipt v3 manifest=sha256:<64 hex characters>

It carries no verdict, no counts and no percentage, because a claim printed
on the line is a claim nobody checked. Everything a reader sees is
recomputed from the verified report; the manifest binds plan and report, and
the report binds every selected record.

Verification is read-only and offline. It opens no network connection, runs
no benchmark, executes nothing from the bundle, and never consults the
verifier's own working directory for configuration.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
from dataclasses import dataclass, field as dcfield
from pathlib import Path

from .protocol.encoding import (
    CanonicalError,
    canonical_bytes,
    digest as object_digest,
    is_digest,
    loads,
)

BUNDLE_KIND = "ceteris.bundle"
BUNDLE_SCHEMA = 1
RECEIPT_VERSION = 3
RECEIPT_PREFIX = "ceteris-receipt"

CANONICALIZATION = "ceteris-json-v1"

# Availability levels, weakest first. A level is a packaging property; the
# strongest of them is still not a promise that a rerun would reproduce the
# numbers.
LEVELS = ("records_only", "evidence_complete", "reproduction_ready")

# Design section 13.4.
MAX_MEMBERS = 10_000
MAX_TOTAL_BYTES = 1024 ** 3
MAX_EVIDENCE_BYTES = 256 * 1024 * 1024
MAX_STRUCTURED_BYTES = 16 * 1024 * 1024

REQUIRED_MEMBERS = ("plan.json", "report.json")


class BundleError(ValueError):
    """The bundle cannot be read as a bundle."""

    code = "invalid_bundle"


class ReceiptError(ValueError):
    """The receipt line cannot be read."""

    code = "invalid_receipt"


def _fail(code: str, message: str):
    err = BundleError(message)
    err.code = code
    return err


# --- paths --------------------------------------------------------------------


def safe_member_path(name: str) -> str:
    """A bundle member path, or an error saying why it is not one.

    Absolute paths, parent traversal, backslashes and empty segments are
    refused before anything is opened, because a verifier that writes or
    reads outside the bundle root has stopped being read-only.
    """
    if not name or name != name.strip():
        raise _fail("invalid_member_path", f"{name!r} is not a usable member path")
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise _fail("invalid_member_path", f"{name!r} is absolute")
    if "\\" in name:
        raise _fail("invalid_member_path", f"{name!r} uses backslashes")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise _fail("invalid_member_path", f"{name!r} contains an empty or traversing segment")
    return posixpath.join(*parts)


# --- receipts -----------------------------------------------------------------


@dataclass(frozen=True)
class Receipt:
    manifest_digest: str

    def line(self) -> str:
        return f"{RECEIPT_PREFIX} v{RECEIPT_VERSION} manifest={self.manifest_digest}"

    def __str__(self) -> str:
        return self.line()


def parse_receipt(line: str) -> Receipt:
    parts = line.strip().split()
    if len(parts) != 3 or parts[0] != RECEIPT_PREFIX:
        raise ReceiptError(f"not a {RECEIPT_PREFIX} line")
    if not parts[1].startswith("v") or not parts[1][1:].isdigit():
        raise ReceiptError("the receipt does not name a version")
    version = int(parts[1][1:])
    if version != RECEIPT_VERSION:
        raise ReceiptError(
            f"receipt version {version} is not supported; this build implements "
            f"version {RECEIPT_VERSION}")
    if not parts[2].startswith("manifest="):
        raise ReceiptError("the receipt does not reference a manifest")
    reference = parts[2][len("manifest="):]
    if not is_digest(reference):
        raise ReceiptError("the manifest reference is not a sha256 digest")
    return Receipt(reference)


# --- writing ------------------------------------------------------------------


def _file_digest(path: Path) -> tuple:
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
            size += len(chunk)
    return "sha256:" + h.hexdigest(), size


def write(root, *, plan: dict, report: dict, records, evidence=(), omitted=(),
          level: str = "records_only", schemas=()) -> Receipt:
    """Write a bundle and return its receipt.

    Protocol members are written as canonical bytes, so their object digest
    and their byte digest are the same number and a reader need not wonder
    which one a manifest entry means.
    """
    if level not in LEVELS:
        raise _fail("invalid_bundle", f"{level!r} is not one of {', '.join(LEVELS)}")
    root = Path(root)
    (root / "records").mkdir(parents=True, exist_ok=True)
    (root / "evidence" / "sha256").mkdir(parents=True, exist_ok=True)

    files = []

    def put(relative: str, payload: bytes, role: str, media: str):
        safe = safe_member_path(relative)
        target = root / safe
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        files.append({"path": safe, "bytes": len(payload),
                      "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
                      "media_type": media, "role": role})

    put("plan.json", canonical_bytes(plan), "required", "application/json")
    put("report.json", canonical_bytes(report), "required", "application/json")
    for record in records:
        run_id = record.get("run_id") or object_digest(record)[7:19]
        put(f"records/{run_id}.json", canonical_bytes(record), "required", "application/json")
    for name, payload in evidence:
        content = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
        put(f"evidence/sha256/{hashlib.sha256(content).hexdigest()}", content,
            "optional", "application/octet-stream")
    for name, payload in schemas:
        content = payload if isinstance(payload, bytes) else canonical_bytes(payload)
        put(f"schemas/{name}", content, "explanatory", "application/schema+json")

    manifest = {
        "kind": BUNDLE_KIND,
        "schema_version": BUNDLE_SCHEMA,
        "canonicalization": CANONICALIZATION,
        "availability_level": level,
        "roots": {"plan": "plan.json", "report": "report.json"},
        "plan_digest": object_digest(plan),
        "report_digest": object_digest(report),
        # The manifest never lists itself; the receipt hashes it.
        "files": sorted(files, key=lambda f: f["path"]),
        "omitted": [dict(entry) for entry in omitted],
        "producer_authentication": "none",
    }
    (root / "manifest.json").write_bytes(canonical_bytes(manifest))
    (root / "README.txt").write_text(
        "A ceteris bundle. Verify it with:\n\n"
        "    ceteris bundle verify <this directory> '<receipt line>'\n\n"
        "Verification is offline and read-only. It recomputes the decision from\n"
        "the frozen plan and the records; it does not rerun the benchmark, and\n"
        "it does not execute anything from this directory.\n",
        encoding="utf-8")
    return Receipt(object_digest(manifest))


# --- verification -------------------------------------------------------------


@dataclass
class Verification:
    """Integrity and acceptance, kept apart on purpose.

    A faithfully recorded failure has perfect integrity. Conflating the two
    is what let a reader treat "this is genuine" as "this passed".
    """

    integrity: bool
    acceptance: "str | None" = None
    level: "str | None" = None
    producer_authentication: str = "none"
    supported_semantics: bool = True
    problems: list = dcfield(default_factory=list)
    notes: list = dcfield(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.integrity and not self.problems

    def to_json(self) -> dict:
        return {"integrity": self.integrity, "acceptance": self.acceptance,
                "availability_level": self.level,
                "producer_authentication": self.producer_authentication,
                "supported_semantics": self.supported_semantics,
                "problems": list(self.problems), "notes": list(self.notes)}


def verify(root, receipt_line: str, *, require_pass: bool = False,
           required_level: "str | None" = None, recompute=None) -> Verification:
    """Check a bundle against its receipt, offline.

    `recompute`, when given, is called with the parsed plan and records and
    must return the semantic report the evaluator derives from them. The
    bundle's own report is then required to equal it exactly, which is what
    makes the stored report a claim rather than an assertion.
    """
    root = Path(root)
    problems: list = []
    try:
        receipt = parse_receipt(receipt_line)
    except ReceiptError as exc:
        return Verification(False, problems=[f"receipt: {exc}"])

    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return Verification(False, problems=["the bundle has no manifest.json"])
    raw = manifest_path.read_bytes()
    if len(raw) > MAX_STRUCTURED_BYTES:
        return Verification(False, problems=["manifest.json is over the size limit"])
    try:
        manifest = loads(raw)
    except CanonicalError as exc:
        return Verification(False, problems=[f"manifest.json: {exc}"])

    if object_digest(manifest) != receipt.manifest_digest:
        return Verification(
            False, problems=["the manifest does not match the receipt; this bundle is not "
                             "the one that receipt was issued for"])

    if manifest.get("canonicalization") != CANONICALIZATION:
        return Verification(False, supported_semantics=False, problems=[
            f"the bundle declares canonicalization "
            f"{manifest.get('canonicalization')!r}, which this build does not implement"])

    entries = manifest.get("files") or []
    if len(entries) > MAX_MEMBERS:
        problems.append(f"{len(entries)} members exceeds the limit of {MAX_MEMBERS}")

    seen, total = set(), 0
    for entry in entries:
        try:
            safe = safe_member_path(entry.get("path", ""))
        except BundleError as exc:
            problems.append(str(exc))
            continue
        if safe in seen:
            problems.append(f"{safe} is listed more than once")
        seen.add(safe)
        target = root / safe
        if target.is_symlink():
            problems.append(f"{safe} is a symlink; a bundle member must be a regular file")
            continue
        if not target.is_file():
            problems.append(f"{safe} is listed in the manifest and missing from the bundle")
            continue
        found, size = _file_digest(target)
        total += size
        if size != entry.get("bytes"):
            problems.append(f"{safe} is {size} bytes, the manifest says {entry.get('bytes')}")
        if found != entry.get("digest"):
            problems.append(f"{safe} does not match its recorded digest")
    if total > MAX_TOTAL_BYTES:
        problems.append("the bundle exceeds the total size limit")

    listed = seen | {"manifest.json", "README.txt"}
    for path in root.rglob("*"):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            if relative not in listed:
                problems.append(f"{relative} is present and not listed in the manifest")

    for member in REQUIRED_MEMBERS:
        if member not in seen:
            problems.append(f"the bundle is missing the required member {member}")

    if problems:
        return Verification(False, level=manifest.get("availability_level"), problems=problems)

    plan = loads((root / "plan.json").read_bytes())
    report = loads((root / "report.json").read_bytes())
    records = [loads((root / e["path"]).read_bytes())
               for e in sorted(entries, key=lambda e: e["path"])
               if e["path"].startswith("records/")]

    if object_digest(plan) != manifest.get("plan_digest"):
        problems.append("the manifest's plan digest does not match plan.json")
    if object_digest(report) != manifest.get("report_digest"):
        problems.append("the manifest's report digest does not match report.json")
    if report.get("plan_digest") != object_digest(plan):
        problems.append("the report was computed against a different plan")

    notes = []
    if recompute is not None:
        recomputed = recompute(plan, records)
        if recomputed != report:
            problems.append(
                "the stored report is not what the frozen plan and these records "
                "produce; a displayed result has been changed")
        else:
            notes.append("the report was recomputed from the plan and the records and agreed")

    level = manifest.get("availability_level")
    if required_level and LEVELS.index(level) < LEVELS.index(required_level):
        problems.append(
            f"this bundle is {level}; the requirement is {required_level}. An "
            f"integrity-valid records-only bundle does not satisfy an "
            f"evidence-complete sharing requirement.")

    acceptance = (report.get("dimensions") or {}).get("acceptance")
    result = Verification(
        integrity=not problems,
        acceptance=acceptance,
        level=level,
        producer_authentication=manifest.get("producer_authentication", "none"),
        problems=problems,
        notes=notes + [
            "digests detect changed content against a known receipt; they do not "
            "prove the recorded experiment was run honestly"
        ],
    )
    if require_pass and result.integrity and acceptance not in ("passed", "passed_with_waivers"):
        result.problems.append(
            f"the bundle is genuine and its result is {acceptance}")
    return result


def redact(source, target, *, remove, reason: str, plan: dict, report: dict,
           records, level: str = "records_only") -> Receipt:
    """Write a derived bundle without the named members.

    A new bundle with a new manifest and a new receipt, never an edit of the
    original, and it records what was removed and why. Its acceptance is not
    inherited: less evidence is a different evaluation.
    """
    omitted = [{"path": path, "reason": reason} for path in sorted(remove)]
    kept = [r for r in records if f"records/{r.get('run_id')}.json" not in set(remove)]
    return write(target, plan=plan, report=report, records=kept,
                 omitted=omitted, level=level)


__all__ = [
    "BUNDLE_KIND",
    "BundleError",
    "CANONICALIZATION",
    "LEVELS",
    "MAX_MEMBERS",
    "RECEIPT_VERSION",
    "Receipt",
    "ReceiptError",
    "Verification",
    "parse_receipt",
    "redact",
    "safe_member_path",
    "verify",
    "write",
]

"""Bundles and receipts: a decision somebody else can check, offline.

Design section 13. The receipt is deliberately tiny:

    ceteris-receipt v3 manifest=sha256:<64 hex characters>

It carries no verdict, counts or percentage. This experimental module checks
the manifest and file integrity. Acceptance requires a trusted recomputation
callback, which the CLI does not yet provide. Availability beyond basic
records-only packaging is not evaluated.

Verification is read-only and offline. It opens no network connection, runs
no benchmark, executes nothing from the bundle, and never consults the
verifier's own working directory for configuration.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import stat
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
    if not isinstance(name, str) or not name or name != name.strip() or "\0" in name:
        raise _fail("invalid_member_path", f"{name!r} is not a usable member path")
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise _fail("invalid_member_path", f"{name!r} is absolute")
    if "\\" in name:
        raise _fail("invalid_member_path", f"{name!r} uses backslashes")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise _fail("invalid_member_path", f"{name!r} contains an empty or traversing segment")
    return posixpath.join(*parts)


def _read_member(root: Path, name: str, limit: int, keep: bool = True) -> tuple:
    """Open each component without following links, then read bounded bytes.

    Directory descriptors prevent a swapped ancestor symlink from redirecting
    a later open outside the bundle. The supported platforms are POSIX.
    """
    parts = safe_member_path(name).split("/")
    directories = []
    descriptor = None
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directories.append(os.open(root, flags))
        for part in parts[:-1]:
            directories.append(os.open(part, flags, dir_fd=directories[-1]))
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directories[-1])
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise BundleError(f"{name} is not a regular file")
        if info.st_size > limit:
            raise BundleError(f"{name} exceeds its size limit")
        hasher, size, chunks = hashlib.sha256(), 0, []
        while True:
            chunk = os.read(descriptor, min(1 << 20, limit - size + 1))
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise BundleError(f"{name} exceeds its size limit")
            hasher.update(chunk)
            if keep:
                chunks.append(chunk)
        return b"".join(chunks), "sha256:" + hasher.hexdigest(), size
    except OSError as exc:
        raise BundleError(f"cannot read {name}: missing, unreadable, or symlinked member/ancestor ({exc.strerror})") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        for directory in reversed(directories):
            os.close(directory)


def inspect(root) -> dict:
    """Read only the manifest; inspection makes no integrity or pass claim."""
    raw, _, _ = _read_member(Path(root), "manifest.json", MAX_STRUCTURED_BYTES)
    manifest = loads(raw)
    if not isinstance(manifest, dict):
        raise BundleError("manifest.json must be an object")
    required = ("kind", "schema_version", "availability_level", "canonicalization", "files")
    if any(key not in manifest for key in required):
        raise BundleError("manifest.json is missing required metadata")
    if not isinstance(manifest["files"], list) or any(
            not isinstance(e, dict) or not {"path", "bytes", "role"}.issubset(e)
            for e in manifest["files"]):
        raise BundleError("manifest files must be member entries")
    return manifest


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
        "Verification is offline and read-only. This experimental CLI checks\n"
        "file integrity only; it cannot verify acceptance or evidence availability.\n"
        "It does not rerun the benchmark or execute anything from this directory.\n",
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
    supported_semantics: bool = False
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

    try:
        raw, _, _ = _read_member(root, "manifest.json", MAX_STRUCTURED_BYTES)
        manifest = loads(raw)
    except (CanonicalError, BundleError) as exc:
        return Verification(False, problems=[f"manifest.json: {exc}"])

    if not isinstance(manifest, dict):
        return Verification(False, problems=["manifest.json must be an object"])

    if object_digest(manifest) != receipt.manifest_digest:
        return Verification(
            False, problems=["the manifest does not match the receipt; this bundle is not "
                             "the one that receipt was issued for"])

    if manifest.get("canonicalization") != CANONICALIZATION:
        return Verification(False, supported_semantics=False, problems=[
            f"the bundle declares canonicalization "
            f"{manifest.get('canonicalization')!r}, which this build does not implement"])

    if manifest.get("kind") != BUNDLE_KIND or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != BUNDLE_SCHEMA:
        return Verification(False, problems=["unsupported bundle kind or schema_version"])
    if manifest.get("availability_level") not in LEVELS:
        return Verification(False, problems=["unsupported availability_level"])
    if required_level is not None and required_level not in LEVELS:
        return Verification(False, problems=["unsupported required availability level"])
    entries = manifest.get("files")
    if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
        return Verification(False, problems=["manifest files must be an array of objects"])
    if len(entries) > MAX_MEMBERS:
        return Verification(False, problems=[f"{len(entries)} members exceeds the limit of {MAX_MEMBERS}"])

    seen, total, structured = set(), 0, {}
    for entry in entries:
        try:
            safe = safe_member_path(entry.get("path", ""))
        except BundleError as exc:
            problems.append(str(exc))
            continue
        if safe in seen:
            problems.append(f"{safe} is listed more than once")
        seen.add(safe)
        keep = safe in REQUIRED_MEMBERS or safe.startswith("records/")
        limit = MAX_STRUCTURED_BYTES if keep else MAX_EVIDENCE_BYTES
        limit = min(limit, MAX_TOTAL_BYTES - total)
        declared_size = entry.get("bytes")
        if type(declared_size) is not int or declared_size < 0 or declared_size > limit:
            problems.append(f"{safe} has an invalid or oversized byte count")
            continue
        try:
            raw, found, size = _read_member(root, safe, limit, keep)
            if keep:
                structured[safe] = loads(raw)
        except (BundleError, CanonicalError) as exc:
            problems.append(f"{safe}: {exc}")
            continue
        total += size
        if size != entry.get("bytes"):
            problems.append(f"{safe} is {size} bytes, the manifest says {entry.get('bytes')}")
        if found != entry.get("digest"):
            problems.append(f"{safe} does not match its recorded digest")
    if total > MAX_TOTAL_BYTES:
        problems.append("the bundle exceeds the total size limit")

    listed = seen | {"manifest.json", "README.txt"}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                problems.append(f"{relative} is a symlink")
            elif name in files and relative not in listed:
                problems.append(f"{relative} is present and not listed in the manifest")

    for member in REQUIRED_MEMBERS:
        if member not in seen:
            problems.append(f"the bundle is missing the required member {member}")

    if problems:
        return Verification(False, level=manifest.get("availability_level"), problems=problems)

    # These are the exact bytes already hashed, not another read that can race.
    plan, report = structured["plan.json"], structured["report.json"]
    records = [structured[name] for name in sorted(structured) if name.startswith("records/")]
    if not isinstance(plan, dict) or not isinstance(report, dict) or any(not isinstance(r, dict) for r in records):
        return Verification(False, problems=["plan, report, and records must be objects"])

    if object_digest(plan) != manifest.get("plan_digest"):
        problems.append("the manifest's plan digest does not match plan.json")
    if object_digest(report) != manifest.get("report_digest"):
        problems.append("the manifest's report digest does not match report.json")
    if report.get("plan_digest") != object_digest(plan):
        problems.append("the report was computed against a different plan")

    notes = []
    acceptance = None
    if recompute is not None:
        recomputed = recompute(plan, records)
        if recomputed != report:
            problems.append(
                "the stored report is not what the frozen plan and these records "
                "produce; a displayed result has been changed")
        else:
            notes.append("the report was recomputed from the plan and the records and agreed")
            acceptance = (recomputed.get("dimensions") or {}).get("acceptance")
    else:
        notes.append("acceptance verification unavailable: this experimental CLI checks file integrity only")

    # Everything above is about whether the bundle is genuine. What follows
    # is about whether it is sufficient for this use, which is a different
    # question and must not be reported as tampering.
    integrity = not problems
    # Availability requires an evidence-closure evaluator, not a manifest label
    # or a report callback. Only the basic packaging level is checked here.
    level = "records_only"
    if required_level in ("evidence_complete", "reproduction_ready"):
        problems.append(f"availability verification unavailable for {required_level}; only records_only integrity is checked")
    if require_pass and recompute is None:
        problems.append("acceptance verification unavailable; cannot satisfy --require-pass")

    result = Verification(
        integrity=integrity,
        acceptance=acceptance,
        level=level,
        producer_authentication="none",
        supported_semantics=recompute is not None and integrity,
        problems=problems,
        notes=notes + [
            "digests detect changed content against a known receipt; they do not "
            "prove the recorded experiment was run honestly"
        ],
    )
    if require_pass and recompute is not None and result.integrity and acceptance not in ("passed", "passed_with_waivers"):
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

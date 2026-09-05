"""Artifact, source and command identity.

Design section 9. The question this module answers is "what exactly was
measured", and the rule throughout is that an identity is either established
from bytes or reported as unknown. Nothing here infers a closure it did not
observe: a manifest covers the files that were declared, and says so.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import stat
from dataclasses import dataclass, field as dcfield
from pathlib import Path
from typing import Any

from .protocol.encoding import canonical_bytes, digest as canonical_digest

CHUNK = 1 << 20

# Design section 9.1. Immutable roles are checked before and after; a
# writable output is expected to differ and is only recorded afterwards.
ROLES = (
    "subject", "input", "correctness-reference", "validator",
    "dependency", "build-config", "harness-output", "output",
)
IMMUTABLE_ROLES = ("subject", "input", "correctness-reference", "validator",
                   "dependency", "build-config")

# The semantic root standing in for a variant's own worktree, so two
# checkouts of the same experiment are not an undeclared workload change
# while a genuinely different path still is.
WORKTREE_ROOT = "worktree:/"


class UnstableArtifact(Exception):
    """The file changed while it was being read.

    Reported rather than answered. Hashing narrows this race; it does not
    close it, and a guessed digest would describe no state of the file.
    """

    code = "unstable_artifact"


@dataclass(frozen=True)
class FileIdentity:
    """One file, by its bytes rather than its metadata."""

    sha256: str
    bytes: int
    executable: bool
    symlink: bool
    link_target: "str | None" = None

    def to_json(self) -> dict:
        out = {
            "sha256": self.sha256,
            "bytes": self.bytes,
            "executable": self.executable,
            "symlink": self.symlink,
        }
        if self.link_target is not None:
            out["link_target"] = self.link_target
        return out


def _stat_key(st: os.stat_result) -> tuple:
    return (st.st_size, st.st_mtime_ns, st.st_ino, st.st_dev)


def hash_file(path: "str | Path") -> str:
    """sha256 over the exact bytes, refusing a file that moves underneath."""
    path = str(path)
    before = os.stat(path)
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            h.update(chunk)
    if _stat_key(os.stat(path)) != _stat_key(before):
        raise UnstableArtifact(
            f"{path} changed while it was being read; no single digest describes it"
        )
    return "sha256:" + h.hexdigest()


def file_identity(path: "str | Path", *, dereference: bool = False) -> FileIdentity:
    """Identity of one path.

    A symlink is identified by its link text unless dereferencing was
    declared, because following links silently is how an artifact identity
    ends up describing a different file than the one named.
    """
    path = str(path)
    lst = os.lstat(path)
    if stat.S_ISLNK(lst.st_mode) and not dereference:
        target = os.readlink(path)
        return FileIdentity(
            sha256="sha256:" + hashlib.sha256(target.encode("utf-8")).hexdigest(),
            bytes=len(target.encode("utf-8")),
            executable=False,
            symlink=True,
            link_target=target,
        )
    st = os.stat(path)
    return FileIdentity(
        sha256=hash_file(path),
        bytes=st.st_size,
        executable=bool(st.st_mode & stat.S_IXUSR),
        symlink=stat.S_ISLNK(lst.st_mode),
        link_target=os.readlink(path) if stat.S_ISLNK(lst.st_mode) else None,
    )


def directory_manifest(root: "str | Path", *, include_empty: bool = False) -> dict:
    """A sorted manifest of a directory's semantic content.

    Relative POSIX paths, object type, executable bit, digest or link text,
    and length. Modification times, inode numbers, ownership and the
    absolute local root are excluded: they differ between two checkouts of
    the same thing and say nothing about what was measured.
    """
    root = Path(root)
    entries: list = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        here = Path(dirpath)
        if include_empty and not filenames and not dirnames and here != root:
            entries.append({
                "path": posixpath.join(*here.relative_to(root).parts),
                "type": "directory",
            })
        for name in sorted(filenames):
            absolute = here / name
            relative = absolute.relative_to(root)
            rel = posixpath.join(*relative.parts)
            lst = os.lstat(absolute)
            if stat.S_ISLNK(lst.st_mode):
                target = os.readlink(absolute)
                entries.append({"path": rel, "type": "symlink", "link_target": target,
                                "bytes": len(target.encode("utf-8"))})
                continue
            identity = file_identity(absolute)
            entries.append({
                "path": rel,
                "type": "file",
                "sha256": identity.sha256,
                "bytes": identity.bytes,
                "executable": identity.executable,
            })
    entries.sort(key=lambda e: e["path"])
    manifest = {"root_kind": "directory", "include_empty": include_empty, "entries": entries}
    return {"manifest": manifest, "digest": canonical_digest(manifest),
            "entry_count": len(entries)}


@dataclass
class Artifact:
    """A declared artifact: what it is for, and where to find it."""

    id: str
    path: str
    role: str
    mutability: str = "immutable"
    dereference: bool = False
    directory_structure: bool = False

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"role {self.role!r} is not one of {', '.join(ROLES)}")
        if self.mutability not in ("immutable", "writable"):
            raise ValueError("mutability is immutable or writable")

    @property
    def checked_before_and_after(self) -> bool:
        return self.mutability == "immutable" and self.role in IMMUTABLE_ROLES


def observe(artifact: Artifact, root: "str | Path") -> dict:
    """Observe one declared artifact, inside its root.

    An absent required artifact, an unreadable one, or one that moves while
    being read are three different answers, and none of them is a digest.
    """
    base = Path(root).resolve()
    target = (base / artifact.path) if not os.path.isabs(artifact.path) else Path(artifact.path)
    entry: dict = {"id": artifact.id, "role": artifact.role,
                   "mutability": artifact.mutability,
                   "logical_path": logical_path(str(target), base)}
    try:
        if not os.path.lexists(target):
            entry.update(status="absent",
                         reason=f"{artifact.path} does not exist under the artifact root")
            return entry
        if os.path.isdir(target) and not os.path.islink(target):
            manifest = directory_manifest(target, include_empty=artifact.directory_structure)
            entry.update(status="observed", kind="directory",
                         digest=manifest["digest"], entries=manifest["entry_count"])
            return entry
        identity = file_identity(target, dereference=artifact.dereference)
        entry.update(status="observed", kind="file", **identity.to_json())
        return entry
    except UnstableArtifact as exc:
        entry.update(status="unstable", reason=str(exc))
        return entry
    except OSError as exc:
        entry.update(status="unreadable", reason=str(exc))
        return entry


def observe_all(artifacts, root: "str | Path") -> dict:
    """Every declared artifact, keyed by logical ID."""
    return {a.id: observe(a, root) for a in artifacts}


def compare_snapshots(before: dict, after: dict, artifacts) -> list:
    """Immutable artifacts that did not survive the run unchanged.

    A writable output is expected to differ and is skipped; that is what
    declaring it writable means.
    """
    immutable = {a.id for a in artifacts if a.checked_before_and_after}
    changed = []
    for artifact_id in sorted(set(before) | set(after)):
        if artifact_id not in immutable:
            continue
        was, now = before.get(artifact_id), after.get(artifact_id)
        if was == now:
            continue
        changed.append({
            "artifact_id": artifact_id,
            "before": (was or {}).get("sha256") or (was or {}).get("status", "<absent>"),
            "after": (now or {}).get("sha256") or (now or {}).get("status", "<absent>"),
        })
    return changed


# --- logical paths ------------------------------------------------------------


def logical_path(path: "str | Path", root: "str | Path") -> str:
    """A path relative to its worktree, as a semantic root token.

    Two variants live in two directories; that is an artefact of how the
    campaign was laid out, not a difference in the experiment. A path
    outside the root keeps its own form and is marked, because pretending it
    is worktree-relative would hide a real external dependency.
    """
    path, root = Path(path), Path(root)
    # A relative token in a command is relative to the run's working
    # directory, which for a variant is its worktree, not wherever this
    # process happens to be.
    if not path.is_absolute():
        path = root / path
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return f"external:{path.as_posix()}"
    return WORKTREE_ROOT + posixpath.join(*relative.parts) if relative.parts else WORKTREE_ROOT


@dataclass
class Substitution:
    """One token replaced by a semantic reference, and why.

    Recorded individually. A blanket regular-expression rewrite of anything
    that looks like a path is how a workload argument and an export
    destination become indistinguishable.
    """

    original: str
    replacement: str
    rule: str

    def to_json(self) -> dict:
        return {"original": self.original, "replacement": self.replacement, "rule": self.rule}


def semantic_argv(argv, root: "str | Path", output_paths=()) -> dict:
    """Rewrite a command's tokens to their semantic form, keeping receipts.

    Only two substitutions are made: a path inside the worktree becomes
    `worktree:/...`, and an adapter's own output destination becomes a typed
    reference. Every other token is left exactly as it was.
    """
    outputs = {str(Path(p).resolve()) for p in output_paths}
    tokens, substitutions = [], []
    for token in argv:
        candidate = None
        if token in outputs or (os.path.isabs(token) and str(Path(token).resolve()) in outputs):
            candidate = Substitution(token, "run-output:/harness-export", "adapter_output_path")
        elif os.sep in token or token.startswith("."):
            logical = logical_path(token, root)
            if logical.startswith(WORKTREE_ROOT):
                candidate = Substitution(token, logical, "worktree_relative_path")
        if candidate is None:
            tokens.append(token)
        else:
            tokens.append(candidate.replacement)
            substitutions.append(candidate)
    return {
        "tokens": tokens,
        "substitutions": [s.to_json() for s in substitutions],
        "digest": canonical_digest(tokens),
    }


# --- source identity ----------------------------------------------------------


def source_snapshot(root: "str | Path", *, tracked, untracked=()) -> dict:
    """Content identity of a working tree, not a dirty boolean.

    A commit describes a tree that may not be the one that ran. When the
    campaign is not from a clean revision, the honest identity is a manifest
    of the bytes that were actually there.
    """
    root = Path(root)
    entries = []
    for relative in sorted(set(tracked) | set(untracked)):
        absolute = root / relative
        entry: dict = {"path": posixpath.join(*Path(relative).parts),
                       "declared": "tracked" if relative in set(tracked) else "untracked"}
        try:
            if not os.path.lexists(absolute):
                entry.update(status="absent")
            elif os.path.islink(absolute):
                entry.update(status="observed", type="symlink",
                             link_target=os.readlink(absolute))
            else:
                identity = file_identity(absolute)
                entry.update(status="observed", type="file", sha256=identity.sha256,
                             bytes=identity.bytes, executable=identity.executable)
        except (OSError, UnstableArtifact) as exc:
            entry.update(status="unreadable", reason=str(exc))
        entries.append(entry)
    manifest = {
        "mode": "snapshot",
        # Part of the digest's meaning: a manifest of tracked files is a
        # different claim from one that also covers declared untracked files.
        "selection_policy": {"tracked": True, "declared_untracked": bool(untracked)},
        "entries": entries,
    }
    return {"manifest": manifest, "digest": canonical_digest(manifest),
            "entry_count": len(entries)}


def source_digest_of(manifest: dict) -> str:
    return canonical_digest(manifest)


__all__ = [
    "Artifact",
    "FileIdentity",
    "IMMUTABLE_ROLES",
    "ROLES",
    "Substitution",
    "UnstableArtifact",
    "WORKTREE_ROOT",
    "compare_snapshots",
    "directory_manifest",
    "file_identity",
    "hash_file",
    "logical_path",
    "observe",
    "observe_all",
    "semantic_argv",
    "source_digest_of",
    "source_snapshot",
]

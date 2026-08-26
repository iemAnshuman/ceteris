"""Git source identity."""

from __future__ import annotations

import os

from ..model import Field, not_applicable, unknown, value
from ._run import run


def collect(ctx) -> dict[str, Field]:
    repo = os.path.abspath(os.path.expanduser(ctx.repo or os.getcwd()))
    out: dict[str, Field] = {
        "source.repo_path": value(repo, provenance="--repo")
    }

    top = run(["git", "rev-parse", "--show-toplevel"], cwd=repo)
    if top.missing:
        # A missing git binary does NOT prove the tree has no source identity --
        # the repository may be sitting right there, unreadable. Reporting
        # not_applicable would let two runs that both lack git compare as
        # agreeing about their commit, which is the worst failure this tool
        # can have. Absence of a tool only implies absence of the thing when
        # the tool IS the thing (no nvidia-smi means no NVIDIA stack).
        for name in ("commit", "branch", "dirty", "submodules"):
            out[f"source.{name}"] = unknown(top.detail, provenance="git")
        return out
    if not top.ok:
        for name in ("commit", "branch", "dirty", "submodules"):
            out[f"source.{name}"] = not_applicable(
                "not inside a git repository", provenance=top.provenance
            )
        return out

    commit = run(["git", "rev-parse", "HEAD"], cwd=repo)
    if commit.ok:
        out["source.commit"] = value(
            commit.stdout.strip(), provenance=commit.provenance
        )
    else:
        # An unborn branch is a known state, not an unreadable one: the
        # repository genuinely has no commit. Reporting UNKNOWN here would make
        # a fresh checkout uncertifiable for a reason that is not a failure.
        count = run(["git", "rev-list", "--all", "--count"], cwd=repo)
        if count.ok and count.stdout.strip() == "0":
            out["source.commit"] = not_applicable(
                "repository has no commits yet", provenance=count.provenance
            )
        else:
            out["source.commit"] = unknown(
                commit.detail, provenance=commit.provenance
            )

    # --show-current works on an unborn branch, unlike rev-parse --abbrev-ref.
    branch = run(["git", "branch", "--show-current"], cwd=repo)
    if not branch.ok:
        out["source.branch"] = unknown(branch.detail, provenance=branch.provenance)
    elif branch.stdout.strip():
        out["source.branch"] = value(
            branch.stdout.strip(), provenance=branch.provenance
        )
    else:
        out["source.branch"] = not_applicable(
            "detached HEAD", provenance=branch.provenance
        )

    status = run(["git", "status", "--porcelain"], cwd=repo)
    if status.ok:
        out["source.dirty"] = value(
            bool(status.stdout.strip()), provenance=status.provenance
        )
    else:
        out["source.dirty"] = unknown(status.detail, provenance=status.provenance)

    subs = run(["git", "submodule", "status", "--recursive"], cwd=repo)
    if not subs.ok:
        out["source.submodules"] = unknown(subs.detail, provenance=subs.provenance)
    elif not subs.stdout.strip():
        out["source.submodules"] = not_applicable(
            "repository has no submodules", provenance=subs.provenance
        )
    else:
        mapping = {}
        for line in subs.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2:
                mapping[parts[1]] = parts[0].lstrip("+-U")
        out["source.submodules"] = value(mapping, provenance=subs.provenance)
    return out

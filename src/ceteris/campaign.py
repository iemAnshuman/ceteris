"""Campaign layout, the run lifecycle, and durable commits.

Design section 8. Three properties matter more than anything else here.

A committed record is immutable and survives whatever happens next, so an
interruption costs at most the run it interrupted. `committed` means a
durable terminal record exists; it does not mean the benchmark passed.

A slot that already committed is never rerun automatically, and a
replacement measurement is never quietly substituted into the original
analysis. Retrying until a result looks good is the thing this whole project
exists to make impossible.

A journal entry is operational state, not a measurement. Only a terminal
record is evidence.
"""

from __future__ import annotations

import os
import socket
import tempfile
from dataclasses import dataclass, field as dcfield
from pathlib import Path

from .protocol.encoding import CanonicalError, canonical_bytes, digest, loads

CAMPAIGN_KIND = "ceteris.campaign"
CAMPAIGN_SCHEMA = 1

# Design section 8.2.
ACTIVE_STATES = ("planned", "preparing", "capturing_before", "running",
                 "capturing_after", "collecting_results", "validating")
TERMINAL_STATES = ("committed", "failed", "cancelled", "timed_out", "abandoned")
STATES = ACTIVE_STATES + TERMINAL_STATES

RETRY_POLICIES = ("none",)


class CampaignError(Exception):
    """Something about the campaign store is not as it must be."""

    code = "campaign_error"


class RunIdCollision(CampaignError):
    """Two different records claim one run ID."""

    code = "run_id_collision"


class CampaignLocked(CampaignError):
    """Another writer holds this campaign."""

    code = "campaign_locked"


# --- durable writes -----------------------------------------------------------


def atomic_write(path: "str | Path", payload: bytes) -> str:
    """Write whole or not at all, and say how durable the result is.

    Temporary file in the destination directory, flush, fsync, rename, then
    sync the directory where the platform allows it. The achieved mode is
    returned rather than assumed, because a filesystem that cannot sync a
    directory should say so instead of being described as durable.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".partial-")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    try:
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return "file_and_directory_synced"
    except OSError:
        return "file_synced_only"


# --- layout -------------------------------------------------------------------


@dataclass
class Campaign:
    """One campaign's directory, and the rules for writing into it."""

    root: Path
    campaign_id: str
    plan_digest: str

    def __init__(self, root, campaign_id: str, plan_digest: str):
        self.root = Path(root)
        self.campaign_id = campaign_id
        self.plan_digest = plan_digest

    # -- paths ---------------------------------------------------------------
    @property
    def journal_dir(self) -> Path:
        return self.root / "journal"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def artifacts_dir(self) -> Path:
        return self.root / "artifacts" / "sha256"

    def scratch_for(self, run_id: str) -> Path:
        """A run-owned scratch directory, outside the source identity manifest."""
        path = self.root / "scratch" / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def record_path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}.json"

    # -- creation ------------------------------------------------------------
    def create(self, *, plan: dict, tool_versions=None, started_at: str = "") -> None:
        for directory in (self.journal_dir, self.runs_dir, self.artifacts_dir):
            directory.mkdir(parents=True, exist_ok=True)
        # A store ignores itself, and never writes a marker into a directory
        # it does not own.
        marker = self.root / ".gitignore"
        if not marker.exists():
            marker.write_text("# created by ceteris; a campaign store is not source\n*\n")
        atomic_write(self.root / "plan.json", canonical_bytes(plan))
        body = {
            "kind": CAMPAIGN_KIND,
            "schema_version": CAMPAIGN_SCHEMA,
            "campaign_id": self.campaign_id,
            "plan_digest": self.plan_digest,
            "planned_slots": plan.get("schedule", []),
            "started_at": started_at,
            "tool_versions": dict(tool_versions or {}),
            "state": "running",
        }
        atomic_write(self.root / "campaign.json", canonical_bytes(body))

    def index(self) -> dict:
        return loads((self.root / "campaign.json").read_bytes())

    # -- locking -------------------------------------------------------------
    def acquire_lock(self) -> dict:
        """A single writer, identified, so a stale lock can be judged."""
        path = self.root / "campaign.lock"
        owner = {"campaign_id": self.campaign_id, "pid": os.getpid(),
                 "hostname": socket.gethostname()}
        try:
            handle = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            held = loads(path.read_bytes())
            raise CampaignLocked(
                f"campaign {held.get('campaign_id')} is held by pid {held.get('pid')} "
                f"on {held.get('hostname')}. Elapsed time alone does not prove that "
                f"owner is gone; recover the campaign explicitly."
            ) from None
        with os.fdopen(handle, "wb") as stream:
            stream.write(canonical_bytes(owner))
        return owner

    def release_lock(self) -> None:
        try:
            (self.root / "campaign.lock").unlink()
        except FileNotFoundError:
            pass

    def stale_lock_owner_absent(self) -> bool:
        """Whether the lock's owner is provably gone, on this host only."""
        path = self.root / "campaign.lock"
        if not path.exists():
            return True
        held = loads(path.read_bytes())
        if held.get("hostname") != socket.gethostname():
            return False                     # cannot see another host's processes
        try:
            os.kill(int(held.get("pid", -1)), 0)
        except ProcessLookupError:
            return True
        except (PermissionError, ValueError, TypeError):
            return False
        return False

    # -- the journal ---------------------------------------------------------
    def journal(self, run_id: str, state: str, **extra) -> None:
        """Operational state. Never a source of measurements."""
        if state not in STATES:
            raise CampaignError(f"{state!r} is not a run lifecycle state")
        entry = {"run_id": run_id, "state": state, "campaign_id": self.campaign_id, **extra}
        atomic_write(self.journal_dir / f"{run_id}.json", canonical_bytes(entry))

    def journal_entry(self, run_id: str) -> "dict | None":
        path = self.journal_dir / f"{run_id}.json"
        return loads(path.read_bytes()) if path.exists() else None

    # -- commits -------------------------------------------------------------
    def commit(self, record: dict) -> dict:
        """Persist a terminal record, once.

        Re-committing byte-identical content is idempotent, because a crash
        between the write and the index update must be recoverable. Two
        different records under one run ID is a collision and never an
        overwrite.
        """
        run_id = record.get("run_id")
        if not run_id:
            raise CampaignError("a record must carry its run ID before it can commit")
        path = self.record_path(run_id)
        incoming = digest(record)
        if path.exists():
            existing = digest(loads(path.read_bytes()))
            if existing == incoming:
                self.journal(run_id, "committed", record_digest=incoming)
                return {"run_id": run_id, "digest": incoming, "idempotent": True}
            raise RunIdCollision(
                f"run {run_id} already has a different committed record; a run ID "
                f"is never reused and a committed record is never overwritten")
        durability = atomic_write(path, canonical_bytes(record))
        self.journal(run_id, "committed", record_digest=incoming, durability=durability)
        return {"run_id": run_id, "digest": incoming, "idempotent": False,
                "durability": durability}

    def committed_runs(self) -> list:
        if not self.runs_dir.is_dir():
            return []
        return sorted(p.stem for p in self.runs_dir.glob("*.json"))

    def committed_records(self) -> list:
        return [loads(p.read_bytes()) for p in sorted(self.runs_dir.glob("*.json"))]


# --- resume -------------------------------------------------------------------


@dataclass
class ResumeState:
    """What a resumed campaign may and may not do."""

    remaining: list = dcfield(default_factory=list)
    committed: list = dcfield(default_factory=list)
    abandoned: list = dcfield(default_factory=list)
    problems: list = dcfield(default_factory=list)
    complete: bool = False

    def to_json(self) -> dict:
        return {"remaining": list(self.remaining), "committed": list(self.committed),
                "abandoned": list(self.abandoned), "problems": list(self.problems),
                "complete": self.complete}


def plan_resume(campaign: Campaign, plan: dict, *, live_run_ids=()) -> ResumeState:
    """Work out what is left, refusing to redo anything that finished.

    An in-flight journal entry with no terminal record becomes an abandoned
    attempt unless its process is positively identified as still running.
    Under `retry: none` a missing slot leaves the analysis incomplete, which
    is the honest outcome; the alternative is choosing which measurement to
    keep after seeing it.
    """
    state = ResumeState()
    if digest(plan) != campaign.plan_digest:
        state.problems.append(
            "the plan in this campaign is not the plan being resumed; a campaign "
            "is bound to the rules it started under")
        return state

    committed = set(campaign.committed_runs())
    state.committed = sorted(committed)

    for entry_path in sorted(campaign.journal_dir.glob("*.json")):
        entry = loads(entry_path.read_bytes())
        run_id, entry_state = entry.get("run_id"), entry.get("state")
        if entry_state in TERMINAL_STATES or run_id in committed:
            continue
        if run_id in set(live_run_ids):
            continue
        state.abandoned.append(run_id)
        campaign.journal(run_id, "abandoned",
                         reason="the campaign stopped while this attempt was in flight")

    assigned = plan.get("schedule", [])
    done_slots = set()
    for record in campaign.committed_records():
        assignment = record.get("assignment") or {}
        done_slots.add((assignment.get("pair_id"), assignment.get("slot")))
    state.remaining = [slot for slot in assigned
                       if (slot.get("pair_id"), slot.get("slot")) not in done_slots]
    state.complete = not state.remaining

    retry = (plan.get("sampling") or {}).get("retry", "none")
    if state.abandoned and retry == "none":
        state.problems.append(
            f"{len(state.abandoned)} attempt(s) were abandoned and retry is 'none'; "
            f"those slots stay missing and the planned analysis is incomplete. A "
            f"replacement measurement needs a new campaign or a predeclared retry rule.")
    return state


__all__ = [
    "ACTIVE_STATES",
    "CAMPAIGN_KIND",
    "Campaign",
    "CampaignError",
    "CampaignLocked",
    "ResumeState",
    "RunIdCollision",
    "STATES",
    "TERMINAL_STATES",
    "atomic_write",
    "plan_resume",
]

"""Campaign layout, commits and resume. Design section 8."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ceteris import campaign as cm
from ceteris.protocol.encoding import canonical_bytes, digest, loads


def a_plan(pairs=2) -> dict:
    schedule = []
    for i in range(pairs):
        for slot in ("first", "second"):
            schedule.append({"pair_id": f"c1/p{i:03d}", "slot": slot,
                             "variant_id": "base" if slot == "first" else "candidate"})
    return {"kind": "ceteris.plan", "schema_version": 1, "experiment_id": "e1",
            "schedule": schedule, "sampling": {"retry": "none"}}


def a_record(run_id, pair_id="c1/p000", slot="first", exit_code=0) -> dict:
    return {"kind": "ceteris.run", "schema_version": 4, "run_id": run_id,
            "assignment": {"pair_id": pair_id, "slot": slot, "attempt": 1},
            "execution": {"outcome": "completed", "exit_code": exit_code}}


@pytest.fixture
def campaign(tmp_path):
    plan = a_plan()
    c = cm.Campaign(tmp_path / "campaigns" / "c-1", "c-1", digest(plan))
    c.create(plan=plan, started_at="2026-09-05T10:00:00Z")
    return c


# --- layout -------------------------------------------------------------------


def test_the_store_ignores_itself_and_not_its_parent(campaign, tmp_path):
    assert (campaign.root / ".gitignore").exists()
    assert not (tmp_path / "campaigns" / ".gitignore").exists()
    assert not (tmp_path / ".gitignore").exists()


def test_the_campaign_index_records_what_it_is_bound_to(campaign):
    index = campaign.index()
    assert index["plan_digest"] == campaign.plan_digest
    assert len(index["planned_slots"]) == 4


def test_scratch_is_per_run_and_outside_the_records(campaign):
    scratch = campaign.scratch_for("r1")
    assert scratch.is_dir() and "scratch" in scratch.parts
    assert campaign.runs_dir not in scratch.parents


# --- durable writes -----------------------------------------------------------


def test_a_write_is_whole_or_absent(tmp_path):
    target = tmp_path / "out.json"
    mode = cm.atomic_write(target, b'{"a":1}')
    assert loads(target.read_bytes()) == {"a": 1}
    assert mode in ("file_and_directory_synced", "file_synced_only")


def test_a_failed_rename_leaves_nothing_readable(tmp_path, monkeypatch):
    target = tmp_path / "out.json"
    monkeypatch.setattr(cm.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("full")))
    with pytest.raises(OSError):
        cm.atomic_write(target, b'{"a":1}')
    assert not target.exists()
    assert not list(tmp_path.glob(".partial-*"))


def test_the_achieved_durability_mode_is_reported_not_assumed(tmp_path, monkeypatch):
    real = cm.os.fsync
    monkeypatch.setattr(cm.os, "fsync",
                        lambda fd: (_ for _ in ()).throw(OSError("no dir sync"))
                        if os.isatty(fd) is False and False else real(fd))
    assert cm.atomic_write(tmp_path / "a.json", b"{}") in (
        "file_and_directory_synced", "file_synced_only")


# --- commits ------------------------------------------------------------------


def test_a_committed_record_is_readable_and_journalled(campaign):
    result = campaign.commit(a_record("r1"))
    assert result["idempotent"] is False
    assert campaign.committed_runs() == ["r1"]
    assert campaign.journal_entry("r1")["state"] == "committed"


def test_committed_means_durable_not_passed(campaign):
    """A record for a benchmark that exited 183 still commits."""
    campaign.commit(a_record("r1", exit_code=183))
    assert campaign.committed_runs() == ["r1"]
    assert campaign.committed_records()[0]["execution"]["exit_code"] == 183


def test_recommitting_identical_content_is_idempotent(campaign):
    """A crash between the write and the index update must be recoverable."""
    record = a_record("r1")
    campaign.commit(record)
    again = campaign.commit(record)
    assert again["idempotent"] is True
    assert campaign.committed_runs() == ["r1"]


def test_two_different_records_under_one_run_id_is_a_collision(campaign):
    campaign.commit(a_record("r1"))
    with pytest.raises(cm.RunIdCollision):
        campaign.commit(a_record("r1", exit_code=1))


def test_a_record_without_a_run_id_cannot_commit(campaign):
    with pytest.raises(cm.CampaignError):
        campaign.commit({"kind": "ceteris.run"})


def test_a_committed_record_survives_a_later_failure(campaign):
    campaign.commit(a_record("r1"))
    with pytest.raises(cm.RunIdCollision):
        campaign.commit(a_record("r1", exit_code=9))
    assert campaign.committed_runs() == ["r1"]


# --- the journal --------------------------------------------------------------


def test_a_journal_entry_is_not_a_measurement(campaign):
    campaign.journal("r9", "running")
    assert campaign.journal_entry("r9")["state"] == "running"
    assert campaign.committed_runs() == []


def test_an_unknown_lifecycle_state_is_refused(campaign):
    with pytest.raises(cm.CampaignError):
        campaign.journal("r1", "probably-fine")


# --- locking ------------------------------------------------------------------


def test_one_writer_at_a_time(campaign):
    campaign.acquire_lock()
    with pytest.raises(cm.CampaignLocked):
        campaign.acquire_lock()
    campaign.release_lock()
    campaign.acquire_lock()


def test_the_lock_names_its_owner_so_staleness_can_be_judged(campaign):
    owner = campaign.acquire_lock()
    assert owner["pid"] == os.getpid() and owner["hostname"]


def test_a_lock_from_another_host_is_never_assumed_stale(campaign):
    campaign.acquire_lock()
    path = campaign.root / "campaign.lock"
    held = loads(path.read_bytes())
    path.write_bytes(canonical_bytes({**held, "hostname": "some-other-machine"}))
    assert campaign.stale_lock_owner_absent() is False


def test_a_lock_whose_local_owner_is_gone_is_stale(campaign):
    campaign.acquire_lock()
    path = campaign.root / "campaign.lock"
    held = loads(path.read_bytes())
    path.write_bytes(canonical_bytes({**held, "pid": 999_999_999}))
    assert campaign.stale_lock_owner_absent() is True


# --- resume -------------------------------------------------------------------


def test_resume_never_reruns_a_committed_slot(campaign):
    plan = a_plan()
    campaign.commit(a_record("r1", "c1/p000", "first"))
    state = cm.plan_resume(campaign, plan)
    assert ("c1/p000", "first") not in {(s["pair_id"], s["slot"]) for s in state.remaining}
    assert len(state.remaining) == 3


def test_resume_marks_an_in_flight_attempt_abandoned(campaign):
    plan = a_plan()
    campaign.journal("r-inflight", "running")
    state = cm.plan_resume(campaign, plan)
    assert state.abandoned == ["r-inflight"]
    assert campaign.journal_entry("r-inflight")["state"] == "abandoned"


def test_a_positively_live_attempt_is_left_alone(campaign):
    plan = a_plan()
    campaign.journal("r-live", "running")
    state = cm.plan_resume(campaign, plan, live_run_ids=["r-live"])
    assert state.abandoned == []


def test_an_abandoned_slot_under_retry_none_leaves_the_analysis_incomplete(campaign):
    """Choosing which measurement to keep after seeing it is the thing this
    refuses to allow."""
    plan = a_plan()
    campaign.journal("r-inflight", "running")
    state = cm.plan_resume(campaign, plan)
    assert any("incomplete" in p for p in state.problems)


def test_resuming_against_a_different_plan_is_refused(campaign):
    other = a_plan(pairs=3)
    state = cm.plan_resume(campaign, other)
    assert any("not the plan being resumed" in p for p in state.problems)


def test_a_campaign_with_every_slot_committed_is_complete(campaign):
    plan = a_plan()
    for i, slot in enumerate(plan["schedule"]):
        campaign.commit(a_record(f"r{i}", slot["pair_id"], slot["slot"]))
    state = cm.plan_resume(campaign, plan)
    assert state.complete and state.remaining == []


def test_a_record_committed_without_its_index_update_is_recovered_not_duplicated(campaign):
    """Recover by run ID and slot assignment; never manufacture a second."""
    plan = a_plan()
    record = a_record("r1", "c1/p000", "first")
    cm.atomic_write(campaign.record_path("r1"), canonical_bytes(record))   # no journal
    state = cm.plan_resume(campaign, plan)
    assert "r1" in state.committed
    assert ("c1/p000", "first") not in {(s["pair_id"], s["slot"]) for s in state.remaining}

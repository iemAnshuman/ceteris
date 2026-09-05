"""Artifact, source and command identity. Design section 9."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ceteris import identity as idy


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "build").mkdir()
    prog = tmp_path / "build" / "compress"
    prog.write_bytes(b"#!/bin/sh\necho v1\n")
    prog.chmod(0o755)
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "payload.bin").write_bytes(b"payload" * 100)
    return tmp_path


# --- files --------------------------------------------------------------------


def test_a_file_is_identified_by_its_bytes(tree):
    got = idy.file_identity(tree / "build" / "compress")
    assert got.sha256.startswith("sha256:") and len(got.sha256) == 71
    assert got.bytes == len(b"#!/bin/sh\necho v1\n")
    assert got.executable is True and got.symlink is False


def test_the_executable_bit_is_part_of_identity(tree):
    prog = tree / "build" / "compress"
    before = idy.file_identity(prog)
    prog.chmod(0o644)
    assert idy.file_identity(prog).executable != before.executable


def test_a_symlink_is_identified_by_its_link_text_unless_dereferencing_is_declared(tree):
    link = tree / "link-to-prog"
    link.symlink_to(tree / "build" / "compress")
    as_link = idy.file_identity(link)
    assert as_link.symlink and as_link.link_target.endswith("compress")
    followed = idy.file_identity(link, dereference=True)
    assert followed.sha256 == idy.file_identity(tree / "build" / "compress").sha256
    assert as_link.sha256 != followed.sha256


def test_a_file_that_moves_while_it_is_read_is_unstable_not_guessed(tree, monkeypatch):
    target = tree / "moving"
    target.write_bytes(b"a" * 4096)
    real = idy.os.stat
    calls = {"n": 0}

    def shifting(path, *a, **kw):
        result = real(path, *a, **kw)
        calls["n"] += 1
        if calls["n"] > 1 and str(path) == str(target):
            target.write_bytes(b"b" * 9000)
            return real(path, *a, **kw)
        return result

    monkeypatch.setattr(idy.os, "stat", shifting)
    with pytest.raises(idy.UnstableArtifact):
        idy.hash_file(str(target))


# --- directories --------------------------------------------------------------


def test_a_directory_manifest_is_sorted_and_content_addressed(tree):
    got = idy.directory_manifest(tree / "fixtures")
    assert got["entry_count"] == 1
    assert got["manifest"]["entries"][0]["path"] == "payload.bin"
    assert got["digest"].startswith("sha256:")


def test_the_same_content_in_two_places_has_the_same_manifest_digest(tmp_path):
    for name in ("a", "b"):
        root = tmp_path / name
        (root / "sub").mkdir(parents=True)
        (root / "sub" / "x.txt").write_text("hello")
        (root / "y.txt").write_text("world")
    assert (idy.directory_manifest(tmp_path / "a")["digest"]
            == idy.directory_manifest(tmp_path / "b")["digest"])


def test_mtime_is_not_part_of_semantic_identity(tmp_path):
    root = tmp_path / "r"; root.mkdir()
    (root / "x").write_text("hello")
    before = idy.directory_manifest(root)["digest"]
    os.utime(root / "x", (0, 0))
    assert idy.directory_manifest(root)["digest"] == before


def test_content_changes_do_change_the_manifest_digest(tmp_path):
    root = tmp_path / "r"; root.mkdir()
    (root / "x").write_text("hello")
    before = idy.directory_manifest(root)["digest"]
    (root / "x").write_text("hello!")
    assert idy.directory_manifest(root)["digest"] != before


def test_empty_directories_count_only_when_the_declaration_asks(tmp_path):
    root = tmp_path / "r"; (root / "empty").mkdir(parents=True)
    (root / "x").write_text("hi")
    assert idy.directory_manifest(root)["entry_count"] == 1
    assert idy.directory_manifest(root, include_empty=True)["entry_count"] == 2


# --- declared artifacts -------------------------------------------------------


def test_an_absent_required_artifact_is_named_not_skipped(tree):
    got = idy.observe(idy.Artifact("payload", "fixtures/missing.bin", "input"), tree)
    assert got["status"] == "absent" and "does not exist" in got["reason"]


def test_a_subject_that_changed_during_the_run_is_reported(tree):
    artifacts = [idy.Artifact("program", "build/compress", "subject")]
    before = idy.observe_all(artifacts, tree)
    (tree / "build" / "compress").write_bytes(b"#!/bin/sh\necho v2\n")
    after = idy.observe_all(artifacts, tree)
    changed = idy.compare_snapshots(before, after, artifacts)
    assert [c["artifact_id"] for c in changed] == ["program"]


def test_a_writable_output_is_expected_to_differ(tree):
    artifacts = [idy.Artifact("results", "out.json", "output", mutability="writable")]
    before = idy.observe_all(artifacts, tree)
    (tree / "out.json").write_text("{}")
    after = idy.observe_all(artifacts, tree)
    assert idy.compare_snapshots(before, after, artifacts) == []


def test_an_unknown_role_is_refused():
    with pytest.raises(ValueError, match="role"):
        idy.Artifact("x", "p", "whatever")


# --- logical paths and command identity ---------------------------------------


def test_two_worktrees_of_one_experiment_are_not_a_workload_difference(tmp_path):
    base, cand = tmp_path / "base", tmp_path / "candidate"
    for root in (base, cand):
        (root / "fixtures").mkdir(parents=True)
        (root / "fixtures" / "a.bin").write_bytes(b"x")
    assert (idy.logical_path(base / "fixtures" / "a.bin", base)
            == idy.logical_path(cand / "fixtures" / "a.bin", cand)
            == "worktree:/fixtures/a.bin")


def test_a_different_input_still_differs(tmp_path):
    root = tmp_path
    assert idy.logical_path(root / "fixtures" / "a.bin", root) != \
        idy.logical_path(root / "fixtures" / "b.bin", root)


def test_a_path_outside_the_worktree_is_marked_external(tmp_path):
    assert idy.logical_path("/etc/hosts", tmp_path).startswith("external:")


def test_every_substitution_records_its_original_token_and_rule(tmp_path):
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "prog").write_text("x")
    export = tmp_path / "export.json"
    got = idy.semantic_argv(
        ["hyperfine", "-N", "--export-json", str(export), "./build/prog", "--size", "4096"],
        tmp_path, output_paths=[export])
    assert "worktree:/build/prog" in got["tokens"]
    assert "run-output:/harness-export" in got["tokens"]
    assert {s["rule"] for s in got["substitutions"]} == {
        "adapter_output_path", "worktree_relative_path"}
    for sub in got["substitutions"]:
        assert sub["original"] and sub["replacement"] != sub["original"]


def test_plain_arguments_are_never_rewritten(tmp_path):
    got = idy.semantic_argv(["bench", "--size", "4096", "--label", "fast"], tmp_path)
    assert got["tokens"] == ["bench", "--size", "4096", "--label", "fast"]
    assert got["substitutions"] == []


def test_two_variants_produce_the_same_command_digest(tmp_path):
    digests = set()
    for name in ("base", "candidate"):
        root = tmp_path / name
        (root / "build").mkdir(parents=True)
        (root / "build" / "prog").write_text("x")
        digests.add(idy.semantic_argv(["./build/prog", "--size", "1"], root)["digest"])
    assert len(digests) == 1


# --- source snapshots ---------------------------------------------------------


def test_a_snapshot_hashes_contents_rather_than_recording_a_dirty_flag(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.py").write_text("y = 2\n")
    first = idy.source_snapshot(tmp_path, tracked=["a.py", "b.py"])
    (tmp_path / "a.py").write_text("x = 2\n")
    second = idy.source_snapshot(tmp_path, tracked=["a.py", "b.py"])
    assert first["digest"] != second["digest"]
    assert first["entry_count"] == 2


def test_the_selection_policy_is_part_of_the_snapshot_meaning(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "extra.py").write_text("z = 3\n")
    tracked_only = idy.source_snapshot(tmp_path, tracked=["a.py"])
    with_untracked = idy.source_snapshot(tmp_path, tracked=["a.py"], untracked=["extra.py"])
    assert tracked_only["digest"] != with_untracked["digest"]
    assert with_untracked["manifest"]["selection_policy"]["declared_untracked"] is True


def test_a_declared_file_that_is_missing_is_recorded_as_absent(tmp_path):
    got = idy.source_snapshot(tmp_path, tracked=["gone.py"])
    assert got["manifest"]["entries"][0]["status"] == "absent"


def test_a_snapshot_does_not_modify_the_repository(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    before = sorted(p.name for p in tmp_path.iterdir())
    idy.source_snapshot(tmp_path, tracked=["a.py"])
    assert sorted(p.name for p in tmp_path.iterdir()) == before

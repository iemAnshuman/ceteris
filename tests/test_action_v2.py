"""The version 2 action's contract. Design section 15.1.

These read the workflow definition rather than running GitHub Actions. They
check the properties the design names, which are the ones that would let a
pull request quietly grade its own homework.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
V1 = ROOT / "action.yml"
V2 = ROOT / "v2" / "action.yml"


@pytest.fixture(scope="module")
def v2() -> str:
    return V2.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def prose() -> str:
    """The file with YAML line wrapping collapsed, for phrase checks."""
    return " ".join(V2.read_text(encoding="utf-8").split())


@pytest.fixture(scope="module")
def executable_lines() -> str:
    """Only the lines a shell would run, with comments stripped."""
    kept = []
    for line in V2.read_text(encoding="utf-8").splitlines():
        body = line.split("#", 1)[0] if line.lstrip().startswith("#") else line
        kept.append(body)
    return "\n".join(kept)


def test_version_one_still_exists_and_is_untouched_by_version_two():
    """A pinned workflow never changes behaviour because v2 was added."""
    assert V1.is_file() and V2.is_file()
    assert "ceteris v2" not in V1.read_text(encoding="utf-8")


def test_the_documented_inputs_are_all_present(v2):
    for name in ("experiment", "base-ref", "candidate-ref", "policy-source",
                 "artifact-name", "python-version", "store-root"):
        assert re.search(rf"^  {re.escape(name)}:", v2, re.M), f"missing input {name}"


def test_the_experiment_is_read_from_the_base_revision(v2):
    """A pull request cannot lower a threshold, drop a metric, widen declared
    variation or switch off a correctness check by editing the file."""
    assert 'git show "$BASE:$EXPERIMENT"' in v2
    assert "policy-source" in v2 and "explicit" in v2


def test_ceteris_is_installed_before_any_candidate_worktree_exists(v2):
    """The tool doing the measuring never comes from the revision under test."""
    install = v2.index("Install ceteris from the action's own source")
    worktree = v2.index("Create isolated worktrees")
    assert install < worktree


def test_a_revision_that_cannot_be_obtained_stops_the_run(v2):
    assert "could not be obtained; refusing to compare a different one" in v2
    assert "git cat-file -e" in v2


def test_the_plan_is_frozen_before_anything_is_built(v2):
    plan = v2.index("Freeze the plan")
    build = v2.index("Create isolated worktrees")
    assert plan < build
    assert "ceteris plan" in v2


def test_a_failed_build_never_lets_a_stale_binary_be_timed(v2):
    assert "no timing slot runs against a stale binary" in v2


def test_user_supplied_strings_reach_the_shell_through_the_environment(v2):
    """A branch named `; rm -rf /` is a branch name, not a command."""
    for run_block in re.findall(r"run: \|\n(.*?)(?=\n    - |\n\nruns:|\Z)", v2, re.S):
        assert "${{" not in run_block, (
            "an input is interpolated directly into a shell script:\n" + run_block[:300])


def test_the_summary_and_upload_happen_even_when_the_comparison_failed(v2):
    for section in ("Summary", "upload-artifact"):
        index = v2.index(section)
        window = v2[max(0, index - 200):index + 200]
        assert "if: always()" in window, f"{section} is not unconditional"


def test_the_artifact_name_is_unique_per_invocation(v2):
    assert "${{ inputs.artifact-name }}-${{ steps.prepare.outputs.campaign_id }}" in v2


def test_the_evaluation_result_is_propagated_not_swallowed(v2):
    assert "Propagate the evaluation result" in v2
    assert 'exit "${CODE:-0}"' in v2


def test_only_the_actions_own_worktrees_are_removed(v2, executable_lines):
    assert "Remove the action's own worktrees" in v2
    assert "git worktree remove --force" in v2
    # Comments may name a dangerous command in order to warn about it; what
    # matters is that no line the shell runs contains one.
    for dangerous in ("rm -rf /", "rm -rf $GITHUB_WORKSPACE", "git clean"):
        assert dangerous not in executable_lines


def test_cleanup_happens_after_the_evidence_is_uploaded(v2):
    upload = v2.index("upload-artifact")
    cleanup = v2.index("Remove the action's own worktrees")
    assert upload < cleanup


def test_the_action_publishes_nothing_by_default(v2):
    """No PR comments, no external posting."""
    for forbidden in ("issues/comments", "createComment", "gh pr comment",
                      "curl ", "wget "):
        assert forbidden not in v2


def test_no_privileged_event_context_is_used(v2):
    """Untrusted pull-request code runs under ordinary unprivileged rules."""
    assert "pull_request_target" not in v2
    assert "secrets." not in v2


def test_the_python_version_input_does_not_claim_to_set_the_subject_runtime(prose):
    assert "does not redefine the subject's runtime" in prose


# --- the file is real YAML ----------------------------------------------------


def test_every_workflow_file_parses_as_yaml():
    """Substring checks cannot see a broken block scalar; this can."""
    yaml = pytest.importorskip("yaml")
    for path in (V1, V2, ROOT / ".github" / "workflows" / "ci.yml",
                 ROOT / ".github" / "workflows" / "release.yml"):
        yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_action_declares_the_documented_outputs():
    yaml = pytest.importorskip("yaml")
    parsed = yaml.safe_load(V2.read_text(encoding="utf-8"))
    assert set(parsed["outputs"]) == {"acceptance", "receipt", "campaign-id"}
    assert parsed["runs"]["using"] == "composite"


def test_every_run_step_names_its_shell():
    yaml = pytest.importorskip("yaml")
    parsed = yaml.safe_load(V2.read_text(encoding="utf-8"))
    for step in parsed["runs"]["steps"]:
        if "run" in step:
            assert step.get("shell"), f"step {step.get('name')!r} has no shell"


def test_a_build_that_is_missing_the_campaign_runner_says_so_rather_than_going_green(v2):
    """An empty upload behind a green check would imply a comparison that
    never happened."""
    assert "has no 'campaign run'" in v2
    assert "no measurements were taken" in v2
    assert "acceptance=not_evaluated" in v2

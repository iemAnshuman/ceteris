"""Correctness evidence: was the answer right, not merely fast.

Design section 10.2. Exit zero is not proof of a correct answer, and a
benchmark that got the wrong answer quickly is not an improvement. A claim
here is bound to the subject and input identities it was checked against, so
it cannot be read as covering a different build.

Nothing in this module runs during import or verification. A validator
command executes only as part of an explicitly authorised experiment.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field as dcfield
from typing import Any

RESULTS = ("passed", "failed", "unverified")
SCOPES = ("execution", "artifact", "harness_iteration")

COMMAND = "command@1"
OUTPUT_SHA256 = "output-sha256@1"
HARNESS_STATUS = "harness-status@1"

VALIDATORS = (COMMAND, OUTPUT_SHA256, HARNESS_STATUS)


@dataclass
class Claim:
    """One correctness claim, bound to what it actually checked."""

    validator_id: str
    result: str
    scope: str = "execution"
    case_ids: tuple = ()
    bound_subjects: dict = dcfield(default_factory=dict)
    bound_inputs: dict = dcfield(default_factory=dict)
    evidence_refs: tuple = ()
    detail: str = ""
    argv: tuple = ()
    exit_code: "int | None" = None
    timeout_s: "float | None" = None
    output_tail: str = ""

    def __post_init__(self) -> None:
        if self.result not in RESULTS:
            raise ValueError(f"result {self.result!r} is not one of {', '.join(RESULTS)}")
        if self.scope not in SCOPES:
            raise ValueError(f"scope {self.scope!r} is not one of {', '.join(SCOPES)}")

    def covers(self, subjects: dict, inputs: dict) -> bool:
        """Whether this claim was made against these exact identities.

        A claim from a previous build is evidence about that build. Reusing
        it would be the correctness equivalent of a stale export.
        """
        return self.bound_subjects == subjects and self.bound_inputs == inputs

    def to_json(self) -> dict:
        return {
            "validator_id": self.validator_id, "result": self.result, "scope": self.scope,
            "case_ids": list(self.case_ids), "bound_subjects": dict(self.bound_subjects),
            "bound_inputs": dict(self.bound_inputs),
            "evidence_refs": list(self.evidence_refs), "detail": self.detail,
            "argv": list(self.argv), "exit_code": self.exit_code,
            "timeout_s": self.timeout_s, "output_tail": self.output_tail,
        }


def command(argv, *, cwd=None, timeout_s: float = 60.0, subjects=None, inputs=None,
            case_ids=(), env=None) -> Claim:
    """`command@1`: run a planned checker, outside the timed region.

    Exit zero means that checker passed. It does not mean the program is
    correct, and the report names whose claim it is.
    """
    subjects, inputs = dict(subjects or {}), dict(inputs or {})
    try:
        finished = subprocess.run(
            list(argv), cwd=cwd, timeout=timeout_s, capture_output=True,
            text=True, errors="replace", check=False, env=env,
        )
    except FileNotFoundError as exc:
        return Claim(COMMAND, "unverified", case_ids=tuple(case_ids),
                     bound_subjects=subjects, bound_inputs=inputs, argv=tuple(argv),
                     detail=f"the checker could not be launched: {exc}")
    except subprocess.TimeoutExpired:
        return Claim(COMMAND, "failed", case_ids=tuple(case_ids),
                     bound_subjects=subjects, bound_inputs=inputs, argv=tuple(argv),
                     timeout_s=timeout_s,
                     detail=f"the checker did not finish within {timeout_s}s")
    tail = (finished.stdout + finished.stderr)[-4096:]
    return Claim(
        COMMAND, "passed" if finished.returncode == 0 else "failed",
        case_ids=tuple(case_ids), bound_subjects=subjects, bound_inputs=inputs,
        argv=tuple(argv), exit_code=finished.returncode, timeout_s=timeout_s,
        output_tail=tail,
        detail=("the checker exited zero" if finished.returncode == 0
                else f"the checker exited {finished.returncode}"),
    )


def output_sha256(path, expected_digest: str, *, subjects=None, inputs=None,
                  case_ids=()) -> Claim:
    """`output-sha256@1`: declared output bytes against a frozen digest.

    A missing or truncated output cannot pass. Absent evidence is
    unverified, which is not the same as correct.
    """
    from .. import identity

    subjects, inputs = dict(subjects or {}), dict(inputs or {})
    make = lambda result, detail: Claim(  # noqa: E731
        OUTPUT_SHA256, result, scope="artifact", case_ids=tuple(case_ids),
        bound_subjects=subjects, bound_inputs=inputs, detail=detail)
    try:
        found = identity.hash_file(path)
    except FileNotFoundError:
        return make("failed", f"{path} was not produced, so its bytes cannot match")
    except identity.UnstableArtifact as exc:
        return make("unverified", str(exc))
    except OSError as exc:
        return make("unverified", f"{path} could not be read: {exc}")
    if found == expected_digest:
        return make("passed", f"{path} matches the expected digest")
    return make("failed", f"{path} is {found}, the expected digest is {expected_digest}")


def harness_status(validity: "str | None", *, detail: str = "", case_ids=(),
                   subjects=None, inputs=None) -> Claim:
    """`harness-status@1`: preserve a harness's own marker, if it made one.

    A harness that says nothing about validity yields `unverified`. Absence
    of a complaint is not a clean bill of health.
    """
    mapping = {"valid": "passed", "invalid": "failed"}
    return Claim(
        HARNESS_STATUS, mapping.get(validity or "", "unverified"),
        case_ids=tuple(case_ids), bound_subjects=dict(subjects or {}),
        bound_inputs=dict(inputs or {}),
        detail=detail or f"the harness reported {validity or 'nothing'}",
    )


def summarise(claims, *, required: bool) -> dict:
    """The correctness dimension for a set of claims.

    A failure fails the experiment. A required check that could not be made
    is incomplete evidence, and is never read as having passed.
    """
    results = [claim.result for claim in claims]
    if "failed" in results:
        state = "failed"
    elif not required:
        state = "validated" if results and all(r == "passed" for r in results) else "unverified"
    elif results and all(r == "passed" for r in results):
        state = "validated"
    else:
        state = "unverified"
    return {
        "state": state,
        "required": required,
        "claims": [claim.to_json() for claim in claims],
        "unverified": [claim.validator_id for claim in claims if claim.result == "unverified"],
    }


__all__ = [
    "COMMAND",
    "Claim",
    "HARNESS_STATUS",
    "OUTPUT_SHA256",
    "RESULTS",
    "SCOPES",
    "VALIDATORS",
    "command",
    "harness_status",
    "output_sha256",
    "summarise",
]

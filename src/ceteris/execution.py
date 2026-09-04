"""Structure the wrapped command line.

`execution.command` as one string is all-or-nothing: sweeping a message size
passed as an argument means declaring the whole command varies, which also
waives a rank-count change in that same command. Splitting the command into
launcher, launcher arguments, program and program arguments lets each part
gate on its own.

The split is a heuristic and is labelled as such in its provenance. The whole
command is still recorded verbatim as the ground truth.

The program binary is also hashed. A stale build is the single most common
cause of an invalid comparison, and git cannot see it: the tree is clean and
at the right commit, but the binary was built before the last change. The
hash catches it regardless.
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil

from .model import Field, not_applicable, unknown, value

# Arguments that are source code rather than data. A stale `bench.py` is the
# interpreted world's stale build, and hashing the interpreter never sees it.
_SCRIPT_EXTENSIONS = (
    ".py", ".js", ".mjs", ".ts", ".rb", ".pl", ".sh", ".bash", ".zsh",
    ".lua", ".jl", ".r", ".tcl", ".php",
)
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

LAUNCHERS = {
    "mpirun", "mpiexec", "mpiexec.hydra", "srun", "jsrun", "aprun", "prun",
    "orterun", "prterun", "flux",
}

# Launcher options that consume the following token as their value. Anything
# written as --opt=value is self-contained and needs no entry here.
_VALUED = {
    "-n", "-np", "--np", "-c", "-N", "-H", "-host", "--host", "-hostfile",
    "--hostfile", "-machinefile", "--machinefile", "-x", "--bind-to",
    "--map-by", "--rank-by", "-rf", "--rankfile", "--ntasks", "--nodes",
    "--ntasks-per-node", "--cpus-per-task", "--gpus", "--gpus-per-task",
    "--gpus-per-node", "--gres", "-p", "--partition", "-t", "--time", "-J",
    "--job-name", "-o", "--output", "-e", "--error", "--cpu-bind",
    "--cpu_bind", "--mem", "--mem-per-cpu", "--distribution", "-m",
    "--mpi", "-a", "-g", "-r", "-b", "-d", "-A", "--account", "-q", "--qos",
    "--exclusive", "-env", "-genv", "-f", "-ppn", "-hosts", "-configfile",
}
# Options taking two values.
_TWO_VALUED = {"--mca", "-mca", "--gmca", "-gmca", "-env", "-genv"}


def split(argv: list[str]) -> tuple[str | None, list[str], str | None, list[str]]:
    if not argv:
        return None, [], None, []
    if os.path.basename(argv[0]) not in LAUNCHERS:
        return None, [], argv[0], list(argv[1:])
    launcher = argv[0]
    i = 1
    launcher_args: list[str] = []
    while i < len(argv):
        token = argv[i]
        if token == "--":
            i += 1
            break
        if token.startswith("-"):
            launcher_args.append(token)
            consume = 2 if token in _TWO_VALUED else (1 if token in _VALUED and "=" not in token else 0)
            for _ in range(consume):
                i += 1
                if i < len(argv):
                    launcher_args.append(argv[i])
            i += 1
            continue
        break
    if i >= len(argv):
        return launcher, launcher_args, None, []
    return launcher, launcher_args, argv[i], list(argv[i + 1 :])


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _scripts(args: list[str]) -> dict[str, str]:
    """sha256 of every argument that is an existing script file."""
    found: dict[str, str] = {}
    for a in args:
        if a.lower().endswith(_SCRIPT_EXTENSIONS) and os.path.isfile(a):
            try:
                found[a] = _sha256(a)
            except OSError:
                continue
    return found


def _scripts_field(args: list[str], what: str) -> Field:
    scripts = _scripts(args)
    if scripts:
        return value(scripts, provenance=f"sha256 of script files among the {what}")
    return not_applicable(f"no script file among the {what}", provenance=what)


def _resolve(exe: str) -> str | None:
    resolved = exe if os.sep in exe else shutil.which(exe)
    return resolved if resolved and os.path.isfile(resolved) else None


def _subject_fields(harness: str, subjects: list[str]) -> dict[str, Field]:
    """The commands a harness runs are what the measurement is about. Each
    is shell-split, its executable resolved from the capturing host and
    hashed, and any script among its arguments hashed too. A harness
    binary's own hash says nothing about a stale benchmark build."""
    prov = f"positional commands of {harness} (heuristic option parse)"
    out: dict[str, Field] = {"execution.subject": value(list(subjects), provenance=prov)}
    hashes: dict[str, str] = {}
    scripts: dict[str, str] = {}
    problems: list[str] = []
    for cmd in subjects:
        try:
            tokens = shlex.split(cmd)
        except ValueError as exc:
            problems.append(f"{cmd!r}: {exc}")
            continue
        while tokens and _ENV_ASSIGNMENT.match(tokens[0]):
            tokens.pop(0)
        if not tokens:
            problems.append(f"{cmd!r}: no executable")
            continue
        resolved = _resolve(tokens[0])
        if resolved is None:
            problems.append(f"{cmd!r}: {tokens[0]} not found on disk from the capturing host")
        else:
            try:
                hashes[cmd] = _sha256(resolved)
            except OSError as exc:
                problems.append(f"{cmd!r}: {exc}")
        scripts.update(_scripts(tokens[1:]))
    out["execution.subject_sha256"] = (
        unknown("; ".join(problems), provenance=f"sha256 of each subject's executable ({prov})")
        if problems
        else value(hashes, provenance=f"sha256 of each subject's executable ({prov})")
    )
    out["execution.subject_scripts_sha256"] = (
        value(scripts, provenance="sha256 of script files among the subjects' arguments")
        if scripts
        else not_applicable("no script file among the subjects' arguments", provenance="subjects")
    )
    return out


def _no_subject(why: str) -> dict[str, Field]:
    return {
        "execution.subject": not_applicable(why, provenance="harness adapter"),
        "execution.subject_sha256": not_applicable(why, provenance="harness adapter"),
        "execution.subject_scripts_sha256": not_applicable(why, provenance="harness adapter"),
    }


def collect(argv: list[str], subjects: list[str] | None = None) -> dict[str, Field]:
    """`subjects`, when a harness adapter supplies them, are the command
    strings the harness itself times; they are taken out of
    execution.program_args, which then holds only the harness's options."""
    out: dict[str, Field] = {
        "execution.command": value(" ".join(argv), provenance="wrapped command line"),
        "execution.workdir": value(os.getcwd(), provenance="os.getcwd()"),
    }
    launcher, largs, program, pargs = split(argv)
    prov = "heuristic split of the wrapped command line"
    out["execution.launcher"] = (
        value(os.path.basename(launcher), provenance=prov)
        if launcher
        else not_applicable("no recognised launcher; program run directly", provenance=prov)
    )
    out["execution.launcher_args"] = (
        value(largs, provenance=prov)
        if launcher
        else not_applicable("no recognised launcher", provenance=prov)
    )
    if program is None:
        out["execution.program"] = unknown("could not identify the program", provenance=prov)
        out["execution.program_args"] = unknown("could not identify the program", provenance=prov)
        out["execution.program_sha256"] = unknown("could not identify the program", provenance=prov)
        out["execution.program_scripts_sha256"] = unknown("could not identify the program", provenance=prov)
        out.update(_no_subject("could not identify the program"))
        return out
    out["execution.program"] = value(program, provenance=prov)
    if subjects:
        remaining = list(pargs)
        for subject in subjects:
            if subject in remaining:
                remaining.remove(subject)
        out["execution.program_args"] = value(
            remaining, provenance=f"{prov}; the harness's own options, the timed commands are in execution.subject"
        )
        out.update(_subject_fields(os.path.basename(program), subjects))
    else:
        out["execution.program_args"] = value(pargs, provenance=prov)
        out.update(_no_subject("no harness adapter; the program itself is the subject"))
    out["execution.program_scripts_sha256"] = _scripts_field(pargs, "program arguments")

    resolved = _resolve(program)
    hprov = f"sha256 of {resolved or program}"
    if resolved:
        try:
            out["execution.program_sha256"] = value(_sha256(resolved), provenance=hprov)
        except OSError as exc:
            out["execution.program_sha256"] = unknown(str(exc), provenance=hprov)
    else:
        out["execution.program_sha256"] = unknown(
            "program not found on disk from the capturing host", provenance=hprov
        )
    return out

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
import shutil

from .model import Field, not_applicable, unknown, value

# Arguments that are source code rather than data. A stale `bench.py` is the
# interpreted world's stale build, and hashing the interpreter never sees it.
_SCRIPT_EXTENSIONS = (
    ".py", ".js", ".mjs", ".ts", ".rb", ".pl", ".sh", ".bash", ".zsh",
    ".lua", ".jl", ".r", ".tcl", ".php",
)

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


def collect(argv: list[str]) -> dict[str, Field]:
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
        return out
    out["execution.program"] = value(program, provenance=prov)
    out["execution.program_args"] = value(pargs, provenance=prov)
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

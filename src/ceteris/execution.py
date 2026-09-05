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

# Launcher option grammars, one per family.
#
# A single shared table got this wrong in both directions: `-c` takes a value
# under srun (cpus-per-task) and is a process count under Open MPI, and
# `--exclusive` was listed as valued although Slurm takes it bare, which ate
# the program name. Each family therefore carries its own grammar, and an
# option outside its family's grammar makes the decomposition unknown rather
# than guessed. The verbatim command line is recorded either way.

_OPENMPI = {
    "valued": {
        "-n", "-np", "--np", "--n", "-c", "-H", "-host", "--host", "-hostfile",
        "--hostfile", "-machinefile", "--machinefile", "-x", "--bind-to",
        "--map-by", "--rank-by", "-rf", "--rankfile", "--output", "--prefix",
        "--wdir", "--path", "--tune", "--report-bindings-to", "-am", "--am",
    },
    "two_valued": {"--mca", "-mca", "--gmca", "-gmca"},
    "flags": {
        "--oversubscribe", "--nooversubscribe", "--use-hwthread-cpus", "-v",
        "--verbose", "--display-map", "--report-bindings", "--do-not-launch",
        "--tag-output", "--timestamp-output", "--merge-stderr-to-stdout",
        "--allow-run-as-root", "-q", "--quiet", "--nolocal", "--novm",
    },
}

_HYDRA = {
    "valued": {
        "-n", "-np", "--np", "-f", "-hostfile", "--hostfile", "-hosts",
        "-ppn", "-configfile", "-env", "-genv", "-launcher", "-bootstrap",
        "-wdir", "-path", "-bind-to", "-map-by", "-iface",
    },
    "two_valued": {"-envlist", "-genvlist"},
    "flags": {"-genvall", "-genvnone", "-usize", "-verbose", "-print-rank-map"},
}

_SRUN = {
    "valued": {
        "-n", "--ntasks", "-N", "--nodes", "--ntasks-per-node", "-c",
        "--cpus-per-task", "--gpus", "-G", "--gpus-per-task", "--gpus-per-node",
        "--gres", "-p", "--partition", "-t", "--time", "-J", "--job-name",
        "-o", "--output", "-e", "--error", "-i", "--input", "--cpu-bind",
        "--cpu_bind", "--mem", "--mem-per-cpu", "--mem-per-gpu",
        "--distribution", "-m", "--mpi", "-A", "--account", "-q", "--qos",
        "-w", "--nodelist", "-x", "--exclude", "-D", "--chdir", "-d",
        "--dependency", "-C", "--constraint", "--export", "--het-group",
        "--threads-per-core", "--sockets-per-node", "--cores-per-socket",
        "--switches", "--nice", "--prolog", "--epilog", "--task-prolog",
        "--task-epilog", "--uid", "--gid", "--reservation",
    },
    # Slurm takes these bare, or as --opt=value, never as two tokens.
    "flags": {
        "--exclusive", "--overlap", "--overcommit", "-O", "--label", "-l",
        "--unbuffered", "-u", "--pty", "--verbose", "-v", "--kill-on-bad-exit",
        "-K", "--no-kill", "-k", "--wait-all-nodes", "--contiguous",
        "--exclusive-user", "--interactive", "--test-only", "--use-min-nodes",
    },
    "two_valued": set(),
}

_GENERIC = {
    "valued": {"-n", "-np", "--np", "-N", "--nodes", "-c", "--cpus"},
    "two_valued": set(),
    "flags": set(),
}

# basename -> grammar
LAUNCHER_GRAMMARS = {
    "mpirun": _OPENMPI, "mpiexec": _OPENMPI, "orterun": _OPENMPI, "prterun": _OPENMPI,
    "mpiexec.hydra": _HYDRA,
    "srun": _SRUN,
    "jsrun": _GENERIC, "aprun": _GENERIC, "prun": _GENERIC, "flux": _GENERIC,
}

LAUNCHERS = set(LAUNCHER_GRAMMARS)

# Raised when a launcher's arguments cannot be decomposed with confidence.
class AmbiguousCommand(Exception):
    def __init__(self, token: str):
        super().__init__(
            f"{token!r} is not a known option of this launcher, so whether the "
            f"next token is its value or the program cannot be decided"
        )
        self.token = token


def split(argv: list[str]) -> tuple[str | None, list[str], str | None, list[str]]:
    """Decompose a launched command. Raises AmbiguousCommand when a known
    launcher carries an option its grammar does not describe."""
    if not argv:
        return None, [], None, []
    grammar = LAUNCHER_GRAMMARS.get(os.path.basename(argv[0]))
    if grammar is None:
        return None, [], argv[0], list(argv[1:])
    launcher = argv[0]
    i = 1
    launcher_args: list[str] = []
    while i < len(argv):
        token = argv[i]
        if token == "--":
            i += 1
            break
        if not token.startswith("-") or token == "-":
            break
        launcher_args.append(token)
        if "=" in token and token.startswith("--"):
            consume = 0                     # --opt=value is self-contained
        elif token in grammar["two_valued"]:
            consume = 2
        elif token in grammar["valued"]:
            consume = 1
        elif token in grammar["flags"]:
            consume = 0
        else:
            raise AmbiguousCommand(token)
        for _ in range(consume):
            i += 1
            if i >= len(argv):
                raise AmbiguousCommand(token)
            launcher_args.append(argv[i])
        i += 1
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
    binary's own hash says nothing about a stale benchmark build.

    Hashes are keyed by the executable as written, not by the whole command:
    `gzip -6` and `gzip -1` are one binary, and a comparison that declares
    the subject varies must not also have to declare that its hash did not.
    """
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
                hashes[tokens[0]] = _sha256(resolved)
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
        # shlex.join, so `hyperfine 'gzip -6 -c f'` is recorded as typed and
        # not flattened into tokens nobody can re-run.
        "execution.command": value(shlex.join(argv), provenance="wrapped command line"),
        "execution.workdir": value(os.getcwd(), provenance="os.getcwd()"),
    }
    prov = "decomposition of the wrapped command line by launcher grammar"
    try:
        launcher, largs, program, pargs = split(argv)
    except AmbiguousCommand as exc:
        # Opaque command, incomplete decomposition coverage. The verbatim
        # line above is still the ground truth and still gates.
        for name in ("launcher", "launcher_args", "program", "program_args",
                     "program_sha256", "program_scripts_sha256"):
            out[f"execution.{name}"] = unknown(str(exc), provenance=prov)
        out.update(_no_subject("the command line could not be decomposed"))
        return out
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
        out.update(_no_subject("the program on the command line is the subject"))
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

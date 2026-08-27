# ceteris

[![ci](https://github.com/iemAnshuman/ceteris/actions/workflows/ci.yml/badge.svg)](https://github.com/iemAnshuman/ceteris/actions/workflows/ci.yml)

Wrap a benchmark run, and refuse to compare two numbers that are not comparable.

Named for *ceteris paribus*, all other things being equal. That is the claim
every benchmark comparison makes, and it is the claim this tool checks.

The failure it exists to catch is always shaped the same way: **you intended to
vary one thing, something else varied too, and nothing told you.** A stale
build on one side. `-O2` against `-O3`. `LCI_ATTR_PACKET_SIZE` left at its
8 KB default on one side and tuned to 73728 on the other, which is a ~35x
performance cliff that reads exactly like an algorithmic result. One node in a
sixteen-node allocation running a different driver.

Experiment trackers record metrics. None of them answer *are these two numbers
even comparable?*

## Quickstart

```sh
pipx install git+https://github.com/iemAnshuman/ceteris.git
```

Two real runs of an MPI ping-pong benchmark on the machine this README was
written on, an Apple M4. The benchmark is [`examples/pingpong.c`](examples/pingpong.c);
the only intended difference is the optimisation level.

```console
$ mpicc -O3 -o pingpong_O3 examples/pingpong.c
$ mpicc -O0 -o pingpong_O0 examples/pingpong.c

$ ceteris run --label tuned-O3 --compiler mpicc --cxx-flags -O3 \
      --metric 'bandwidth_gbs=bandwidth ([0-9.]+) GB/s' \
      -- mpirun -n 2 ./pingpong_O3 1048576 200
size 1048576 bytes  iters 200  bandwidth 30.850 GB/s
ceteris: recorded .ceteris/runs/20260827-111049Z-tuned-O3.json

$ ceteris run --label tuned-O0 --compiler mpicc --cxx-flags -O0 \
      --metric 'bandwidth_gbs=bandwidth ([0-9.]+) GB/s' \
      -- mpirun -n 2 ./pingpong_O0 1048576 200
size 1048576 bytes  iters 200  bandwidth 51.269 GB/s
ceteris: recorded .ceteris/runs/20260827-111050Z-tuned-O0.json
```

`ceteris run` captured the environment, ran the benchmark, captured again, and
recorded one file holding the fingerprint *and* the number. Nothing to name,
nothing to pair up later.

```console
$ ceteris compare --last 2
2 runs compared. Declared varying: nothing

MEASUREMENTS:
  run       bandwidth_gbs  exit      wall
  tuned-O3          30.85     0     0.52s
  tuned-O0         51.269     0     0.60s

UNDECLARED DIFFERENCES (comparison is not valid):
  build.cxx_flags           -O3 (tuned-O3)  vs  -O0 (tuned-O0)
  execution.program         ./pingpong_O3 (tuned-O3)  vs  ./pingpong_O0 (tuned-O0)
  execution.program_sha256  56d7060c5d6ea948be9d66f482b7614b0240ffde7b4a3… (tuned-O3)  vs  d82a3febc7d215d4d0c0d2d0d1293416a62b0b4adcd5c… (tuned-O0)

DIFFERS, NOT GATING (informational severity):
  execution.command         mpirun -n 2 ./pingpong_O3 1048576 200 (tuned-O3)  vs  mpirun -n 2 ./pingpong_O0 1048576 200 (tuned-O0)

Matched on 94 other fields.
$ echo $?
1
```

There is a 66% gap between those two numbers, and in this particular pair
the *unoptimised* build came out ahead. The tool's answer is not "-O0 is
66% faster" -- it is **you may not draw that conclusion**, because the build
flags, the program and its binary hash all changed and none of it was
declared. Once they are declared, the comparison certifies:

```console
$ ceteris compare --last 2 --vary build.cxx_flags --vary 'execution.program*'
2 runs compared. Declared varying: build.cxx_flags, execution.program*

MEASUREMENTS:
  run       bandwidth_gbs  exit      wall
  tuned-O3          30.85     0     0.52s
  tuned-O0         51.269     0     0.60s

DECLARED VARYING (expected):
  build.cxx_flags           -O3 (tuned-O3)  vs  -O0 (tuned-O0)
  execution.program         ./pingpong_O3 (tuned-O3)  vs  ./pingpong_O0 (tuned-O0)
  execution.program_sha256  56d7060c5d6ea948be9d66f482b7614b0240ffde7b4a3… (tuned-O3)  vs  d82a3febc7d215d4d0c0d2d0d1293416a62b0b4adcd5c… (tuned-O0)

DIFFERS, NOT GATING (informational severity):
  execution.command         mpirun -n 2 ./pingpong_O3 1048576 200 (tuned-O3)  vs  mpirun -n 2 ./pingpong_O0 1048576 200 (tuned-O0)

Matched on 94 other fields.

OK: every difference was declared. Comparison is valid.
$ echo $?
0
```

Declaring only the flags is not enough, and that is deliberate: the binary
hash is its own field, because **a stale build is the most common invalid
comparison there is and git cannot see it.** The tree is clean, the commit is
right, and the binary predates the last change.

```console
$ ceteris compare --last 2 --vary build.cxx_flags
2 runs compared. Declared varying: build.cxx_flags

MEASUREMENTS:
  run       bandwidth_gbs  exit      wall
  tuned-O3          30.85     0     0.52s
  tuned-O0         51.269     0     0.60s

UNDECLARED DIFFERENCES (comparison is not valid):
  execution.program         ./pingpong_O3 (tuned-O3)  vs  ./pingpong_O0 (tuned-O0)
  execution.program_sha256  56d7060c5d6ea948be9d66f482b7614b0240ffde7b4a3… (tuned-O3)  vs  d82a3febc7d215d4d0c0d2d0d1293416a62b0b4adcd5c… (tuned-O0)

DECLARED VARYING (expected):
  build.cxx_flags           -O3 (tuned-O3)  vs  -O0 (tuned-O0)

DIFFERS, NOT GATING (informational severity):
  execution.command         mpirun -n 2 ./pingpong_O3 1048576 200 (tuned-O3)  vs  mpirun -n 2 ./pingpong_O0 1048576 200 (tuned-O0)

Matched on 94 other fields.
$ echo $?
1
```

### It has to certify, too -- and the noise floor is the real yardstick

A gate that always fails is a gate nobody keeps. Eight runs of the *identical*
configuration, same binary and same command:

```console
$ ceteris compare examples/noise/*.json
8 runs compared. Declared varying: nothing

MEASUREMENTS:
  run          bw  exit      wall
  rep1     48.965     0     0.07s
  rep2     49.444     0     0.08s
  rep3      45.97     0     0.07s
  rep4     52.838     0     0.07s
  rep5     48.244     0     0.07s
  rep6     49.114     0     0.07s
  rep7     48.166     0     0.07s
  rep8     46.686     0     0.07s

Matched on 98 other fields.

OK: every difference was declared. Comparison is valid.
$ echo $?
0
```

All eight certify. And the numbers run 46.0 to 52.8 GB/s, a **15% spread
with nothing changed at all.** The quickstart pair sits well outside that
band, in the wrong direction, and with nothing controlled there is no way to
say what it measured: thermal state, a first-run effect, or the build. Two
runs is not a measurement.

`ceteris` makes no claim about statistical significance. What it does is stop
you comparing two numbers unless the runs producing them were actually
comparable, which is the precondition for any of the rest being worth doing.

## Why wrapping the run is the whole point

An earlier design had `capture` as a standalone command that you ran yourself
and paired with your results by hand. That does not work, and it fails for the
reason the underlying problem exists: **it is bookkeeping, and bookkeeping is
what already failed.** A tool you have to remember to use fails the way the
discipline it replaces failed.

Wrapping the run gets four things a standalone capture cannot have:

1. **The fingerprint is taken in the job's own context.** Put `ceteris run`
   inside an sbatch script and it sees the compute nodes, the allocation and
   the job environment -- not the login node you happened to type on.
2. **The launcher command line is recorded for real** and split into launcher,
   launcher arguments, program and program arguments, so `mpirun -n 16
   --bind-to core` is captured rather than inferred, and sweeping a message
   size passed as an argument does not also waive a change in rank count.
3. **The benchmark binary is hashed**, so a rebuild is caught regardless of
   what git says.
4. **The environment is captured before *and* after**, so a change that happens
   mid-run -- a module swap, a rebuild into the same tree -- is detected
   instead of silently splitting the run in half.

## On a cluster

`ceteris run` sits inside the batch script, wrapping the launcher. A project
config at `./ceteris.toml` is picked up automatically:

```toml
# ceteris.toml
[metrics]
latency_us = "avg latency ([0-9.]+) us"

[capture]
env_allowlist = ["MY_PROJECT_TUNABLE"]
```

```bash
#!/bin/bash
#SBATCH -N 16 -n 256 -p buran

module load gcc/13 openmpi/5
export LCI_ATTR_PACKET_SIZE=73728

ceteris run --label "lci-$LCI_ATTR_PACKET_SIZE-$SLURM_JOB_ID" \
    --repo ~/codes/hpx --cmake-cache ~/codes/hpx/build \
    --store ~/campaigns/collectives \
    -- srun ./bench_all_to_all --size 4096
```

**Every node is fingerprinted.** Under a multi-node allocation, capture fans
out one short task per node with `srun` inside the allocation that already
exists, and merges the node-local fields. A value identical on every node
collapses to one; a value that differs becomes `[value, node count]` pairs, so
two allocations with the same hardware mix compare equal regardless of which
hosts they landed on, and one node with a different driver shows up as a
difference. A node that fails to report makes every hardware field `unknown`:
fifteen of sixteen nodes is not a fingerprint of the allocation.

Then, after the campaign:

```bash
ceteris compare --store ~/campaigns/collectives --label 'lci-*' \
    --vary runtime.env.LCI_ATTR_PACKET_SIZE
```

Non-zero exit means the campaign is confounded, so it gates a script directly.

## The commands

| | |
|---|---|
| `ceteris run -- CMD` | capture, run `CMD`, capture again, record it. Passes `CMD`'s exit code through. |
| `ceteris compare` | check that runs differ only in what you declared. Non-zero if not. |
| `ceteris list` | show recorded runs and their numbers |
| `ceteris capture` | emit a fingerprint alone, without running anything |

Runs land in `.ceteris/runs` by default, which ignores itself so it never
dirties your repository; `--store` or `$CETERIS_STORE` moves it. `compare`
takes files directly, or selects with `--last N` and `--label GLOB`.

Also importable:

```python
from ceteris import compare
from ceteris.runner import run_command

a = run_command(["mpirun", "-n", "2", "./bench"], label="a")
b = run_command(["mpirun", "-n", "2", "./bench"], label="b")
assert compare([a, b]).exit_code == 0
```

Python 3.11 or newer. **No runtime dependencies.**

## What a record looks like

Real output, 98 fields / 524 lines, committed at
[`examples/run-tuned-O3.json`](examples/run-tuned-O3.json). This is a verbatim
excerpt of 30 fields -- every one that captured a value, plus a few that
degraded.

```json
{
  "fields": {
    "build.compiler_id": {
      "p": "mpicc --version",
      "s": "value",
      "v": "clang"
    },
    "build.compiler_path": {
      "p": "--compiler",
      "s": "value",
      "v": "/opt/homebrew/bin/mpicc"
    },
    "build.compiler_version": {
      "p": "mpicc --version",
      "s": "value",
      "v": "22.1.8"
    },
    "build.cxx_flags": {
      "p": "--cxx-flags",
      "s": "value",
      "v": "-O3"
    },
    "execution.command": {
      "p": "wrapped command line",
      "s": "value",
      "v": "mpirun -n 2 ./pingpong_O3 1048576 200"
    },
    "execution.launcher": {
      "p": "heuristic split of the wrapped command line",
      "s": "value",
      "v": "mpirun"
    },
    "execution.launcher_args": {
      "p": "heuristic split of the wrapped command line",
      "s": "value",
      "v": [
        "-n",
        "2"
      ]
    },
    "execution.program": {
      "p": "heuristic split of the wrapped command line",
      "s": "value",
      "v": "./pingpong_O3"
    },
    "execution.program_args": {
      "p": "heuristic split of the wrapped command line",
      "s": "value",
      "v": [
        "1048576",
        "200"
      ]
    },
    "execution.program_sha256": {
      "p": "sha256 of ./pingpong_O3",
      "s": "value",
      "v": "56d7060c5d6ea948be9d66f482b7614b0240ffde7b4a392a4c78b5eb9ccf62b7"
    },
    "execution.workdir": {
      "p": "os.getcwd()",
      "s": "value",
      "v": "/Users/anshumanagrawal/codes/workplace/2026_projects/ceteris"
    },
    "hardware.arch": {
      "p": "platform.uname().machine",
      "s": "value",
      "v": "arm64"
    },
    "hardware.cpu_cores_logical": {
      "p": "sysctl -n hw.logicalcpu",
      "s": "value",
      "v": 10
    },
    "hardware.cpu_cores_physical": {
      "p": "sysctl -n hw.physicalcpu",
      "s": "value",
      "v": 10
    },
    "hardware.cpu_model": {
      "p": "sysctl -n machdep.cpu.brand_string",
      "s": "value",
      "v": "Apple M4"
    },
    "hardware.gpu_models": {
      "d": "nvidia-smi not on PATH",
      "p": "nvidia-smi",
      "s": "not_applicable"
    },
    "hardware.hostnames": {
      "p": "platform.uname().node",
      "s": "value",
      "v": [
        "MacBook-Air-7.local"
      ]
    },
    "hardware.kernel": {
      "p": "platform.uname().release",
      "s": "value",
      "v": "24.6.0"
    },
    "hardware.node_count": {
      "p": "single-host capture",
      "s": "value",
      "v": 1
    },
    "hardware.os": {
      "p": "platform.uname().system",
      "s": "value",
      "v": "Darwin"
    },
    "hardware.os_version": {
      "p": "platform",
      "s": "value",
      "v": "15.7.7"
    },
    "runtime.env.LCI_ATTR_PACKET_SIZE": {
      "d": "unset",
      "p": "$LCI_ATTR_PACKET_SIZE",
      "s": "not_applicable"
    },
    "runtime.mpi_implementation": {
      "p": "mpirun --version",
      "s": "value",
      "v": "Open MPI"
    },
    "runtime.mpi_launcher": {
      "p": "shutil.which('mpirun')",
      "s": "value",
      "v": "/opt/homebrew/bin/mpirun"
    },
    "runtime.mpi_version": {
      "p": "mpirun --version",
      "s": "value",
      "v": "5.0.9"
    },
    "scheduler.job_id": {
      "d": "not running under Slurm",
      "p": "$SLURM_JOB_ID",
      "s": "not_applicable"
    },
    "source.branch": {
      "p": "git branch --show-current",
      "s": "value",
      "v": "main"
    },
    "source.commit": {
      "p": "git rev-parse HEAD",
      "s": "value",
      "v": "5e88fdb5280e4de0bd37acf8ede7332bc3768a5f"
    },
    "source.dirty": {
      "p": "git status --porcelain",
      "s": "value",
      "v": true
    },
    "source.repo_path": {
      "p": "--repo",
      "s": "value",
      "v": "/Users/anshumanagrawal/codes/workplace/2026_projects/ceteris"
    }
  },
  "meta": {
    "captured_at": "2026-08-27T11:10:49+00:00",
    "content_hash": "e0cdedd8e85876e9e961a2aa9628632badf8b263e0dea06f347249ad95b699ef",
    "kind": "run",
    "label": "tuned-O3",
    "schema_version": 1,
    "tool": "ceteris",
    "tool_version": "0.1.0"
  },
  "metrics": {
    "bandwidth_gbs": {
      "p": "regex /bandwidth ([0-9.]+) GB/s/",
      "s": "value",
      "v": 30.85
    }
  },
  "run": {
    "drift": [],
    "duration_s": 0.519,
    "exit_code": 0,
    "output": "size 1048576 bytes  iters 200  bandwidth 30.850 GB/s",
    "output_truncated": false,
    "started_at": "2026-08-27T11:10:49+00:00"
  }
}
```

Four things to notice, because they are the design:

- **Every field records its own provenance** (`"p"`). When a comparison reports
  a difference, the next question is always "how did you determine that", and
  the answer is in the artifact rather than in the documentation.
- **`captured_at` lives in `meta`, never in `fields`.** The content hash covers
  the comparable body only, so two captures of an identical environment hash
  identically and the files diff cleanly. Keys are sorted.
- **An unset tuning variable is recorded as `not_applicable`, not omitted.**
  That is what makes a tuned run and a default run differ *visibly* instead of
  both being silently absent.
- **Metrics sit outside `fields`.** They are the dependent variable -- what you
  are measuring, and therefore what is *supposed* to differ. Holding them out
  of the comparable body by construction is what stops the tool flagging every
  real experiment.

## How a field can be

Four states, not two. The distinction that carries the most weight is
`unknown` against `not_applicable`:

| state | meaning | example |
|---|---|---|
| `value` | captured | `source.commit = 81c60cb…` |
| `not_applicable` | structurally absent | no GPU in this machine at all |
| `unknown` | may exist, could not be read | `nvidia-smi` present but hung |
| `error` | the collector itself failed | |

Two GPU-less laptops both report `not_applicable` for `hardware.gpu_driver`,
and that is a genuine **match**. A laptop against a GPU node is
`not_applicable` against a real version string, and that is a genuine
**difference**. Collapsing the two states into one gets one of those cases
wrong whichever way you collapse it.

The rule that decides it: **a tool's absence implies the thing's absence only
when the tool *is* the thing.** No `nvidia-smi` means no NVIDIA stack, so
`not_applicable`. No `git` does *not* mean no commit -- the repository may be
sitting right there, unreadable -- so `unknown`. Getting that backwards would
let two runs that both lack `git` compare as agreeing on their source commit.

An unknown is reported in its own section, separately from a difference,
because the response differs: a difference means the experiment is confounded,
an unknown means the capture is incomplete.

`examples/run-b-gpu-probe-failed.json` is the one file here that was not
captured: it is `run-a.json` with `hardware.gpu_driver` edited to the
`unknown` state, because a hung `nvidia-smi` cannot be produced on a machine
that has no `nvidia-smi`. The comparison output below is real.

```console
$ ceteris compare examples/run-a.json examples/run-b-gpu-probe-failed.json
2 runs compared. Declared varying: nothing

UNKNOWN (could not be captured -- comparison is not certified):
  hardware.gpu_driver
      run-b-gpu-probe-failed: unknown: timed out after 10.0s
      run-a: known, <not applicable>

Matched on 90 other fields.
$ echo $?
2
```

## Severity

If `scheduler.job_id` gated, every comparison would fail and the tool would be
switched off within a week. Fields carry a severity, and only `critical` and
`material` gate by default:

- **critical** -- `source.commit`, `source.dirty`, everything under `build.`,
  the launcher and program parts of `execution.`, the binary hash, every
  `runtime.env.*` tuning variable
- **material** -- CPU and GPU model, node count, rank and thread counts, MPI
  version, allocation shape
- **informational** -- `scheduler.job_id`, `hardware.hostnames`,
  `source.branch` (the branch name does not change the binary; the commit
  does), the verbatim `execution.command`

`--strict` promotes informational fields into the gate. Any field not listed
defaults to **material**, so a field added in a later version gates by default
rather than quietly escaping the check.

## Declaring intent

```sh
--vary runtime.env.LCI_ATTR_PACKET_SIZE   # exact
--vary 'runtime.env.LCI_*'                # glob -- a 40-config sweep cannot enumerate by hand
--vary build                              # bare prefix, covers every build.* field
--vary execution.program_args             # the sweep is in the arguments; rank count still gates
--waive hardware.cpu_model:"same partition, different node draw"
```

`--vary` says *this is my independent variable*. `--waive` says *this differs
and I have decided it does not matter*, and **the reason is mandatory** so the
decision stays auditable six months later. Without an escape hatch the tool
gets abandoned the first time two allocations land on different nodes.

Two warnings you cannot get any other way: a declaration matching **no** field
is flagged as a likely typo, and a declaration under which **nothing varied** is
flagged, because that usually means the sweep script never applied the setting.

## Metrics

`--metric NAME=REGEX`, or a `[metrics]` table in `ceteris.toml`. One capture
group per pattern. A pattern that does not match records `unknown` -- never a
zero, never the last number that happened to appear, and never a silent
omission.

## Exit codes

| code | meaning |
|---|---|
| 0 | comparable -- every difference was declared |
| 1 | undeclared differences: the comparison is confounded |
| 2 | indeterminate: something could not be captured, or a run drifted mid-flight |
| 3 | usage error, unreadable input |

1 wins when both 1 and 2 apply. `ceteris run` instead passes the wrapped
command's own exit code through, so wrapping a benchmark does not change how a
surrounding script behaves.

## Configuration

Which variables and build keys matter differs per project, so they are data,
not code. [`src/ceteris/defaults.toml`](src/ceteris/defaults.toml) ships a set
for HPX / MPI / LCI / CUDA. `./ceteris.toml` (or `--config PATH`) extends it:

```toml
[capture]
env_allowlist = ["MY_PROJECT_TUNABLE"]

[severity]
"hardware.hostnames" = "critical"   # heterogeneous partition: the nodes matter

[metrics]
bandwidth_gbs = "bandwidth ([0-9.]+) GB/s"
```

JSON is accepted as well as TOML, so a cluster on an interpreter older than
3.11 can still configure the tool without the package taking a TOML dependency.

## What this deliberately does not capture

Every one of these could be filled with a plausible value. A guessed value in a
fingerprint is precisely the class of error this tool exists to catch, so the
gaps are left open and documented instead.

- **The transport actually negotiated at run time.** `mpirun --version` and
  `ompi_info` report what is *available*, not what was selected; UCX picks
  transports during init, inside the job. Captured instead: the transport
  *configuration* visible in the environment, which is a real observation.
- **Per-rank observed CPU affinity.** Seeing where each rank actually landed
  needs code inside every rank. Captured instead: the launcher arguments
  (`--bind-to core` lives there), binding *intent* in the environment, and
  each node's capture-process affinity mask where the OS exposes one.
- **NUMA topology beyond a node count.** Low silent variance, high parsing
  cost, largely implied by CPU model and partition.

Emitting these as a permanent `unknown` would make every comparison
uncertifiable; emitting them as `not_applicable` would be worse, because two
runs that both failed to observe binding would compare as agreeing.

## Status

Alpha. The single-host path is exercised for real on macOS and Linux in CI.
The Slurm fan-out and the CUDA collector are tested against recorded command
output and hand-built per-node records; they have not yet run on a real
allocation. If you run one, `ceteris capture -o fp.json` inside the job and
the resulting file is the most useful thing you can send.

## Tests

```sh
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```

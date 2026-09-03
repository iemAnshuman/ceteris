# ceteris

[![ci](https://github.com/iemAnshuman/ceteris/actions/workflows/ci.yml/badge.svg)](https://github.com/iemAnshuman/ceteris/actions/workflows/ci.yml)
[![pypi](https://img.shields.io/pypi/v/ceteris)](https://pypi.org/project/ceteris/)
[![python](https://img.shields.io/pypi/pyversions/ceteris)](https://pypi.org/project/ceteris/)

**Wrap any benchmark. Refuse the comparison unless it is valid.**

A comparison of two benchmark numbers is valid if, and only if:

1. the only things that differ between the runs are the things you *meant* to vary, and
2. the difference is bigger than the noise.

Every benchmark harness -- hyperfine, Google Benchmark, JMH, pytest-benchmark,
criterion, MLPerf, OSU -- does some of (2) and none of (1). Their own docs list
the confounds and tell *you* to handle them: CPU governor, turbo, SMT, a stale
build, a different library version, one node in sixteen on another driver.
ceteris captures them, checks both conditions, and exits non-zero when either
fails. It sits underneath the harness you already use.

Named for *ceteris paribus*: all other things being equal.

```sh
pip install ceteris        # or: pipx install ceteris, or: uv tool install ceteris
```

Python 3.9+. No runtime dependencies.

## Quickstart

Two real runs on the machine this README was written on, an Apple M4 laptop.
Compress a 27 MB file with `gzip -6` and `gzip -1`, each timed by hyperfine,
each repeated three times. No `--metric` needed: ceteris recognises hyperfine
and reads its export.

```console
$ ceteris run --label gzip-6 --repeats 3 -- hyperfine -N --warmup 1 --runs 5 'gzip -6 -c /tmp/payload.txt'
$ ceteris run --label gzip-1 --repeats 3 -- hyperfine -N --warmup 1 --runs 5 'gzip -1 -c /tmp/payload.txt'

$ ceteris compare
6 runs compared. Declared varying: nothing

MEASUREMENTS (per configuration):
  configuration    n  metric                  min     median        max  spread
  gzip-6           3  hyperfine.median_s     0.6276     0.6337     0.6417     2%
  gzip-6           3  hyperfine.min_s      0.6228     0.6306     0.6361     2%
  gzip-1           3  hyperfine.median_s     0.5076     0.5089     0.5092     0%
  gzip-1           3  hyperfine.min_s       0.507     0.5082     0.5085     0%

NOISE FLOOR:
  hyperfine.median_s signal        gap 25% exceeds the largest within-configuration spread of 2%
  hyperfine.min_s  signal        gap 24% exceeds the largest within-configuration spread of 2%

UNDECLARED DIFFERENCES (comparison is not valid):
  execution.subject  gzip -6 -c /tmp/payload.txt (gzip-6 x3)  vs  gzip -1 -c /tmp/payload.txt (gzip-1 x3)

DIFFERS, NOT GATING (informational severity):
  execution.command  hyperfine -N --warmup 1 --runs 5 'gzip -6 -c … (gzip-6 x3)  vs  hyperfine -N --warmup 1 --runs 5 'gzip -1 -c … (gzip-1 x3)
  system.load_1m     5 distinct values across 6 runs (range 1.53 to 1.74)

Matched on 135 other fields.
$ echo $?
1
```

The tool found a real 25% signal above a 2% noise floor -- and still refused,
because the command hyperfine timed changed and nobody said that was the
experiment. It knows which part of the line is hyperfine's and which is the
subject: the options still gate, the subject is one field. Declare it, and ask
for a certificate:

```console
$ ceteris compare --vary execution.subject --require-signal --certify
6 runs compared. Declared varying: execution.subject

MEASUREMENTS (per configuration):
  configuration    n  metric                  min     median        max  spread
  gzip-6           3  hyperfine.median_s     0.6276     0.6337     0.6417     2%
  gzip-6           3  hyperfine.min_s      0.6228     0.6306     0.6361     2%
  gzip-1           3  hyperfine.median_s     0.5076     0.5089     0.5092     0%
  gzip-1           3  hyperfine.min_s       0.507     0.5082     0.5085     0%

NOISE FLOOR:
  hyperfine.median_s signal        gap 25% exceeds the largest within-configuration spread of 2%
  hyperfine.min_s  signal        gap 24% exceeds the largest within-configuration spread of 2%

DECLARED VARYING (expected):
  execution.subject  gzip -6 -c /tmp/payload.txt (gzip-6 x3)  vs  gzip -1 -c /tmp/payload.txt (gzip-1 x3)

DIFFERS, NOT GATING (informational severity):
  execution.command  hyperfine -N --warmup 1 --runs 5 'gzip -6 -c … (gzip-6 x3)  vs  hyperfine -N --warmup 1 --runs 5 'gzip -1 -c … (gzip-1 x3)
  system.load_1m     5 distinct values across 6 runs (range 1.53 to 1.74)

Matched on 135 other fields.

OK: every difference was declared. Comparison is valid.

ceteris-certified v2 configs=2 n=3,3 vary=execution.subject waive= strict=0 signal=1 verdict=ok noise=2% config=02282b8304e8 sha256:5913ed8e93600be80a67276d1e98d7ab0354d80e65ffe701e998ca0ff3365ccf
$ echo $?
0
```

That last line is portable. Paste it into a README, a pull request or a
paper's artifact appendix, and anyone holding the records can check it. It
binds every record in full -- every field, every measurement, the exit code --
so a number nudged after the fact fails the check, and it names the severity
configuration it was issued under, so a verifier holding a different one is
told that rather than shown a bare mismatch:

```console
$ ceteris verify 'ceteris-certified v2 configs=2 n=3,3 vary=execution.subject waive= strict=0 signal=1 verdict=ok noise=2% config=02282b8304e8 sha256:5913ed8e93600be80a67276d1e98d7ab0354d80e65ffe701e998ca0ff3365ccf' examples/hyperfine/*.json
ceteris: verified: ok
```

The six records are committed under [`examples/hyperfine/`](examples/hyperfine/).

## The other failure mode: a result that is not a result

An MPI ping-pong ([`examples/pingpong.c`](examples/pingpong.c)) built at `-O3`
and at `-O0`, three runs each, declaring the flags as the variable:

```console
$ ceteris compare examples/pingpong/*.json --vary build.cxx_flags
6 runs compared. Declared varying: build.cxx_flags

MEASUREMENTS (per configuration):
  configuration    n  metric                  min     median        max  spread
  tuned-O3         3  bandwidth_gbs         48.59      49.15       52.9     9%
  tuned-O0         3  bandwidth_gbs          45.5      46.51      51.57    13%

NOISE FLOOR:
  bandwidth_gbs    WITHIN NOISE  gap 6% between configuration medians is not larger than the 13% spread within a single configuration

CONFOUNDED WITH A DECLARED VARIABLE (re-run; do not waive):
  execution.program moves in lockstep with build.cxx_flags:
      build.cxx_flags = -O0  ->  execution.program = ./pingpong_O0  (3 runs)
      build.cxx_flags = -O3  ->  execution.program = ./pingpong_O3  (3 runs)
  execution.program_sha256 moves in lockstep with build.cxx_flags:
      build.cxx_flags = -O0  ->  execution.program_sha256 = d82a3febc7d215d4d0c0d2d…  (3 runs)
      build.cxx_flags = -O3  ->  execution.program_sha256 = 56d7060c5d6ea948be9d66f…  (3 runs)

UNDECLARED DIFFERENCES (comparison is not valid):
  execution.program         ./pingpong_O3 (tuned-O3 x3)  vs  ./pingpong_O0 (tuned-O0 x3)
  execution.program_sha256  56d7060c5d6ea948be9d66f482b7614b0240ffde7b4a3… (tuned-O3 x3)  vs  d82a3febc7d215d4d0c0d2d0d1293416a62b0b4adcd5c… (tuned-O0 x3)

DECLARED VARYING (expected):
  build.cxx_flags           -O3 (tuned-O3 x3)  vs  -O0 (tuned-O0 x3)

DIFFERS, NOT GATING (informational severity):
  execution.command         mpirun -n 2 ./pingpong_O3 1048576 200 (tuned-O3 x3)  vs  mpirun -n 2 ./pingpong_O0 1048576 200 (tuned-O0 x3)
  system.load_1m            2.96 (tuned-O3 x2, tuned-O0 x3)  vs  2.78 (tuned-O3)

Matched on 126 other fields.
$ echo $?
1
```

Three things happened there, and each is a class of invalid comparison that
gets published:

- **WITHIN NOISE.** The 6% gap between the builds is smaller than the 13%
  scatter inside one build. Two numbers is not a measurement.
- **CONFOUNDED.** The binary hash moves in lockstep with the declared
  variable. Of course it does -- they are different builds -- but that is
  exactly what a stale build looks like too, and ceteris cannot tell the
  difference. It asks you to declare it rather than waive it.
- **`system.power_source = battery`** is in every one of these records. This
  laptop was unplugged. That field compares equal here because it was equal
  on every run; it would not have been equal against a run from last week.

## What it captures

One record per run, ~138 fields, every field carrying its own provenance and one
of four states. This is [`examples/pingpong/20260827-215234Z-tuned-O3-2.json`](examples/pingpong/20260827-215234Z-tuned-O3-2.json),
excerpted to the 41 fields that carried a value plus a few that degraded:

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
    "packs.active": {
      "p": "pack activation",
      "s": "value",
      "v": [
        "hpc",
        "python"
      ]
    },
    "runtime.env.OMP_NUM_THREADS": {
      "d": "unset",
      "p": "$OMP_NUM_THREADS",
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
      "v": "9c98a7b8a1b02cab930ecd27594502d6aa5d45bc"
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
    },
    "system.aslr": {
      "p": "darwin policy",
      "s": "value",
      "v": "always-on"
    },
    "system.container": {
      "p": "darwin",
      "s": "value",
      "v": "no"
    },
    "system.cpu_governor": {
      "d": "darwin does not expose this",
      "p": "sysfs",
      "s": "not_applicable"
    },
    "system.load_1m": {
      "p": "os.getloadavg()[0]",
      "s": "value",
      "v": 2.96
    },
    "system.power_source": {
      "p": "pmset -g batt",
      "s": "value",
      "v": "battery"
    },
    "system.smt": {
      "p": "sysctl hw.logicalcpu vs hw.physicalcpu",
      "s": "value",
      "v": "off"
    },
    "system.swap": {
      "p": "sysctl -n vm.swapusage",
      "s": "value",
      "v": "in-use"
    },
    "system.thermal_throttle": {
      "p": "pmset -g therm",
      "s": "value",
      "v": "none"
    },
    "system.virtualization": {
      "p": "sysctl -n kern.hv_vmm_present",
      "s": "value",
      "v": "none"
    },
    "toolchain.python": {
      "p": "python3 --version",
      "s": "value",
      "v": "3.14.7"
    }
  },
  "meta": {
    "captured_at": "2026-08-27T21:52:34+00:00",
    "content_hash": "5b3cdc03723ca49d901834c23075cdb0a525e36d26c561c4ad232b4f18c7c042",
    "kind": "run",
    "label": "tuned-O3",
    "repeat": 2,
    "schema_version": 2,
    "series": "tuned-O3@2026-08-27T21:52:34+00:00",
    "tool": "ceteris",
    "tool_version": "0.1.0"
  },
  "metrics": {
    "bandwidth_gbs": {
      "p": "regex /bandwidth ([0-9.]+) GB/s/",
      "s": "value",
      "v": 48.585
    }
  },
  "run": {
    "drift": [],
    "duration_s": 0.072,
    "exit_code": 0,
    "output": "size 1048576 bytes  iters 200  bandwidth 48.585 GB/s",
    "output_truncated": false,
    "started_at": "2026-08-27T21:52:34+00:00"
  }
}
```

| namespace | what |
|---|---|
| `source` | commit, dirty flag, submodules |
| `build` | compiler, flags, CMake cache entries |
| `execution` | launcher, launcher args, program, program args, **sha256 of the binary**; under a harness, the command it times and **that command's sha256**; sha256 of any script argument |
| `system` | governor, turbo, SMT, ASLR, hugepages, power source, thermal throttle, load, container, VM |
| `hardware` | CPU, NUMA, GPU model/count/driver, CUDA -- **for every node of an allocation** |
| `runtime` | MPI implementation and version, transport configuration, tuning variables |
| `toolchain`, `deps` | language toolchain versions, **lockfile hashes**, container image |
| `parallelism`, `scheduler` | ranks, threads, binding intent, Slurm allocation |

`runtime.env.*`, `toolchain.*` and `deps.*` come from **ecosystem packs** that
activate from what is in the tree and on PATH: `Cargo.toml` turns on
`RUSTFLAGS` and `Cargo.lock`; `mpirun` on PATH turns on LCI, UCX and OMPI
variables; `nvidia-smi` turns on NCCL and CUDA. A Node project is never asked
about UCX.

### Four states, not two

| state | meaning |
|---|---|
| `value` | captured |
| `not_applicable` | structurally absent -- no GPU in this machine |
| `unknown` | may exist, could not be read -- `nvidia-smi` hung |
| `error` | the collector itself failed |

Two GPU-less laptops agreeing on `not_applicable` is a match. A laptop
against a GPU node is a difference. An `unknown` anywhere is neither: it is
reported separately and the comparison is not certified, because the response
differs -- a difference means the experiment is confounded, an unknown means
the capture is incomplete.

The rule: **a tool's absence implies the thing's absence only when the tool
*is* the thing.** No `nvidia-smi` means no NVIDIA stack. No `git` does not
mean no commit.

```console
$ ceteris compare examples/run-a.json examples/run-b-gpu-probe-failed.json
2 runs compared. Declared varying: nothing

UNKNOWN (could not be captured -- comparison is not certified):
  hardware.gpu_driver
      run-b-gpu-probe-failed: unknown: timed out after 10.0s
      run-a: known, <not applicable>

Matched on 107 other fields.
$ echo $?
2
```

(`run-b-gpu-probe-failed.json` is `run-a.json` with one field hand-edited to
`unknown`; a hung `nvidia-smi` cannot be produced on a machine without one.
It is the only non-captured file in `examples/`.)

## Harnesses it understands

| harness | how it is recognised | what ceteris does |
|---|---|---|
| hyperfine | `hyperfine` on the command line | adds `--export-json` if absent, reads median and min; records the timed commands as `execution.subject` and hashes their binaries |
| Google Benchmark | any `--benchmark_*` flag | adds `--benchmark_out`, reads `real_time` |
| pytest-benchmark | `pytest` with `--benchmark*` | adds `--benchmark-json`, reads medians |
| JMH | `-rf json` | reads `-rff` output |
| criterion | `cargo bench` | reads fresh `target/criterion/*/new/estimates.json` |
| OSU micro-benchmarks | `osu_*` | parses the size/value table |
| nccl-tests | `*_perf` | parses out-of-place busbw |
| MLPerf loadgen | `mlperf` / `loadgen` in the command | reads `mlperf_log_summary.txt` |

Anything else: `--metric NAME='regex with one (group)'`, or `--ingest FILE`.
A pattern that does not match records `unknown`, never zero. The hyperfine,
Google Benchmark and pytest-benchmark parsers are tested against files those
tools produced; the other five against formats reconstructed from their
documentation, and say so in their tests.

## Where it plugs in

**Any script.** `ceteris run -- <command>` passes the command's exit code
through, so wrapping changes nothing.

**A batch job.** Inside the sbatch script, wrapping the launcher. Every node of
the allocation is fingerprinted via a one-task-per-node `srun` inside the
existing allocation; a node that fails to report makes the hardware fields
`unknown`, because fifteen of sixteen nodes is not a fingerprint.

```bash
#SBATCH -N 16 -n 256
export LCI_ATTR_PACKET_SIZE=73728
ceteris run --label "lci-$LCI_ATTR_PACKET_SIZE" --repo ~/hpx --cmake-cache ~/hpx/build \
    --store ~/campaigns/collectives -- srun ./bench_all_to_all --size 4096
```

**A pull request.** The action checks out the base, builds, runs the
benchmark, does the same for the head, and fails the check unless the
comparison is valid. Check out with the full history so both commits are
reachable:

```yaml
- uses: actions/checkout@v4
  with: { fetch-depth: 0 }
- uses: iemAnshuman/ceteris@main
  with:
    build: cargo build --release
    command: hyperfine -N 'target/release/mytool bench.dat'
    repeats: "5"
    require-signal: "true"
```

Without `build`, both sides run whatever binary was already in the tree. The
record hashes the command hyperfine times, not hyperfine, and the action
declares that hash as the thing expected to vary; when it does not, the report
says so under *declared but did not vary*.

**pytest.** `pytest --ceteris` records the session; with pytest-benchmark
installed, its results come along.

**A library.** `from ceteris import compare`, `from ceteris.runner import
run_command`.

## Checking the capture itself

A fingerprint is 150 fields, and reading it by eye to decide whether ceteris
understood the machine does not scale. `ceteris doctor` does it:

```console
$ ceteris doctor
this machine: 127 fields (29 captured, 98 not applicable, 0 unknown, 0 error)

WORTH KNOWING (will widen the noise floor):
  source.dirty  the working tree had uncommitted changes; the commit does not describe the code

Active ecosystem packs: hpc, python
```

Three groups, and the middle one is the point:

- **LOOKS WRONG** -- a claim contradicted by the machine itself. "No GPU" is
  a normal answer on a laptop and a suspicious one where `/dev/kfd` exists.
  Exit 1. This is the check that would have caught the AMD bug before a
  cluster did.
- **COULD NOT BE READ** -- every unknown, with its reason. Exit 2.
- **WORTH KNOWING** -- turbo on, a scaling governor, battery power, a busy
  machine, a dirty tree. Never a failure; these are the things that make
  numbers move before any code changes.

Pass a record file to inspect a capture from another machine, which is the
useful form when someone sends you one:

```sh
ceteris doctor examples/rostam/het2.json
```

## Declaring intent

```sh
--vary build.cxx_flags                  # exact
--vary 'runtime.env.LCI_*'              # glob
--vary execution.program_args           # the sweep is in the arguments; rank count still gates
--vary execution.subject                # a harness timed a different command; its options still gate
--waive hardware.cpu_model:"same partition, different node draw"
--require-signal                        # exit 4 unless a metric beats the noise floor
--strict                                # informational fields gate too
```

`--waive` needs a reason and the reason lands in the certificate. A declared
field that did not vary is flagged (the sweep did not apply); a declaration
matching no field is flagged (typo). Fields carry a severity -- `critical`
and `material` gate, `informational` is shown -- and unlisted fields gate.

## Exit codes

| code | meaning |
|---|---|
| 0 | valid: every difference was declared |
| 1 | undeclared differences, or a confound |
| 2 | something could not be captured, or the environment changed mid-run |
| 3 | usage |
| 4 | valid but within noise, or nothing was measured (`--require-signal`) |
| 130 | interrupted; the benchmark was terminated |

## Configuration

`./ceteris.toml` is picked up automatically:

```toml
packs = ["cuda"]                       # force a pack on

[capture]
env_allowlist = ["MY_PROJECT_TUNABLE"]

[severity]
"hardware.hostnames" = "critical"      # heterogeneous partition: the nodes matter

[metrics]
latency_us = "avg latency ([0-9.]+) us"
```

The record format is specified in [`docs/SPEC.md`](docs/SPEC.md) so that
harnesses can emit it directly.

## What it does not do

- It does not measure. The harness measures; ceteris asks where the result went.
- It does not claim statistical significance. Median and range, and the
  honest word *unassessed* below three repeats.
- It does not capture the transport MPI actually negotiated, per-rank
  observed affinity, or NUMA topology beyond a node count. Each could be
  filled with a plausible value, and a plausible value in a fingerprint is
  the exact error the tool exists to catch.

## Status

Alpha, but the parts that matter have run on real hardware. CI covers Ubuntu
and macOS on Python 3.9 through 3.14. Ten records captured on **LSU's Rostam
cluster** are committed under [`examples/rostam/`](examples/rostam/), each
verified against ground truth taken in the same job:

| verified on real hardware | |
|---|---|
| `ceteris run` with `--repeats` across two nodes | Open MPI 5.0.7, gcc 14.3.0 |
| per-node fan-out, homogeneous **and heterogeneous** | CUDA 12.8 via `nvcc` |
| Slurm field mapping | NVIDIA V100 via `nvidia-smi` |
| Linux CPU, NUMA, governor, turbo, SMT, ASLR, THP | AMD Instinct MI100 via `rocm-smi` |
| container identity inside a real Apptainer image | a real `CMakeCache.txt` |
| rust, go, node and JVM toolchains and lockfiles | |

Those runs found six bugs, all fixed: `ceteris compare` certified three runs
whose benchmark had exited 183; `system.*` was taken from the head node
alone; a failing `nvidia-smi` on a GPU-less login node blocked every
comparison; the ROCm parser asked `rocm-smi` two questions in one call and
lost every card row; `java -version` writes to stderr so no JDK was ever
recorded; and one fingerprint contradicted itself about being in a container.

**Still unverified — treat as unproven, not as working.** Every one of these
is written from documentation, which the ROCm case showed is wrong about half
the time:

- schedulers other than Slurm (PBS, LSF, Flux, Grid Engine)
- MPI other than Open MPI (MPICH, Intel MPI, MVAPICH)
- five of the eight harness adapters: JMH, criterion, OSU, nccl-tests, MLPerf
- ARM CPUs (`/proc/cpuinfo` has no `model name` there; it degrades to
  `unknown`, so it fails safe)
- the AMD `cpufreq/boost` turbo path, fan-out beyond two nodes, and GPUs
  within one node reporting different driver versions

If you run ceteris on any of those, `ceteris capture -o fp.json` and the
resulting file is the most useful thing you can send.

```sh
python -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/python -m pytest
```

# Changelog

## 0.3.0 (2026-09-04)

Fixes found by reviewing every path the tool can fail open on. Each shipped
with a regression test.

### The certificate now binds the whole record (format v2)

The v1 line hashed only the gating fields and one boolean per metric, so a
measurement could be nudged, or an informational field rewritten, without
failing `ceteris verify`. Version 2 hashes every record in full (fields,
metrics, exit code, drift), carries `--require-signal` so a within-noise
verdict can be reproduced, percent-encodes waiver reasons so any reason
round-trips, sorts the noise verdicts so the file order does not matter, and
names the severity configuration it was issued under. Version 1 lines are
refused with a reason.

### What is under test is fingerprinted

Under a harness the record used to hash the harness: `hyperfine 'tool bench'`
recorded the sha256 of hyperfine. Records now carry `execution.subject` (the
commands the harness times), `execution.subject_sha256` (their executables,
keyed by executable) and `execution.subject_scripts_sha256`; script arguments
of a plain program are hashed as `execution.program_scripts_sha256`. The
GitHub Action gained a `build` input, run after each checkout, and declares
the subject hashes as the thing expected to vary. Schema version is 3.

### Fail-closed fixes

- A repository git refuses (dubious ownership, the usual case on shared
  clusters and in CI) and a nonexistent `--repo` were `not_applicable` and
  compared as agreeing; both are `unknown` now.
- AMD GPUs on a node that also ships `nvidia-smi` were never identified,
  because the failing NVIDIA probe claimed the answer. `rocm-smi` is asked.
- A multi-node job under PBS, LSF, Flux, or Slurm without `srun` described
  the head node as the allocation; its node-local fields are `unknown` and
  `ceteris doctor` flags a record whose node count contradicts the scheduler.
- LSF's node count came from a slot count.
- `--require-signal` with no metric at all exited 0.
- A benchmark killed by a signal exited 0 through `ceteris run`.

### Behaviour fixes

- Harness export files were created in the working tree, so every zero-config
  run in a clean repository drifted on `source.dirty`. They go to the temp
  directory.
- Configurations are grouped by canonical value, the way fields are matched,
  so reordered flags or a different provenance no longer split a
  configuration in the table.
- `scheduler.nodelist` and `build.cmake_cache_path` are informational.
- The store no longer writes a `*` gitignore into the parent of a custom
  store named `runs`.
- Non-UTF-8 output no longer aborts the run; Ctrl-C terminates the benchmark
  and exits 130; Google Benchmark repetitions fold into a median; a
  multi-valued regex metric says so instead of "no value";
  `execution.command` keeps its quoting.

## 0.2.0

First release on PyPI.

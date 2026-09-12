# Supported scope for 0.4

The supported entrypoints are `capture`, `run`, `compare`, `verify`, `doctor`,
`list`, the root GitHub Action, and pytest session recording. A passing legacy
comparison checks the captured fields and required run evidence under the
selected policy. It does not prove all confounds were observed, validate an
arbitrary program's output, or establish non-regression.

| Area | Status and evidence |
|---|---|
| Python 3.9–3.14, Ubuntu and macOS | CI matrix; new release artifacts depend on those checks. |
| Hyperfine | Real committed exports, executable integration tests, and local smoke runs. |
| Google Benchmark | Real committed exports and parser/validity regression tests. No new hardware run during the September 9 repairs. |
| pytest-benchmark | Real session integration tests, expected-case enforcement at comparison, and wrapper/plugin execution linkage. |
| Slurm, Open MPI, NVIDIA/AMD, Apptainer collectors | Historical Rostam fixtures described in the README. Not revalidated on cluster hardware during these repairs. |
| JMH, criterion, OSU, nccl-tests, MLPerf | Experimental; reconstructed fixtures do not establish real-version compatibility. |
| Other schedulers/MPI implementations; Linux ARM; large allocations | Unverified paths listed in the README. Do not infer support from another platform's successful test. |
| `plan`, `migrate`, schema-4 protocol libraries | Experimental. Plans require a matching profile supplied as JSON and full commit IDs. No installed native profile or campaign execution is provided. |
| Receipt-v3 bundles | File integrity checks only in the CLI. Verified acceptance and stronger availability levels are unavailable and fail closed. |
| `v2/` Action | Disabled scaffold; exits before installation, checkout, or builds. Use the root Action for legacy comparisons. |

The root Action takes comparison configuration from the base revision and
keeps it fixed. Its command is quoted argv; use an explicit shell invocation
for pipelines or shell expansion. Source/dependency and resulting binary-hash
changes remain declared by default for that legacy integration.

The Action is not an execution sandbox or a producer attestation service.
Benchmark code runs with the job's permissions.

Independent methodology review, independent-verifier agreement, a complete
prospective campaign workflow, and external beta evidence remain prerequisites
for the broader claims in [DESIGN.md](DESIGN.md#195-gates).

## 0.4.1 correctness update

Version 0.4.0 could produce a passing certificate for an invalid required
export in these cases:

- Automatic `--ingest out.json` detection saw a Google Benchmark failure
  before any successful case and treated the export as pytest output.
- A required export contained null, boolean, nonnumeric or nonfinite
  measurements. Google Benchmark repetition folding could also discard an
  unreadable repetition while retaining usable ones.

Upgrade to 0.4.1 and rerun these captures and comparisons from the benchmark
commands, producing fresh exports. A later successful verification of file
integrity alone does not establish that the original comparison passed.
`verify --require-pass` also checks the recomputed acceptance result.

The new comparison checks reject unreadable required measurements still
present in older records. They cannot recover failures or repetitions that
an older importer omitted. Regenerate affected evidence rather than relying
on an old passing certificate.

The experimental decimal, artifact, per-node and recovery repairs also require
recomputation of affected results: rerun decimal analyses from original
measurement text, regenerate directory manifests with child symlinks and node
identity keys, and reload campaign recovery state with the updated library.

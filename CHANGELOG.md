# Changelog

## 0.4.0 (2026-09-12)

This release tightens evidence checks in the capture/compare workflow. Planned
campaigns, the `v2/` Action, and schema-4 acceptance verification remain
experimental and are excluded from the supported scope. See [SUPPORT.md](docs/SUPPORT.md).

### Shipment review repairs (9–11 September)

- Give each new execution a stable ID and reject relabelled copies, including
  wrapper/plugin views of the same pytest session. Legacy duplicate detection
  ignores presentation and storage metadata.
- Bind new execution evidence into certificates. Reject malformed imported
  fields and exit codes before comparison; missing required pytest cases and
  explicit unavailable pre/post observation block certification.
- Apply freshness and harness-validity checks to explicit `--ingest` exports.
  Missing measurements within a configuration remain unassessed instead of
  disappearing from the signal check.
- Stream output in bounded byte chunks, including long lines, and record
  accurate dropped-byte counts. Preserve newline normalization for CRLF and
  CR output so line-anchored metric patterns keep working. Return detached
  views of frozen plans.
- Freeze the root Action's base configuration before building and use it
  throughout capture and comparison. Give each invocation its own evidence
  directory; parse command inputs as argv instead of shell interpolation.
- Check bundle paths and size limits before reading, including ancestor
  symlinks. The experimental bundle CLI verifies integrity only and refuses
  unsupported acceptance and availability claims.
- Require an explicit matching profile and full commit IDs for experimental
  plans. Keep the unfinished v2 Action disabled before setup. Campaigns and
  schema-4 acceptance are excluded from the 0.4 release scope.
- Make release builds depend on the test matrix; exclude floating major tags
  from publishing triggers. Clarify the supported scope and signal semantics.

### Earlier design repairs

The twelve correctness repairs in Section 3 of [the design](docs/DESIGN.md).
Each was reproduced first, each has a regression test named for its issue,
and each is its own commit. Every one of them is a case where the tool
could report a false success.

### Certificates say only what they can prove (format 2, tightened)

- **F01** The line's *displayed* claims were unauthenticated. Editing
  `verdict=confounded` to `verdict=ok` still printed `verified: ok` and
  exited 0, because the digest bound the recomputed report while `verify`
  echoed the line's own words back. Every displayed field is now recomputed
  and checked, the verdict vocabulary is closed, and verification separates
  *this line honestly describes these records* from *the comparison passed*.
  `verify --require-pass` asks the second question; exit 5 is an integrity
  mismatch.

### Differences that were reported as matches

- **F02** Token sorting made `-n 2 -N 4` equal to `-n 4 -N 2`, and
  `-I a -I b` equal to its reverse. Command lines and flag strings now
  compare in order, `flagset` is retained only as a named legacy comparator,
  and each launcher family has its own option grammar. A launcher option
  outside its grammar makes the decomposition unknown instead of guessed.
- **F03** Subject identity was collected after the command finished, so a
  program that rewrote itself was recorded as the thing it became,
  identically on every run, with no drift. Identity is taken before launch
  and again after, and the difference is drift.
- **F05** One record offered three times produced three samples, a zero
  spread and a signal. An execution now contributes at most once; copies,
  repeated arguments, symlinks and repeated object references are refused.
- **F12** Two empty captures compared successfully. A record carrying no
  gating evidence certifies nothing, and a configuration that produced no
  value for a metric no longer vanishes from the noise assessment.

### Results that were not results

- **F04** NaN satisfied `--require-signal`, because every comparison against
  NaN is false. NaN, infinities, booleans and malformed numbers are refused
  before any statistic, and the relative-noise method states that it needs
  strictly positive samples.
- **F06** `Result is : INVALID` arrived as a string metric that no statistic
  read, so the comparison passed. A harness verdict is now evidence, not a
  measurement, and a harness that declares its own run invalid has failed
  whatever the exit status was. Absence of a claim is *unverified*.
- **F07** A pre-existing export was read as this run's result. Export files
  are snapshotted before launch and an unchanged file is rejected as stale.
  Caller-owned files are never deleted to make freshness easy.
- **F08** Two equally specific policy rules resolved by dictionary order, so
  the same policy written in another order gated differently while hashing
  the same. A tie is refused with both patterns named, and the policy
  identity now includes the engine that read it.

### Evidence that was lost

- **F09** Interrupting a repeat discarded the repeats that had already run.
  Each record is written before the next run starts, and writes are atomic.
- **F10** All output accumulated in memory to keep a 64 KiB tail. Output
  streams through a bounded spool that records what it dropped, and
  interruption terminates the process group rather than one process.
- **F11** Comparison grouped on canonical values while drift compared whole
  fields, so a provenance string changing marked a run uncertifiable. One
  equivalence rule serves both. The pytest plugin captured only at session
  end and wrote an empty drift list; it now observes both ends, or says it
  could not.

### The protocol, built alongside the shipped format (WP03 to WP11, WP15)

None of this replaces schema 3 yet. `ceteris run` still writes schema 3, and
`compare` still evaluates it. What exists now is the machinery the planned
flow needs, each piece pure and separately testable:

- **`ceteris.protocol`** — the canonical encoding `ceteris-json-v1` with byte
  vectors frozen in a fixture, exact decimals and rationals, schema 4 typed
  values, and a validator that reports structured issues instead of raising.
- **`identity`** — artifact manifests by content rather than metadata,
  source snapshots that hash bytes rather than record a dirty flag, and
  command identity where two worktrees of one experiment are not a workload
  difference while a different input still is.
- **`policy`** — rules with explicit integer priority, so source order never
  decides and a tie is an error; `typed-exact@1` and `multiset@1`; waivers
  that need a reason and a reference and cannot reach a malformed record, a
  duplicate execution, an invalid harness result, a failed check or a broken
  receipt.
- **`coverage`** — expected evidence from the frozen plan, never from the
  records that happened to arrive, with three-valued conditions where an
  unreadable input is unresolved and never quietly false.
- **`experiment`** — an authored experiment frozen into an immutable plan,
  with a schedule generated from a documented digest rather than a language's
  random number generator, so another implementation schedules identically.
  Amendments create a new lineage labelled retrospective.
- **`analysis`** — `descriptive@1`, and `paired-median-relative@1` as the
  reference inferential method: exact rational pair effects, a
  distribution-free order-statistic interval, and non-regression,
  improvement and equivalence predicates. Rounding is for display only. The
  method is experimental until it has independent methodology review.
- **`validators`** — correctness claims bound to the subject and input
  identities they were checked against, so a claim about a previous build
  cannot be read as covering this one.
- **`campaign`** — durable commits, a run ID that is never reused, an
  idempotent recommit, and a resume that never reruns a finished slot and
  never substitutes a replacement measurement into the original analysis.
- **`report`** — one semantic report that renderers display and never
  decide, with every dimension kept after one of them has settled the
  outcome.
- **`bundle`** — `ceteris-receipt v3`, which carries a manifest reference and
  no verdict. CLI verification is offline, read-only, and checks file
  integrity with bounded reads that refuse symlinks. Acceptance requires a
  trusted recomputation callback at the library level; the CLI cannot verify
  acceptance or availability beyond records-only packaging.
- **`migration`** — reads schema 2 and 3 without letting them gain evidence.
  Every gap becomes a named limitation, and a legacy record qualifies for a
  policy only when it genuinely satisfies it.

Experimental commands: `ceteris plan`, `ceteris migrate`, `ceteris bundle verify`,
`ceteris bundle inspect`. These do not provide an executable campaign workflow.

### Integrations and the report page (WP12 to WP14)

- **`v2/action.yml`** is a disabled scaffold for the planned campaign workflow.
  It exits before installation, checkout, or builds. The supported root Action
  runs legacy comparisons using the base configuration frozen before builds.
- **The pytest plugin** treats one session as one outer execution. Twenty
  pairs means twenty sessions per variant, never twenty inner rounds in one.
  It records the session's own outcome, so a test failure is failed
  correctness for its scope and another benchmark producing numbers does not
  cover for it. `--ceteris-expect-case` makes a case that never appeared
  incomplete evidence. `CETERIS_PARENT_RUN_ID` links a wrapped session to the
  wrapper's run so one session is never counted as two measurements.
- **`nodes_evidence`** keeps per-node evidence per node, with the multiset as
  a derived view rather than the storage. A missing, duplicated, malformed or
  wrong-plan response are four named outcomes, not silence. Node IDs are
  campaign-local pseudonyms; a real host name is optional disclosure. The
  fan-out probe's own affinity is labelled as the probe's, never offered as
  the benchmark's.
- **`html`** renders a static report that opens offline: no network, no
  script, every supplied string escaped, colour never the only signal, and an
  execution-order plot beside a table of the same numbers. It displays a
  report and computes nothing.

### Migration

Policy and evidence-digest changes can require reissuing older certificates
with `ceteris compare --certify`. Verification recomputes the comparison;
it does not upgrade an old claim automatically. The committed schema-2
Hyperfine example still verifies. Version 1 certificates are refused.

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

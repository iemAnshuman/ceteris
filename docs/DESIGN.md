# Ceteris: design for a benchmark comparison standard

Status: proposed implementation design; no features described here are implied to exist yet.

Design revision: 1, 2026-09-05.

Implementation baseline: Ceteris 0.3.0, record schema 3, certificate format 2.

Audience: maintainers, implementers, adapter authors, methodology reviewers, and early adopters.

This document turns the eight recommendations from the readiness review into an implementation contract. MUST, MUST NOT, SHOULD, and MAY express requirements of the proposed protocol. Release names below are planning targets, not published commitments. The existing [record specification](SPEC.md) remains the description of the shipped format until a release explicitly replaces it.

## Contents

1. [Outcome and scope](#1-outcome-and-scope)
2. [Decisions and invariants](#2-decisions-and-invariants)
3. [Immediate correctness repairs](#3-immediate-correctness-repairs)
4. [Architecture and module ownership](#4-architecture-and-module-ownership)
5. [Protocol objects and canonical encoding](#5-protocol-objects-and-canonical-encoding)
6. [Experiment specification and resolution](#6-experiment-specification-and-resolution)
7. [Coverage and comparison policy](#7-coverage-and-comparison-policy)
8. [Execution lifecycle and persistence](#8-execution-lifecycle-and-persistence)
9. [Workload and environment identity](#9-workload-and-environment-identity)
10. [Adapters and correctness evidence](#10-adapters-and-correctness-evidence)
11. [Measurement analysis](#11-measurement-analysis)
12. [Reports, decisions, and exit codes](#12-reports-decisions-and-exit-codes)
13. [Receipts, bundles, and offline verification](#13-receipts-bundles-and-offline-verification)
14. [CLI and Python interfaces](#14-cli-and-python-interfaces)
15. [CI, pytest, and distributed execution](#15-ci-pytest-and-distributed-execution)
16. [Compatibility and migration](#16-compatibility-and-migration)
17. [Testing and conformance](#17-testing-and-conformance)
18. [Implementation work packages](#18-implementation-work-packages)
19. [Adoption, governance, and release gates](#19-adoption-governance-and-release-gates)
20. [Risks, deferred work, and references](#20-risks-deferred-work-and-references)

## 1. Outcome and scope

### 1.1 Product statement

Ceteris records the evidence behind a benchmark comparison and determines whether that evidence satisfies an explicit comparison policy. A recipient can reproduce the decision from an offline bundle. A harness or independent producer can emit the same protocol without invoking the Ceteris runner.

The product does not promise that every possible confound was observed. Its precise positive claim is:

> These executions satisfy this policy, for these benchmark cases and metrics, under these recorded capabilities, declarations, exclusions, and analysis assumptions.

An empty capture, a failed correctness check, or an unsupported analysis MUST NOT receive an unrestricted success label.

### 1.2 Initial supported workflow

The first complete workflow is a baseline/candidate comparison of native-code revisions on one Linux host using Hyperfine or Google Benchmark. Both revisions are built in isolated directories. Executions are paired and their order is balanced. Required inputs and correctness evidence are declared. The output is a report and an offline bundle.

macOS remains supported for collection and supported local comparisons. Existing Slurm capabilities remain maintained; distributed assurance is explicitly scoped to observed nodes and capabilities. Python/pytest is the next complete integration. Other existing adapters retain diagnostic use with explicit support status until they pass integration gates.

### 1.3 Non-goals for the first protocol release

- A hosted benchmark dashboard, billing, or an account requirement.
- Proof of truthful observations on an adversarial machine.
- A guarantee of causal attribution or the absence of all confounds.
- Automatic instrumentation of every loaded library or remote service.
- A universal statistical procedure for every performance metric.
- Automatic machine tuning, privileged installation, or scheduler submission.
- Claiming Windows or an untested platform is supported because Python runs there.

### 1.4 Mapping to the eight readiness recommendations

| Recommendation | Concrete deliverables |
|---|---|
| Repair false success | Section 3 repairs; adversarial regression fixtures |
| Define success precisely | Sections 7 and 12; separate verdict dimensions |
| Model experiments and coverage | Sections 5–7; authored plan, resolved plan, capability evidence |
| Identify the workload | Section 9; artifact manifests, source identity, runtime scope |
| Strengthen measurement | Section 11; independent execution IDs, pairing, exact reference method |
| Improve adoption workflow | Sections 8, 13–15; campaign runner, bundles, CI, diagnostics |
| Prove reliability/interoperability | Sections 16–17; schemas, migration, conformance corpus |
| Earn adoption | Section 19; external beta, integration targets, governance, release criteria |

## 2. Decisions and invariants

### 2.1 Decisions

| ID | Decision | Reason |
|---|---|---|
| D01 | Keep a standard-library-only core on Python 3.9+ during this migration. | Existing cluster installations must remain usable. Development and optional integrations may have dependencies. |
| D02 | Use JSON as the normative exchange and plan format. | It works on every currently supported interpreter. TOML is a convenience authoring format, converted before resolution. |
| D03 | Introduce record schema 4, experiment schema 1, report schema 1, bundle schema 1, and receipt format 3 independently. | A change to one object must not silently change the meaning of another. |
| D04 | Keep the current low-level field comparison API, but distinguish diagnostic comparison from policy evaluation. | Partial records are useful without granting complete assurance. |
| D05 | Use declared variant IDs for experimental groups. | Environmental differences are evidence to evaluate, not instructions to regroup a failed experiment. |
| D06 | Preserve command order by default. | Incorrect equivalence is more harmful than an explainable extra difference. |
| D07 | Separate correctness evidence from process exit status. | Exit zero is not proof of a correct answer. |
| D08 | Freeze the resolved plan and policy before a campaign starts. | Results must not silently determine the rules by which they pass. |
| D09 | Start with one narrowly specified paired analysis method and diagnostic summaries. | Independent implementations need a reproducible target. Broader methods can be versioned extensions. |
| D10 | Use immutable records and derived artifacts. | Redaction, migration, and reanalysis must preserve provenance without rewriting originals. |
| D11 | Verification is read-only and offline by default. | Verifying someone else's result must not execute their benchmark, plugin, shell command, or download instruction. |
| D12 | A policy pass with waivers is visibly different from an unwaived pass. | An accepted exception must remain discoverable in every report and receipt. |

### 2.2 Invariants

1. Unknown, unsupported, omitted, and structurally absent evidence are not interchangeable.
2. A declared variable permits a known difference; it does not supply missing evidence.
3. A failed benchmark or correctness check cannot be made successful by a field waiver.
4. Every primary metric has an explicit benchmark identity, unit, direction, domain, and aggregation rule.
5. An execution contributes at most once to a given analysis. Relabeling or copying its file does not create a new execution.
6. Required evidence missing from every input still causes incomplete coverage.
7. The decision is a pure function of validated inputs, resolved policy, and versioned method semantics.
8. Changing a displayed semantic claim invalidates its receipt or produces a different receipt.
9. A complete execution survives interruption of a subsequent execution.
10. The capturing process's environment is labeled as such; it is not silently attributed to remote ranks, containers, or subjects.
11. Reanalysis cannot change the original plan, pairing, exclusions, or sample-selection history.
12. Unsupported versions and required extensions produce an unsupported result, never an optimistic fallback.

## 3. Immediate correctness repairs

Ship these changes before broad promotion. Implement them against the current architecture first; do not make them depend on all of schema 4. Each ID becomes a regression fixture and work item. Reproductions listed as observed were exercised in the readiness review with small synthetic records or isolated processes. They are not claims of an exhaustive security or methodology audit.

### F01 — certificate display is not authenticated

Current location: `src/ceteris/certificate.py`, `Parsed`, `parse`, `verify`.

Observed: replace `verdict=confounded` with `verdict=ok` in a valid v2 line; verification returns `(True, "verified: ok")`. `configs`, `n`, and `noise` can also be changed without rejection.

Repair:

1. Parse all displayed fields with a closed verdict enum and strict numeric grammar.
2. Recompute the expected verdict, configuration count, count multiset, and noise summary from the report.
3. Validate all of them in addition to the existing digest.
4. Treat legacy `n` as an unordered multiset because v2 hashes do not bind discovery order of configurations. Explain this limitation in the legacy verifier.
5. Return `integrity_verified` separately from `comparison_passed`. A verified failed result must say so.
6. Add `verify --require-pass`; default legacy verification can keep integrity-oriented exit behavior, but must not print a success verdict from untrusted input.

Acceptance: mutate each displayed field independently; every false semantic claim fails. Permuting input files still verifies. An honestly recorded failed comparison verifies its integrity but fails `--require-pass`.

### F02 — token sorting changes command semantics

Current locations: `comparators.py`, `defaults.json`, `execution.py`.

Observed: `-n 2 -N 4` and `-n 4 -N 2` compare equal; so do `-I first -I second` and the reverse search order.

Repair:

- Change `execution.launcher_args` to ordered comparison immediately.
- Replace default compiler `flagset` use with conservative ordered comparison. Retain the old comparator only under a clearly named legacy engine, never as a new-policy default.
- Preserve exact argv token boundaries. Do not use whitespace splitting to reconstruct shell syntax.
- A future semantic comparator may normalize only explicitly proven independent options, must retain option/value pairing, and must have a versioned identifier and conformance fixtures.
- Correct `--exclusive` as a valueless Slurm option; introduce launcher-specific grammars rather than one shared option table. Unknown ambiguous launcher syntax yields an opaque command plus incomplete decomposition coverage.

Acceptance: swapped counts, reversed include/library paths, macro redefinitions, quoted spaces, repeated flags, `--`, and malformed options never collapse incorrectly. Extra reported differences are acceptable during migration.

### F03 — hashes are collected after execution

Current location: `runner.py`, `run_command`.

Observed: a script replacing itself during its first run and executing the replacement on its second run gets identical recorded hashes and no drift.

Repair: collect execution identity and explicit immutable artifact identity before launch and after completion. Add these observations to the same drift evaluator as other evidence. Never derive the pre-execution identity from the post-execution filesystem. Hash immediately before launch, detect changes during hashing with before/after file metadata checks, and state that this narrows rather than eliminates races. Executed-file attestation is a later optional capability.

Acceptance: a script or executable changing before, during, or after its use cannot be represented as one unchanged observed identity. The self-rewrite fixture must fail comparability. Explicit writable output artifacts do not trigger immutable-input drift.

### F04 — non-finite and inappropriate metric values

Current locations: `stats.py`, `metrics.py`, adapters, `model.py`.

Observed: NaN samples satisfy `--require-signal`.

Repair: reject NaN, infinities, booleans, and malformed numeric values before statistical reduction. The legacy relative-noise method supports strictly positive values only; otherwise return unassessed with a reason. New metrics use the explicit domains in Section 5. Invalid export values become failed metric extraction evidence; they must not crash the process or become zero.

Acceptance: exercise NaN in every sample position, positive/negative infinity, booleans, zero denominators, overflow, numeric strings, missing fields, and multi-valued regex matches. No invalid value produces a signal verdict.

### F05 — duplicated observations manufacture sample size

Current locations: `cli.py` input loading, `stats.py` grouping.

Observed: two records passed three times each produce three samples per configuration and a passing signal.

Repair now: reject duplicate resolved file identities and repeated identical legacy record payloads in signal analysis with `duplicate_observation`. Do not silently count or discard them. Byte-identical legacy observations may be real repeats, but independence cannot be established; explain how to recapture with run IDs. Schema 4 uses execution IDs and immutable record digests. Do not deduplicate legitimate new executions solely because their metrics/environment are equal.

Acceptance: repeated arguments, symlinked input paths, copied files, and repeated object references cannot inflate `n`. Distinct schema 4 run IDs with equal measured values remain distinct observations, subject to the declared producer trust boundary.

### F06 — harness-invalid results are treated as numbers

Current location: MLPerf adapter and metric model.

Observed: `Result is : INVALID` is a string metric and does not prevent a passing signal verdict.

Repair: introduce an adapter-result object carrying metrics, parse diagnostics, harness validity, and correctness evidence. A reported harness failure is a failure even when the outer process exits zero. For the hotfix, propagate an explicit failed-run/adapter-validity marker understood by `compare`; do not overload a performance metric.

Acceptance: MLPerf `INVALID`, Google Benchmark error entries, missing required case output, malformed exports, and failed correctness checks cannot pass. Lack of a harness correctness claim is `unverified`, not `validated`.

### F07 — stale exports

Current location: adapter `plan` and `collect` methods.

Observed: a pre-existing Hyperfine export is accepted even when older than the supplied execution start.

Repair: inject a unique run-owned output path when the adapter supports it. If a caller supplies an export path, snapshot its existence, digest, and file metadata before launch; require evidence of a new export after launch, plus supported content checks. An unchanged old file is rejected as stale even if its contents happen to be plausible. Timestamp-only freshness is insufficient. Never delete or overwrite caller-owned files merely to make freshness easy. `import` is a separate workflow that records absent execution linkage.

Acceptance: stale file, timestamp granularity collision, wrong benchmark names, failed command leaving an old result, and export written outside the planned path all have deterministic outcomes.

### F08 — ambiguous policy precedence

Current locations: `config.py`, `compare.py::_config_digest`.

Observed: reversing equal-score glob rules changes effective severity without changing the sorted-map digest.

Repair now: reject conflicting equal-score rules on any evaluated path. Preserve a clear error identifying both patterns. Future policies use explicit priority and the resolution rules in Section 7. Persist the effective rules and the engine identifier; a short digest of unordered source maps is not sufficient policy identity.

Acceptance: permuting source dictionary order never changes a valid policy's verdict. Conflicting ties are errors. Comparator ties receive the same treatment as severity ties.

### F09 — completed repeats are lost on interruption

Current locations: `runner.py::run_repeated`, `cli.py::_cmd_run`, `store.py`.

Observed: interrupting repeat two prevents repeat one's record from reaching `save`.

Repair: add an internal record iterator or completion callback; the CLI persists each yielded result immediately. Keep the existing list-returning library wrapper for compatibility. Atomically save a terminal record before starting another repeat. Preserve a partial journal for an interrupted active run. Section 8 specifies the full implementation.

Acceptance: interrupt or simulate a crash at every lifecycle transition; completed executions remain readable exactly once. Failure to save stops the campaign before another measurement starts.

### F10 — resource and subprocess lifecycle

Inspection finding: all output accumulates in `chunks`; only the final saved text is capped. Ctrl-C terminates the immediate process, not an explicitly managed process group.

Repair: stream binary chunks to a bounded spool, retain a 64 KiB tail, decode display with replacement, and manage local process groups with bounded termination. Record truncation and lost evidence. Never claim control over remote MPI ranks unless the launcher integration provides that guarantee. See Section 8 for limits.

### F11 — false drift and weaker pytest capture

Observed: comparator-equivalent raw fields trigger drift. Inspection: the pytest plugin captures only at session finish and writes an empty drift list.

Repair: use one versioned field-equivalence function for comparison and drift. Compare observed states/values, not prose or provenance strings. Record new failed reads as incomplete post-capture evidence. Add pytest start/end observations; for collection-only or end-only modes, represent drift observation as unavailable.

### F12 — empty/missing coverage

Observed: two empty field maps compare successfully; a third configuration lacking the metric can disappear from noise assessment.

Repair: in legacy mode print an explicit limited-coverage warning and reject an empty capture for certification. Planned evaluation requires declared capabilities and complete primary-case selection, including fields missing everywhere. Keep ad hoc field comparison possible, labeled diagnostic. Do not redefine every optional metric as mandatory; enforce the plan's selected primary metrics.

## 4. Architecture and module ownership

The core boundary is between observation and evaluation. Observation may inspect files and launch commands. Evaluation and verification must be pure with respect to external machine state.

```text
authored experiment + selected profile + trusted policy
                         |
                      resolver
                         |
                   resolved plan (immutable)
                         |
            campaign scheduler / runner
             /           |           \
       collectors     artifacts     adapters + validators
             \           |           /
                journal -> immutable run records
                              |
                 schema and coverage validation
                              |
                 comparison -> analysis -> policy
                              |
                    report + receipt + bundle
                              |
               independent offline verifier
```

| Module | Responsibility | Side effects |
|---|---|---|
| `protocol/encoding.py` | Canonical JSON, decimal/rational validation, digests | None |
| `protocol/validation.py` | Structural and cross-object validation | None |
| `protocol/models.py` | Immutable protocol-facing types | None |
| `experiment.py` | Authoring validation, plan resolution, variant/pair expansion | Repository reads during resolution only |
| `policy.py` | Rule resolution, requirements, predicates, aggregate decision | None |
| `coverage.py` | Expected versus observed capability evaluation | None |
| `identity.py` | Artifact manifests, source manifests, semantic command IDs | Reads during capture |
| `campaign.py` | Build scheduling, pair order, resume, lifecycle | Subprocesses and campaign storage |
| `runner.py` | One execution, before/after capture, output transport | Subprocesses and spooling |
| `store.py` | Immutable records, atomic commits, journal recovery | Filesystem |
| `collectors/` and `nodes.py` | Scoped observations and capability results | Read-only probes, bounded fan-out |
| `adapters/` | Harness output planning and interpretation | Owned export reads; planning instructions |
| `validators/` | Explicit correctness checks | Only when executing an authorized plan |
| `compare.py` | Known-value relations and declared variation | None |
| `analysis/` | Versioned metric analysis methods | None |
| `report.py` | Deterministic report assembly | None |
| `certificate.py` / `bundle.py` | Receipt and manifest construction/verification | Explicit bundle reads/writes only |
| `render.py` | Text/JSON/HTML display of one report | Output only; no verdict computation |
| `cli.py` | Argument handling and routing | Delegates effects |

Do not move everything in one refactor. Introduce modules as work packages land; retain thin adapters for `Fingerprint`, `Report`, `capture`, and `compare` until their documented migration points. Renderer tests must not become the only tests of policy behavior.

## 5. Protocol objects and canonical encoding

### 5.1 Object graph and identifiers

The protocol comprises an authored experiment, a resolved plan, run records, evidence artifacts, a report, a manifest, and a receipt. Each file has a `kind` discriminator and an integer `schema_version` where applicable.

| Identifier | Meaning | Construction |
|---|---|---|
| `experiment_id` | Human-selected stable experiment name | ASCII identifier, 1–128 characters |
| `plan_digest` | Exact resolved rules and planned workload | Full SHA-256 of canonical resolved plan |
| `campaign_id` | One execution campaign | Lowercase UUIDv4 generated before work starts |
| `variant_id` | An intended configuration | Unique ASCII name within plan |
| `pair_id` | Baseline/candidate block | Stable ASCII ID within campaign and comparison |
| `run_id` | One process execution attempt | UUIDv4 created before launch; never reused |
| `attempt` | Retry position for a scheduled slot | Positive integer; all attempts retained |
| `record_digest` | Immutable record contents | SHA-256 of the full canonical record |
| `artifact_digest` | Evidence-file bytes | SHA-256 streamed over exact bytes |
| `report_digest` | Deterministic semantic report | SHA-256 of canonical report |
| `manifest_digest` | Bundle membership and roots | SHA-256 of canonical manifest |

Run ID uniqueness detects accidental duplication; it does not prove independent or honest execution. A producer can invent IDs. This is part of the trust statement, not solved by a checksum.

Digest-valued protocol members use the string form `sha256:` followed by 64 lowercase hexadecimal characters. Content-addressed filenames use only the 64-character suffix. ASCII identifiers use `[A-Za-z0-9][A-Za-z0-9._/-]{0,127}`; path-like IDs are names, not filesystem paths, and validators still reject traversal when constructing storage paths. Use UUIDs/digests, not arbitrary IDs, for record/artifact filenames.

### 5.2 Canonical JSON: `ceteris-json-v1`

Use a small deliberately restricted encoding rather than Python's default floating-point JSON behavior:

1. Input is UTF-8 without a BOM. Reject duplicate object keys and invalid Unicode, including unpaired surrogates.
2. Permitted values are null, booleans, strings, arrays, objects, and integers in `[-9007199254740991, 9007199254740991]`. Fractional JSON numbers are not permitted in schema 4 protocol objects. Decimal measurements are strings in typed fields.
3. Sort object keys by Unicode scalar value sequence. Array order remains significant unless the object's schema explicitly requires a canonical sort before encoding.
4. Emit compact JSON with no insignificant whitespace and no trailing newline in the hashed byte sequence.
5. Escape quote and backslash; use `\b`, `\t`, `\n`, `\f`, `\r` for those five control characters. Escape other U+0000–U+001F characters, U+007F, and all non-ASCII characters as lowercase `\uXXXX`; supplementary characters use the standard surrogate pair representation. Do not escape `/`. Do not apply Unicode normalization.
6. Encode integer zero as `0`; never emit `-0` or leading zeros. Emit booleans as JSON booleans, not integers.
7. Human-facing pretty JSON may differ in whitespace. Parsing and canonicalizing it must recover the same digest.
8. Do not put an object's own digest inside its hashed body. Its parent references the digest. This avoids circular exclusions and hidden mutable fields.

Implement a reference encoder and freeze byte-level test vectors before any new receipts are issued. This is a Ceteris-specific encoding, not a claim of compliance with an unrelated canonical JSON specification.

### 5.3 Decimal and rational values

Canonical decimal strings contain no exponent, leading plus, unnecessary leading zeros, trailing fractional zeros, or negative zero. Examples: `"0"`, `"12"`, `"0.125"`, `"-2.5"`. Accept at most 128 significant digits and an absolute base-10 exponent at most 308 during import; the expanded canonical representation must be at most 1024 characters. Reject larger values with `numeric_limit_exceeded` rather than rounding silently.

Adapters parse source decimal tokens without an intermediate binary float where possible. A source already expressed as a binary float must record that precision origin. Computed rational effects are encoded as `{ "numerator": "-1", "denominator": "10" }`; integers are canonical decimal integer strings, denominator is positive, and the fraction is reduced by greatest common divisor. Display rounding never participates in a policy decision.

### 5.4 Schema 4 run envelope

The following table is normative for the first schema 4 implementation. Additional names are permitted only under `extensions`, or as optional future members whose preservation is specified by the schema. An unknown required extension blocks evaluation.

| Member | Type and requirement |
|---|---|
| `kind` | Literal `ceteris.run` |
| `schema_version` | Integer `4` |
| `producer` | Object: `name`, `version`, `record_semantics` identifier |
| `run_id`, `campaign_id` | UUID strings |
| `experiment_id`, `variant_id` | ASCII identifiers |
| `plan_digest` | Full SHA-256 reference; null only for diagnostic/unplanned records |
| `assignment` | `comparison_id`, `pair_id`, `slot`, `attempt`; null for unpaired diagnostics |
| `timestamps` | UTC RFC 3339 start/end strings; duration as nonnegative decimal seconds; unavailable values explicitly null |
| `execution` | Requested argv, effective argv, logical cwd reference, lifecycle outcome, exit code/signal, timeout/cancellation information |
| `observations` | `before` and `after` scoped field maps; either snapshot may be unavailable with an explicit reason |
| `capabilities` | Capability evidence entries, including stage and scope |
| `artifacts` | Logical artifact ID to before/after content identity and availability |
| `metrics` | Array of typed metric observations keyed by case/metric identity |
| `correctness` | Array of validator/harness claims with evidence references |
| `drift` | `{ "status": "observed" or "unavailable", "changes": [...], "issues": [...] }` |
| `issues` | Structured collection, execution, parsing, and coverage issues |
| `extensions` | Optional namespaced extension objects |
| `requires` | Required extension/semantics identifiers; default empty array |

Every terminal record includes failed and missing observations rather than omitting the run. Fields required for a completed execution may be unknown in an abandoned attempt, but the outcome cannot then be `completed`.

### 5.5 Fields and capability evidence

Keep the four field states `value`, `not_applicable`, `unknown`, and `error`. `value` requires `v`, and non-value states forbid it. Provenance is structured as `collector_id`, `collector_version`, `source_kind`, `source_ref`, and optional detail. `not_applicable` requires an applicability reason and evidence reference; `not implemented` is not an applicability reason.

Observation maps are scoped: `controller`, `subject`, or `node/<node_id>`. Required capability evidence has:

```json
{
  "capability": "cpu.topology",
  "version": 1,
  "scope": "node/node-1",
  "stage": "before",
  "status": "observed",
  "fields": ["hardware.cpu_model", "hardware.cpu_cores_logical"],
  "reason": null,
  "evidence_refs": []
}
```

Capability statuses are `observed`, `not_applicable`, `unavailable`, `unsupported`, and `excluded`. A field-level collector exception is `error`; its capability is `unavailable` with the same issue reference. `excluded` records intentional scope/redaction choices. Expected stages and scopes come from the resolved plan, never from the set of records that arrived.

Capability entries may additionally use `execution`, `campaign`, or `validator/<validator_id>` scope for evidence that is not a machine snapshot. Their stage is one of `resolution`, `before`, `after`, or `validation`. In schema 4, registry-defined nonintegral observed fields such as load average use canonical decimal strings with their registered decimal type; they cannot retain legacy untyped JSON floats. Preserve raw probe text as evidence where useful.

### 5.6 Metric observation

```json
{
  "case_id": "compress/payload-small",
  "metric_id": "elapsed",
  "unit": "s",
  "direction": "lower",
  "domain": "positive",
  "state": "value",
  "estimate": "0.125",
  "aggregation": "median",
  "sampling_unit": "process_execution",
  "raw_samples": ["0.124", "0.125", "0.127"],
  "inner_sample_count": 3,
  "source": {
    "adapter": "hyperfine@1",
    "artifact_id": "harness-export",
    "selector": "/results/0/median"
  }
}
```

Units are explicit registry values: first release supports `s`, `ns`, `us`, `ms`, `B`, `B/s`, `count`, `count/s`, and `ratio`. Convert compatible time units using exact powers of ten; do not equate bytes and bits or decimal and binary prefixes implicitly. Custom units use namespaced identifiers and require exact agreement unless a supported conversion is declared.

Directions are `lower`, `higher`, or `none`. Domains are `positive`, `nonnegative`, or `real`. The reference relative method accepts positive values and a declared direction. `none` can be displayed but cannot drive a directional predicate. Missing observations use `state: unknown/error` and a structured reason; they do not contain an estimate. Raw samples are optional, immutable evidence; their count never inflates the process execution count.

### 5.7 Strict validation and limits

Validate structure before calling comparators. The first implementation must enforce: 16 MiB per structured JSON file, nesting depth 64, 100,000 field entries per record, 10,000 metric entries per record, 1,000,000 raw scalar samples per record, and 1,000,000 characters per ordinary string. File-size limits still apply when component maxima are individually valid. Large raw arrays belong in digest-referenced artifacts.

Duplicate metric identities in one run are invalid unless represented as explicit parameterized cases. Unknown enum values, missing state/value relationships, mismatched plan IDs, invalid timestamps, and malformed exit codes are structured validation failures, not tracebacks. Imported legacy records are validated under their legacy rules first, then normalized with limitations as described in Section 16.

## 6. Experiment specification and resolution

### 6.1 Authored example

This is proposed syntax, not a command/config supported by 0.3.0. Paths resolve relative to the experiment file, except variant-relative artifact and command paths, which resolve inside the variant worktree. `main` and `HEAD` are resolved to full commits before execution.

```json
{
  "kind": "ceteris.experiment",
  "schema_version": 1,
  "id": "compression-regression",
  "profile": "native-linux-local@1",
  "variants": [
    {"id": "base", "revision": "main"},
    {"id": "candidate", "revision": "HEAD"}
  ],
  "build": {
    "argv": ["cmake", "--build", "build", "--config", "Release"],
    "configure_argv": ["cmake", "-S", ".", "-B", "build", "-DCMAKE_BUILD_TYPE=Release"],
    "timeout_s": 900
  },
  "benchmark": {
    "adapter": "hyperfine@1",
    "argv": ["hyperfine", "-N", "--warmup", "2", "--runs", "10", "./build/compress fixtures/payload.bin"],
    "timeout_s": 120,
    "cases": [{"id": "compress/payload-small", "selector": {"result_index": 0}}]
  },
  "artifacts": [
    {"id": "program", "path": "build/compress", "role": "subject", "mutability": "immutable"},
    {"id": "payload", "path": "fixtures/payload.bin", "role": "input", "mutability": "immutable"},
    {"id": "expected-output", "path": "fixtures/expected.bin", "role": "correctness-reference", "mutability": "immutable"}
  ],
  "correctness": {
    "mode": "required",
    "validators": [{"id": "roundtrip", "argv": ["./build/compress", "--check", "fixtures/payload.bin", "fixtures/expected.bin"], "timeout_s": 60}]
  },
  "comparisons": [{"id": "candidate-v-base", "baseline": "base", "candidate": "candidate"}],
  "sampling": {
    "unit": "process_execution",
    "pairs": 20,
    "order": "balanced-random",
    "seed": "20260905",
    "retry": "none"
  },
  "metrics": [{
    "case_id": "compress/payload-small",
    "id": "elapsed",
    "source": "hyperfine.median_s",
    "unit": "s",
    "direction": "lower",
    "domain": "positive",
    "aggregation": "median",
    "primary": true,
    "predicate": {"type": "non_regression", "max_relative_regression": "0.05"}
  }],
  "analysis": {"method": "paired-median-relative@1", "confidence": "0.95", "family": "all-primary", "min_pairs": 10},
  "policy": {
    "required_capabilities": [],
    "vary": ["source.commit", "source.tree_digest", "artifact.program.digest"],
    "field_rules": [],
    "waivers": [],
    "require_observed_change": ["artifact.program.digest"]
  }
}
```

The correctness command is illustrative of an application-provided checker. Ceteris cannot infer that `--check` is a valid option. The repository owner must supply an executable checker appropriate to the workload. The checker executable/source and references are included in the trusted plan's artifact manifest.

### 6.2 Resolution algorithm

1. Parse authored input and reject unknown authoring keys except under namespaced extensions; catch typos early.
2. Load the named installed profile at its exact version. Do not retrieve profiles from the network implicitly.
3. Merge profile defaults and explicit authoring choices; list every effective requirement. Project config discovery is disabled during planned evaluation.
4. Resolve revisions to full commits and require a clean repository for managed campaigns. Uncommitted experiments use the explicit snapshot mode in Section 9.
5. Resolve adapter IDs, validator commands, artifact globs, case selectors, metric units, and the comparator engine version. Every primary case must be known before timing starts. A separate unmeasured discovery step may produce the case list; freeze its artifact in the plan.
6. Resolve policy rules against the field/capability registry; evaluate dynamic field conflicts again after collection.
7. Materialize exact run assignments, pair order, and fixed sample count. For each comparison, create `pairs` blocks, each with one base and one candidate slot.
8. Produce the complete effective plan: all defaults expanded, full profile contents/digest, full source revisions, ordered schedule, metric family, required capabilities, rules, limits, validators, and engine/method IDs.
9. Canonicalize and hash. Create the campaign manifest referencing that digest before any build or benchmark command executes.

Resolution is allowed to observe revisions and installed tool versions. Offline verification does not repeat resolution; it consumes the frozen plan. Local absolute directory assignments live in the campaign's execution journal and record provenance; the plan uses logical worktree roots, so local path placement does not redefine the experiment.

Planned capture enables only the profile's collectors and explicitly selected extensions. It does not activate every ecosystem pack merely because an unrelated tool is on PATH. Discovery may recommend a relevant extension while authoring the plan; activating it changes the resolved plan and must happen before execution. Legacy diagnostic capture may retain automatic pack discovery with its existing behavior.

### 6.3 Deterministic order generation

For `balanced-random`, require an even number of pairs, at least 10. Form `pairs/2` labels `AB` and `pairs/2` labels `BA`. Assign each label an occurrence index, compute SHA-256 of the UTF-8 string `ceteris-order-v1:<seed>:<comparison_id>:<label>:<index>`, and sort by digest then label/index to obtain the block-order sequence. The resulting schedule, not just its seed, is stored in the resolved plan. Do not use language-specific PRNG defaults.

`fixed-ab` is available for diagnostics and explicitly reviewed custom protocols, but the initial inferential profile requires balanced order. Randomization reduces ordering bias; it does not establish independence or eliminate thermal/cache carryover.

### 6.4 Amendments and retrospective analysis

Changing a required metric, threshold, waiver, selected run set, or analysis method produces a new resolved plan/report lineage. It must not rewrite the original campaign plan. Retrospective analysis is labeled `analysis_origin: retrospective`, references its original plan/report, and does not satisfy a CI policy requiring prospective rules. Display both the original result and the amendment reason in an exported review report.

Profiles may allow optional secondary metrics to be discovered at runtime. Such metrics are descriptive, excluded from the primary decision family, and cannot rescue a failed primary predicate.

## 7. Coverage and comparison policy

### 7.1 Initial profiles

Profiles are versioned JSON documents shipped alongside schemas. Requirements refer to capabilities, not a universal fixed count of fields.

| Profile | Required evidence | Permitted claim |
|---|---|---|
| `diagnostic@1` | Structurally valid input only | Observed field differences and descriptive metrics; no policy acceptance certificate |
| `native-linux-local@1` | Source snapshot; subject and input artifact identities before/after; CPU model/topology; OS/kernel; subject/launcher identity; controller affinity and explicit binding intent; harness validity; required correctness validator; selected primary metrics; complete pair assignments | Acceptance for a fixed-build local process comparison under the recorded host controls; actual descendant/rank affinity is not implied |
| `python-local@1` | Local requirements plus interpreter identity, declared Python source/package artifacts, installed distribution manifest for that interpreter | Acceptance scoped to the observed Python environment |
| `hpc-slurm@1` | Local workload requirements plus scheduler allocation identity, expected node inventory, required node-scoped observations, explicit rank/placement intent | Acceptance for the covered allocation; observed per-rank affinity is a separate optional/required extension |

Optional controls include governor, turbo, SMT, thermal state, container identity, virtualization, and available memory. Their precise default rules are defined in a field registry. Relevant observed controls are still compared; unsupported optional controls are listed as limitations. A site can make any optional capability required. A profile must explain exclusions prominently; it cannot claim complete system identity.

The first native profile declares sampling scope `fixed_builds`. It does not require rebuilding for each pair and does not claim uncertainty across compiler/build randomness. Docker/container and GPU workloads require an explicit profile extension; they cannot silently inherit host-only assurance.

The first native profile's minimum capability registry is explicit:

| Capability | Required scope/stage | Evidence and applicability |
|---|---|---|
| `source.snapshot@1` | Controller, before and after | Declared clean commit/tree or explicit content snapshot; cannot be structurally absent in a managed revision campaign. |
| `artifact.subject@1` | Subject, before and after | Every declared subject file identity; at least one required subject. |
| `artifact.inputs@1` | Subject, before and after | All declared immutable inputs/references. An intentionally input-free workload requires an explicit `no_external_inputs` assertion with reason in the plan; an empty discovered set is not proof. |
| `command.identity@1` | Subject, before and after | Requested/effective command, harness/launcher identity, explicit or supported discovered subjects, and logical argument structure. |
| `cpu.identity@1` | `node/local`, before and after | CPU model and architecture, known values. |
| `cpu.topology@1` | `node/local`, before and after | Logical CPU count and physical topology where the Linux platform exposes it; the first supported x86-64 profile requires known physical/logical counts. ARM needs a separately validated profile revision. |
| `os.identity@1` | `node/local`, before and after | OS/kernel identity, known values. |
| `parallelism.controller_affinity@1` | Controller, before and after | Controller affinity mask observed through the OS API. |
| `parallelism.binding_intent@1` | Controller/subject invocation, before | Declared launcher/subject binding options and allowlisted environment; explicit unset/no-binding intent is allowed. |
| `harness.validity@1` | Execution, after | Supported adapter output validation and a known absence of harness-reported failure. This is distinct from output correctness. |
| `correctness.required@1` | Declared checker scope, planned validator stage | All required validator claims passed and bound to the same subject/input identities. |
| `metrics.primary@1` | Execution, after | Every declared primary case/metric observation with eligible type/unit/domain. |
| `sampling.assignments@1` | Campaign | Complete frozen pair/slot assignments, unique execution/source-observation IDs. |

Actual `parallelism.subject_affinity@1` is optional in this first profile and remains an explicit limitation when unobserved. A site requiring it adds that capability; the report example in Section 12 illustrates such a stricter policy. Implementing it for harness descendants requires a supported subject launcher/instrumentation contract. Merely reading the controller's mask never satisfies it.

Ship exact field rules with the profile: default observed fields are material/typed-exact; source branch/path, host display names, scheduler job IDs/names, logical workdir display, load average, and available memory are informational. Program/input/dependency identities and tuning environment are critical. Registry-declared decimal observations normalize decimals; argument arrays use ordered comparison. All profile rules have priority 0, site/project overrides must use explicit higher priorities, and unsupported optional observations remain limitations. `--strict` in a new authored policy expands into explicit rules before freezing; it is not an ambient evaluator flag.

### 7.2 Required capability evaluation

For every requirement, expand its expected variants, runs, stages, scopes, and condition from the plan. Conditions use a closed declarative grammar: `all`, `any`, equality against a known field, or an explicitly listed profile parameter. Unknown condition inputs make the requirement unresolved, never false by default.

Requirements include `id`, `capability`, `scope_selector`, `stages`, `allow_not_applicable`, and optional `when`. Scope selectors are `controller`, `subject`, `execution`, `campaign`, `all_allocated_nodes`, or an explicit list of node/validator IDs. Run applicability is all assigned runs unless a comparison/case selector is explicitly present. The `when` grammar is recursive objects of the form `{"all": [...]}`, `{"any": [...]}`, or `{"equals": {"ref": "field:<scope>:<path> or parameter:<name>", "value": ...}}`; exactly one operator is allowed per object. Equality is typed. Empty `all`/`any` lists are invalid. Evaluate the expression using three-valued logic: false dominates `all`, true dominates `any`, and otherwise an unresolved operand keeps the result unresolved.

Evaluate:

- `observed` plus valid required fields: satisfied.
- `not_applicable`: satisfied only if the requirement explicitly allows structural absence and its applicability evidence is present.
- `unavailable`, `unsupported`, `excluded`, or no entry: incomplete.
- Unknown/error required field inside an observed capability: incomplete and flag contradictory capability metadata.

Requiring node-scoped evidence means all expected node IDs must be represented exactly once. A count alone is insufficient. Required benchmark/metric identities must occur in every assigned successful run used for that comparison.

### 7.3 Field rules and comparator precedence

New rules have `id`, `pattern`, integer `priority`, `severity`, `comparator`, and `scope`. Pattern grammar supports exact paths and `*`/`?` glob matching with documented case-sensitive semantics; a CLI bare prefix expands to `prefix.*` before plan hashing.

For a path, choose the highest-priority matching rule. If multiple rules at that priority specify different severities or comparators, resolution fails with `ambiguous_policy_rule`. Equivalent duplicate rules collapse and preserve their source IDs for explanation. There is no insertion-order tie-breaker. Exact-match convenience rules must still have an explicit effective priority.

Default unmatched observed fields have `material` severity and `typed-exact@1` comparison. Unknown optional fields are reported but only block if a requirement or rule demands readability. Known differences in material/critical fields block unless declared or waived. Informational differences do not block. Required capability evaluation is independent of informational severity.

`typed-exact@1` preserves JSON type, recursive structure, and array order; integer `1`, string `"1"`, and boolean `true` are distinct. Decimal fields compare normalized decimal values only when declared as decimal in the registry. `multiset@1` sorts canonical typed elements and preserves duplicates. Path comparison uses logical paths and exact case; it never silently resolves symlinks or lowercases paths. Ordered argv compares token arrays exactly after only the explicitly allowed logical-root/output substitutions.

### 7.4 Variation and expected changes

`vary` permits differences across specified variant IDs only. It does not permit differences between repeats of one variant, pre/post drift within one execution, missing values, or a changed required metric definition. An optional `require_observed_change` assertion ensures a intended change actually occurred. Assertion failure is an experiment-design failure, even if two builds happen to have identical measured performance.

Source revision changes and the resulting subject digest change are separate declarations. The resolver may propose both for a code-change template, but neither the runner nor GitHub Action automatically grants broad `source.*` or `deps.*` exceptions. A dependency change must be explicit in the reviewed plan.

Known environment differences across repetitions cannot create new experimental groups to make the analysis pass. Preserve variant assignment, report incompatibility, and withhold primary inferential acceptance. A diagnostic view may show environmental clusters as explanatory output.

### 7.5 Waivers

A waiver contains `id`, exact target pattern/capability, comparison scope, reason, author-provided reference, and optional expiry date. The frozen resolved plan binds every waiver. Field/capability waivers can accept specific missing or differing evidence; they cannot waive malformed records, duplicate executions, harness-invalid output, failed correctness, receipt integrity, or unsupported required semantics.

The report retains raw coverage/comparability failures and records which obligations were accepted by waiver. Effective policy evaluation can pass only when that policy permits those waiver types. The summary must be `passed_with_waivers`; never erase the original unknown/difference or change it to a match. Expiry is evaluated against the campaign start timestamp for reproducible analysis; display whether a waiver is currently expired separately as a non-semantic viewer annotation.

### 7.6 Association diagnostics

Keep the current partition-based detection of undeclared fields tracking declared variables, but call the output `associated_difference`. It establishes association in the supplied observations, not causality. Store typed canonical group keys, not rendered strings, in the calculation. Explain that a changed binary hash may be an expected consequence of a code change and must be declared. A field waiver does not prove it was causally irrelevant.

## 8. Execution lifecycle and persistence

### 8.1 Campaign directory

```text
.ceteris/campaigns/<campaign_id>/
  plan.json
  campaign.json
  journal/<run_id>.json
  runs/<run_id>.json
  artifacts/sha256/<digest>
  reports/<report_digest>.json
  worktrees/base/
  worktrees/candidate/
  scratch/<run_id>/
```

The default directory ignores itself in Git. A custom store writes its ignore marker inside its own directory, never into a parent that it does not own. Worktrees may instead live under a caller-specified scratch root. The manifest records logical root mappings. Verification does not require worktrees.

`campaign.json` records the campaign ID, plan digest, planned slot IDs, start time, selected tool versions, and current campaign lifecycle state. The journal holds resumable operational state. Completed run records are immutable. A journal is not a source of successful measurements until its terminal record commits.

### 8.2 State machine

Run lifecycle states are:

```text
planned -> preparing -> capturing_before -> running
       -> capturing_after -> collecting_results -> validating -> committed

Any active state -> failed | cancelled | timed_out | abandoned
```

`committed` means a durable terminal record exists, not that the benchmark passed. Terminal records carry separate execution, harness, correctness, and evidence outcomes. A parse failure after process exit zero commits a record with successful process execution but invalid/missing measurement evidence.

Required sequence:

1. Allocate run ID and write the assigned slot/attempt into a durable journal.
2. Prepare a run-owned scratch directory outside the source identity manifest.
3. Validate that the required built artifacts match the frozen campaign artifact manifest.
4. Prepare the adapter's export contract and explicit validator prerequisites.
5. Capture environment and immutable artifacts before launch. Record durations of probes separately from benchmark time.
6. Launch effective argv with explicit cwd and environment overlay. Record the actual overlay keys/values permitted by disclosure policy; secret omissions remain explicit evidence gaps.
7. Stream output and wait for exit, timeout, or cancellation.
8. Perform bounded post-capture, including execution and immutable input identities, even after benchmark failure where practical.
9. Parse run-owned exports; preserve parse problems and partial evidence.
10. Run required untimed validators in the specified stage; bind them to this run's subject/input identities.
11. Construct and validate the terminal record; persist artifacts before a record that references them.
12. Atomically commit the record, update the journal/campaign index, then start the next assigned execution.

Collectors that change machine settings are prohibited in the collection interface. Any explicit setup/tuning command is an ordinary planned preparation step with recorded outcome, not an invisible collector side effect.

### 8.3 Atomic writes and recovery

Write each JSON object to a uniquely named temporary file in the destination filesystem. Flush, `fsync` the file, atomically rename to its final path, and sync the directory where supported. Report the achieved durability mode on platforms/filesystems where directory synchronization is unavailable. Never overwrite an existing run ID. An existing same-ID/same-digest record is an idempotent commit; a different digest is `run_id_collision`.

Campaigns use a single-writer lock created atomically, containing campaign ID, process ID, hostname, and start time. Automatic stale-lock removal is allowed only after confirming the owner is absent on the local host. Otherwise require an explicit recovery command; elapsed time alone does not prove ownership is stale. Parallel worker executions write distinct run paths and send completion events to the campaign coordinator.

On resume:

- Revalidate the plan digest, source/workload artifacts, committed records, and referenced evidence.
- Never rerun a committed slot automatically.
- An in-flight journal without a terminal record becomes an `abandoned` attempt unless its process is positively identified as still active.
- `retry: none` is the inferential default. A missing slot makes the planned analysis incomplete.
- Resuming after an abandoned timing attempt may finish evidence collection, but cannot silently substitute a new measurement into the original primary analysis. Starting a replacement pair requires a new recorded campaign or an explicit protocol that predeclared retry/selection rules.
- If a run committed but its index update did not, recover it by run ID and slot assignment. Do not manufacture a duplicate.

No SQL database is required initially. JSON files and content-addressed artifacts are adequate. Add an optional rebuildable index only after measured directory-scan costs justify it.

### 8.4 Output handling and limits

Read stdout/stderr as binary chunks of 64 KiB. Default capture keeps separate stream artifacts plus event order where supported; a combined compatibility display is allowed but marked as combined. Retain a 64 KiB byte tail per stream in memory. Stream to disk up to 256 MiB per stream by default, then continue draining without storing further bytes. Record total bytes observed, bytes retained, truncation, and a streaming digest of the entire observed stream. A full-stream digest without full bytes is a commitment, not a fully available artifact.

For stdout-table adapters, parse incrementally or use the spool. If truncation discards required result evidence, metrics become unavailable and the policy cannot pass. The record's displayed tail is decoded with UTF-8 replacement and includes a decoding-loss indicator. The byte artifact preserves original encoding when retained.

No adapter may force unlimited memory by returning all lines into the runner. Configurable limits are part of the resolved plan. The memory target for a 1 GiB output stress fixture is less than 32 MiB incremental runner RSS excluding loaded interpreter/test overhead; acceptance uses comparative measurements on the same CI host.

### 8.5 Cancellation and timeout

Local POSIX executions use a new session/process group. On cancellation or timeout, send SIGTERM to the owned group, wait up to 5 seconds, then SIGKILL and reap. Never signal the parent's process group. Cleanup and final evidence collection get a total 10-second budget after termination; incomplete cleanup is recorded. If the wrapper itself receives SIGKILL, recovery marks the unfinished execution abandoned.

Remote launcher integrations specify whether cancellation propagates and record the launcher/job-step identity. For Slurm, cancellation is scoped to the Ceteris-created job step, never the user's entire allocation. If remote termination cannot be confirmed, record `remote_cleanup_unconfirmed`; do not state that all ranks were terminated.

`ceteris run -- ...` continues to expose child-like exit behavior for scripting. Planned `campaign run` returns the campaign/report exit code described in Section 12. Both retain terminal evidence whenever possible.

### 8.6 Build and validation isolation

Build once per variant before measured pairs in the first native profile. Capture configure/build commands, exit status, logs, source digest, environment manifest, and resulting artifacts. The plan is frozen before building; resulting build digests are bound in campaign records and must remain stable throughout timing.

Correctness validators run before each measured execution when they establish a precondition, or after it when they consume its output. The initial explicit command validator runs after each measured execution, outside the timing interval, against that variant's artifacts. Such a checker validates the declared workload/artifact combination; it is not automatically evidence that every inner harness iteration's output was correct. Adapters may provide stronger per-execution evidence and must name its scope.

Validators can affect cache/thermal state. Their placement and any reset/setup step are part of the plan and identical across variants. Do not claim the validator has no experimental effect merely because its runtime is excluded.

## 9. Workload and environment identity

### 9.1 Artifact manifests

Every declared artifact has a stable logical ID, role, path selector, scope, mutability, availability requirement, and content descriptor. Supported first-release roles are `subject`, `input`, `correctness-reference`, `validator`, `dependency`, `build-config`, `harness-output`, and `output`. Immutable roles receive before/after checks. Writable output artifacts record post-execution identity and are not required to equal their pre-execution state.

For a file record exact byte SHA-256, byte length, executable mode bit, and whether the path was a symlink. A symlink has its link-text identity and the identity of a target when dereferencing is declared. An unreadable or disappearing target is unknown. Do not silently follow links outside an allowed source/artifact root; explicit external artifacts are allowed and separately named.

For a directory, produce a sorted manifest of relative POSIX paths, object type, executable bit, content digest or symlink target, and length. Exclude mtimes, inode numbers, ownership, and absolute local roots from semantic identity. Include zero-byte files and empty directories only when the artifact declaration requests directory structure; that choice is part of the manifest semantics. Hash the canonical manifest. Glob expansion is frozen at resolution or pre-build discovery, and zero matches for a required selector are a failure.

Read files in chunks; metadata changes during hashing produce `unstable_artifact`, not a guessed digest. Large data files are hashed once during campaign preparation and rechecked as required by the plan. A metadata-only optimization cannot claim byte-verified before/after identity. The first strict profile requires full hashes for required immutable artifacts; any faster mode is an explicit weaker capability.

### 9.2 Source identity

For managed clean-Git campaigns, record full commit, tree digest, submodule commit/clean state, build-relevant LFS materialized content identities, and source root identity. A submodule's leading dirty/uninitialized status must not be discarded. Missing or unavailable Git is unknown source identity, not an absent source tree.

For explicit `source_mode: snapshot`, construct a file manifest of tracked working-tree content plus declared untracked source files, their executable bits, symlink text, and submodule manifests. Hash actual contents rather than a dirty boolean. Gitignored files remain excluded unless declared as artifacts. Include the selection policy in the source digest's semantics. Dirty state remains informational evidence explaining why the commit alone is insufficient.

Do not invent a complete source closure. Generated files, inputs, installed packages, and outside-root code require their own declarations. Snapshot creation must not modify the user's repository or discard changes.

### 9.3 Command identity

Keep both requested argv and effective argv. Requested argv records user intent; effective argv includes injected export flags and launch wrapping. Comparability uses a versioned structured command representation only where parsing is supported:

- Launcher executable and ordered launcher arguments.
- Harness executable, version, ordered measurement options, and adapter version.
- Subject executable(s), ordered subject arguments, and declared artifact references.
- Logical worktree roots instead of arbitrary temporary directory prefixes.
- Run-owned output destinations replaced with typed output references only for adapter-known output arguments.

Every substitution records its original token and rule. A generic regular-expression replacement of paths is prohibited. Workload paths and export paths are not interchangeable. Display labels are not benchmark identity. Multi-command Hyperfine exports require explicit stable case mappings; numbering alone must not silently match a different command after order changes.

Use the same semantic root token `worktree:/` for equivalent variant-local paths in field comparison; keep variant ID in the run assignment and physical root mapping in provenance. Thus two separate worktree directories do not themselves constitute an undeclared workload change. Changing `worktree:/fixtures/a.bin` to `worktree:/fixtures/b.bin` still differs unless both are explicitly mapped to the same declared logical artifact under a documented rule. Their content identity remains independently checked.

Shell commands are opaque unless an adapter supplies a supported interpretation. The tool may record shell text and declared artifacts, but cannot claim to have discovered every executable in a pipeline, command substitution, `env` wrapper, container launch, or remote command. Unknown decomposition blocks a policy that requires discovered subject identity; explicit subject artifacts can satisfy a separate declared-identity requirement.

### 9.4 Actual runtime and dependency identity

Collectors must interrogate the interpreter/runtime associated with the subject, not an unrelated `python3` or `java` on the controller's PATH. The Python integration invokes the selected interpreter in a dedicated metadata subprocess to obtain implementation/version/ABI, environment prefix, and installed distribution name/version metadata. Declared import/package/source manifests supplement this inventory; package metadata alone is not installed-byte identity.

Lockfile hashes mean intended dependency resolution, not actual installed dependencies. Store those as distinct capabilities. Native library inventory is a later versioned capability that records its observation method and whether it describes linked, resolved, or actually loaded libraries. Merely running `ldd` is not a claim about every library loaded at runtime.

Container profiles record runtime, immutable image digest when available, platform, relevant mounts, and configured limits. A tag or image name does not satisfy an immutable-image requirement. A host observation does not establish the same property inside the container. Remote service benchmarks must declare service/version/deployment identity and workload/request artifacts; client-only evidence is diagnostic for that scope.

GPU profiles must distinguish hardware model/partition, driver, compiler toolkit, user-space runtime, visible devices, power/clock limits, and precision/model/input identity. Do not rename `nvcc --version` as the runtime actually loaded by the subject.

### 9.5 Privacy by design

Capture only allowlisted environment variables. Do not collect all environment values by default. Command lines, output, source paths, hostnames, and artifact names may still contain sensitive information; make this visible in `bundle inspect --disclosure`.

Redaction produces a derivative bundle with a new manifest and receipt. It records the removed field/artifact IDs and references the original manifest commitment. A redacted required field makes public coverage incomplete unless an explicitly permitted waiver remains. Do not replace secrets with an unqualified `not_applicable`, and do not pretend a public verifier checked omitted bytes. Hashing low-entropy secrets is not reliable concealment; omit their commitments when disclosure policy requires it and record that omission.

## 10. Adapters and correctness evidence

### 10.1 Interface version 1

Define immutable interface objects and a public adapter protocol:

```python
class Adapter:
    id: str  # e.g. "hyperfine@1"

    def detect(self, invocation, context) -> Detection: ...
    def prepare(self, invocation, owned_paths, context) -> ExecutionPlan: ...
    def parse(self, artifacts, invocation, case_map) -> AdapterResult: ...
```

`Detection` contains `supported`, `unsupported`, or `ambiguous`, the evidence used, and supported harness versions. If two adapters claim the invocation without a deterministic specific match, require an explicit adapter. A generic `*_perf` filename must not conclusively identify NCCL.

`ExecutionPlan` contains effective argv, declared subjects, ordered semantic options, owned export paths, and parser requirements. The runner creates and owns scratch paths; adapters cannot use arbitrary shared filenames. `AdapterResult` contains typed observations, harness validity (`passed`, `failed`, `unverified`), correctness claims, source selectors, and structured issues.

Expected bad output produces a result with issues. Unexpected adapter exceptions are caught at the boundary, stored as `adapter_error`, and make required evidence unavailable. They do not lose a successfully completed process record.

### 10.2 Correctness claims

A correctness claim contains validator ID/version, result (`passed`, `failed`, `unverified`), scope (`execution`, `artifact`, or `harness_iteration`), bound subject/input digests, checked case IDs, and evidence artifact references. Command validators additionally record argv, timeout, exit status, and captured output.

Core validators:

| Validator | Behavior |
|---|---|
| `command@1` | Run an explicitly planned checker outside timing. Exit zero means that checker passed; the report names its scope and identity. |
| `output-sha256@1` | Compare declared output bytes against a frozen expected digest. Missing/truncated output cannot pass. |
| `harness-status@1` | Preserve a supported harness validity/correctness marker. Missing markers are unverified. |

No implicit user shell execution is allowed during import or verification. Validator commands run only as part of an explicitly executed experiment. A required validator that is unsupported is incomplete evidence; a validator reporting failure is a failed experiment.

### 10.3 Adapter-specific requirements

| Adapter | Required changes before supported acceptance |
|---|---|
| Hyperfine | Unique export; finite positive statistics; stable explicit case mapping; requested/effective option split; retain inner samples; preserve subject identity limits; reject stale exports. |
| Google Benchmark | Preserve case parameters, `run_type`, units, error fields, repetition count, and raw iterations. Select one declared aggregation; never silently drop error repetitions. Honor JSON output format explicitly. |
| pytest-benchmark | Bind to selected Python environment; preserve benchmark full identity and parameterization; distinguish session executions from inner rounds; retain pytest exit outcome. |
| JMH | Bind benchmark, parameters, forks, mode, and score unit. Detect an absent/new export; preserve fork/iteration hierarchy. Documentation-derived fixtures alone do not grant supported status. |
| Criterion | Respect configured target/output directories and discovered case IDs; prove outputs belong to the current execution; preserve statistics' provenance. |
| OSU | Parse selected benchmark type, sizes, units, and error output. Parameterized sizes become case identities. Parse the actual named artifact during import. |
| NCCL | Require supported output structure and correctness/error counters, selected operation, datatype, rank count, and out-of-place/in-place identity. |
| MLPerf | Treat `INVALID` as harness failure; bind summary to explicit scenario/model/configuration; preserve accuracy evidence separately; do not infer official MLPerf compliance from a parsed throughput line. |

Until each adapter passes its fixtures and real integration matrix, it is `experimental`. Users may collect and inspect its output, but the CLI must name that status in any policy result requiring it. The standard profile can require only supported adapter versions.

### 10.4 Imports and extensions

`ceteris import` records the source artifact digest, format/version, importer ID/version, original IDs if present, and an `execution_linkage` status. It must never claim to have captured the historical environment merely because import happened on a particular machine. A fresh run ID assigned by an importer does not create a new independent execution; preserve a stable source-observation ID derived from the source artifact and record selector.

External adapters register through an explicitly configured entry-point group `ceteris.adapters.v1`. No network discovery or installation happens automatically. Loading an adapter executes locally installed code and is restricted to capture/import operations. Offline verifiers consume normalized records and bundled evidence with built-in supported semantics; they never load bundle-provided Python.

## 11. Measurement analysis

### 11.1 Two initial methods

`descriptive@1` reports valid sample counts, missing counts, minimum, median, maximum, and per-execution distributions. It produces no confidence or acceptance conclusion about a performance effect. Existing median/range noise output can remain a labeled `legacy-range@1` diagnostic with the finite-positive restrictions from F04.

`paired-median-relative@1` is the proposed reference inferential method. It is intentionally restricted to positive scalar metrics, predeclared independent execution pairs, and a fixed sample count. It estimates the population median of within-pair relative effects for the specified fixed builds and testbed. It does not estimate a ratio of global medians, a mean effect, or uncertainty over rebuilds/machines.

This method must receive independent methodology review and conformance validation before a stable acceptance profile uses it. Until then it is explicitly experimental. The design below is sufficiently specified to implement and test without silently inventing statistical choices.

### 11.2 Input eligibility

For each declared comparison and primary case/metric:

1. Select exactly the run slots frozen in the plan. Include all terminal attempts in the audit trail.
2. Require one eligible baseline and one eligible candidate execution per planned pair. Duplicate run/source-observation IDs are invalid.
3. Require successful execution, supported harness output, policy-required correctness, and satisfied effective evidence obligations. Explicitly permitted waivers may satisfy only the obligations listed in Section 7; raw evidence states remain unchanged.
4. Require the same unit, metric definition, aggregation, and sampling level within each selected case/metric.
5. Require all planned pairs, and at least `min_pairs`, which must be at least 10. A failed/missing measurement does not reduce the expected sample set.
6. Reject list-valued estimates, nonpositive values, NaN/infinities, or unsupported numeric precision.

Incomplete inputs yield `unavailable` or `inconclusive` with counts and reasons. Do not silently select only configurations carrying a metric, remove outliers, retry failed timing slots, or select a later successful attempt. Secondary descriptive metrics may have incomplete coverage without affecting the primary result.

### 11.3 Pair effects

For baseline value `b_i > 0` and candidate value `c_i > 0`, compute exact rational effects:

```text
lower is better:  d_i = (c_i - b_i) / b_i
higher is better: d_i = (b_i - c_i) / b_i
```

Positive is worse, negative is better, and zero is unchanged. These two directional definitions deliberately use the baseline as denominator. For example, latency 100 ms to 106 ms is `+0.06`; throughput 100/s to 106/s is `-0.06`. Do not switch denominators based on which value is smaller.

Sort effects exactly as rationals, `d_(1) <= ... <= d_(n)`. The point estimate is their median; for even `n`, use the arithmetic average of the central two rationals.

### 11.4 Distribution-free order-statistic interval

Let family confidence be `C`, e.g. `0.95`, and `M` be the number of predeclared primary comparison/case/metric hypotheses. Set `alpha = (1-C)/M` using exact rational arithmetic. This is a Bonferroni family-wise allocation; correlated metrics do not require an independence assumption for that allocation.

Choose the largest integer `k`, with `1 <= k <= floor((n+1)/2)`, satisfying:

```text
2 * sum(comb(n, j) for j in range(k)) / 2**n <= alpha
```

The interval is `[d_(k), d_(n-k+1)]`, endpoints inclusive. If no such `k` exists, return an unbounded interval represented with null bounds and `interval_status: insufficient_resolution`; do not insert numeric infinities into JSON. The policy is then inconclusive.

Reference checks:

- `n=10`, `M=1`, `C=0.95`: `k=2`, interval is the second through ninth order statistics.
- `n=20`, `M=1`, `C=0.95`: `k=6`, interval is the sixth through fifteenth order statistics.
- `n=10`, `M=100`, `C=0.95`: no finite interval at this confidence under this method; report insufficient resolution.

The coverage argument assumes independent pairs sampling a common effect distribution. A unique ID, balanced execution order, or three identical numbers does not prove those assumptions. Ties yield conservative coverage in the usual median interpretation; the report includes tie counts and the method's assumptions. Repeated identical deterministic outputs are not automatically invalid, but duplicated observations are.

### 11.5 Predicates and practical conclusions

Each primary metric has exactly one decision predicate in the initial protocol:

| Predicate | Pass | Fail | Inconclusive |
|---|---|---|---|
| `non_regression`, allowed relative regression `t >= 0` | Upper bound `U <= t` | Lower bound `L > t` | Interval crosses threshold or is unavailable |
| `improvement`, required relative improvement `t >= 0` | `U < -t` | `L >= -t` | Interval crosses target or is unavailable |
| `equivalence`, relative margin `t > 0` | `L >= -t` and `U <= t` | `U < -t` or `L > t` | Remaining cases or unavailable interval |

For non-regression, no detectable difference may legitimately pass when the whole interval lies within the allowed budget. Absence of a statistically detected regression is not sufficient by itself. For equivalence, failing means evidence lies beyond the allowed equivalence region; it does not mean the candidate is necessarily worse.

Display a separate practical effect classification using a declared material-effect margin `e` (defaults to the predicate margin): `improvement` if `U < -e`, `regression` if `L > e`, `no_material_change` if the interval is contained in `[-e,e]`, otherwise `inconclusive`. A classification describes evidence and does not replace the predicate's exact decision rule.

All primary predicates must pass for policy acceptance. Any primary failure fails the policy. Otherwise any inconclusive primary predicate makes the policy inconclusive. An unrelated metric showing a signal cannot rescue another metric.

### 11.6 Sample planning and diagnostics

At plan resolution, check whether the planned `n`, `M`, and confidence can produce a finite interval. Reject an inferential plan that cannot do so, with the minimum `n` satisfying the formula. Do not estimate statistical power from this check: interval existence is not adequate power for a particular effect.

The default example uses 20 pairs. The tool may run a separately labeled pilot to estimate practical runtime and variability, but pilot observations are not silently reused in a prospectively fixed experiment. Fixed stopping is required for method version 1. Adaptive stopping, bootstrap intervals, hierarchical effects, unpaired comparisons, and signed/zero-valued metric methods require distinct reviewed method IDs.

Report run order, times, per-pair effects, raw sample availability, ties, and drift/coverage diagnostics. Provide a plot in the HTML report of individual baseline/candidate values over execution order, with an accessible table of the same values. Do not hide variation behind only a single percentage or a green badge.

### 11.7 Method conformance and determinism

Policy decisions and interval endpoint selection use integer/rational arithmetic. Define display rounding separately: percentages show two decimal places by default using round-half-even; unrounded rational values remain in JSON. A report digest covers rational values and method ID, not locale-specific display text.

External method implementations may use different numerical libraries, but must match normalized semantic output exactly for the reference method. Methods requiring nondeterministic computation must specify their PRNG, seed, stopping rule, and numeric tolerance protocol before registration; none is needed for the initial reference method.

## 12. Reports, decisions, and exit codes

### 12.1 Report dimensions

A semantic report contains validated object digests, comparison IDs, selected assignments, per-run issues, capability results, field relations, primary/secondary metric analyses, waiver applications, method assumptions, and these separate dimensions:

| Dimension | States | Meaning |
|---|---|---|
| `execution` | `passed`, `failed`, `incomplete` | Every required execution terminated successfully and its terminal evidence exists. |
| `correctness` | `validated`, `failed`, `unverified` | Required scoped checks passed, failed, or were unavailable/not requested. |
| `coverage` | `sufficient`, `incomplete` | Required observations were actually available; waivers do not rewrite this. |
| `comparability` | `compatible`, `incompatible`, `indeterminate` | Known evidence satisfies invariants/declarations, conflicts, or cannot decide. |
| `measurement` | `assessed`, `inconclusive`, `unavailable` | Primary method could compute eligible evidence and a decision, could not resolve a threshold, or lacked usable inputs. |
| `acceptance` | `passed`, `passed_with_waivers`, `failed`, `inconclusive`, `not_evaluated` | Result of the specified policy. Diagnostic comparisons use `not_evaluated`. |

Raw dimensions describe evidence before waivers. An additional `obligations` array states which requirement was satisfied, violated, unresolved, or explicitly accepted by waiver. This resolves the apparent contradiction of `coverage: incomplete` alongside `acceptance: passed_with_waivers`.

Inference may be computed for diagnostics on runs with unwaived incompatible or incomplete evidence, but its result has `eligible_for_acceptance: false` and cannot drive a passing policy. If all blocking obligations are satisfied by explicitly permitted waivers, inference can be eligible while the final acceptance remains visibly `passed_with_waivers`. Default rendering explains blocking conditions before numerical effect claims.

### 12.2 Decision order

1. Invalid object structure, unsupported mandatory versions, or identity collisions prevent normal policy evaluation.
2. A known failed execution, harness validity check, or required correctness check produces `acceptance: failed`.
3. Unwaived known comparability violations or failed observed-change assertions produce `failed`.
4. Unwaived missing evidence, unavailable required methods, incomplete assigned executions, or required unverified correctness produce `inconclusive`.
5. Evaluate eligible primary measurement predicates: any fail produces `failed`; otherwise any inconclusive produces `inconclusive`.
6. All obligations satisfied produces `passed`; any accepted waiver changes this to `passed_with_waivers`.

Policy evaluation stores all reasons even when an earlier failure determines the exit code. Do not hide missing evidence behind the first violation. Diagnostic mode skips acceptance predicates and never issues a positive acceptance receipt.

### 12.3 Structured issues

Each issue has `code`, `severity`, `stage`, optional run/case/field/capability IDs, `message`, `evidence_refs`, and `remediation`. Codes are stable API values such as `duplicate_observation`, `stale_export`, `harness_invalid`, `metric_nonfinite`, `required_capability_missing`, `subject_changed_during_run`, `ambiguous_policy_rule`, and `unsupported_method`.

Remediation is data: a concise explanation and optional suggested command/plan edit. The renderer may display it but never executes it. A remediation must not suggest waiving a failed benchmark, fabricated sample count, or broken integrity check.

### 12.4 CLI exit-code contract

Preserve legacy commands' published behavior during migration. New planned `compare --plan`, `campaign run`, and `verify --require-pass` use:

| Code | Meaning |
|---|---|
| `0` | Requested policy passed, including explicitly permitted waivers; or integrity verification succeeded when no acceptance assertion was requested. |
| `1` | Known policy rejection: comparability, correctness, execution, or measured predicate failure. |
| `2` | Evidence incomplete, unsupported required semantics, unavailable analysis, or verification cannot complete. |
| `3` | Invalid invocation, malformed input, invalid/ambiguous plan, duplicate observation, or structural identity violation. |
| `4` | Eligible measurement evidence is inconclusive at the planned threshold/confidence. |
| `5` | Digest, bundle membership, or receipt semantic integrity mismatch. |
| `130` | Interrupted by the user; completed evidence retained. |

Precedence for a single command is interruption if interrupted; otherwise structural/usage failure; integrity mismatch if verification is possible and fails; known policy rejection; incomplete evidence; statistical inconclusiveness; success. Integrity checks precede re-evaluation in verification, so malformed receipt structure produces `3`, readable altered content produces `5`, and missing required content produces `2`.

The shell code is only a summary; JSON includes dimension states and stable reason codes. `run -- COMMAND` continues to pass through the child's conventional status for a successful wrapper operation, with `130` for wrapper interruption and `3` for usage/launch failure. Its output warns when the saved record has invalid evidence even if the child exited zero. Users wanting policy enforcement use planned evaluation.

### 12.5 Human report

First lines show the requested comparison, profile/policy identity, acceptance state, and main reason. Then show execution/correctness/coverage/comparability/measurement dimensions, primary metric intervals and predicates, undeclared differences, missing capabilities, waivers, and secondary diagnostics. Use the same semantic report for text, JSON, and HTML.

Example rendering:

```text
candidate vs base — compression-regression
INCONCLUSIVE: required subject affinity was not observed on 2 executions.

Execution: passed    Correctness: validated    Coverage: incomplete
Comparability: indeterminate    Measurement: unavailable for acceptance

Required evidence: parallelism.subject_affinity, runs r17 and r18
Next step: enable the subject-affinity collector or use a reviewed profile
that explicitly scopes this capability out. Existing records are retained.
```

Run names here are illustrative display aliases, not UUID syntax. Every report links a displayed row to the corresponding execution/evidence record. Limitations and waivers must remain visible in exported reports and short summaries.

## 13. Receipts, bundles, and offline verification

### 13.1 Rename the claim

New output uses `ceteris-receipt v3`, not a blanket `ceteris-certified` assertion. A receipt records the result of evaluation, including failure. Positive statements must name the policy and scope. Legacy certificate verification remains available with the repairs in Section 3.

The one-line form is deliberately small:

```text
ceteris-receipt v3 manifest=sha256:<64 lowercase hex characters>
```

This syntax block describes the grammar; the angle-bracket text is not a literal receipt. The line contains no unbound verdict, count, or noise percentage. Human-readable annotations are emitted on separate lines and are recomputed from the referenced verified report. The manifest binds plan and report; the report binds every selected run and its semantic result.

### 13.2 Bundle layout and graph

```text
manifest.json
plan.json
report.json
records/<run_id>.json
evidence/sha256/<digest>
schemas/<schema-id>.json
README.txt
```

`manifest.json` has `kind: ceteris.bundle`, `schema_version: 1`, canonicalization ID, semantic engine/method IDs, root file references for plan/report, and a sorted `files` array of relative path, byte size, digest, media type, and required/optional role. It also declares omitted evidence descriptors with reasons. The manifest does not list itself; the receipt hashes it. The report lists selected record digests sorted by assignment identity and carries its exact plan digest.

All regular file entries use exact byte digests. Protocol files in a bundle are written in canonical bytes, so their object and byte digests agree. A pretty-printed copy outside the bundle can still be parsed/canonicalized, but changing bundle member bytes requires regenerating its manifest. No digest cycle is allowed.

Schemas in the bundle are explanatory copies with digests; a verifier uses its installed supported schema/semantics implementation rather than trusting arbitrary supplied schema code. New required semantics need an installed verifier implementation, not an instruction to execute code from the bundle.

### 13.3 Verification algorithm

1. Parse receipt grammar and version; reject unsupported versions explicitly.
2. Read the supplied manifest and match its digest to the receipt.
3. Validate relative paths, unique file entries, sizes, required members, and format limits before opening archive contents.
4. Verify all listed available member bytes and reject unexpected members. Optional omitted evidence is listed as omitted, not as a present file with an unverifiable digest.
5. Parse and validate plan, records, and report with supported schemas. Check their cross-references, run IDs, slot assignments, and required extension IDs.
6. Validate selection completeness and duplicate-observation rules.
7. Recompute field comparison, coverage, analysis, predicates, and normalized semantic report using the frozen plan. Never call `Config.load()` against the current working directory.
8. Require exact semantic report equality and digest equality. Verify every displayed semantic field through that report.
9. Return separate integrity and acceptance outcomes, available-evidence level, supported semantics, and producer-authentication status. `--require-pass` additionally enforces the plan/profile's minimum bundle availability level; an integrity-valid records-only bundle cannot satisfy an evidence-complete sharing requirement.

Verification does not rerun validators. It verifies the recorded validator claim, its bound identities, and evidence bytes where present. It cannot prove the machine actually ran the checker or that the checker is correct. Optional reproducibility execution is a separately authorized command and creates new records.

### 13.4 Archive handling and availability levels

The initial transport is a directory or `.zip`; no extraction is necessary for ordinary verification. Reject absolute paths, `..` segments, duplicate normalized paths, symlinks/hardlinks, encryption, and paths escaping the bundle root. Default limits: 10,000 members, 1 GiB total uncompressed data, 256 MiB per evidence member, 16 MiB per structured member, and compression ratio at most 100:1. Explicit caller overrides are local verification resource choices and do not alter the certified comparison; report them in verifier diagnostics.

Availability levels:

- `records_only`: normalized observations and digests are available; raw harness/checker evidence may be omitted. Report can be recomputed from records.
- `evidence_complete`: all required raw harness/validator artifacts named by the profile are present and byte-verified.
- `reproduction_ready`: additionally includes or resolves all explicitly required workload/build artifacts under a declared execution environment. This is a packaging property, not proof that a rerun will reproduce performance.

The first supported acceptance profile requires `evidence_complete` for shared acceptance receipts. Large datasets may remain content-identified rather than bundled; their absence affects reproduction readiness, not necessarily report recomputation. Missing required harness/validator evidence lowers the bundle level and prevents claims requiring that level.

### 13.5 Producer identity and trust

The unsigned core reports `producer_authentication: none`. Digests detect changed supplied content relative to a known receipt; an author can construct a new misleading record and issue a new receipt. No language should imply cryptographic proof of an honest experiment.

Optional signatures may later sign the manifest digest using a separate attestation format. Verification must then distinguish signature validity, signer identity/trust, evidence integrity, and policy acceptance. A valid signature does not override failed measurements or incomplete coverage. Key management and external trust services are outside the first release.

### 13.6 Redaction and reanalysis

`bundle redact` creates a new bundle, never edits the original. Record omitted members/fields, original manifest commitment when disclosure permits, reason, and transformation version. Recompute report coverage and acceptance under the disclosed evidence. A derived bundle cannot inherit the old acceptance state without reevaluation.

`compare --reanalyze` creates a new report referencing original record digests, original plan, amended analysis policy, and retrospective origin. It preserves original results in the bundle lineage. An independent verifier can reproduce either result using its exact method version. Display-only formatting changes need not change the semantic report, but bundled display files receive new byte digests if regenerated.

## 14. CLI and Python interfaces

### 14.1 Proposed commands

Keep existing `capture`, `run`, `list`, `doctor`, `compare`, and `verify`. Add explicit plan/campaign/bundle operations rather than hiding more behavior inside positional arguments. All examples in this section are target interfaces.

```sh
# Author and inspect an experiment without running it.
ceteris init --profile native-linux-local@1 -o ceteris.experiment.json
ceteris plan ceteris.experiment.json -o resolved-plan.json
ceteris doctor --plan resolved-plan.json --json

# Execute an already resolved plan; save each run as it finishes.
ceteris campaign run --plan resolved-plan.json
ceteris campaign status CAMPAIGN_ID
ceteris campaign resume CAMPAIGN_ID

# Re-evaluate only the explicit campaign/plan; no ambient config lookup.
ceteris compare --campaign CAMPAIGN_ID --plan resolved-plan.json --json
ceteris report --campaign CAMPAIGN_ID --format html -o report.html

# Export locally; no implicit publication or network upload.
ceteris bundle create --campaign CAMPAIGN_ID -o comparison.zip
ceteris bundle inspect comparison.zip --disclosure
ceteris verify --bundle comparison.zip
ceteris verify --bundle comparison.zip --require-pass

# Import pre-existing evidence without claiming fresh capture.
ceteris import results.json --adapter hyperfine@1 --variant base --output imported.json
ceteris compare base.json candidate.json --diagnostic
```

`CAMPAIGN_ID` above is a symbolic argument placeholder; actual commands accept a UUID or an explicit campaign directory. `init` generates a draft with required project-specific command/input/checker fields clearly marked; it cannot produce a runnable, accepted experiment until those fields are supplied. `plan` rejects unresolved draft markers.

### 14.2 Selection rules

Planned comparison requires exactly one campaign and one matching plan, or an explicit record manifest with all required assignments. Never silently select all runs from the working directory's default store for a policy decision. Legacy `compare` without inputs may retain store discovery in diagnostic/legacy mode.

`--last`, label globs, and arbitrary input lists are exploratory selectors. A user can save their selected set into a retrospective analysis manifest, which remains labeled retrospective. Duplicate file arguments are errors. Multiple files for the same run ID with conflicting content are integrity/identity failures rather than last-write-wins.

`--vary` and `--waive` continue to work for diagnostics. When supplied alongside a frozen plan, reject them with instructions to create an explicit amendment. `--require-signal` remains a legacy diagnostic behavior and cannot silently become a non-regression policy. New users select an explicit metric predicate.

### 14.3 Doctor behavior

`doctor --plan` performs only the probes/discovery needed for preflight; it does not run the benchmark or mutate machine settings. It distinguishes a missing capability, an unsupported capability, a contradictory observation, and a known plan error. It reports expected capture cost, tools that would be queried, and required evidence that cannot yet be established until execution.

Default remediation examples:

- Missing required input: identify logical artifact/path and the unresolved selector.
- Unsupported harness version: show detected version and supported tested range; suggest diagnostic import or explicit supported adapter.
- Insufficient planned sample count for the metric family: show the interval-resolution calculation and minimum finite-interval count.
- Unknown GPU image identity: explain the exact missing field; do not recommend a blanket hardware waiver.
- Duplicated observation: identify repeated run IDs/files and the resulting independent sample count.

### 14.4 Python API

Target pure interfaces:

```python
plan = resolve_experiment(authored, profile_registry, repository_context)
for record in execute_campaign(plan, store):
    consume_committed_record(record)

report = evaluate(plan, validated_records, evidence_index)
receipt = create_receipt(plan, report, bundle_manifest)
result = verify_bundle(bundle_reader, supported_protocols, require_pass=True)
```

`evaluate` must not probe the machine, read config from cwd, spawn subprocesses, discover plugins, or access the network. All inputs are explicit. `execute_campaign` yields only committed immutable records; its events API separately exposes progress and partial attempts.

Retain `compare(fingerprints, ...)` as a legacy diagnostic wrapper with documented behavior. Do not overload its `Report.exit_code` with the new acceptance semantics without a versioned API transition. Public protocol types and extension interfaces receive API stability guarantees after 1.0; internal helper functions do not.

### 14.5 Report usability and accessibility

The default text report should fit an ordinary terminal and show the primary reason before field detail. Collapse repeated missing-capability messages into one issue with affected run IDs. Preserve an option to expand every observation. Use words in addition to color; HTML tables require labels and keyboard-accessible controls. No browser service is required to read an exported report.

Add a small static HTML report with local assets only: dimension summary, metric intervals, per-pair values, execution-order plot, field differences, raw evidence links, and waiver/limitation list. It must open offline and safely escape every user/harness-provided string. The UI computes no new verdict; it displays the signed/hashed semantic report supplied to it.

## 15. CI, pytest, and distributed execution

### 15.1 GitHub Action contract

Introduce an Action major version for the planned workflow. Do not change an existing pinned Action's input interpretation silently. Proposed primary inputs:

| Input | Meaning |
|---|---|
| `experiment` | Path to reviewed experiment definition; required |
| `base-ref`, `candidate-ref` | Optional explicit commit refs; otherwise derive from the event |
| `policy-source` | `base` by default; `explicit` for a separately supplied trusted policy |
| `artifact-name` | Prefix for uploaded bundle/report; campaign UUID appended |
| `python-version` | Interpreter for Ceteris; does not redefine subject runtime |
| `store-root` | Optional root; each invocation creates a new campaign directory |

Implementation sequence:

1. Install Ceteris from the Action's pinned release/source, before entering candidate worktrees.
2. Read experiment/profile overrides from the base revision or explicit reviewed location. Candidate changes cannot silently lower thresholds, remove metrics, widen variation, or disable correctness.
3. Resolve both commit refs; fail visibly if either cannot be obtained. Do not ignore a failed fetch and proceed with a different revision.
4. Create isolated base/candidate worktrees and build directories. Preserve the user's checkout and active branch.
5. Freeze the resolved plan and campaign schedule outside either worktree.
6. Run configured builds and per-pair measurements on the same assigned testbed. Avoid concurrent baseline/candidate execution unless that is a different declared workload protocol.
7. Preserve all failed executions, logs, preflight findings, and completed records.
8. Render a summary and bundle in an `always()` cleanup/finalization step when the runner is still available. Hard runner termination cannot guarantee upload; local journaling still limits loss.
9. Upload report/bundle with an invocation-unique artifact name even when comparison fails. Propagate the actual evaluation code without losing it through a shell pipeline.
10. Remove only Action-owned worktrees/scratch after evidence is retained; never clean unrelated user files.

Use structured argv from JSON rather than interpolating user strings into generated shell. Explicit shell build steps, if supported, are executed as documented shell scripts whose exact contents are recorded. Untrusted PR benchmark code runs only under ordinary unprivileged pull-request CI rules; do not use a privileged target-event context to expose secrets or write tokens to it. The Action does not post PR comments or publish external results by default.

A candidate may legitimately change the benchmark definition. This requires a reviewed policy/experiment update and a campaign using a definition that meaningfully applies to both revisions. Do not silently compare unrelated baseline and candidate benchmark cases.

### 15.2 pytest integration

Start capture at `pytest_sessionstart` and end it at `pytest_sessionfinish`, using one frozen effective config and one run ID. A pytest process/session is one outer execution. Each benchmark case supplies one aggregate plus optional rounds/iterations. A campaign requiring 20 pairs launches 20 independent sessions per variant, not 20 inner rounds in one session.

Store session exit status, collection errors, selected/deselected/skipped cases, and benchmark definition identities. Expected missing cases cause incomplete evidence. A test failure causes failed correctness for its relevant scope; a session failure cannot be hidden because another benchmark produced numbers. Capture pytest/plugin versions and parameterization.

The plugin and `ceteris run -- pytest ...` must not record the same session twice as independent measurements. Propagate a parent run ID through a documented environment variable, `CETERIS_PARENT_RUN_ID`, and link plugin observations to the wrapper-owned run. Without a wrapper, the plugin owns the terminal run record. Register this environment variable as coordination metadata, not a comparable tuning variable.

### 15.3 Multi-node records

Replace lossy heterogeneous scalar/count flattening with a per-node evidence map plus deterministic aggregate views. The record binds an expected node inventory resolved from the allocation, reported node IDs, missing node IDs, and per-node stage observations. Use one campaign-local pseudonymous node ID mapping; real hostnames remain optional disclosure metadata.

Comparability of a hardware multiset compares typed canonical values and multiplicities, excluding prose/provenance from the grouping key. If placement matters, the policy compares node identity/placement maps rather than only a multiset. Keep both raw node evidence and the aggregate result so a reviewer can inspect heterogeneity.

Node captures receive the exact resolved capture configuration and collector version requirements. Do not allow remote tasks to discover a different ambient `ceteris.toml`. Use a shared explicitly owned scratch directory or launcher transport; system temp on one node is not assumed visible on all nodes. A missing, duplicated, malformed, or wrong-plan node response produces incomplete coverage.

Node-local requirements are profile-defined. Hardware/system observations may be required on every node; runtime libraries, executable hashes, and loaded drivers need node-scoped evidence when they may differ. A controller's MPI version is not proof of all remote ranks' runtime identity. Unsupported PBS/LSF/Flux fan-out remains incomplete for profiles requiring all-node evidence.

The fan-out collector must not claim that the affinity of its own short probe task equals the actual benchmark rank affinity. Those are separate fields/capabilities. Remote work submission remains out of scope; Ceteris uses an existing allocation unless the user explicitly selects a future scheduler orchestration extension.

### 15.4 Testbed limitations in CI

Hosted runners may expose incomplete hardware controls and variable neighboring workloads. A passing result is scoped to the profile and observed testbed. Store the testbed description and limitations, do not silently waive every unavailable sysfs field. Provide a `ci-observed-local@1` derived profile only after beta evidence establishes which required controls are practically observable; it must name weaker coverage than a dedicated machine profile.

Campaigns whose intended workload is contention or concurrency must declare it explicitly; a generic quiet-host template is not universally appropriate. Performance acceptance thresholds belong to the project, not a universal Ceteris default hidden in the Action.

## 16. Compatibility and migration

### 16.1 Version axes

Maintain independent identifiers for package version, record schema, plan schema, report schema, receipt format, canonical encoding, comparator engine, adapter interface, adapter semantics, profile, and analysis method. Every receipt identifies enough of these through its manifest/plan for a verifier to choose exact supported semantics.

Bug fixes changing a verdict require a new comparator/analysis semantics ID when applied to archived protocol results. A verifier may preserve the old algorithm for historical integrity checks while reporting a known defect. It must not silently recompute an old claim with a new algorithm and call the mismatch data tampering.

### 16.2 Legacy records

Read schema 2/3 without rewriting originals. Normalize into an internal diagnostic representation with explicit limitations:

- Missing execution IDs: assign an import identity tied to source payload and selector; independence remains unestablished.
- No prospective plan: `analysis_origin: retrospective`.
- No capability manifest: infer only explicitly represented observations, never complete expected coverage.
- Old `not_applicable` meanings that represented unsupported capture remain ambiguous unless the producer/version supplies a safe migration rule.
- No correctness evidence: `unverified`.
- No pre-execution artifact hash: pre-execution identity is unavailable.
- No raw samples: retain the reported aggregate; do not invent inner samples.

A migration command writes a derivative record with `migration` provenance and original digest. It must not relabel an old record as newly captured schema 4 simply by calling `to_json`. The current unconditional assignment of `SCHEMA_VERSION` during serialization must be replaced by explicit construction/migration semantics.

Legacy evidence can be viewed and compared diagnostically. It qualifies for a new policy only when it actually satisfies that policy; source omissions cannot be repaired by migration. Users must recapture to obtain missing observations.

### 16.3 Legacy certificates

Keep v1 refusal with a clear reason. Harden v2 parsing/display checks immediately, but explain that its counts are unordered and its bound record subset excludes some provenance/execution details. Preserve a named legacy engine for historical reproduction.

If the required historical engine/config semantics are unavailable, return unsupported rather than claiming a hash mismatch. Do not issue new v2 lines after v3 receipts become the default. Provide `verify --legacy` only as an explicit mode that shows integrity and original comparison outcome separately.

### 16.4 Transition releases

| Planning release | Scope | Compatibility behavior |
|---|---|---|
| `0.3.1` | F01–F08 and immediate false-success repairs | Keep record schema 3 where possible; reject unsafe cases; document conservative comparator changes and legacy verification semantics. |
| `0.4.0` | Durable lifecycle, schema 4 collection, typed adapter results | Read legacy records; new collection may opt into schema 4 until tooling is ready. |
| `0.5.0` | Frozen plans, coverage, pure evaluation, reference analysis behind experimental designation | New planned commands coexist with legacy diagnostics. |
| `0.6.0` | Bundles, receipts, CI/pytest workflow, external beta | New planned flow becomes recommended for supported integrations. |
| `1.0.0` | Stable protocol and externally validated interoperability | New acceptance semantics and extension compatibility commitments apply. |

These numbers may change; work-package dependencies and exit criteria govern readiness. A bugfix that requires a schema change may move to the next compatible release rather than smuggling an undocumented field reinterpretation into a patch.

## 17. Testing and conformance

### 17.1 Test layers

| Layer | Purpose | Execution |
|---|---|---|
| Unit | Deterministic field, numeric, policy, and lifecycle behavior | Every PR; no real hardware/network dependency |
| Regression | Every F01–F12 reproduction and subsequent reported defect | Every PR |
| Property/fuzz | Parser safety, canonicalization, selection, comparator invariants | Fixed corpus every PR; longer seeded jobs nightly |
| Adapter fixtures | Real supported-version exports and malformed variants | Every PR |
| Local integration | Real subprocesses, process trees, output streaming, interruption, persistence | Linux/macOS CI |
| Harness integration | Real Hyperfine, Google Benchmark, pytest-benchmark campaigns | Pinned supported versions plus scheduled current-version checks |
| Hardware integration | Actual GPU/scheduler/container/architecture evidence | Explicit platform jobs and contributor runs; never inferred from mocks |
| Conformance | Independent implementations produce identical normalized outputs | Release gate |

Use pytest markers `unit`, `integration`, `hardware`, and `slow`. Unit tests inject probe results and do not fail because the execution sandbox denies macOS sysctl. Hardware tests should fail when an advertised capability is broken on their declared testbed; absence of the declared testbed causes an explicit skip with a reason, not a silent pass.

The readiness baseline was 247 passed, 3 skipped, and 3 failed in the restricted local environment. A direct capture showed denied sysctl probes. This is a baseline observation, not a replacement for a clean supported-host CI run or a guarantee that every failure was independently resolved.

### 17.2 Required properties

- Reordering object keys does not change canonical digests or valid policy resolution.
- Canonical encoding is idempotent; decoding canonical bytes and encoding again yields exactly the same bytes.
- Typed equality is reflexive/symmetric/transitive on validated values.
- Exact ordered argv preserves option/value binding and precedence.
- Reordering input files does not change an explicitly assigned experiment's report.
- Adding a duplicate observation never increases independent `n`.
- Removing required evidence never upgrades acceptance.
- Adding an unknown optional field does not fabricate required coverage; a new material known difference still gates under default rules.
- Declaring a field varying does not remove its readability obligation or permit within-run drift.
- Changing any manifest-listed byte without rebuilding its digest graph fails verification.
- Mutating acceptance text without changing the underlying report cannot pass receipt verification.
- Failed correctness/harness validity never becomes accepted through a field waiver.
- A missing primary case cannot be rescued by a secondary metric's effect.
- Interrupting an execution cannot erase a previously committed record.
- Verification does not depend on cwd, PATH, local config, hostname, locale, current time, or network access.

Use generated cases to challenge these properties, not tests that merely repeat implementation expressions. Hypothesis or another property-testing package may be a development dependency; it must not become a core runtime requirement.

### 17.3 Conformance corpus structure

```text
tests/conformance/
  encoding/<case>/input.json + canonical.bin + sha256.txt
  records/<case>/record.json + expected-validation.json
  policies/<case>/plan.json + records/ + expected-report.json
  analysis/<case>/input.json + expected-analysis.json
  receipts/<case>/bundle/ + receipt.txt + expected-verification.json
  README.md
```

Each case declares supported protocol IDs, expected success/failure code, issue codes, and rationale. Store valid fixtures, malformed fixtures, and malicious-path fixtures separately so ordinary fixture discovery does not accidentally parse the wrong format. Include the exact observed false-success cases from Section 3.

Mandatory analysis vectors include all-equal positive values, threshold boundaries, lower/higher directions, unit conversion, even/odd medians, exact ties, outlier effects, incomplete pairs, duplicate IDs, all-invalid values, multiple primary metrics, and insufficient binomial interval resolution. Validate interval-index selection using an independently written exact reference in the test corpus generation process.

### 17.4 Fault injection and scale targets

Inject failures at journal creation, pre-capture, launch, output write, adapter parse, validator execution, artifact commit, record rename, directory sync, and campaign index update. Assert retained evidence and deterministic recovery.

Initial performance budgets, measured on a published reference machine and labeled as targets:

- Compare 10,000 validated small records within 5 seconds and under 512 MiB RSS.
- Stream 1 GiB child output with bounded incremental memory as specified in Section 8.
- Hash artifact files with at most a few fixed-size buffers; never read a large binary/dataset wholesale.
- Pure offline verification makes zero subprocess and network calls.
- Collector probes have explicit individual timeouts and a campaign-defined total capture budget; a timed-out optional probe creates a limitation rather than extending runtime indefinitely.

Do not gate release on arbitrary wall-clock numbers from shared CI. Publish controlled benchmark measurements and investigate regressions against the same testbed. If a target is missed, document its cause and adjust implementation or supported scale explicitly.

### 17.5 Support matrix

Create `docs/SUPPORT.md` listing platform/architecture, collector capability, harness/version range, real fixture provenance, last successful integration date, known limitations, and status (`supported`, `experimental`, `unsupported`). A fixture reconstructed from documentation never counts as a real-harness validation.

Supported status requires at least one real exported fixture, malformed/error fixtures, a real invocation integration test, documented capability scope, and an identified maintainer or reviewer. New versions outside the tested range are detected and reported; users may explicitly choose experimental collection, but stable profiles do not silently accept unsupported semantics.

## 18. Implementation work packages

These packages are the execution order for implementation. Each package should be a reviewable PR or a small sequence of PRs. The listed file ownership defines implementation responsibility, not permission to revert unrelated changes. Do not combine protocol stabilization, UI expansion, and unrelated refactoring in the same PR.

### 18.1 Dependency map

```text
WP01 -> WP02
  |       |
  +----> WP03 -> WP04 -> WP05
                    \      \
                     -> WP06 -> WP07 -> WP08
                                  \      \
                                   -> WP09 -> WP10
                              WP08 + WP10 -> WP11
                      WP04 + WP06 + WP11 -> WP12
                      WP06 + WP10 + WP11 -> WP13
                                 WP05 + WP06 -> WP14
                        all protocol packages -> WP15 -> WP16
```

The prerequisite column below is authoritative if the sketch is ambiguous. Work may be implemented independently where dependencies permit, but integration order follows the table. This document does not require multi-agent execution.

| Package | Prerequisites | Owned changes | Completion evidence |
|---|---|---|---|
| WP01: trust regression corpus | None | `tests/test_certificate.py`, `test_execution.py`, `test_stats.py`, `test_adapters.py`, new targeted fixtures | F01–F08 reproduced as failing tests against baseline; no production behavior changes. |
| WP02: trust hotfixes | WP01 | `certificate.py`, `comparators.py`, `defaults.json`, `execution.py`, narrow pre/post repair in `runner.py`, input checks in `cli.py`, `stats.py`, `config.py`, adapter validity bridge | All F01–F08 regressions pass; legacy behavior changes documented; no reproduced F01–F08 false-success path remains unaddressed. |
| WP03: protocol foundation | WP02 | New `protocol/`, draft schemas, encoding vectors, typed fields/metrics | Canonical bytes/digests, strict parser, decimal/rational validation, record structural rules pass unit/conformance tests. |
| WP04: durable runner/store | WP03 | `runner.py`, `store.py`, lifecycle journal, output spooling, process management | F03/F09/F10 fault tests; each execution persisted; bounded output; cancellation retains prior records. |
| WP05: source/artifact identity | WP03, WP04 | `identity.py`, `collectors/source.py`, execution identity, artifact manifests | Dirty-source/input/script changes detected; symlink/unreadable/unstable artifact tests; immutable before/after binding. |
| WP06: experiments/coverage/policy | WP03, WP05 | `experiment.py`, `coverage.py`, `policy.py`, profiles, registry | Authored example resolves; missing-everywhere requirements fail; deterministic priorities, waivers, variant assignment, plan immutability tested. |
| WP07: adapter contract/validators | WP04, WP06 | Split `adapters/__init__.py` into per-harness modules, `validators/`, import API | Hyperfine/Google Benchmark supported real integrations; stale/error/invalid output fixtures; case mapping and correctness evidence retained. |
| WP08: campaign orchestration | WP04, WP06, WP07 | `campaign.py`, worktree/build orchestration, schedule/resume | Complete paired campaign on two revisions; fixed schedule; no overwrite/retry selection; all failed outcomes retained. |
| WP09: analysis methods | WP03, WP06, WP07 | `analysis/`, descriptive and paired methods, statistical vectors | Exact reference results, family correction, threshold edge tests, written methodology review before stable designation. |
| WP10: semantic reports/CLI | WP06, WP09 | `report.py`, `compare.py` adapters, `render.py`, `cli.py` | Dimension truth tables, explicit selection, stable issue codes, exit precedence, JSON/text consistency. |
| WP11: receipts/bundles | WP08, WP10 | `bundle.py`, receipt v3, offline verifier, static HTML export | Tampering/path/omission fixtures; full offline recomputation; receipt distinguishes integrity from acceptance. |
| WP12: GitHub Action v2 | WP04, WP06, WP08, WP11 | `action.yml`, CI fixture repo/workflow, usage documentation | Trusted base policy; isolated builds; records uploaded on failure; repeated action invocation isolation. |
| WP13: pytest/Python | WP06, WP07, WP10, WP11 | `pytest_plugin.py`, selected-interpreter collector, Python profile | Before/after evidence; wrapper/plugin ID linkage; expected cases enforced; independent session pairs and package identity tested. |
| WP14: distributed evidence | WP05, WP06 | `nodes.py`, scheduler collectors, HPC profile | Correct scope/config propagation; expected inventory; heterogeneous and missing-node real Slurm tests. |
| WP15: migration/conformance | WP03–WP14 protocol interfaces settled | `migration.py`, legacy engines, conformance CLI/docs, support matrix | Legacy records never gain invented evidence; independent verifier passes shared corpus. |
| WP16: external beta/1.0 gate | WP11, WP12, WP15 | Documentation, onboarding, governance, release checklist, support triage | Section 19 gates met; no unsupported claims hidden in launch materials. |

### 18.2 Per-package implementation instructions

**WP01–WP02:** preserve minimal reproductions and assign stable issue IDs. Fix parsing and comparison before changing prose. For every tightened behavior, update CLI/help/spec examples and document any previously accepted input now rejected. Test original committed example bundles under their explicitly supported legacy semantics; do not edit measurements to make them pass.

**WP03:** ship schema documents and hand-written runtime validators together. JSON Schema validation may be used in development, but the dependency-free core must enforce equivalent runtime rules. Cross-object constraints such as duplicate execution IDs and matching plan references need code beyond JSON Schema. Include tests proving parity on the conformance corpus.

**WP04–WP05:** add a `run_records` iterator internally and keep `run_repeated` as a compatibility list wrapper. Write tests using actual short-lived child processes plus filesystem fault injection. Do not invoke expensive real hardware probes in persistence tests. Validate artifact identity under content changes that preserve filename and byte size.

**WP06:** keep authored and resolved plan types separate. Never mutate the resolved plan when a collector discovers a new field. Append observations, resolve applicable frozen rules, and flag unresolved requirements. Hash defaults and profile contents, not just a profile name. Define canonical schedule ordering once and test another implementation against it.

**WP07–WP08:** first deliver one complete native example repository with a correct checker and a deliberate regression. A harness export must link to its producing execution. Keep campaign/controller logs distinct from measured subject output. A preparation failure stops affected timing slots with retained evidence rather than executing a stale existing binary.

**WP09:** publish the reference method specification and exact vectors before integrating a green/red CLI gate. Obtain a review addressing estimand, independence assumptions, interval coverage, ties, multiple metrics, stopping rule, and predicate boundaries. A reviewer objection is a design revision, not something hidden behind a looser confidence threshold.

**WP10–WP11:** centralize decision computation. Renderers never decide whether a benchmark passed. Test offline verification with hostile cwd config and unavailable network/subprocess facilities. Include at least one honestly failed report whose integrity verifies, and one successful-looking altered report that fails.

**WP12–WP14:** test the actual integrations, not only mocked output. Keep unsupported environments visibly experimental. Scope any contributor hardware validation to the configuration actually tested. Do not promote all schedulers or all GPU vendors because one Slurm/NVIDIA fixture passes.

**WP15–WP16:** write migration examples and public compatibility promises. Have an implementer who did not write the Python evaluator build a read-only verifier from the spec and corpus. Resolve every disagreement as either a spec defect or an implementation defect before standardizing the format.

### 18.3 Acceptance scenarios

| Scenario | Required behavior |
|---|---|
| Identical valid builds with a narrow interval within 5% | Non-regression passes; no false requirement for a performance signal. |
| Candidate consistently 10% slower, budget 5% | Measured predicate fails; comparability may still be compatible. |
| Candidate faster but required correctness checker fails | Execution evidence retained; acceptance fails regardless of timing. |
| Candidate changes input bytes at same path | Artifact difference blocks unless it is an explicitly declared workload change. |
| Candidate removes a required benchmark case | Coverage incomplete; remaining case improvements cannot rescue it. |
| Run two interrupted after run one commits | Run one survives; interrupted attempt retained/recovered; campaign incomplete. |
| Same record supplied three times | Duplicate-observation error; no inflated sample size. |
| Raw harness output says INVALID | Harness failure; no acceptance receipt claiming pass. |
| One of sixteen allocated nodes absent | Required node coverage incomplete; report names missing node IDs. |
| User edits report acceptance/counts | Bundle/receipt verification fails. |
| Verifier has a different cwd config | Frozen-plan result unchanged. |
| Policy accepts one documented unknown capability | Raw coverage remains incomplete; result may be passed_with_waivers only under that policy. |
| Legacy capture lacks pre-run subject identity | Diagnostic viewing works; new required capability remains unavailable. |
| Export is intentionally redacted | New bundle/receipt; omitted evidence and reduced assurance visible. |

## 19. Adoption, governance, and release gates

### 19.1 Initial positioning and documentation

Use: "Ceteris makes the evidence and rules behind a benchmark comparison portable and verifiable." Follow it with the exact supported workflow and limitations. Remove universal claims that other benchmark tools never capture environment information. Pyperf already exposes substantial metadata, while Bencher has directional regression thresholds; Ceteris should explain the added policy/evidence contract and interoperability rather than dismiss those systems. See the primary references in Section 20.

Required documentation before external beta:

- A ten-minute supported native-code walkthrough using real committed records.
- A worked unchanged-result example that correctly passes a non-regression policy.
- A real regression example, a correctness-failure example, and an incomplete-evidence example.
- A guide to fields, capabilities, scope, and profile selection.
- An explanation of independent repetitions versus harness iterations.
- A bundle verification guide requiring no account or network.
- A support matrix, known limitations, migration notes, and stable CLI exit codes.
- Contributor and adapter-author guides, issue templates with optional sanitized bundles, and a vulnerability-reporting route.

Avoid making a dashboard, logo redesign, broad adapter count, or package-download target a prerequisite for correctness work. An independent project that retains Ceteris in its workflow provides stronger adoption evidence than a launch-day install spike.

### 19.2 External beta protocol

Recruit 5–10 consenting external teams after the trust gate. Target at least three native-code maintainers, one performance/CI tooling maintainer, and one HPC user; include people who were not involved in the implementation. This is a proposed recruitment target, not a claim of existing users or authorization to contact anyone.

For each team:

1. Record their existing harness, platform, desired comparison decision, and current manual process.
2. Have them complete the documented workflow without a maintainer editing their files.
3. Collect voluntarily supplied failure reports and sanitized bundles; do not enable telemetry by default.
4. Categorize problems as real experiment defects, collector limitations, false rejections, unclear wording, integration problems, or protocol defects.
5. Follow up after at least four weeks to see whether the workflow remains enabled and which waivers persist.

Measure: time to first useful report, first-run completion rate, maintainer interventions, unresolved false rejections, waiver frequency by capability, repeated weekly/campaign use, and independent verification success. Do not treat every waiver as a failure; identify recurring waivers that indicate an incorrectly scoped default profile.

### 19.3 Integration priorities

1. First-class Hyperfine and Google Benchmark supported examples and CI usage.
2. A stable producer/import API and pytest/Python integration.
3. An independently implemented reader/verifier using the published protocol.
4. Contributions or optional export support in existing harnesses, after their maintainers confirm the interface is useful.
5. HPC/GPU/scheduler breadth backed by real fixtures and capability ownership.

Do not require users to replace their harness, upload results to a proprietary service, or accept a fixed benchmark suite. Keep records and verification usable independently of the Ceteris runner and independently of the project's future hosting/business choices.

### 19.4 Governance and protocol evolution

Before 1.0, add `CONTRIBUTING.md`, `GOVERNANCE.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, and `docs/COMPATIBILITY.md`. Existing MIT-licensed code remains reusable. State that implementing the documented protocol and running its conformance tests requires no membership or fee. Clarify specification/test-fixture reuse terms with the project owner before publishing a formal standards claim; do not imply rights to third-party harness fixture content beyond its license.

Protocol changes use numbered design proposals containing motivation, exact semantic/schema changes, compatibility treatment, test vectors, and migration examples. A semantics-changing proposal requires review from at least two maintainers, including one reviewer outside the originating implementation area. Statistical methods additionally require qualified methodology review. Record dissent, alternatives, and unresolved limitations in the proposal.

Reserve core identifiers under `ceteris.*`; third-party extensions use a reverse-domain namespace. Published schema/profile/method IDs are immutable. A corrected meaning receives a new ID/version; a registry entry can mark an older version deprecated or known-defective without rewriting it. Maintain a machine-readable registry and conformance version list in the repository.

### 19.5 Gates

| Gate | Required evidence |
|---|---|
| Trust gate, before broad promotion | F01–F12 addressed or explicitly blocked from positive claims; no known reproduced false-success case remains possible in advertised supported flow; regressions run in CI. |
| Workflow gate, before external beta | Complete native campaign, per-run persistence, required correctness/input identity, readable failures, frozen plan, offline bundle verification. |
| Methodology gate, before stable statistical acceptance | Written external review, exact conformance vectors, fixed stopping/selection contract, documented estimand and limits. |
| Beta gate, before default recommendation | At least five external teams complete the workflow; at least three retain it over four weeks; no unresolved critical false success; recurring false rejections have documented fixes or correctly scoped profiles. |
| Protocol gate, before 1.0 | Independent verifier agrees on the corpus; schemas and semantics frozen; migration/support policy published; release artifacts reproducible enough to trace to their source commit. |
| Maintenance gate, before standardization claim | At least two active maintainers, issue triage ownership, security-report route, release/compatibility process, and a publicly maintained conformance suite. |

These are proposed minimum gates, not statistically proven adoption thresholds. A known incorrect acceptance result blocks release even when usage targets are met. Missing independent methodology/interoperability review blocks the relevant stable claim; it does not block publishing clearly labeled experimental tools.

## 20. Risks, deferred work, and references

### 20.1 Risks and explicit mitigations

| Risk | Mitigation and residual limitation |
|---|---|
| Excessive false rejections drive users to broad waivers | Capability-specific profiles, precise diagnostics, beta waiver analysis; retain unknown evidence rather than silently claiming absence. |
| Collector overhead changes cache/thermal state | Measure and report capture overhead; fixed capture/validation placement and explicit reset/warmup procedures; no promise that observation is free. |
| Input hashing is expensive | Streaming/campaign preparation and explicit capability levels; strict byte identity cannot be replaced with metadata-only caching without disclosure. |
| Process/build/runtime identity remains incomplete | Explicit artifact closure and scope; optional actual-loaded dependency/remote attestation capabilities later. |
| Statistical method assumptions do not fit a workload | Narrow method eligibility, external review, descriptive fallback, separately versioned future methods. |
| Protocol becomes too large to implement | Freeze a small core; required extension IDs; independent minimal verifier as an early constraint. |
| Changing semantics invalidates historical results | Preserve old records, named legacy engines, known-defect advisories, and new report/receipt lineage for reanalysis. |
| Sensitive information leaks through public artifacts | Allowlisting, disclosure preview, explicit derivative redaction, no implicit upload. |
| Claimed authenticity exceeds unsigned evidence | Separate integrity, producer identity, correctness evidence, and policy acceptance in UI/API. |
| Maintainer burden exceeds capacity | Limit supported integrations, require real fixtures/ownership, recruit outside maintainers before universal claims. |

### 20.2 Deferred capabilities

Deferred work has no implicit placeholder pass:

- Windows process groups, counters, path semantics, and a validated Windows profile.
- Actual loaded native library/page provenance and subject execution attestation.
- Automatic model/dataset/remote deployment discovery.
- Hierarchical rebuild/machine statistical models and adaptive sampling.
- General unpaired historical baseline analysis and historical regression dashboards.
- Signed producer attestations and external identity/trust services.
- Full scheduler submission and portable cancellation beyond existing allocations.
- Arbitrary shell-program dependency inference.
- Hosted collaboration, artifact hosting, and automated publishing.

Each capability should enter through a concrete external use case, a scoped design proposal, supported evidence, and a conformance extension. Do not add a field as permanently unknown merely to claim a larger feature list.

### 20.3 External validation still required

The document chooses implementable defaults; the following are release checks, not unspecified implementation choices:

1. Independent methodology review of `paired-median-relative@1` and its reporting/acceptance interpretation.
2. Real Hyperfine/Google Benchmark/pytest version compatibility and timing-boundary validation.
3. Real multi-node Slurm and supported GPU/container capability validation.
4. An independently implemented canonical encoder/verifier agreeing on the corpus.
5. External-user evidence that required capabilities and errors are practical on their testbeds.

### 20.4 Primary references

These references motivate requirements; they do not endorse Ceteris or validate this implementation. The proposed reference statistical method and protocol decisions are specified in this document, not attributed wholesale to another project.

- [Pyperf API and metadata](https://pyperf.readthedocs.io/en/latest/api.html): demonstrates established metadata, units, warmups, and inner-loop/outer-run distinctions. Interoperability should retain those distinctions.
- [Pyperf system tuning](https://pyperf.readthedocs.io/en/latest/system.html): documents existing affinity and machine-tuning support; Ceteris positioning must acknowledge it.
- [Bencher thresholds](https://bencher.dev/docs/explanation/thresholds/): demonstrates directional upper/lower regression policies; a generic requirement for any signal is not a substitute for a regression policy.
- [Kalibera and Jones, Rigorous Benchmarking in Reasonable Time](https://kar.kent.ac.uk/33611/): motivates explicit levels of repetition and uncertainty reporting. It does not by itself validate the proposed method in Section 11.
- [SPEC CPU2017 run and reporting rules](https://www.spec.org/cpu2017/Docs/runrules.html): demonstrates the role of correct-output validation and disclosure of reproducibility evidence.
- [MLPerf Inference submission guide](https://docs.mlcommons.org/inference/submission/): demonstrates separate performance and accuracy evidence in a benchmark workflow.

### 20.5 Definition of completion for this design

The design is implemented when the supported native workflow can produce a prospectively planned, correctly validated, durably stored comparison; every positive statement is scoped to its evidence and policy; a recipient can reproduce that decision offline; and an independent verifier agrees with the reference implementation. Broader ecosystem support is an ongoing, evidence-backed expansion of that core.

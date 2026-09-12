**Ceteris shipment review — 9 September 2026**

**Repair status — 10 September 2026.** The reproduced defects below have been repaired in the working tree, with unfinished protocol features explicitly excluded from the supported release. Local validation passed for the documented `0.4` capture/compare workflow. This is a release candidate for that scope; the repaired commit still needs the hosted CI matrix before publication. It is not qualification for the complete prospective campaign workflow in `DESIGN.md`.

| Finding | Current disposition |
|---|---|
| R1: unevaluated bundle acceptance and availability | CLI verification now reports file integrity only, with no verified acceptance. `--require-pass` and stronger availability requirements refuse the claim, including an empty bundle whose stored report says `passed`. Full acceptance evaluation remains unsupported. |
| R2: false or colliding repetitions | Runs receive an execution UUID before launch; the pytest plugin links to its wrapper. Copies retain their identity despite relabels. Legacy duplicate detection ignores presentation metadata. Separate fast executions remain distinct. |
| R3: candidate-controlled Action policy | The root Action freezes the effective base configuration before builds, reuses it for both runs and comparison, and stores each invocation's evidence outside the checkout in a unique directory. Inputs pass through environment variables and argv parsing. |
| R4: explicit ingestion | The runner snapshots each named export before execution, checks freshness and adapter validity afterward, and records evidence that gates comparison. Stale, invalid, or unreadable required exports prevent a pass. |
| R5: missing cases and observation | Comparison consumes expected-case coverage, recomputes missing cases from metrics, and refuses unavailable pre/post observation. New certificate digests bind this evidence and execution identity. |
| R6: campaign workflow | Explicitly excluded. The `v2/` Action fails before installation, checkout, or builds. No campaign runner has been added. |
| R7: substituted profiles and unresolved revisions | Planning requires a supplied profile matching the authored identifier and full immutable commit IDs. It cannot silently use a diagnostic profile or freeze symbolic refs. |
| R8: bundle symlinks and bounds | Member reads open each path component without following symlinks, check regular files and size limits, and parse the same bytes that were hashed. The manifest uses the same safe reader. |
| R9: unbounded lines | The runner reads fixed-size byte chunks into a bounded tail and reports actual dropped bytes, including output with no newline. |
| R10: mutable plan views | Plans retain canonical immutable bytes; public nested views are independent copies. |
| R11: malformed records | Imported and library records validate exit codes and evidence structures before comparison; malformed field states are rejected. |
| R12: missing measurements | A metric is unassessed unless every selected execution contributes a readable sample. Its readable subset cannot satisfy the signal requirement. |
| Release and promises | Full-version tags invoke the CI matrix before build/publish; floating `v0` does not trigger publication. README, SPEC, changelog, releasing instructions, and [support status](SUPPORT.md) describe the delivered scope. |

**Validation of the repaired working tree**

| Check | Observed result |
|---|---|
| Full local suite, Python 3.14.7 on macOS | **869 passed, 3 skipped**, 17.37 seconds, with normal hardware access. Includes real pytest sessions missing required cases and regression coverage for the findings above. |
| Workflow and patch checks | `actionlint` and `git diff --check` passed. |
| Distribution | Built wheel and sdist from a snapshot of the repaired tracked and new source files. Both passed `twine check`; a fresh offline wheel install passed `pip check` and reported `ceteris 0.4.0`. |
| Installed Hyperfine flow | Three executions each of `/bin/sleep 0.02` and `/bin/sleep 0.04`; required-signal comparison and offline `verify --require-pass` passed. The committed README certificate also still verifies. |
| Actual root Action scripts, executed locally | Two temporary commits produced three records per side. Base, head, comparison, and offline verification passed. The base configuration stayed fixed despite a candidate severity override; two preparation invocations produced different directories. A separate regression test confirms the candidate override cannot turn a CPU mismatch into a pass. |
| Installed refusal checks | Comparing a single configuration with required signal exited 4. Failed commands and unchanged explicit exports compared as indeterminate, exit 2. Their certificates verified for integrity, while `verify --require-pass` refused them with exit 1. An empty bundle claiming passed acceptance and reproduction readiness was also refused, exit 1. |

Repair smoke scripts, distribution files, and command logs are under `/tmp/ceteris-fixed-20260909`, including `smoke-results.json` and `negative-smoke-results.json`. The test suite preserves the defect regressions in the repository. No release was published. Hosted CI on the repaired commit, cluster/GPU revalidation, independent verifier agreement, and broader campaign qualification remain unverified.

**Review follow-up — 11 September 2026.** Review found that binary output capture preserved CRLF and CR endings, breaking existing line-anchored metric patterns. The decoded output now uses universal newline normalization while its buffer and byte counters retain raw bytes. Regression tests cover LF, CRLF, CR, and a CRLF pair split across chunks after truncation. The full suite passed **873 tests, with 3 skipped**, in 19.54 seconds with normal hardware access. Release validation after this dated review is recorded in the release's GitHub Actions run.

**Original audit, preserved below**

The following verdict and source line numbers refer to the original commit, before these repairs.

**Original verdict: do not ship that checkout under its then-current promises.** The normal capture/compare flow worked, the test matrix was green, and the package installed. Several paths still certified insufficient or invalid evidence. The newer planned-experiment workflow was also incomplete. This failed the project's own trust and workflow gates in [DESIGN.md](DESIGN.md#195-gates).

Reviewed commit: `ecd8421cc487dd1c105b7fc7d5fb24b2b8c5016f`, package version `0.4.0`, marked unreleased in the changelog. The implementation was not changed during the initial review. All original experimental records, builds, and scripts were created under `/tmp/ceteris-shipment-review-20260909`.

**What passed**

| Check | Observed result |
|---|---|
| Full local suite, Python 3.14.7 on macOS | **836 passed, 3 skipped**, 16.27 seconds. An initial sandboxed run had three hardware-probe failures; all disappeared with normal hardware access. |
| CI for the exact reviewed commit | All **12 Ubuntu/macOS × Python 3.9–3.14 test jobs passed**. The Action self-check was skipped because this was a push run. [CI run](https://github.com/iemAnshuman/ceteris/actions/runs/33973123452). |
| Clean distribution build | Built wheel and sdist from `git archive HEAD` in a temporary directory; both passed `twine check`. |
| Fresh installation | Installed the wheel into a new virtual environment with `--no-index --no-deps`; version output and `pip check` passed. Defaults loaded, and metadata contains only optional development dependencies. |
| README's committed Hyperfine example | Its exact certificate verified. Recomputing the comparison reproduced the certificate. The freshly installed wheel also verified it with `--require-pass`. |
| New real Hyperfine experiment | Three executions each of `/bin/sleep 0.02` and `/bin/sleep 0.04`; run, compare with declared subject variation and required signal, certification, and verification all exited 0. |
| Local doctor | 111 fields: 25 captured, 86 not applicable, zero unknown/error. Battery power was reported as advisory. |
| Real pytest integration | Two real pytest-benchmark sessions produced records and measurements. Required-case enforcement failed as detailed below. |

These establish that installation and selected normal flows work. They do not establish that every positive verdict is justified.

**Release-blocking correctness findings**

**R1 · P1 · Bundle verification trusts the stored verdict and availability claim.**

`bundle.verify()` only recomputes a report when the caller supplies its optional `recompute` callback. The CLI never supplies one. It takes acceptance directly from `report.json` and checks the availability level by its declared name. It does not establish that the plan, observations, and evidence justify those claims.

Reproduction: created a bundle containing a minimal plan, a report saying `passed`, and **zero run records**, labelled `reproduction_ready`. `ceteris bundle verify ... --require-pass --require-level reproduction_ready --json` exited **0**, with `integrity: true`, `acceptance: passed`, `supported_semantics: true`, and no problems.

This does not demonstrate changing an existing bundle while retaining its original receipt. It demonstrates that a newly issued, internally consistent receipt can endorse an unevaluated claim. The distinction matters because the bundle README promises decision recomputation.

Fix: validate supported plan/record/report semantics, derive coverage and availability from actual evidence, and recompute acceptance before reporting a verified pass. Until the evaluator is connected, refuse acceptance verification or explicitly expose integrity-only verification without a positive acceptance claim.

Source: `src/ceteris/bundle.py:328`, `:342`, `:348`; `src/ceteris/cli.py:469`. Evidence: `probe-results.json`, key `empty_bundle_claims_pass_and_reproduction_ready`.

**R2 · P1 · Relabelling copies manufactures independent repetitions.**

Duplicate detection hashes presentation metadata, including `meta.label`, instead of a stable execution identity. I took one committed Hyperfine observation from each of two configurations, copied each three times, and changed only the labels. `compare --require-signal --certify` exited **0** and issued `configs=2 n=3,3 ... verdict=ok noise=0%`. Only two original executions existed.

The reverse problem also appeared in live checks: two separately launched, very short executions produced identical rounded/timestamped records and were rejected as duplicates. That result is recorded in `integration-results.json`; the subsequent ingestion check used explicit repeats to keep execution metadata distinct.

Fix: assign durable execution IDs before launch, preserve them through copies/relabels, and deduplicate by producing execution. Legacy records need a conservative identity rule and explicit assurance limits.

Source: `src/ceteris/compare.py:297–334`; `src/ceteris/runner.py:249`. Evidence: `probe-results.json`, key `relabel_two_executions_as_six`.

**R3 · P1 · The advertised GitHub Action lets candidate configuration change the gate.**

The root Action checks out the candidate and then runs `ceteris compare` there without a trusted explicit config. Automatic config discovery reads the candidate's `ceteris.toml`.

Reproduction: two temporary records differed in CPU model and matched on architecture. Comparison exited **1**. After adding a candidate config that made only `hardware.cpu_model` informational, I executed the actual `Compare` shell block extracted from `action.yml`, with its default inputs substituted. It exited **0** and issued `verdict=ok` for the same records. This was a local execution of the Action's real comparison script, not a hosted PR run.

Fix: freeze the effective policy from a trusted revision before either variant runs and use it for both capture and evaluation. The v2 design addresses this trust boundary, but that Action cannot execute campaigns yet. The root Action also grants broad `source` and `deps` variation, which should be explicitly documented and reviewed.

Source: `action.yml:66`, `:78–84`; `src/ceteris/cli.py:254`. Evidence: `action-policy-result.json`.

**R4 · P1 · Explicit ingestion bypasses freshness and harness validity.**

The normal adapter path records validity and snapshots exports. The `--ingest` path calls a metrics-only parser, constructs its plan without a pre-run snapshot, and discards harness validity.

Reproduction: supplied a pre-existing synthetic Google Benchmark export with one numeric case and another case reporting `error_occurred: true`. Two real `python -c pass` executions did not rewrite that export. Their records retained the numeric case, had no harness validity claim, and `compare --certify` exited **0** with `verdict=ok`.

Fix: use the same evidence/validity contract for explicit ingestion and detected adapters. Bind exports to their producing execution, propagate harness errors, and reject unchanged exports when claiming they came from a wrapped run. Historical import should explicitly retain its weaker provenance.

Source: `src/ceteris/runner.py:271–273`; `src/ceteris/adapters/__init__.py:476–493`. Evidence: `final-check-results.json`, `integration-results.json`, and `live/old-invalid-gbench.json`.

**R5 · P1 · Explicitly missing pytest cases do not prevent certification.**

Two real pytest-benchmark sessions requested `--ceteris-expect-case pytest.test_missing.median_s` while producing only `pytest.test_present.median_s`. Both records correctly say coverage is `incomplete` and name the missing case. Both pytest commands exited 0, and comparing their records issued a certificate with `verdict=ok` and exit **0**.

The comparison engine never consumes `run.case_coverage`. It also ignores an explicit `drift_observed: false`; a focused record-level probe returned exit 0 for that condition.

Fix: feed required-case coverage and unavailable required pre/post observation into the actual decision path. Preserve compatibility for legacy diagnostic records explicitly instead of silently treating unavailable evidence as success.

Source: `src/ceteris/pytest_plugin.py:195–201`, `:217–221`; `src/ceteris/compare.py:182–195`. Evidence: `integration-results.json`, key `pytest_compare_missing_required_case`, and `probe-results.json`.

**Incomplete planned-workflow features**

**R6 · P1 for planned-workflow shipment · No campaign runner is available.** `ceteris campaign --help` exits 2 because the subcommand does not exist. `v2/action.yml:182–192` explicitly reports that no measurements were taken, sets `acceptance=not_evaluated`, and ultimately propagates exit 2. This failure is honest, but the workflow is unusable for a release claiming complete prospective campaigns. `campaign.py` provides persistence machinery; it does not connect the full build/capture/validate/analyse/bundle lifecycle. The changelog acknowledges that `run` and `compare` still use the older format.

The v2 Action has further integration gaps visible in source: it uses fixed paths below `STORE_ROOT` without appending its campaign UUID, and calls `bundle inspect --acceptance`, an option the CLI does not implement. Those require actual repeated-invocation integration tests when the runner is connected. Current Action tests primarily inspect YAML and strings.

**R7 · P1 for planned-workflow shipment · Planning silently substitutes a diagnostic profile.** An authored experiment requested `native-linux-local@1`. Running `ceteris plan` without a separate `--profile` file exited **0** but froze `{id: diagnostic, version: 1}`. It also retained `main` and `HEAD` as the “resolved” revisions when explicit commit overrides were omitted. The Action supplies revisions but does not supply a profile file, so the profile substitution affects its path too.

Fix: resolve the authored profile identifier and all effective requirements, or fail with an unsupported-profile error. Resolve references to full immutable revisions, or require them explicitly. Source: `src/ceteris/cli.py:391–393`; `src/ceteris/experiment.py:244–252`. Evidence: `probe-results.json`, key `named_profile_resolution`.

**Additional reproduced defects**

| Finding | Evidence and consequence | Required correction |
|---|---|---|
| **R8 · P1 · Bundle ancestor symlinks escape the root** | Moved a synthetic bundle's `records` directory outside the root and replaced it with a directory symlink. Verification still exited 0. Only the final file is checked with `is_symlink()` (`bundle.py:284–291`). No private files were used. | Check every path component and root containment before opening any member, including the manifest. |
| **R9 · P2 · Output buffering remains unbounded for a single long line** | A 5 MiB ASCII line left 5,242,880 characters retained in a spool limited to 65,536; only 65,536 were returned and the dropped counter stayed 0. The reader also iterates by line. (`runner.py:61–71`, `:220`.) | Read bounded chunks, trim the retained buffer as data arrives, and count actual dropped bytes. |
| **R10 · P2 · “Frozen” plans expose mutable nested state** | Appending `*` to `plan.to_json()['policy']['vary']` changed the original plan's digest while it remained labelled `prospective`. `to_json()` makes only a shallow copy (`experiment.py:220–221`). | Do not expose internal mutable containers; ensure amendments create separately labelled lineage. |
| **R11 · P1 · Malformed legacy evidence can pass** | Record-level probes with `exit_code: "183"` or a `value` field lacking `v` both compared successfully. The reader accepts them and failure checking only recognizes integer exit codes (`model.py:64–77`, `:154–181`; `compare.py:208–211`). | Validate legacy records before evaluating or issuing certificates, with malformed evidence ineligible for a positive claim. |
| **R12 · P2 · Missing measurements within a configuration are discarded** | Two configurations with four records each, three values and one explicit unknown per configuration, passed `require_signal=True`. Statistics used only the three readable values (`stats.py:84–102`). | Report missing observations and apply an explicit inclusion policy; do not imply a result covers every selected observation. |

These focused reproductions are in `probe-results.json`. R11 and R12 are synthetic evaluator cases, not additional real benchmark executions.

**Release setup, documentation, and remaining uncertainty**

The latest GitHub release is `v0.3.0`; this checkout's `0.4.0` changelog remains unreleased. This review did not publish anything or verify PyPI account configuration. A historical release workflow failed on the floating **`v0`** tag because the workflow matches `v*` but requires the tag to equal the full package version. That conflicts with the documented instruction to move `v0`. [Observed failed workflow](https://github.com/iemAnshuman/ceteris/actions/runs/33870738344).

The release workflow builds and checks package metadata but does not itself require the test matrix to pass for the release commit. Add that dependency before treating tag publication as a validated release process.

The README opening promises to refuse a comparison when either environmental comparability or the noise requirement fails. Actual default comparison makes signal optional, and its help documents “some metric” rather than a complete primary-metric policy. Documentation should state exactly what a passing legacy comparison means and distinguish it from planned non-regression/correctness acceptance. It should also distinguish the new library components from features accessible through a complete CLI flow.

This audit did not repeat Slurm, multi-node, GPU, container, or the five adapters the README labels unverified on real hardware. It did not establish independent methodology review, independent-verifier agreement, or external beta retention. No such completion evidence was found in the inspected repository material. These remain unverified here, not assumed successful or proven absent elsewhere. The design itself limits stable statistical and protocol claims until those gates are met.

**What must change before sign-off**

1. Close the positive-verdict holes in R1–R5, R8, and R11, and add tests through the real CLI/integration boundaries. Include relabelled duplicates, missing required cases, invalid imported exports, and unevaluated bundles.
2. Make R6–R7 work end to end before shipping the planned workflow, or exclude that workflow from release claims and prevent unfinished verification paths from reporting acceptance.
3. Address R9–R10 and make R12's inclusion policy explicit. Verify the corrected execution identity against both copied records and legitimate fast executions.
4. Run one supported native campaign covering unchanged performance, a real regression, failed correctness, and incomplete evidence; verify each result offline from an installed distribution.
5. Require successful validation for the release commit, correct tag handling, and align the public documentation and support status with the delivered behavior.

**Evidence location**

Detailed scripts and observations are in [the temporary audit directory](/tmp/ceteris-shipment-review-20260909). The main files are [probe-results.json](/tmp/ceteris-shipment-review-20260909/probe-results.json), [integration-results.json](/tmp/ceteris-shipment-review-20260909/integration-results.json), [final-check-results.json](/tmp/ceteris-shipment-review-20260909/final-check-results.json), [action-policy-result.json](/tmp/ceteris-shipment-review-20260909/action-policy-result.json), [ci-status.json](/tmp/ceteris-shipment-review-20260909/ci-status.json), and [build.log](/tmp/ceteris-shipment-review-20260909/build.log). Temporary files may be cleaned by the OS; the findings and measured outcomes are preserved in this report.

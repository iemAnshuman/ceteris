# ceteris record format, version 3

This is the file `ceteris run` and `ceteris capture` write and `ceteris
compare` reads. It is documented so that harnesses can emit records natively
and other tools can consume them. Anything not described here is not
guaranteed.

## Top level

```json
{
  "meta":    { ... },        // non-comparable: label, timestamps, tool, hash
  "fields":  { "<path>": <field>, ... },   // the comparable body
  "run":     { ... },        // optional: execution facts
  "metrics": { "<name>": <field>, ... }    // optional: the dependent variable
}
```

Keys are sorted at every level. Files are UTF-8 JSON with a trailing newline.

### meta

| key | type | meaning |
|---|---|---|
| `schema_version` | int | `3` for this document |
| `label` | string | display name; repeats of one configuration share it |
| `captured_at` | RFC 3339 string | when capture began |
| `content_hash` | hex sha256 | over `fields` only, as compact sorted JSON |
| `tool`, `tool_version` | string | producer |
| `kind` | `"capture"` or `"run"` | |
| `series`, `repeat` | string, int | set by `--repeats`; repeat is 1-based |
| `adapter` | string | harness adapter used, if any |

Nothing in `meta` participates in comparison. `captured_at` is here and not
in `fields` precisely so two captures of the same environment hash identically.

### field

```json
{ "s": "<state>", "v": <any>, "p": "<provenance>", "d": "<detail>" }
```

| `s` | meaning | `v` present |
|---|---|---|
| `value` | captured | yes |
| `not_applicable` | structurally absent (no GPU in this machine) | no |
| `unknown` | may exist, could not be read (nvidia-smi hung) | no |
| `error` | the collector itself failed | no |

`p` records how the value was obtained: a command line, a file path, an
environment variable. `d` is free text explaining a non-value state or
annotating a value.

The rule that decides `unknown` against `not_applicable`: a tool's absence
implies the thing's absence only when the tool *is* the thing.

### paths

Dotted, lower-case, first segment is the namespace:

`source` `build` `runtime` `parallelism` `hardware` `scheduler` `system`
`execution` `toolchain` `deps` `packs`

`runtime.env.<VAR>` holds one environment variable. `build.cmake.<KEY>` one
CMake cache entry. `deps.<lockfile>` one lockfile hash. Consumers must not
assume the set of paths is fixed: unknown paths are compared like any other
and gate at `material` severity by default.

`execution.*` describes the wrapped command line. `execution.program` and
`execution.program_args` are the split of the line after any recognised
launcher; `execution.program_sha256` is the hash of the program binary and
`execution.program_scripts_sha256` the hashes of any script files among its
arguments. When a harness adapter can tell which commands the harness itself
times (hyperfine), those are `execution.subject`, their executables' hashes
keyed by executable are `execution.subject_sha256`, scripts among their
arguments are `execution.subject_scripts_sha256`, and `execution.program_args`
then holds only the harness's own options. Without such an adapter the three
subject fields are `not_applicable`. (Added in version 3.)

`hardware.*` and `system.*` describe every node of a Slurm allocation, merged
(a value shared by all nodes, or sorted `[value, count]` pairs). Under another
scheduler, or without `srun`, a multi-node job's node-local fields are
`unknown` and `hardware.node_count` carries the scheduler's node count.

### run

| key | type |
|---|---|
| `exit_code` | int; a signal death is `128 + signal`, as a shell reports it |
| `signal` | int, only when the command died by signal |
| `started_at` | RFC 3339 |
| `duration_s` | float |
| `output` | string, last 64 KiB of combined stdout/stderr |
| `output_truncated` | bool |
| `drift` | list of `{path, before, after}` for gating fields that changed between the before and after captures |

### metrics

Same field encoding as `fields`, keyed by metric name. Names produced by
adapters are `<adapter>.<benchmark>.<stat>_<unit>`. Metrics never enter the
content hash and are never compared for equality: they are what is being
measured.

## Comparison semantics

Per path across N records:

| condition | verdict |
|---|---|
| any record `unknown` or `error`, or path absent from a record | indeterminate |
| all `not_applicable` | match |
| mix of `not_applicable` and values | differ |
| more than one distinct canonical value | differ |
| otherwise | match |

Canonicalisation is per comparator (`scalar`, `flagset`, `version`, `path`,
`set`). `flagset` sorts tokens only when no last-wins family (`-O*`,
`-march=*`, ...) repeats; otherwise order is significant.

Severity: `critical` and `material` gate; `informational` is reported. The
shipped map is in `defaults.toml`; unlisted paths are `material`.

Exit codes: `0` valid · `1` undeclared difference · `2` indeterminate,
drift or a failed run · `3` usage · `4` within noise, or nothing measured
(only with `--require-signal`) · `130` interrupted. `1` outranks `2`.

### configurations and noise

Records whose gating fields are identical form one configuration, each
field reduced to its comparator's canonical value first, so two records that
match field by field are one configuration. For each metric, with at least
three samples per configuration:

```
gap   = (max(medians) - min(medians)) / min(medians)
noise = max over configurations of (max - min) / median
```

`gap <= noise` is *within noise*. Fewer samples: *unassessed*, never a guess.
A metric whose value is a list (a pattern that matched several lines) is
*unassessed* and says so.

## Certificate line

```
ceteris-certified v2 configs=<k> n=<n1,...,nk> vary=<a,b> waive=<f:reason;...> strict=<0|1> signal=<0|1> verdict=<ok|confounded|indeterminate|within-noise> noise=<pct|unassessed> config=<c> sha256:<h>
```

`h` is sha256 over sorted JSON of `{version, records, vary, waive, strict,
require_signal, exit_code, noise, config}` where `records` is the sorted list
of per-record digests, each the sha256 of `{fields: content_hash, metrics,
exit_code, drift}`, and `noise` is the sorted list of `(metric, assessed,
within_noise, gap, noise)` rounded to four places. `c` is the first twelve
hex digits of the sha256 of the severity and comparator maps the comparison
ran under. `ceteris verify LINE FILES...` recomputes all of it; a
`config` mismatch is reported as such rather than as a hash mismatch.
Declarations are percent-encoded (`urllib.parse.quote`), reasons with
nothing left unencoded, so any reason round-trips exactly.

Version 1 lines hashed only the gating fields and one boolean per metric;
they are refused by `verify` rather than checked.

## Compatibility

Consumers must accept unknown keys everywhere. Producers must not remove or
re-type a key without incrementing `schema_version`. A comparison across
schema versions is allowed, warns, and reports fields missing on the older
side as indeterminate. Version 2 records load unchanged; version 3 adds the
`execution.subject*` and `execution.program_scripts_sha256` fields and
narrows `execution.program_args` under a harness adapter.

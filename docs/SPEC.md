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
shipped map is in `defaults.json`; unlisted paths are `material`.

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

## Schema 4 (in progress)

Schema 3 above is the shipped format. Schema 4 is being built alongside it
under `ceteris.protocol`, and is not yet written by any command. It is
described in full in [the design](DESIGN.md) sections 5.1 to 5.7. What
exists today:

### Canonical encoding, `ceteris-json-v1`

A digest means nothing unless two implementations agree on the bytes it
covers, so the encoding is small and pinned:

- UTF-8 without a BOM. Duplicate object keys and unpaired surrogates are
  refused, not resolved.
- null, booleans, strings, arrays, objects, and integers within
  ±9007199254740991. No fractional JSON numbers: a decimal measurement is a
  string, so `0.1` survives every language's parser unchanged.
- Object keys sort by Unicode scalar value; array order is significant.
- Compact, with no trailing newline in the hashed bytes.
- `"` and `\` escaped; `\b \t \n \f \r` for those five; everything else
  below U+0020, plus U+007F and all non-ASCII, as lowercase `\uXXXX`, with
  surrogate pairs above the BMP. `/` is not escaped, and no normalization is
  applied.
- Pretty-printed input canonicalizes to the same digest. An object never
  contains its own digest.

Digests are `sha256:` followed by 64 lowercase hex characters. Byte vectors
are frozen in `tests/fixtures/protocol/encoding_vectors.json`; an
independent implementation must reproduce them exactly.

### Decimals and rationals

Canonical decimals carry no exponent, no leading plus, no unnecessary
leading zeros, no trailing fractional zeros and no negative zero. At most
128 significant digits, absolute exponent at most 308, expanded form at most
1024 characters; beyond that the value is refused as `numeric_limit_exceeded`
rather than rounded. A binary float cannot become a decimal measurement,
because the precision is already gone. Computed effects are exact rationals,
reduced, with a positive denominator.

### Typed values

Fields keep the four states. `value` carries `v` and the others must not.
`not_applicable` needs a real applicability reason, and "not implemented" is
not one. Provenance is structured as collector id, collector version, source
kind and source ref, so a wording change is not mistaken for a change in the
world.

Observations are scoped: `controller`, `subject`, `node/<id>`, `execution`,
`campaign`, or `validator/<id>`. Capability evidence records whether a
required observation was `observed`, `not_applicable`, `unavailable`,
`unsupported` or `excluded`; only the first two answer a requirement.

A metric carries case, metric id, unit, direction and domain alongside its
estimate. Units come from a registry (`s`, `ns`, `us`, `ms`, `B`, `B/s`,
`count`, `count/s`, `ratio`); time converts by exact powers of ten and
anything else is refused rather than guessed. A metric whose direction is
`none` can be displayed but cannot decide whether a change was an
improvement.

### Limits

16 MiB per file, nesting depth 64, 100,000 field entries, 10,000 metric
entries, 1,000,000 raw samples, 1,000,000 characters per string. Each is
refused with the limit named. Malformed structure produces a structured
issue with a stable code, never a traceback: `invalid_uuid`,
`malformed_exit_code`, `duplicate_metric_identity`, `invalid_scope`,
`missing_applicability_reason`, `limit_exceeded` and their kin.

## Compatibility

Consumers must accept unknown keys everywhere. Producers must not remove or
re-type a key without incrementing `schema_version`. A comparison across
schema versions is allowed, warns, and reports fields missing on the older
side as indeterminate. Version 2 records load unchanged; version 3 adds the
`execution.subject*` and `execution.program_scripts_sha256` fields and
narrows `execution.program_args` under a harness adapter.

# ceteris record format, version 2

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
| `schema_version` | int | `2` for this document |
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

### run

| key | type |
|---|---|
| `exit_code` | int |
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

Exit codes: `0` valid · `1` undeclared difference · `2` indeterminate or
drift · `3` usage · `4` within noise (only with `--require-signal`). `1`
outranks `2`.

### configurations and noise

Records whose gating fields are identical form one configuration. For each
metric, with at least three samples per configuration:

```
gap   = (max(medians) - min(medians)) / min(medians)
noise = max over configurations of (max - min) / median
```

`gap <= noise` is *within noise*. Fewer samples: *unassessed*, never a guess.

## Certificate line

```
ceteris-certified v1 configs=<k> n=<n1,...,nk> vary=<a,b> waive=<f:reason;...> strict=<0|1> verdict=<ok|confounded|indeterminate|within-noise> noise=<pct|unassessed> sha256:<h>
```

`h` is sha256 over sorted-JSON of `{records: sorted content hashes, vary,
waive, strict, exit_code, noise verdicts}`. `ceteris verify LINE FILES...`
recomputes it. Spaces inside waiver reasons are written as `_`.

## Compatibility

Consumers must accept unknown keys everywhere. Producers must not remove or
re-type a key without incrementing `schema_version`. A comparison across
schema versions is allowed and reports fields missing on the older side as
indeterminate.

# Testing evidence decisions

A large passing suite did not catch the 0.4.0 required-export failures. The
tests must check the decision boundary as well as individual parsers. A
refusal test needs a nearby valid case that passes, so rejecting everything
cannot satisfy the test.

| Contract | Regression and consistency coverage |
|---|---|
| Required exports cannot certify failed or unreadable measurements | `test_evidence_consistency.py`: failed-case permutations, ambiguous formats, invalid numeric types, malformed rows, duplicate names, mixed repetitions, valid controls, and older valid-claim records. |
| CLI exit codes express acceptance separately from integrity | `scripts/smoke_release.py`, called by `test_release_smoke.py`: fresh `run --ingest` records, `compare --certify`, `verify`, and `verify --require-pass`, including a passing control and seven refusal scenarios. |
| Decimal processing preserves the original value | `test_protocol_encoding.py` frozen vectors; `test_evidence_consistency.py` precision limits, normalization idempotence, decimal contexts with rounding traps, unit round trips, and threshold decisions beyond 28 digits. |
| Artifact identity includes link text but does not follow child links | `test_identity.py` and `test_evidence_consistency.py`: retargeting, external target changes, broken/cyclic links, creation order, relocated roots, and empty directories. |
| Node identity preserves state and placement | `test_nodes_evidence.py` and `test_evidence_consistency.py`: missing/unknown/error/absent/value fields, response failures, provenance independence, input permutations, placement swaps, typed values and multiplicity. |
| Recovery preserves its restrictions across restarts | `test_campaign.py`: repeated recovery after reloading persisted journals, committed slots, live attempts supplied as lists or iterators, and unchanged abandoned journal entries. |
| Output streaming retains extraction semantics | `test_shipment_regressions.py`: CRLF/CR normalization, bounded output and raw byte accounting. |

For a correctness fix, first demonstrate a failing counterexample, then add
the invariants it violates and valid controls. Keep fixtures explicit about
whether they came from a real harness or were reconstructed. Test the public
entrypoint when the failure depends on several components working together.

Run the full suite with `python -m pytest -q`. Hardware collector tests need
normal probe access; a sandbox denial is not evidence that the collector
works. CI runs Ubuntu and macOS on Python 3.9–3.14.

Before publishing, the release workflow builds and checks the distributions,
installs the wheel without dependencies in a fresh environment, and runs:

```sh
/path/to/fresh-env/bin/python -I scripts/smoke_release.py
```

The smoke script uses temporary working directories and isolated Python
imports. It exercises the installed package rather than importing the source
tree. The script is also included in the source distribution. Publishing
depends on this check passing; a failed gate must be fixed before release.

These checks do not validate cluster/GPU execution or the full experimental
campaign workflow. See [SUPPORT.md](SUPPORT.md) for the evidence behind each
supported path.

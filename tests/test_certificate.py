"""A certificate must fail when anything it covers changes, and it must
cover everything a reader of the records could be misled by."""

from __future__ import annotations

import json

import pytest

from ceteris import certificate
from ceteris.cli import main
from ceteris.compare import EXIT_INTEGRITY, EXIT_OK, EXIT_UNDECLARED, compare
from ceteris.config import Config
from ceteris.model import Field, State, value

from conftest import fp


def two(tmp_path, commit_b="abc"):
    a = fp("a", source__commit="abc", build__cxx_flags="-O3")
    b = fp("b", source__commit=commit_b, build__cxx_flags="-O0")
    pa, pb = tmp_path / "a.json", tmp_path / "b.json"
    pa.write_text(a.dumps()); pb.write_text(b.dumps())
    return a, b, str(pa), str(pb)


def measured(label, flags, samples, extra=None):
    """Three repeats of one configuration carrying one metric."""
    out = []
    for x in samples:
        r = fp(label, source__commit="abc", build__cxx_flags=flags)
        r.metrics = {"t": Field(State.VALUE, x)}
        if extra:
            r.metrics.update({k: Field(State.VALUE, v) for k, v in extra.items()})
        r.run = {"exit_code": 0}
        out.append(r)
    return out


def test_issue_and_verify_round_trip(tmp_path, cfg):
    a, b, pa, pb = two(tmp_path)
    line = certificate.issue(compare([a, b], vary=["build.cxx_flags"], cfg=cfg))
    assert line.startswith("ceteris-certified v2 configs=2 n=1,1 vary=build.cxx_flags")
    assert "verdict=ok" in line
    assert certificate.verify(line, compare([a, b], vary=["build.cxx_flags"], cfg=cfg)).integrity_verified


def test_an_edited_record_fails_verification(tmp_path, cfg):
    a, b, pa, pb = two(tmp_path)
    line = certificate.issue(compare([a, b], vary=["build.cxx_flags"], cfg=cfg))
    b.fields["source.commit"] = value("tampered")
    result = certificate.verify(line, compare([a, b], vary=["build.cxx_flags"], cfg=cfg))
    assert not result.integrity_verified and "mismatch" in result.message


def test_an_edited_measurement_fails_verification(cfg):
    """The v1 hash covered a verdict per metric and nothing else about the
    measurements, so numbers could be nudged as long as the verdict held."""
    runs = measured("a", "-O3", [1.0, 1.01, 1.02]) + measured("b", "-O0", [2.0, 2.01, 2.02])
    line = certificate.issue(compare(runs, vary=["build.cxx_flags"], cfg=cfg))
    runs[0].metrics["t"] = Field(State.VALUE, 1.005)   # verdict still "signal"
    report = compare(runs, vary=["build.cxx_flags"], cfg=cfg)
    assert [v.within_noise for v in report.noise] == [False]
    assert not certificate.verify(line, report).integrity_verified


def test_an_edited_informational_field_fails_verification(cfg):
    runs = measured("a", "-O3", [1.0, 1.01, 1.02]) + measured("b", "-O0", [2.0, 2.01, 2.02])
    for r in runs:
        r.fields["source.branch"] = value("main")
    line = certificate.issue(compare(runs, vary=["build.cxx_flags"], cfg=cfg))
    runs[3].fields["source.branch"] = value("other")
    assert not certificate.verify(line, compare(runs, vary=["build.cxx_flags"], cfg=cfg)).integrity_verified


def test_the_hash_does_not_depend_on_file_order(cfg):
    """Configurations carrying different metric sets used to serialise the
    noise verdicts in discovery order, so the same files named in another
    order produced another hash."""
    a = measured("a", "-O3", [1.0, 1.01, 1.02], extra={"a_only": 5.0})
    b = measured("b", "-O0", [2.0, 2.01, 2.02], extra={"b_only": 7.0})
    line = certificate.issue(compare(a + b, vary=["build.cxx_flags"], cfg=cfg))
    assert certificate.verify(line, compare(b + a, vary=["build.cxx_flags"], cfg=cfg)).integrity_verified


def test_the_line_carries_its_own_declarations(tmp_path, cfg):
    a, b, _, _ = two(tmp_path)
    report = compare([a, b], vary=["build.cxx_flags"], waive={"source.commit": "known good"}, cfg=cfg)
    parsed = certificate.parse(certificate.issue(report))
    assert parsed.vary == ["build.cxx_flags"]
    assert parsed.waive == {"source.commit": "known good"}


@pytest.mark.parametrize("reason", [
    "different node_draw",          # underscores were spaces on the way back
    "same partition; other rack",   # the item separator
    "see ticket HPC-12: approved",  # the key separator
    "100% fine",
])
def test_waiver_reasons_round_trip_exactly(tmp_path, cfg, reason):
    a, b, _, _ = two(tmp_path)
    report = compare([a, b], vary=["build.cxx_flags"], waive={"source.commit": reason}, cfg=cfg)
    line = certificate.issue(report)
    assert certificate.parse(line).waive == {"source.commit": reason}
    assert certificate.verify(line, compare([a, b], vary=["build.cxx_flags"], waive={"source.commit": reason}, cfg=cfg)).integrity_verified


def test_a_within_noise_certificate_verifies(cfg):
    """--require-signal changes the exit code, which is in the hash. The
    flag is carried in the line so a verifier can reproduce the verdict."""
    runs = measured("a", "-O3", [1.0, 1.5, 1.02]) + measured("b", "-O0", [1.05, 1.0, 1.1])
    report = compare(runs, vary=["build.cxx_flags"], cfg=cfg, require_signal=True)
    line = certificate.issue(report)
    assert "verdict=within-noise" in line and "signal=1" in line
    parsed = certificate.parse(line)
    again = compare(runs, vary=["build.cxx_flags"], cfg=cfg, require_signal=parsed.require_signal)
    assert certificate.verify(line, again).integrity_verified


def test_a_different_severity_map_is_named_not_a_bare_mismatch(tmp_path, cfg):
    a, b, _, _ = two(tmp_path)
    line = certificate.issue(compare([a, b], vary=["build.cxx_flags"], cfg=cfg))
    other = Config.load()
    other.severity["source.commit"] = "informational"
    result = certificate.verify(line, compare([a, b], vary=["build.cxx_flags"], cfg=other))
    assert not result.integrity_verified and "configuration mismatch" in result.message


def test_a_confounded_comparison_certifies_as_confounded(tmp_path, cfg):
    a, b, _, _ = two(tmp_path, commit_b="zzz")
    assert "verdict=confounded" in certificate.issue(compare([a, b], vary=["build.cxx_flags"], cfg=cfg))


def test_cli_verify(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _, _, pa, pb = two(tmp_path)
    main(["compare", pa, pb, "--vary", "build.cxx_flags", "--certify"])
    line = [l for l in capsys.readouterr().out.splitlines() if l.startswith("ceteris-certified")][0]
    assert main(["verify", line, pa, pb]) == EXIT_OK
    json.dump({"fields": {"source.commit": {"s": "value", "v": "nope"}}, "meta": {"label": "b"}}, open(pb, "w"))
    assert main(["verify", line, pa, pb]) == EXIT_UNDECLARED


def test_cli_verify_carries_require_signal(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runs = measured("a", "-O3", [1.0, 1.5, 1.02]) + measured("b", "-O0", [1.05, 1.0, 1.1])
    paths = []
    for i, r in enumerate(runs):
        p = tmp_path / f"r{i}.json"; p.write_text(r.dumps()); paths.append(str(p))
    assert main(["compare", *paths, "--vary", "build.cxx_flags", "--require-signal", "--certify"]) == 4
    line = [l for l in capsys.readouterr().out.splitlines() if l.startswith("ceteris-certified")][0]
    assert main(["verify", line, *paths]) == EXIT_OK


def test_version_one_is_refused_with_a_reason():
    old = ("ceteris-certified v1 configs=2 n=3,3 vary=x waive= strict=0 verdict=ok noise=4% "
           "sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="version 1"):
        certificate.parse(old)


def test_garbage_is_rejected():
    with pytest.raises(ValueError):
        certificate.parse("definitely not a certificate")


# --- F01: the displayed claims are part of the certificate --------------------


def _confounded(cfg):
    """A genuine certificate for a comparison that did not pass."""
    a = fp("a", source__commit="abc", build__cxx_flags="-O3")
    b = fp("b", source__commit="zzz", build__cxx_flags="-O0")
    report = compare([a, b], vary=["build.cxx_flags"], cfg=cfg)
    assert report.exit_code != 0
    return certificate.issue(report), [a, b]


@pytest.mark.parametrize("edit, why", [
    (("verdict=confounded", "verdict=ok"), "a failed comparison relabelled as passing"),
    (("configs=2", "configs=9"), "an inflated configuration count"),
    (("n=1,1", "n=7,7"), "an inflated sample count"),
])
def test_editing_a_displayed_field_fails_verification(cfg, edit, why):
    """The whole point of the line is that a reader can trust what it says.
    Version 2 bound the records and left the sentence unbound: changing
    `verdict=confounded` to `verdict=ok` still printed `verified: ok`."""
    line, runs = _confounded(cfg)
    old, new = edit
    assert old in line, line
    tampered = line.replace(old, new)
    result = certificate.verify(tampered, compare(runs, vary=["build.cxx_flags"], cfg=cfg))
    assert not result.integrity_verified, why
    assert "altered" in result.message


def test_an_unknown_verdict_word_is_refused(cfg):
    line, _ = _confounded(cfg)
    with pytest.raises(ValueError, match="not one of"):
        certificate.parse(line.replace("verdict=confounded", "verdict=splendid"))


def test_a_genuine_failure_verifies_its_integrity_and_says_it_failed(cfg):
    line, runs = _confounded(cfg)
    result = certificate.verify(line, compare(runs, vary=["build.cxx_flags"], cfg=cfg))
    assert result.integrity_verified
    assert not result.comparison_passed
    assert result.verdict == "confounded"
    assert "verified: confounded" == result.message


def test_naming_the_files_in_another_order_still_verifies(cfg):
    """`n` is a multiset: the hash sorts the records, so it never bound the
    order configurations were discovered in."""
    a = measured("a", "-O3", [1.0, 1.01, 1.02])
    b = measured("b", "-O0", [2.0, 2.01])
    line = certificate.issue(compare(a + b, vary=["build.cxx_flags"], cfg=cfg))
    assert certificate.verify(line, compare(b + a, vary=["build.cxx_flags"], cfg=cfg)).integrity_verified


def test_cli_require_pass_separates_genuine_from_passing(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    a = fp("a", source__commit="abc", build__cxx_flags="-O3")
    b = fp("b", source__commit="zzz", build__cxx_flags="-O0")
    pa, pb = tmp_path / "a.json", tmp_path / "b.json"
    pa.write_text(a.dumps()); pb.write_text(b.dumps())
    main(["compare", str(pa), str(pb), "--vary", "build.cxx_flags", "--certify"])
    line = [l for l in capsys.readouterr().out.splitlines() if l.startswith("ceteris-certified")][0]

    # Honest certificate for a failed comparison: integrity is fine on its own.
    assert main(["verify", line, str(pa), str(pb)]) == EXIT_OK
    assert "verified: confounded" in capsys.readouterr().out
    # Asking whether it passed is a different question.
    assert main(["verify", "--require-pass", line, str(pa), str(pb)]) == EXIT_UNDECLARED
    assert "did not pass" in capsys.readouterr().out
    # A tampered line is an integrity failure, which is its own exit code.
    assert main(["verify", "--require-pass", line.replace("verdict=confounded", "verdict=ok"),
                 str(pa), str(pb)]) == EXIT_INTEGRITY

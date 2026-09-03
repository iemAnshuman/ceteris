"""A certificate must fail when anything it covers changes, and it must
cover everything a reader of the records could be misled by."""

from __future__ import annotations

import json

import pytest

from ceteris import certificate
from ceteris.cli import main
from ceteris.compare import EXIT_OK, EXIT_UNDECLARED, compare
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
    assert certificate.verify(line, compare([a, b], vary=["build.cxx_flags"], cfg=cfg))[0]


def test_an_edited_record_fails_verification(tmp_path, cfg):
    a, b, pa, pb = two(tmp_path)
    line = certificate.issue(compare([a, b], vary=["build.cxx_flags"], cfg=cfg))
    b.fields["source.commit"] = value("tampered")
    ok, why = certificate.verify(line, compare([a, b], vary=["build.cxx_flags"], cfg=cfg))
    assert not ok and "mismatch" in why


def test_an_edited_measurement_fails_verification(cfg):
    """The v1 hash covered a verdict per metric and nothing else about the
    measurements, so numbers could be nudged as long as the verdict held."""
    runs = measured("a", "-O3", [1.0, 1.01, 1.02]) + measured("b", "-O0", [2.0, 2.01, 2.02])
    line = certificate.issue(compare(runs, vary=["build.cxx_flags"], cfg=cfg))
    runs[0].metrics["t"] = Field(State.VALUE, 1.005)   # verdict still "signal"
    report = compare(runs, vary=["build.cxx_flags"], cfg=cfg)
    assert [v.within_noise for v in report.noise] == [False]
    ok, _ = certificate.verify(line, report)
    assert not ok


def test_an_edited_informational_field_fails_verification(cfg):
    runs = measured("a", "-O3", [1.0, 1.01, 1.02]) + measured("b", "-O0", [2.0, 2.01, 2.02])
    for r in runs:
        r.fields["source.branch"] = value("main")
    line = certificate.issue(compare(runs, vary=["build.cxx_flags"], cfg=cfg))
    runs[3].fields["source.branch"] = value("other")
    assert not certificate.verify(line, compare(runs, vary=["build.cxx_flags"], cfg=cfg))[0]


def test_the_hash_does_not_depend_on_file_order(cfg):
    """Configurations carrying different metric sets used to serialise the
    noise verdicts in discovery order, so the same files named in another
    order produced another hash."""
    a = measured("a", "-O3", [1.0, 1.01, 1.02], extra={"a_only": 5.0})
    b = measured("b", "-O0", [2.0, 2.01, 2.02], extra={"b_only": 7.0})
    line = certificate.issue(compare(a + b, vary=["build.cxx_flags"], cfg=cfg))
    assert certificate.verify(line, compare(b + a, vary=["build.cxx_flags"], cfg=cfg))[0]


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
    assert certificate.verify(line, compare([a, b], vary=["build.cxx_flags"], waive={"source.commit": reason}, cfg=cfg))[0]


def test_a_within_noise_certificate_verifies(cfg):
    """--require-signal changes the exit code, which is in the hash. The
    flag is carried in the line so a verifier can reproduce the verdict."""
    runs = measured("a", "-O3", [1.0, 1.5, 1.02]) + measured("b", "-O0", [1.05, 1.0, 1.1])
    report = compare(runs, vary=["build.cxx_flags"], cfg=cfg, require_signal=True)
    line = certificate.issue(report)
    assert "verdict=within-noise" in line and "signal=1" in line
    parsed = certificate.parse(line)
    again = compare(runs, vary=["build.cxx_flags"], cfg=cfg, require_signal=parsed.require_signal)
    assert certificate.verify(line, again)[0]


def test_a_different_severity_map_is_named_not_a_bare_mismatch(tmp_path, cfg):
    a, b, _, _ = two(tmp_path)
    line = certificate.issue(compare([a, b], vary=["build.cxx_flags"], cfg=cfg))
    other = Config.load()
    other.severity["source.commit"] = "informational"
    ok, why = certificate.verify(line, compare([a, b], vary=["build.cxx_flags"], cfg=other))
    assert not ok and "configuration mismatch" in why


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

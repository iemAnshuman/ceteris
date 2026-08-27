"""A certificate must fail when anything it covers changes."""

from __future__ import annotations

import json

import pytest

from ceteris import certificate
from ceteris.cli import main
from ceteris.compare import EXIT_OK, EXIT_UNDECLARED, compare
from ceteris.model import Fingerprint, value

from conftest import fp


def two(tmp_path, commit_b="abc"):
    a = fp("a", source__commit="abc", build__cxx_flags="-O3")
    b = fp("b", source__commit=commit_b, build__cxx_flags="-O0")
    pa, pb = tmp_path / "a.json", tmp_path / "b.json"
    pa.write_text(a.dumps()); pb.write_text(b.dumps())
    return a, b, str(pa), str(pb)


def test_issue_and_verify_round_trip(tmp_path, cfg):
    a, b, pa, pb = two(tmp_path)
    line = certificate.issue(compare([a, b], vary=["build.cxx_flags"], cfg=cfg))
    assert line.startswith("ceteris-certified v1 configs=2 n=1,1 vary=build.cxx_flags")
    assert "verdict=ok" in line
    assert certificate.verify(line, compare([a, b], vary=["build.cxx_flags"], cfg=cfg))[0]


def test_an_edited_record_fails_verification(tmp_path, cfg):
    a, b, pa, pb = two(tmp_path)
    line = certificate.issue(compare([a, b], vary=["build.cxx_flags"], cfg=cfg))
    b.fields["source.commit"] = value("tampered")
    ok, why = certificate.verify(line, compare([a, b], vary=["build.cxx_flags"], cfg=cfg))
    assert not ok and "mismatch" in why


def test_the_line_carries_its_own_declarations(tmp_path, cfg):
    a, b, _, _ = two(tmp_path)
    report = compare([a, b], vary=["build.cxx_flags"], waive={"source.commit": "known good"}, cfg=cfg)
    parsed = certificate.parse(certificate.issue(report))
    assert parsed.vary == ["build.cxx_flags"]
    assert parsed.waive == {"source.commit": "known good"}


def test_a_confounded_comparison_certifies_as_confounded(tmp_path, cfg):
    a, b, _, _ = two(tmp_path, commit_b="zzz")
    assert "verdict=confounded" in certificate.issue(compare([a, b], vary=["build.cxx_flags"], cfg=cfg))


def test_cli_verify(tmp_path, capsys):
    _, _, pa, pb = two(tmp_path)
    main(["compare", pa, pb, "--vary", "build.cxx_flags", "--certify"])
    line = [l for l in capsys.readouterr().out.splitlines() if l.startswith("ceteris-certified")][0]
    assert main(["verify", line, pa, pb]) == EXIT_OK
    json.dump({"fields": {"source.commit": {"s": "value", "v": "nope"}}, "meta": {"label": "b"}}, open(pb, "w"))
    assert main(["verify", line, pa, pb]) == EXIT_UNDECLARED


def test_garbage_is_rejected():
    with pytest.raises(ValueError):
        certificate.parse("definitely not a certificate")

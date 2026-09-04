"""CLI surface and exit codes -- the exit code is the whole CI integration."""

from __future__ import annotations

import json
import sys

import pytest

from ceteris.cli import main
from ceteris.compare import EXIT_INDETERMINATE, EXIT_OK, EXIT_UNDECLARED, EXIT_USAGE

from conftest import fp, unk


def write(tmp_path, name, fingerprint):
    path = tmp_path / f"{name}.json"
    path.write_text(fingerprint.dumps())
    return str(path)


def test_capture_writes_valid_json_to_a_file(tmp_path, capsys):
    out = tmp_path / "run.json"
    assert main(["capture", "--repo", ".", "-o", str(out)]) == EXIT_OK
    body = json.loads(out.read_text())
    assert body["meta"]["tool"] == "ceteris"
    assert body["fields"]


def test_capture_writes_to_stdout_by_default(capsys):
    assert main(["capture", "--repo", "."]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["fields"]


def test_compare_exits_zero_when_only_declared_fields_differ(tmp_path, capsys):
    a = write(tmp_path, "a", fp("run-a", runtime__transport_configured="lci"))
    b = write(tmp_path, "b", fp("run-b", runtime__transport_configured="mpi"))
    code = main(["compare", a, b, "--vary", "runtime.transport_configured"])
    assert code == EXIT_OK
    assert "Comparison is valid" in capsys.readouterr().out


def test_compare_exits_nonzero_on_an_undeclared_difference(tmp_path, capsys):
    a = write(tmp_path, "a", fp("run-a", source__commit="a1b2c3d"))
    b = write(tmp_path, "b", fp("run-b", source__commit="9f8e7d6"))
    assert main(["compare", a, b]) == EXIT_UNDECLARED
    assert "UNDECLARED DIFFERENCES" in capsys.readouterr().out


def test_compare_reports_unknown_separately_from_differing(tmp_path, capsys):
    a = write(tmp_path, "a", fp("run-a", hardware__gpu_driver="550.54.15"))
    b = write(tmp_path, "b", fp("run-b", hardware__gpu_driver=unk("nvidia-smi timed out")))
    assert main(["compare", a, b]) == EXIT_INDETERMINATE
    out = capsys.readouterr().out
    assert "UNKNOWN" in out and "nvidia-smi timed out" in out
    assert "UNDECLARED DIFFERENCES" not in out


def test_label_falls_back_to_the_filename(tmp_path, capsys):
    from ceteris.model import Fingerprint, value

    for name, commit in (("alpha", "a1b2c3d"), ("beta", "9f8e7d6")):
        (tmp_path / f"{name}.json").write_text(
            Fingerprint({"source.commit": value(commit)}, {}).dumps()
        )
    main(["compare", str(tmp_path / "alpha.json"), str(tmp_path / "beta.json")])
    out = capsys.readouterr().out
    assert "alpha" in out and "beta" in out


def test_waiver_without_a_reason_is_refused(tmp_path, capsys):
    a = write(tmp_path, "a", fp("run-a", hardware__cpu_model="M4"))
    b = write(tmp_path, "b", fp("run-b", hardware__cpu_model="M3"))
    with pytest.raises(SystemExit) as exc:
        main(["compare", a, b, "--waive", "hardware.cpu_model"])
    assert exc.value.code == EXIT_USAGE
    assert "needs a reason" in capsys.readouterr().err


def test_waiver_with_a_reason_is_accepted_and_printed(tmp_path, capsys):
    a = write(tmp_path, "a", fp("run-a", hardware__cpu_model="M4"))
    b = write(tmp_path, "b", fp("run-b", hardware__cpu_model="M3"))
    code = main(["compare", a, b, "--waive", "hardware.cpu_model:same partition"])
    assert code == EXIT_OK
    assert "reason: same partition" in capsys.readouterr().out


def test_json_report_is_machine_readable(tmp_path, capsys):
    a = write(tmp_path, "a", fp("run-a", source__commit="a1b2c3d"))
    b = write(tmp_path, "b", fp("run-b", source__commit="9f8e7d6"))
    code = main(["compare", a, b, "--json"])
    body = json.loads(capsys.readouterr().out)
    assert code == EXIT_UNDECLARED
    assert body["exit_code"] == EXIT_UNDECLARED
    assert body["fields"][0]["path"] == "source.commit"


def test_unreadable_input_is_a_usage_error(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    good = write(tmp_path, "a", fp("run-a", source__commit="a1b2c3d"))
    with pytest.raises(SystemExit) as exc:
        main(["compare", good, str(bad)])
    assert exc.value.code == EXIT_USAGE


def test_compare_needs_two_files(tmp_path):
    a = write(tmp_path, "a", fp("run-a", source__commit="a1b2c3d"))
    with pytest.raises(SystemExit) as exc:
        main(["compare", a])
    assert exc.value.code == EXIT_USAGE


# --- run / list / store selection -------------------------------------------


@pytest.fixture
def store(monkeypatch, tmp_path):
    path = tmp_path / "runs"
    monkeypatch.setenv("CETERIS_STORE", str(path))
    return path


def test_run_records_to_the_store_and_passes_the_exit_code_through(store, capsys):
    import sys as _sys

    code = main(
        ["run", "--label", "a", "-q", "--", _sys.executable, "-c", "raise SystemExit(4)"]
    )
    assert code == 4
    assert len(list(store.glob("*.json"))) == 1


def test_run_extracts_a_metric_and_list_shows_it(store, capsys):
    import sys as _sys

    main(
        [
            "run", "--label", "bench", "-q",
            "--metric", "bw=bandwidth ([0-9.]+) GB/s",
            "--", _sys.executable, "-c", "print('bandwidth 57.44 GB/s')",
        ]
    )
    capsys.readouterr()
    assert main(["list"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "bench" in out and "57.44" in out


def test_a_dash_valued_option_does_not_confuse_the_parser(store, capsys):
    """`--cxx-flags -O3` must work; argparse alone reads -O3 as an option."""
    import sys as _sys

    code = main(
        ["run", "--label", "o3", "-q", "--cxx-flags", "-O3",
         "--", _sys.executable, "-c", "pass"]
    )
    assert code == 0
    body = json.loads(next(store.glob("*.json")).read_text())
    assert body["fields"]["build.cxx_flags"]["v"] == "-O3"


def test_compare_selects_from_the_store(store, capsys):
    import sys as _sys

    for label, flags in (("o3", "-O3"), ("o0", "-O0")):
        main(["run", "--label", label, "-q", "--cxx-flags", flags,
              "--", _sys.executable, "-c", "pass"])
    capsys.readouterr()
    code = main(["compare", "--last", "2"])
    out = capsys.readouterr().out
    assert code == EXIT_UNDECLARED
    assert "build.cxx_flags" in out


def test_compare_selects_by_label_glob(store, capsys):
    import sys as _sys

    for label in ("lci-8192", "lci-73728", "mpi-only"):
        main(["run", "--label", label, "-q", "--", _sys.executable, "-c", "pass"])
    capsys.readouterr()
    main(["compare", "--label", "lci-*"])
    out = capsys.readouterr().out
    assert "2 runs compared" in out


def test_run_without_a_command_explains_itself(store, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["run", "--label", "a"])
    assert exc.value.code == EXIT_USAGE
    assert "after --" in capsys.readouterr().err


def test_compare_with_an_empty_store_says_so(store, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["compare"])
    assert exc.value.code == EXIT_USAGE
    assert "no runs selected" in capsys.readouterr().err


def test_output_with_repeats_writes_one_readable_record_per_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "rec.json"
    main(["run", "--no-store", "-q", "-o", str(out), "--repeats", "3", "--", sys.executable, "-c", "pass"])
    from ceteris.model import Fingerprint

    written = sorted(p.name for p in tmp_path.glob("rec*.json"))
    assert written == ["rec-2.json", "rec-3.json", "rec.json"]
    for p in tmp_path.glob("rec*.json"):
        assert Fingerprint.from_json(json.loads(p.read_text())).meta["kind"] == "run"


def test_a_run_without_any_metric_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    main(["run", "--no-store", "-q", "--", sys.executable, "-c", "print('throughput 12.5 MB/s')"])
    assert "no metric was extracted" in capsys.readouterr().err
    main(["run", "--no-store", "-q", "--metric", "tp=throughput ([0-9.]+)", "--",
          sys.executable, "-c", "print('throughput 12.5 MB/s')"])
    assert "no metric was extracted" not in capsys.readouterr().err

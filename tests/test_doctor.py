"""`ceteris doctor`: does the capture know what it failed to see?"""

from __future__ import annotations

import json
from pathlib import Path

from ceteris import doctor
from ceteris.cli import main
from ceteris.model import Fingerprint, not_applicable, unknown, value

from conftest import fp

ROSTAM = Path(__file__).parent.parent / "examples" / "rostam"


def levels(findings):
    return {(f.level, f.field) for f in findings}


def test_unknown_and_error_fields_are_reported_as_blind():
    record = Fingerprint(
        {"hardware.gpu_driver": unknown("nvidia-smi timed out"),
         "source.commit": value("abc")},
        {"label": "x"},
    )
    findings = doctor.diagnose(record, local=False)
    assert (doctor.BLIND, "hardware.gpu_driver") in levels(findings)
    assert doctor.exit_code(findings) == 2


def test_a_gpu_claimed_absent_while_a_driver_is_loaded_is_suspect(monkeypatch):
    """The check that would have caught the AMD bug before a cluster did."""
    record = Fingerprint({"hardware.gpu_models": not_applicable("no query tool")}, {"label": "x"})
    monkeypatch.setattr(doctor.os.path, "exists", lambda p: p == "/dev/kfd")
    findings = doctor.diagnose(record, local=True)
    assert (doctor.SUSPECT, "hardware.gpu_models") in levels(findings)
    assert doctor.exit_code(findings) == 1
    # The same record inspected from another machine must not be judged by
    # this machine's filesystem.
    assert not [f for f in doctor.diagnose(record, local=False) if f.level == doctor.SUSPECT]


def test_a_scheduler_claimed_absent_while_a_job_variable_is_set_is_suspect(monkeypatch):
    record = Fingerprint({"scheduler.system": not_applicable("no batch scheduler")}, {"label": "x"})
    monkeypatch.setenv("COBALT_JOBID", "77")
    monkeypatch.setattr(doctor.os.path, "exists", lambda p: False)
    assert (doctor.SUSPECT, "scheduler.system") in levels(doctor.diagnose(record, local=True))


def test_a_container_claimed_absent_inside_one_is_suspect(monkeypatch):
    record = Fingerprint({"deps.container_runtime": not_applicable("not in a container")}, {"label": "x"})
    monkeypatch.setattr(doctor.os.path, "exists", lambda p: p == "/.singularity.d")
    assert (doctor.SUSPECT, "deps.container_runtime") in levels(doctor.diagnose(record, local=True))


def test_noise_widening_settings_are_notes_not_failures():
    record = fp("x", system__cpu_governor="powersave", system__turbo="on",
                system__power_source="battery", source__dirty=True)
    findings = doctor.diagnose(record, local=False)
    fields = {f.field for f in findings if f.level == doctor.NOTE}
    assert {"system.cpu_governor", "system.turbo", "system.power_source", "source.dirty"} <= fields
    assert doctor.exit_code(findings) == 0  # notes never fail


def test_a_busy_machine_is_noted():
    record = fp("x", system__load_1m=40.0, hardware__cpu_cores_logical=24)
    assert (doctor.NOTE, "system.load_1m") in levels(doctor.diagnose(record, local=False))


def test_a_clean_record_reports_nothing():
    record = fp("x", source__commit="abc", system__turbo="off")
    findings = doctor.diagnose(record, local=False)
    assert findings == []
    assert "Nothing to report" in doctor.render(record, findings)


# apptainer.json is captured inside a container whose image does not ship
# nvidia-smi, on a host whose NVIDIA driver is visible through /proc and
# /sys. Its GPU fields are legitimately unknown, and doctor must say so.
_EXPECTED_BLIND = {"apptainer.json": {
    "hardware.gpu_count", "hardware.gpu_driver", "hardware.gpu_models", "hardware.gpu_vendor",
}}


def test_real_cluster_records_report_exactly_what_they_could_not_see():
    """Every record captured on Rostam. Nothing is suspect anywhere, and the
    only unknowns are the ones a container without nvidia-smi must have."""
    seen = 0
    for path in sorted(ROSTAM.glob("*.json")):
        record = Fingerprint.from_json(json.loads(path.read_text()))
        findings = doctor.diagnose(record, local=False)
        assert not [f for f in findings if f.level == doctor.SUSPECT], (path.name, findings)
        blind = {f.field for f in findings if f.level == doctor.BLIND}
        assert blind == _EXPECTED_BLIND.get(path.name, set()), (path.name, blind)
        seen += 1
    assert seen >= 10, f"expected the full set of cluster records, found {seen}"


def test_the_container_record_explains_its_unknowns():
    """The rule was written for AMD machines and is what keeps this honest:
    a driver is loaded, no query tool can be found, so the GPU is unknown
    rather than absent."""
    record = Fingerprint.from_json(json.loads((ROSTAM / "apptainer.json").read_text()))
    findings = doctor.diagnose(record, local=False)
    assert doctor.exit_code(findings) == 2
    assert all("driver is loaded" in f.message
               for f in findings if f.level == doctor.BLIND)


def test_cli_doctor_on_a_file_and_on_this_machine(capsys):
    code = main(["doctor", str(ROSTAM / "gpu1.json")])
    out = capsys.readouterr().out
    assert code == 0 and "fields" in out and "diablo" in out
    assert main(["doctor"]) in (0, 1, 2)

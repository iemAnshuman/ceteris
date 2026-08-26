"""A campaign is forty runs, not two."""

from __future__ import annotations

from pathlib import Path

from ceteris import store as store_mod
from ceteris.model import Fingerprint, value


def make(label: str, when: str) -> Fingerprint:
    return Fingerprint(
        {"source.commit": value("abc")},
        {"label": label, "captured_at": when},
    )


def test_save_and_load_round_trip(tmp_path: Path):
    path = store_mod.save(make("lci-73728", "2026-08-26T10:00:00+00:00"), tmp_path)
    assert path.exists()
    assert store_mod.load(path).label == "lci-73728"


def test_labels_are_slugged_into_filenames(tmp_path: Path):
    path = store_mod.save(make("lci/73728 tuned", "2026-08-26T10:00:00+00:00"), tmp_path)
    assert "/" not in path.name and " " not in path.name


def test_same_label_and_time_does_not_overwrite(tmp_path: Path):
    a = store_mod.save(make("x", "2026-08-26T10:00:00+00:00"), tmp_path)
    b = store_mod.save(make("x", "2026-08-26T10:00:00+00:00"), tmp_path)
    assert a != b
    assert len(store_mod.all_runs(tmp_path)) == 2


def test_select_last_n(tmp_path: Path):
    for i in range(5):
        store_mod.save(make(f"r{i}", f"2026-08-26T10:0{i}:00+00:00"), tmp_path)
    picked = [store_mod.load(p).label for p in store_mod.select(tmp_path, last=2)]
    assert picked == ["r3", "r4"]


def test_select_by_label_glob(tmp_path: Path):
    for label in ("lci-8192", "lci-73728", "mpi-default"):
        store_mod.save(make(label, "2026-08-26T10:00:00+00:00"), tmp_path)
    picked = sorted(
        store_mod.load(p).label for p in store_mod.select(tmp_path, labels=["lci-*"])
    )
    assert picked == ["lci-73728", "lci-8192"]


def test_missing_store_is_empty_not_an_error(tmp_path: Path):
    assert store_mod.all_runs(tmp_path / "nope") == []


def test_env_var_sets_the_default_store(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CETERIS_STORE", str(tmp_path / "elsewhere"))
    assert store_mod.store_path() == tmp_path / "elsewhere"
    monkeypatch.delenv("CETERIS_STORE")
    assert store_mod.store_path() == Path(store_mod.DEFAULT_STORE)

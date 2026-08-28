"""Multi-node merge. The fan-out itself needs Slurm; the merge is where the
correctness lives, and it is driven from hand-built per-node fingerprints."""

from __future__ import annotations

from ceteris import nodes
from ceteris.compare import EXIT_INDETERMINATE, EXIT_OK, EXIT_UNDECLARED, compare
from ceteris.model import Fingerprint, State, unknown, value

from conftest import fp


def node(host, driver="550.54.15", cpu="Xeon 6148"):
    return Fingerprint(
        {
            "hardware.hostname": value(host),
            "hardware.gpu_driver": value(driver),
            "hardware.cpu_model": value(cpu),
            "parallelism.capture_process_affinity": value("0-39"),
            "source.commit": value("head-node-only"),
        },
        {"label": host},
    )


HEAD = node("n01")


def test_homogeneous_nodes_collapse_to_one_value():
    merged = nodes.merge(HEAD, [(f"n{i:02d}", node(f"n{i:02d}")) for i in range(1, 5)], 4)
    f = merged.fields["hardware.gpu_driver"]
    assert f.state is State.VALUE and f.value == "550.54.15"
    assert "identical on 4 nodes" in f.provenance
    assert merged.fields["hardware.node_count"].value == 4
    assert merged.fields["hardware.hostnames"].value == ["n01", "n02", "n03", "n04"]
    assert "hardware.hostname" not in merged.fields


def test_one_odd_node_makes_the_field_heterogeneous():
    """The silent-false-certification case: node 3 has a different driver."""
    per = [(f"n{i}", node(f"n{i}")) for i in (1, 2, 4)] + [("n3", node("n3", driver="535.104.05"))]
    merged = nodes.merge(HEAD, per, 4)
    f = merged.fields["hardware.gpu_driver"]
    assert f.value == [["550.54.15", 3], ["535.104.05", 1]]
    assert "heterogeneous" in f.detail


def test_heterogeneous_allocation_differs_from_a_clean_one(cfg):
    clean = nodes.merge(HEAD, [(f"n{i}", node(f"n{i}")) for i in range(1, 5)], 4)
    mixed = nodes.merge(
        HEAD, [(f"n{i}", node(f"n{i}")) for i in range(1, 4)] + [("n4", node("n4", driver="535.104.05"))], 4
    )
    clean.meta["label"], mixed.meta["label"] = "clean", "mixed"
    report = compare([clean, mixed], cfg=cfg)
    assert report.exit_code == EXIT_UNDECLARED
    assert any(r.path == "hardware.gpu_driver" for r in report.violations)


def test_same_hardware_mix_on_different_hosts_compares_equal(cfg):
    """Two allocations, same mix of nodes, different host names: comparable."""
    a = nodes.merge(HEAD, [("n1", node("n1")), ("n2", node("n2", driver="535"))], 2)
    b = nodes.merge(HEAD, [("n7", node("n7", driver="535")), ("n9", node("n9"))], 2)
    a.meta["label"], b.meta["label"] = "a", "b"
    assert compare([a, b], cfg=cfg).exit_code == EXIT_OK


def test_a_missing_node_fails_closed():
    """Fifteen of sixteen nodes reporting is not a fingerprint of the allocation."""
    per = [(f"n{i}", node(f"n{i}")) for i in range(1, 4)] + [("n4", None)]
    merged = nodes.merge(HEAD, per, 4)
    for path in ("hardware.gpu_driver", "hardware.cpu_model", "parallelism.capture_process_affinity"):
        assert merged.fields[path].state is State.UNKNOWN
        assert "3 of 4" in merged.fields[path].detail
    assert merged.fields["source.commit"].state is State.VALUE  # not node-local


def test_an_unknown_on_one_node_is_unknown_overall():
    odd = node("n2"); odd.fields["hardware.gpu_driver"] = unknown("nvidia-smi hung")
    merged = nodes.merge(HEAD, [("n1", node("n1")), ("n2", odd)], 2)
    assert merged.fields["hardware.gpu_driver"].state is State.UNKNOWN
    assert "n2" in merged.fields["hardware.gpu_driver"].detail


def test_fanout_is_not_triggered_off_slurm_or_inside_a_node_task(monkeypatch):
    monkeypatch.delenv("SLURM_JOB_NUM_NODES", raising=False)
    assert nodes.wanted() is None
    monkeypatch.setenv("SLURM_JOB_NUM_NODES", "16")
    monkeypatch.setenv(nodes.NODE_MODE_ENV, "1")
    assert nodes.wanted() is None


def test_apply_pads_unreported_nodes_and_fails_closed(monkeypatch):
    monkeypatch.setenv("SLURM_JOB_NUM_NODES", "3")
    monkeypatch.delenv(nodes.NODE_MODE_ENV, raising=False)
    monkeypatch.setattr(nodes.shutil, "which", lambda name: "/usr/bin/srun")
    calls = []

    def fake_fanout(n, args):
        calls.append((n, args))
        return [("n1", node("n1")), ("n2", node("n2"))]  # only two of three came back

    merged = nodes.apply(HEAD, ["--repo=."], fanout=fake_fanout)
    assert calls == [(3, ["--repo=."])]
    assert merged.fields["hardware.gpu_driver"].state is State.UNKNOWN
    assert merged.fields["hardware.node_count"].value == 3


def test_single_host_capture_uses_the_same_schema():
    single = nodes.apply(node("laptop"), [])
    assert single.fields["hardware.hostnames"].value == ["laptop"]
    assert single.fields["hardware.node_count"].value == 1
    assert "hardware.hostname" not in single.fields


def test_system_state_is_merged_per_node():
    """Found on Rostam: governor, turbo, SMT and hugepages were taken from the
    head node alone, so a node left in powersave inside a 16-node allocation
    was invisible."""
    assert nodes.is_node_local("system.cpu_governor")
    assert nodes.is_node_local("system.turbo")

    def n(host, governor):
        return Fingerprint(
            {"hardware.hostname": value(host), "system.cpu_governor": value(governor)},
            {"label": host},
        )

    merged = nodes.merge(n("n1", "performance"),
                         [("n1", n("n1", "performance")), ("n2", n("n2", "powersave"))], 2)
    f = merged.fields["system.cpu_governor"]
    assert f.value == [["performance", 1], ["powersave", 1]]
    assert "heterogeneous" in f.detail

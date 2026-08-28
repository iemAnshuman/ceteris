# Records captured on LSU's Rostam cluster, 2026-08-28

Real fingerprints from a real Slurm cluster. Until these were taken, every
Linux, Slurm, CUDA and multi-node code path in ceteris had only ever run
against fixtures written from documentation.

| file | where | what it exercises |
|---|---|---|
| `login2.json` | login node `rostam1` | Linux `/proc/cpuinfo`, sysfs system state, no scheduler, `nvidia-smi` present but no GPU |
| `gpu1.json` | `diablo`, 1 node, `cuda-V100` | Slurm field mapping, real `nvidia-smi` output |
| `fanout.json` | `medusa00,medusa01` | the `srun` per-node fan-out, homogeneous merge |
| `het2.json` | `diablo,bahram` | **heterogeneous merge** — two node types in one allocation |
| `amd-mi100.json` | `kamand1`, partition `mi100` | ROCm: 2x AMD Instinct MI100, no `nvidia-smi` anywhere |

`het2.json` is the important one. Those two nodes differ, and the merge says so:

```
hardware.cpu_model          [["Intel Xeon E5-2660 v3", 1], ["Intel Xeon Gold 6148", 1]]
hardware.cpu_cores_logical  [[20, 1], [40, 1]]
hardware.gpu_models         [[["Tesla V100-PCIE-32GB", ...], 1], [["Tesla V100-SXM2-32GB", ...], 1]]
hardware.gpu_driver         580.65.06          (identical on 2 nodes)
```

Verified against ground truth taken in the same job with `srun ... nvidia-smi`
and `nproc`. Before per-node capture existed, a fingerprint described the head
node alone and two allocations with different hardware would have compared as
equal.

Two bugs were found by these runs and fixed in the same session: `system.*`
was not being merged per node, and a failing `nvidia-smi` on a GPU-less login
node was recorded as unknown rather than as no GPU.


## What `amd-mi100.json` found

The ROCm collector had been written from documentation and was wrong. It
asked `rocm-smi` for the product name and the driver version in one call, and
rocm-smi answers such a request with only the last table, so every card row
vanished. The first run on this node produced three unknowns:

```
COULD NOT BE READ (these block certification):
  hardware.gpu_count   could not parse rocm-smi --csv output
  hardware.gpu_driver  no driver version row in rocm-smi --csv output
  hardware.gpu_models  could not parse rocm-smi --csv output
```

It failed closed instead of inventing a GPU count, and `ceteris doctor` named
the fields and the reasons. After fixing it to issue each query separately
and read the JSON output, the same node reports what `rocm-smi` reports:
2 x AMD Instinct MI100, driver 6.12.12, zero unknowns.

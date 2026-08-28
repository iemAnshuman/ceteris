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

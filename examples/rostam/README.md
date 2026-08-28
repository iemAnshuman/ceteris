# Records captured on LSU's Rostam cluster, 2026-08-28/29

Real fingerprints from a real Slurm cluster. Every Linux, Slurm, CUDA, ROCm,
container and multi-node path in ceteris was fixture-only until these.

| file | where | what it exercised |
|---|---|---|
| `login2.json` | login node `rostam1` | Linux `/proc/cpuinfo`, sysfs system state, no scheduler, `nvidia-smi` present with no GPU |
| `gpu1.json` | `diablo`, `cuda-V100` | Slurm field mapping, real `nvidia-smi` |
| `fanout.json` | `medusa00,01` | the `srun` per-node fan-out, homogeneous merge |
| `het2.json` | `diablo,bahram` | **heterogeneous merge** — two node types in one allocation |
| `amd-mi100.json` | `kamand1`, `mi100` | **ROCm**: 2x AMD Instinct MI100, no `nvidia-smi` anywhere |
| `mpi-2node-run.json` | `medusa01,02` | **`ceteris run`** with `--repeats 3` across 2 nodes |
| `openmpi-gcc.json` | `medusa` | real Open MPI 5.0.7 and gcc 14.3.0 banners |
| `cmake-cache.json` | `medusa` | a real `CMakeCache.txt` from an existing build tree |
| `cuda-v100.json` | `diablo` | `nvcc` / CUDA runtime 12.8 |
| `apptainer.json` | inside a `.sif` on `diablo` | **container identity** |

## What these caught

**`ceteris run` had never executed on a cluster.** The first attempt exited
183 because the benchmark binary sat on node-local `/tmp`. Three failed runs,
no measurement — and `ceteris compare` reported *"every difference was
declared, comparison is valid"* with exit 0. The wrapped command's exit code
lives outside the comparable body and compare had never looked at it. Fixed:
a run that exited non-zero is never certified.

**`mpi-2node-run.json`** is the corrected run: 6.202 GB/s inter-node, three
repeats, 0% spread, and the before/after fan-out across both nodes cost
4.3 s for all six captures.

**`apptainer.json` is the most interesting record here.** Inside the image
the NVIDIA kernel driver is visible through `/proc` and `/sys`, but
`nvidia-smi` is not in the container. ceteris reports *"a GPU driver is
loaded but neither nvidia-smi nor rocm-smi is on PATH"* and refuses to
certify, rather than concluding there is no GPU. That rule was written for
AMD machines and turned out to be exactly right in a case nobody had in mind.

The same record exposed a contradiction: `deps.container_runtime` said
apptainer while `system.container` said no, because Apptainer creates neither
`/.dockerenv` nor a docker-shaped cgroup line. Both now use one detector.

**`amd-mi100.json`** proved the ROCm collector wrong: it asked `rocm-smi` for
the product name and driver version in one call, and rocm-smi answers such a
request with only the last table, so every card row vanished. It failed
closed and `ceteris doctor` named the fields; after the fix the same node
reports 2 x AMD Instinct MI100, driver 6.12.12.

**`het2.json`** is what per-node capture exists for. `diablo` and `bahram`
differ, and the merge says so instead of describing the head node:

```
hardware.cpu_model          [["Intel Xeon E5-2660 v3", 1], ["Intel Xeon Gold 6148", 1]]
hardware.cpu_cores_logical  [[20, 1], [40, 1]]
hardware.gpu_models         V100-PCIE x2  vs  V100-SXM2 x4
hardware.gpu_driver         580.65.06          (identical on 2 nodes)
```

Ground truth for every record was taken in the same job with `srun
nvidia-smi`, `rocm-smi`, `nproc` and `mpirun --version`.

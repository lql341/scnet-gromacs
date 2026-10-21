# Local performance observations

These are short, site-specific observations, not universal benchmark results and
not part of the correctness gate. They are kept separate from `catalog.json` and
are not loaded as skill context.

## Kunshan GROMACS 2026.3 / gfx906

Case: existing Lysozyme-in-water TPR, 71,844 atoms, 500 steps, one node.
All HIP runs used `-nb gpu -pme gpu`; the two-rank run used `-npme 1`.

| Configuration | Performance |
| --- | ---: |
| 1 MPI rank, 1 GPU, 4 OpenMP threads | 33.9 ns/day |
| 2 MPI ranks, 2 GPUs, 4 threads each | 26.7 ns/day |
| 2 MPI ranks, 2 GPUs, forced GPU-aware MPI | 0.79 ns/day |

Interpretation:

- two GPUs were slower for this small system; the likely costs are domain
  decomposition/communication and PME decomposition, not lack of GPU support;
- forcing GPU-aware MPI completed, but the platform MPI path was unusably slow.
  Do not enable `GMX_FORCE_GPU_AWARE_MPI` without measuring it on the target MPI;
- this does not predict behavior for larger systems. Use a representative
  benchmark case before making multi-GPU scaling or performance claims.

# Local performance observations

These are short, reference-environment observations, not universal benchmark
results and not part of the correctness gate. A blank SCNet account must
reproduce them. They are kept separate from `catalog.json` and are not loaded as
skill context.

## Kunshan GROMACS 2026.3 / gfx906

Case: existing Lysozyme-in-water TPR, 71,844 atoms, 500 steps, one node.
All HIP runs used `-nb gpu -pme gpu`; the two-rank run used `-npme 1`.

| Configuration | Performance |
| --- | ---: |
| 1 MPI rank, 1 GPU, 4 OpenMP threads | 33.9 ns/day |
| 2 MPI ranks, 2 GPUs, 4 threads each | 26.7 ns/day |
| 2 MPI ranks, 2 GPUs, forced GPU-aware MPI | 0.79 ns/day |

## GROMACS 2026.4 reference build

Lysozyme-in-water TPR, 71,844 atoms, 200 steps, same reference node type.
All HIP runs used `srun` with `SLURM_MPI_TYPE=pmix`, `-nb gpu -pme gpu`; multi-rank
runs used `-npme 1`.

| Configuration | Performance |
| --- | ---: |
| 1 GPU, 1 rank | 29.0 ns/day |
| 2 GPUs, 2 ranks | 27.3 ns/day |
| 4 GPUs, 4 ranks, one node | 43.1 ns/day |
| 4 GPUs, 4 ranks, two nodes | 43.5 ns/day |

The two-node run used one rank/GPU per node and `UCX_NET_DEVICES` restricted to
the working HCA. It was not faster than the single-node four-GPU run for this
small system; the result is communication- and size-limited, not a claim that
multi-node provides no benefit.

## GROMACS 2026.4 larger ADH system

ADH benchmark, 134,177 atoms, 200 steps, 2026.4:

| Configuration | Performance |
| --- | ---: |
| 1 GPU | 21.1 ns/day |
| 2 GPUs, one node | 22.7 ns/day |
| 4 GPUs, one node | 28.7 ns/day |
| 4 GPUs, two nodes | 27.8 ns/day |

The larger system scales better than Lysozyme but is still sublinear; two nodes
were slightly slower than one four-GPU node at this size. This is a reference
observation, not a production benchmark.

## Cross-node transport check

On the same 71,844-atom case, 4 ranks across 2 nodes, 200 steps:

| Transport | Result |
| --- | --- |
| UCX, working HCA (`mlx5_0:1`) | 41.3 ns/day, pass |
| UCX, default HCA selection | failed before mdrun (`ibv_create_ah`, invalid argument) |
| OB1/TCP fallback | 32.0 ns/day, pass |
| PMPI 2026.4, OB1 + `ib0` interface selection, 2 nodes/4 ranks/4 GPUs | 21.4 ns/day, pass |

OB1 is a fallback, not the best default on this fabric. Keep the HCA/transport
choice site-configurable; do not hardcode OB1. PMPI multi-node also needs a
hostfile and explicit `ib0` TCP/OOB interface selection; without it the platform
MPI tries the management network and hangs.

## ROCm-enabled UCX/OpenMPI experiment

A ROCm-enabled UCX/OpenMPI build was tested with the 2026.4 Lysozyme case:

| Configuration | Result |
| --- | ---: |
| 2 nodes/4 GPUs, host-staged (no GPU-aware) | 43.5 ns/day |
| 2 nodes/4 GPUs, GPU-aware, default UCX TLS | 1.7 ns/day |
| 1 node/4 GPUs, host-staged | 43.1 ns/day |
| 1 node/4 GPUs, GPU-aware, default UCX TLS | 0.97 ns/day |
| 1 node/4 GPUs, GPU-aware, `UCX_TLS=rocm_ipc,sm,self,tcp` | 18.1 ns/day |
| ADH 134k, 1 node/4 GPUs, host-staged | 28.7 ns/day |
| ADH 134k, 1 node/4 GPUs, GPU-aware default TLS | 0.57 ns/day |

GROMACS detected GPU-aware MPI and used direct GPU communication, but the
direct path was far slower than host staging. The larger 134k-atom ADH case was
also about 50x slower with GPU-aware communication (0.57 versus 28.7 ns/day), so
the problem is not only the tiny system size. The experiment proves the build can
expose GPU-aware MPI; it does not justify enabling it. Keep it off by default
until the site's ROCm/UCX/mlx5 path is tuned.

Interpretation:

- two GPUs were slower than one for this small system; the likely costs are
  domain decomposition/communication and PME decomposition, not lack of GPU
  support;
- forcing GPU-aware MPI completed, but the platform MPI path was unusably slow.
  The default reference UCX build is configured without ROCm, so GPU-aware MPI is
  unavailable there; a ROCm-enabled build exposed it but was much slower. Do not
  enable `GMX_FORCE_GPU_AWARE_MPI` without measuring it;
- cross-node results are sensitive to allocation balance, Slurm PMIx and HCA
  selection; a blank account must re-run the transport check;
- this does not predict behavior for larger systems. Use a representative
  benchmark case before making multi-GPU or multi-node performance claims.

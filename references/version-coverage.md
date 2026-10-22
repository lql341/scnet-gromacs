# GROMACS version coverage

This is a coverage declaration for the reference environment, not a bundled
GROMACS distribution. The standard is **one user-level module per application
version**, for example `gromacs/2026.3` and `gromacs/2026.4`. Backend, MPI and
launcher variants are build/profile choices, not separate module names. The
reference modules are user-level only; system-wide publication is out of scope.

| GROMACS | CPU/HIP | PME | multi-rank PME | multi-GPU | multi-node |
| --- | --- | --- | --- | --- | --- |
| 2026.3 | yes | yes | yes | yes | yes |
| 2026.4 | yes | yes | yes | yes | yes |

## Basis

- **2026.3**: reference module. CPU/HIP, PME energy components, two-rank PME
  decomposition, two-GPU execution and two-node/four-GPU execution were
  exercised.
- **2026.4**: canonical reference module uses the official 2026.4 source with
  OpenMPI 5 + UCX + HIP. CPU/HIP, PME, two-rank PME decomposition, two-GPU PME
  and two-node/four-GPU execution were exercised.
- **PMPI**: an optional compatibility profile, not a module name. It was
  validated single-node (single-rank CPU/HIP, two-rank CPU PME, two-GPU PME) and
  on two nodes/four ranks/four GPUs with `mpirun`, a hostfile, OB1 and explicit
  `ib0` TCP/OOB interface selection. PMPI/OB1 was slower than the OpenMPI 5 UCX
  path (21.4 versus 41.3 ns/day on the same 200-step Lysozyme run).

## Environment-dependent facts

- Multi-node OpenMPI 5 needs `srun` with `SLURM_MPI_TYPE=pmix` on this reference
  site; a balanced allocation also needs `--ntasks-per-node`.
- HCOLL is disabled by the reference OpenMPI 5 module. Keep it off for GROMACS
  multi-rank, especially when testing GPU-aware communication.
- The default UCX HCA choice failed on one fabric path. Restricting
  `UCX_NET_DEVICES` to the working HCA made cross-node runs pass and was faster
  than the OB1/TCP fallback. Keep the HCA selection site-specific; do not
  hardcode OB1.
- The reference UCX build without ROCm has no GPU-aware MPI. Normal host-staged
  GPU communication works. A ROCm-enabled UCX/OpenMPI build was also tested:
  GROMACS detected GPU-aware MPI, but the direct path was much slower than
  host-staged communication, including on the 134k-atom ADH case. Forced
  GPU-aware MPI is therefore not a supported default.

## Minimum evidence for a new account/version

Run the module probe, version gate, CPU/HIP smoke, PME smoke and at least one
multi-rank or multi-GPU case that matches the intended use. Record scheduler
state, workload status, process/GPU counts, comparison result and untested
boundaries.

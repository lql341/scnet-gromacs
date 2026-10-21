# GROMACS version coverage

This is a coverage declaration for the reference environment, not a bundled
GROMACS distribution and not a guarantee for every SCNet account. A blank account
must provide a site module or its own build through `GROMACS_MODULE`,
`GROMACS_MODULEPATH`, `GROMACS_BINARY` and/or `GROMACS_ENV_SCRIPT`.

| GROMACS | CPU | HIP | PME | multi-rank PME | multi-GPU | multi-node | PMPI |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026.3 | yes | yes | yes | yes | yes | yes | yes |
| 2026.4 | yes | yes | yes | yes | yes | yes | not tested |

## Basis

- **2026.3**: reference site module and PMPI variant. CPU/HIP, PME energy
  components, two-rank PME decomposition, two-GPU execution, PMPI single-rank and
  multi-rank (with an OB1 fallback), and two-node/four-GPU execution were exercised.
  PMPI multi-node was not tested.
- **2026.4**: reference build from the official 2026.4 source, validated through
  a private module path. CPU/HIP, PME, two-rank PME decomposition and two-node/
  four-GPU execution were exercised. It is not a site-published module; a blank
  account must build or obtain its own module. PMPI 2026.4 was not built/tested.

## Environment-dependent facts

- Multi-node OpenMPI 5 needs `srun` with `SLURM_MPI_TYPE=pmix` on this reference
  site; a balanced allocation also needs `--ntasks-per-node`.
- The default UCX HCA choice failed on one fabric path. Restricting
  `UCX_NET_DEVICES` to the working HCA made cross-node runs pass and was faster
  than the OB1/TCP fallback. Keep this site-specific; do not hardcode OB1.
- The reference UCX build was configured without ROCm, so GPU-aware MPI is not
  available. Normal host-staged GPU communication works. Forced GPU-aware MPI is
  not a supported default.
- Performance numbers are local observations in `benchmarks/observations.md`,
  not production or cross-site guarantees.

## Minimum evidence for a new account/version

Run the module probe, version gate, CPU/HIP smoke, PME smoke and at least one
multi-rank or multi-GPU case that matches the intended use. Record scheduler
state, workload status, process/GPU counts, comparison result and untested
boundaries.

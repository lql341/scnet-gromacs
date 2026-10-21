# GROMACS version coverage

This is a coverage declaration for the reference environment, not a bundled
GROMACS distribution and not a guarantee for every SCNet account. A blank account
must provide a site module or its own build through `GROMACS_MODULE`,
`GROMACS_MODULEPATH`, `GROMACS_BINARY` and/or `GROMACS_ENV_SCRIPT`.

| GROMACS | CPU | HIP | PME | multi-rank PME | multi-GPU | multi-node | PMPI |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026.3 | yes | yes | yes | yes | yes | yes | yes |
| 2026.4 | yes | yes | yes | yes | yes | yes | yes (single-node) |

## Basis

- **2026.3**: reference site module and PMPI variant. CPU/HIP, PME energy
  components, two-rank PME decomposition, two-GPU execution, PMPI single-rank and
  multi-rank (with an OB1 fallback), and two-node/four-GPU execution were exercised.
  PMPI multi-node was not tested.
- **2026.4**: reference builds from the official 2026.4 source, validated through
  reference modules. CPU/HIP, PME, two-rank PME decomposition, two-GPU PME and
  two-node/four-GPU execution were exercised. The PMPI variant was validated
  single-node (single-rank CPU/HIP, two-rank CPU PME, two-GPU PME) with
  `mpirun` and an OB1 transport override; PMPI multi-node was not tested. The
  reference modules live in the maintainer's module path; system-wide
  publication requires the site's module/package process. They are not bundled.

## Environment-dependent facts

- Multi-node OpenMPI 5 needs `srun` with `SLURM_MPI_TYPE=pmix` on this reference
  site; a balanced allocation also needs `--ntasks-per-node`.
- The default UCX HCA choice failed on one fabric path. Restricting
  `UCX_NET_DEVICES` to the working HCA made cross-node runs pass and was faster
  than the OB1/TCP fallback. Keep this site-specific; do not hardcode OB1.
- The reference UCX build without ROCm has no GPU-aware MPI. Normal host-staged
  GPU communication works. A ROCm-enabled UCX/OpenMPI build was also tested:
  GROMACS detected GPU-aware MPI, but the direct path was much slower than
  host-staged communication on this DTK/HIP/mlx5 fabric. Forced GPU-aware MPI is
  therefore not a supported default.
- Performance numbers are local observations in `benchmarks/observations.md`,
  not production or cross-site guarantees.

## Minimum evidence for a new account/version

Run the module probe, version gate, CPU/HIP smoke, PME smoke and at least one
multi-rank or multi-GPU case that matches the intended use. Record scheduler
state, workload status, process/GPU counts, comparison result and untested
boundaries.

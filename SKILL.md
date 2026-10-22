---
name: scnet-gromacs
description: Validate GROMACS modules on SCNet CPU and Hygon DCU/HIP compute nodes with a deterministic CPU oracle, explicit device evidence, CPU/HIP tolerance checks and scheduler-aware results.
---

# SCNet GROMACS

Use this skill for GROMACS module validation and small CPU/HIP smoke runs on
SCNet. Read [references/validation.md](references/validation.md) and, for a
first-time SCNet user, [references/first-use.md](references/first-use.md).
Run `python3 scripts/doctor.py` before configuring or submitting.

## Rules

- Never run GROMACS validation on the agent workstation.
- The core path is `scripts/gromacs_module_probe.sh`,
  `scripts/gromacs_argon_smoke.sbatch` and `scripts/compare_gromacs_energy.py`.
- `contrib/run_openapi.py` is optional orchestration over `scnet-hpc` OpenAPI
  for mkdir, upload, submit, wait, job details and artifact download. Users load
  only this skill; `scnet-hpc` is an optional installed CLI dependency.
- Use SSH only when OpenAPI cannot expose a needed fact, and then only for
  bounded diagnosis.
- Use a unique run directory and preserve all prior results.
- Compute nodes are Linux. The local agent may be Windows, macOS or Linux;
  keep remote paths POSIX and use `python3 scripts/validate.py` for local checks.
- Treat module names as hints; load and inspect `gmx_mpi --version` on the target node.
- Keep CPU as the numerical oracle and treat GPU as a separate backend/runtime check.
- Use `cases/argon8` for the no-charge CPU/HIP smoke and `cases/ionpair_pme`
  for the PME GPU path; do not add PME options to the Argon case.
- On a single MPI rank, use `-pme gpu` without `-npme`; GROMACS rejects
  `-npme` when only one rank is requested. Add `-npme` only for a real
  multi-rank job.
- Compare CPU and HIP energies with the documented tolerance script; do not
  require bitwise equality.
- For multi-rank work, record the MPI process count; for PME decomposition,
  record the separate PME rank count; for multi-GPU, record the selected GPU
  count. Do not infer these from the requested resources.
- Propagate nonzero `grompp`, `mdrun`, checker and scheduler statuses.

## Execution profiles and blank accounts

Copy `clusters/_template.conf` to a private `clusters/<profile>.conf` and set the
CPU/DCU queues, CPU/HIP modules, CPU count, DCU count, walltime and expected
GROMACS version. The template is Z100/DCU-oriented but is not live availability
evidence. The optional runner passes `--dcus` only for HIP jobs and refuses
existing remote run roots.

Do not assume the maintainer's module or prefix. A blank SCNet account may use a
site module, a private module path, or a user-owned binary plus environment
script. `GROMACS_MODULE` may be empty; set `GROMACS_BINARY` and optionally
`GROMACS_ENV_SCRIPT`. Reference modules are user-level only; system-wide
publication is out of scope. Coverage in `references/version-coverage.md` is
reference evidence, not a bundled GROMACS distribution.

For multi-node work set `NODES`, `MPI_RANKS` and `MPI_RANKS_PER_NODE`. On the
reference OpenMPI 5 build, `srun` needs `SLURM_MPI_TYPE=pmix`; the allocation must
be balanced with `--ntasks-per-node`. Keep the UCX HCA/transport choice
configurable; OB1 is a fallback, not a universal default.

When the site module changes, update the profile module/version, rerun the same
CPU/HIP/PME cases and record the new evidence. Do not silently change tolerances
or assume that a new GROMACS version has the same log markers or backend options.

## Evidence gates

Require:

1. scheduler state `COMPLETED` and platform exit status zero;
2. `gmx_mpi --version` with compiler/MPI/GPU/architecture metadata;
3. successful `grompp` and CPU `mdrun`;
4. finite energy output and a final-state summary;
5. for HIP mode, visible device evidence and explicit GPU-offload options;
6. for PME mode, the log line `PME tasks will do all aspects on the GPU`;
7. for multi-rank, the requested MPI process count and, when requested, the
   separate PME rank count;
8. for multi-GPU, the requested selected GPU count.

GPU/CPU equality is not a default bitwise requirement. Compare physical sanity,
finite values, energy trends and the documented tolerance with
`scripts/compare_gromacs_energy.py`. The comparison only accepts two runs with
`status=passed`, identical input checksums and the same time grid.

Performance data is separate: `benchmarks/catalog.json` is not loaded as skill
context and contains no committed measurements. Use it only for a deliberate
performance task with a representative system.

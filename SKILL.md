---
name: scnet-gromacs
description: Validate GROMACS modules on SCNet CPU and Hygon DCU/HIP compute nodes with a deterministic CPU oracle, explicit device evidence, CPU/HIP tolerance checks and scheduler-aware results.
---

# SCNet GROMACS

Use this skill for GROMACS module validation and small CPU/HIP smoke runs on
SCNet. Read [references/validation.md](references/validation.md) first.

## Rules

- Never run GROMACS validation on the agent workstation.
- Prefer `scnet-hpc` OpenAPI for queue, submission, wait, status and cancellation.
- Use SSH only for bounded script upload and logs.
- Use a unique run directory and preserve all prior results.
- Treat module names as hints; load and inspect `gmx_mpi --version` on the target node.
- Keep CPU as the numerical oracle and treat GPU as a separate backend/runtime check.
- Use `cases/argon8` for the no-charge CPU/HIP smoke and `cases/ionpair_pme`
  for the PME GPU path; do not add PME options to the Argon case.
- On a single MPI rank, use `-pme gpu` without `-npme`; GROMACS rejects
  `-npme` when only one rank is requested. Add `-npme` only for a real
  multi-rank job.
- Compare CPU and HIP energies with the documented tolerance script; do not
  require bitwise equality.
- Propagate nonzero `grompp`, `mdrun`, checker and scheduler statuses.

## Evidence gates

Require:

1. scheduler state `COMPLETED` and platform exit status zero;
2. `gmx_mpi --version` with compiler/MPI/GPU/architecture metadata;
3. successful `grompp` and CPU `mdrun`;
4. finite energy output and a final-state summary;
5. for HIP mode, visible device evidence and explicit GPU-offload options;
6. for PME mode, the log line `PME tasks will do all aspects on the GPU`.

GPU/CPU equality is not a default bitwise requirement. Compare physical sanity,
finite values, energy trends and the documented tolerance with
`scripts/compare_gromacs_energy.py`. The comparison only accepts two runs with
`status=passed`, identical input checksums and the same time grid.

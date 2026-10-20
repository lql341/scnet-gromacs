# Changelog

## 0.1.1 (2026-10-20)

- Make the Argon smoke checker compatible with GROMACS 2026.3 output and
  multi-column `energy.xvg`.
- Record visible HIP devices and use a case-correct `-nb gpu` path for the
  no-charge Argon smoke.
- Document MPI, topology-name, PME-option and scheduler/workload evidence
  pitfalls observed during target-node validation.

## 0.1.0 (2026-10-20)

- Add a small remote-first GROMACS module validation skill.
- Add a deterministic eight-atom Argon CPU oracle case.
- Add optional HIP/DCU execution with explicit device and scheduler evidence.
- Record Kunshan GROMACS 2026.3, OpenMPI, HIP, rocFFT and gfx906 observations.

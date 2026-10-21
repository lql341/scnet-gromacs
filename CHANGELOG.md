# Changelog

## 0.2.0 (2026-10-21)

- Add a PME-enabled ion-pair case and a `-nb gpu -pme gpu` HIP path that
  requires the explicit `PME tasks will do all aspects on the GPU` log line.
- Add a CPU/HIP energy-tolerance checker with input provenance checks, time-grid
  validation and documented absolute-plus-relative tolerances.
- Record input checksums and support a configurable case coordinate file and
  output prefix.
- Document that `-npme` must be omitted for a single MPI rank and that the tiny
  smoke cases do not establish production accuracy or performance.

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

# Changelog

## 0.5.0 (2026-10-21)

- Extend numerical comparison with PME components and configurable energy
  terms while keeping the CPU oracle and tolerance contract.
- Add explicit multi-rank, PME decomposition, multi-GPU, forced GPU-aware MPI
  and PMPI execution paths with log-based process/GPU/PME-rank evidence.
- Record the Kunshan launcher findings: `mpirun` for the self-built OpenMPI 5
  module; PMPI multi-rank needs an MPI transport override such as OB1.
- Add read-only queue/walltime preflight and best-effort failure artifact plus
  scheduler-log collection; downloaded logs stay outside the repository.
- Add a non-loaded performance benchmark catalog under `benchmarks/`.
- Validate energy coverage, multi-rank CPU/HIP, multi-GPU PME and PMPI paths on
  the target cluster.
- Add `GROMACS_MODULEPATH` for private candidate builds and verify the version
  adaptation path with a private GROMACS 2026.4 build.

## 0.4.0 (2026-10-21)

- Make OpenAPI orchestration optional under `contrib/`; the compute-node
  scripts remain the canonical validation path.
- Default the optional runner's `scnet-hpc` lookup to the sibling
  `../scnet-hpc` skill, so a shared `skills/` tree works without extra flags.
- Add `GROMACS_EXPECT_VERSION` to pin the loaded module version and fail early
  if a site upgrade does not match the selected profile.
- Document the version-adaptation procedure for new GROMACS releases.

## 0.3.0 (2026-10-21)

- Add an OpenAPI-first runner that uses scnet-hpc for remote mkdir, upload,
  submit, bounded wait, job details and artifact download; SSH is no longer
  required in the normal execution path.
- Run CPU and HIP together, download both result sets and apply the tolerance
  checker in one command.
- Add Z100/DCU-oriented profile defaults for CPU/DCU queues, modules, CPU/DCU
  counts and walltime, while keeping site-specific values out of the repository.
- Validate the runner end to end on both the Argon and PME cases.

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

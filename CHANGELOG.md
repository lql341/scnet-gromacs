# Changelog

## 0.8.1 (2026-10-21)

- Record the larger 134,177-atom ADH GPU-aware result: direct communication was
  about 50x slower than host staging, so the GPU-aware limitation is not only a
  small-system effect.

## 0.8.0 (2026-10-21)

- Keep the 2026.4 reference modules user-level only; system-wide publication is
  explicitly out of scope.
- Make local orchestration cross-platform: POSIX remote paths from Windows,
  macOS or Linux; add a Python validator that works without a local bash.
- Validate PMPI 2026.4 multi-node on two nodes/four ranks/four GPUs with
  hostfile, OB1 and explicit `ib0` interface selection.
- Add launcher-argument support and document the PMPI multi-node transport
  contract; keep OB1 a configurable fallback, not a hardcoded default.
- Update version coverage, validation notes and benchmark observations.

## 0.7.0 (2026-10-21)

- Add formal 2026.4 PMPI reference module coverage and single-node validation
  (single-rank CPU/HIP, two-rank CPU PME, two-GPU PME).
- Add launcher-argument support and document the PMPI OB1 fallback as a
  site-configurable transport, not a default.
- Expand the reference benchmark to the 134,177-atom ADH system across 1/2/4
  GPUs and two nodes/four GPUs.
- Build a ROCm-enabled UCX/OpenMPI variant. GPU-aware MPI is detected but much
  slower than host staging on this fabric; keep it disabled by default.
- Update version coverage, blank-account guidance and multi-node/transport notes.

## 0.6.0 (2026-10-21)

- Add a formal version-coverage declaration for 2026.3 and 2026.4, based on the
  reference environment but not assuming a maintainer-owned module.
- Support blank-account operation with no module: configurable module path,
  absolute binary and environment script.
- Add multi-node orchestration: node count, ranks per node, balanced scheduler
  options and `srun --ntasks-per-node`.
- Debug cross-node transport: `srun` plus Slurm PMIx works for OpenMPI 5; the
  default UCX HCA path can fail, and a working `UCX_NET_DEVICES` path outperforms
  the OB1/TCP fallback. OB1 remains a user-configurable fallback, not a default.
- Expand the reference benchmark to 1/2/4 GPUs and two-node/four-GPU runs, with
  observations kept outside skill context.

## 0.5.1 (2026-10-21)

- Add a separate local performance-observation note for small-system multi-GPU
  behavior; it is not loaded as skill context.
- Record that forcing GPU-aware MPI was slower on the site MPI path and must not
  be enabled without measurement.

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

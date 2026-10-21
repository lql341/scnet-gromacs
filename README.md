# scnet-gromacs

English | [中文](README_CN.md)

Current release: 0.8.0

Validate an existing GROMACS module on SCNet compute nodes with a tiny,
deterministic molecular-dynamics case. The workflow is remote-first: module
loading, `grompp`, `mdrun`, device checks and numerical comparisons happen on the
target compute node, not on the agent workstation.

The first target is the Kunshan Z100/DTK environment. Its module inventory
contains GROMACS 2026.3; official GROMACS documentation currently describes
2026.4, so this skill reports the patch-level difference instead of silently
rebuilding the software. See the [official 2026.4 release notes](https://manual.gromacs.org/current/release-notes/2026/2026.4.html).

## One-sentence agent installation

> Use `$skill-installer` to install `scnet-gromacs` from the root of GitHub repository `lql341/scnet-gromacs` (path `.`, ref `main`), name it `scnet-gromacs`, do not overwrite an existing destination, then run `scripts/validate.sh`; do not submit a cluster job during installation.

## What this validates

- module identity and `gmx_mpi --version`;
- compiler, MPI, HIP/DTK, GPU FFT and target architecture metadata;
- deterministic CPU `grompp` + `mdrun` on the bundled eight-atom Argon case;
- optional HIP/DCU `mdrun` with explicit `-nb gpu` for the bundled no-charge
  Argon case;
- a separate PME-enabled ion-pair case with `-nb gpu -pme gpu`, a PME GPU log
  check and no forced PME options on the Argon case;
- finite energy output, a compact final-state checksum and recorded input
  checksums;
- an explicit CPU/HIP energy comparison with documented tolerances;
- PME energy components (`Coulomb (SR)`, `Coul. recip.`, `LJ (SR)`), not just
  the total potential;
- optional multi-rank, PME decomposition, multi-GPU and PMPI execution paths;
- scheduler completion and workload exit status.

The CPU run is the oracle. A GPU run is an integration and runtime check, not a
claim of bitwise equivalence or production performance. Floating-point
differences must be reported with tolerances and physical sanity checks.

The bundled cases are only smoke tests. They exercise selected PME
decomposition, GPU-aware and PMPI paths, but do not establish multi-node
scaling or production-size accuracy.

## Version coverage and blank-account baseline

The skill does not bundle GROMACS. A blank SCNet account must provide a site
module or its own build. Coverage below means the path was exercised on the
reference environment; it is not a guarantee for every account or cluster.

| GROMACS | CPU | HIP | PME | multi-rank PME | multi-GPU | multi-node | PMPI |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026.3 | yes | yes | yes | yes | yes | yes | yes |
| 2026.4 | yes | yes | yes | yes | yes | yes | yes |

The 2026.4 reference builds came from the official 2026.4 source and were
exercised through user-level reference modules. The 2026.4 PMPI variant was
validated single-node and on two nodes/four ranks/four GPUs. These are user-level
modules only; system-wide publication is out of scope, and a blank account must
build or obtain its own. See
[references/version-coverage.md](references/version-coverage.md) for the basis,
multi-node/UCX findings and the minimum evidence needed for a new account.

A user-owned build can be selected without a module:

```text
GROMACS_MODULE=""
GROMACS_GPU_MODULE=""
GROMACS_BINARY=/absolute/path/to/gmx_mpi
GROMACS_ENV_SCRIPT=/absolute/path/to/env.sh
```

## Workflow

Use `scnet-hpc` OpenAPI for queue discovery, submission, status, waiting and
cancellation. SSH is only for bounded script upload and log diagnosis.

```bash
bash scripts/validate.sh
```

Submit the scripts through `scnet-hpc` OpenAPI on the selected compute queue.
The scripts accept:

```text
GROMACS_MODULE     module name, default gromacs/2026.3
GROMACS_MODULEPATH optional private modulefile directory for a candidate build
GROMACS_BINARY     binary name, default gmx_mpi
GROMACS_GPU_MODE   cpu or hip, default cpu
GROMACS_GPU_PME    1 to add -pme gpu, default 0; only for a PME-enabled case
GROMACS_EXPECT_GPU_ARCH  optional expected gfx name, e.g. gfx906
GROMACS_EXPECT_VERSION   optional expected GROMACS version, e.g. 2026.3
GROMACS_ENERGY_TERMS     comma-separated gmx energy input terms
GROMACS_MPI_RANKS        MPI ranks, default 1
GROMACS_OMP_THREADS      OpenMP threads per rank, default 2
GROMACS_MPI_LAUNCHER     srun or mpirun, default srun
GROMACS_NPME             -npme value; only valid when MPI ranks > 1
GROMACS_EXPECT_GPU_COUNT expected selected GPU count in HIP mode
GROMACS_FORCE_GPU_AWARE_MPI set GMX_FORCE_GPU_AWARE_MPI=1
GROMACS_REQUIRE_GPU_AWARE_MPI fail if the log says GPU-aware MPI is absent
GROMACS_CASE_ROOT  case directory, default <repo>/cases/argon8
GROMACS_CASE_GRO   input coordinate file, default argon.gro
GROMACS_DEFFNM     output prefix, default argon
GROMACS_RUN_ROOT   unique writable run root
```

Do not infer GPU support from a module name alone. The compute-node probe must
show visible devices and the binary must report HIP support. For the PME case,
set `GROMACS_CASE_ROOT` to `cases/ionpair_pme`, `GROMACS_CASE_GRO=ionpair.gro`,
`GROMACS_DEFFNM=ionpair` and `GROMACS_GPU_PME=1`.

On a single MPI rank, use `-pme gpu` without `-npme`. The installed GROMACS
rejects `-npme` when only one rank is requested; set `GROMACS_NPME` only when
the job really has multiple MPI ranks.

For multi-rank work, set `GROMACS_MPI_RANKS`, `GROMACS_OMP_THREADS` and a
launcher. The allocation must provide at least `ranks * threads` CPUs. HIP
validation currently requires one requested DCU per rank. Use `GROMACS_NPME=1`
with a PME case to request a separate PME rank.

Observed launcher behavior on Kunshan:

- the self-built OpenMPI 5 module supports Slurm PMIx. Multi-rank jobs work with
  `srun` when `SLURM_MPI_TYPE=pmix` is set; without it, `srun` launched singleton
  ranks;
- a multi-node allocation must be balanced with `#SBATCH --ntasks-per-node=...`.
  Otherwise the scheduler can place most ranks on one node and GROMACS fails its
  GPU task assignment;
- the PMPI module's platform OpenMPI 4.1.5 is not Slurm-PMI enabled. Its
  multi-rank path needed `mpirun` plus an MPI transport override, for example
  `MPI_ENV_OMPI_MCA_PML=ob1`;
- cross-node UCX initially failed on one HCA path. Restricting
  `UCX_NET_DEVICES` to the working HCA made UCX pass and outperform the OB1/TCP
  fallback. OB1 is a fallback, not a universal best practice; keep the
  transport/HCA choice site-configurable.

These are reference-site observations, not universal launcher recommendations.
For cross-node runs, set `NODES`, `MPI_RANKS`, `MPI_RANKS_PER_NODE` and, if
needed, `SCHEDULER_OPTIONS`; the runner balances the allocation and passes
`--ntasks-per-node` to `srun`.

## Optional OpenAPI runner

The core validation path is still the three compute-node scripts. Optional
orchestration lives in `contrib/run_openapi.py`; it calls the installed
`scnet-hpc` CLI with `--backend openapi` for remote directory creation, script
and case upload, submission, bounded wait, job-detail checking and artifact
download. You can also drive the same scripts directly with `scnet-hpc` without
this wrapper. The wrapper does not use SSH and does not implement a second
credential or transport layer. It looks for `scnet-hpc` in the sibling
`../scnet-hpc` directory first, which matches a shared `skills/` tree; then it
falls back to `SCNET_HPC_ROOT` and agent-specific skill directories.

```bash
python3 contrib/run_openapi.py \
  --cluster <scnet-hpc-profile> \
  --profile clusters/<scnet-hpc-profile>.conf \
  --run-root /absolute/new/remote/run-root \
  --case ionpair_pme \
  --mode both \
  --download-dir ./out/gromacs-pme
```

`--mode both` submits one CPU job and one HIP job, waits for both, downloads
`result.txt`, version, checksum, energy and run logs, and applies
`compare_gromacs_energy.py`. `--mode cpu` (the default) or `--mode hip` runs one
backend.
The runner refuses an existing remote run root or local download directory.

Copy [clusters/_template.conf](clusters/_template.conf) to a private
`clusters/<profile>.conf` and set the CPU/DCU queue, CPU/HIP module, CPU count,
DCU count and walltime. The template is Z100/DCU-oriented; it is a hint, not
live availability evidence. Alternatively pass `--cpu-queue`, `--hip-queue`,
`--cpu-module`, `--hip-module`, `--cpus`, `--dcus` and `--walltime` directly.
The optional `GPU_ARCH` profile field is passed to the compute-node device check;
for Z100 set `GPU_ARCH="gfx906"`. `GROMACS_EXPECT_VERSION` pins the module
version for a reproducible run; update it when the site module changes.

The optional runner performs a read-only queue/walltime preflight and, on
failure, best-effort downloads application artifacts plus scheduler
stdout/stderr into the local download directory. Those logs stay outside the
repository and are for diagnosis only.

OpenAPI credentials are configured only through `scnet-hpc`; never put AK/SK,
private keys or site paths in this repository. If OpenAPI cannot expose a fact,
use SSH only for bounded diagnosis.

The smoke harness checks the GROMACS 2026.x completion message
`Writing final coordinates.` (and accepts the older `Finished mdrun` wording),
parses multi-column `energy.xvg` data, records input and final checksums, and
for PME mode requires the log line `PME tasks will do all aspects on the GPU`.
A scheduler `COMPLETED` state is not sufficient unless the workload also writes
`status=passed`.

## CPU/HIP energy comparison

Run the same case once in `cpu` mode and once in `hip` mode, then compare the
two run directories:

```bash
python3 scripts/compare_gromacs_energy.py CPU_RUN_DIR HIP_RUN_DIR \
  --report comparison.txt
```

The checker requires `status=passed` in both runs, identical input checksums,
the same time grid and the finite energy columns recorded by the smoke job.
PME runs include `Coulomb (SR)`, `Coul. recip.` and `LJ (SR)` in addition to
`Potential`, `Kinetic En.` and `Temperature`. It applies, per data point:

```text
|CPU - HIP| <= atol + rtol * max(|CPU|, |HIP|)
```

Defaults are `atol=0.05 kJ/mol` for energy terms, `atol=0.5 K` for temperature
and `rtol=1e-3`. These defaults are a smoke-level contract, not a production
accuracy specification. A pass is evidence of numerical consistency for this
tiny case, not a claim that CPU and GPU trajectories are bitwise identical.

## Multi-rank, multi-GPU and performance

The micro-cases exercise multi-rank and multi-GPU execution, not performance.
The optional runner supports `--mpi-ranks`, `--omp-threads`, `--mpi-launcher`,
`--npme` and `--force-gpu-aware`. The smoke script verifies the MPI process
count, PME rank decomposition when requested, selected GPU count and optional
forced GPU-aware MPI.

Performance characterization is separate. `benchmarks/catalog.json` is a
public catalog of benchmark classes and measurement fields; it is deliberately
not loaded as skill context and contains no committed performance values.
`benchmarks/observations.md` keeps short reference-site results separate. Use a
representative system for scaling claims.

Reference 2026.4 Lysozyme run, 71,844 atoms, 200 steps:

| Configuration | Performance |
| --- | ---: |
| 1 GPU | 29.0 ns/day |
| 2 GPUs | 27.3 ns/day |
| 4 GPUs, one node | 43.1 ns/day |
| 4 GPUs, two nodes | 43.5 ns/day |

Two GPUs were slower than one for this small system, and four GPUs were sublinear;
the measured reason is system size, decomposition/communication and PME overhead,
not lack of GPU support. A cross-node transport check with four ranks on two
nodes measured 41.3 ns/day with the working UCX HCA path, 32.0 ns/day with the
OB1/TCP fallback, and a default-UCX HCA failure before mdrun. OB1 is a fallback,
not a default. Forced GPU-aware MPI was unusably slow; do not enable it without
measurement.

A larger ADH benchmark, 134,177 atoms, 200 steps, measured 21.1 ns/day on one
GPU, 22.7 on two GPUs, 28.7 on four GPUs and 27.8 on two nodes/four GPUs. It
scales better than the tiny cases but remains sublinear; this is not a production
benchmark.

A ROCm-enabled UCX/OpenMPI build was also tested. GROMACS detected GPU-aware MPI
(`MPI library: MPI (GPU-aware: HIP)` and `GPU direct communication will be used`),
but the direct path was much slower than host-staged communication: about
1.7 ns/day for the two-node/four-GPU Lysozyme run and 0.97 ns/day for the
single-node/four-GPU run, versus 43.5/43.1 ns/day host-staged. A restricted
`UCX_TLS=rocm_ipc,sm,self,tcp` run reached 18.1 ns/day, still below host-staged.
The site's DTK/HIP/mlx5 path needs more UCX tuning before GPU-aware MPI is
useful; keep it disabled by default.

The checker needs the `inputs.sha256` file written by the current smoke script.
Runs from older script versions do not contain it.

## Measured scope on Kunshan

The reference environment was exercised on gfx906 with GROMACS 2026.3 and a
GROMACS 2026.4 reference build, OpenMPI 5.0.11, DTK 26.04, HIP 6.3.26113 and
rocFFT 1.0.28. Validated paths include single-rank CPU/HIP, PME GPU, two-rank
PME decomposition, two-rank/two-GPU HIP and PME, forced GPU-aware MPI on the
micro-case, PMPI single-rank plus multi-rank/multi-GPU, and two-node/four-GPU
runs.

The 2026.4 build came from the official source and was validated through a
private module path. It is not a site-published module and required local
toolchain compatibility work. A blank account must provide its own module or
build; the repository does not ship GROMACS. See
[references/version-coverage.md](references/version-coverage.md).

All normal smoke runs completed with `status=passed`; comparisons passed. These
are short, micro-case results and do not establish production accuracy. The
performance observations are separate reference-site measurements, not
production benchmarks or cross-site guarantees.

## DCU porting lessons retained

This is a mature application validation, not a new kernel port. The reusable
DCU lessons are still important: use the target node as the source of truth,
record the architecture (`gfx906` here), keep a CPU numerical oracle, separate
runtime/device checks from correctness, preserve finite/invariant checks, and
return nonzero workload and scheduler statuses on failures. Do not transfer
CUDA, ROCm or newer-GPU claims to DTK without a target probe.

## Local validation and host platforms

SCNet compute nodes are Linux; every submitted job runs Linux bash. The local
agent may be Windows, macOS or Linux:

- `contrib/run_openapi.py` and `scripts/compare_gromacs_energy.py` use Python
  3.8+ and are cross-platform.
- Remote paths are always POSIX. `--run-root` is normalized to POSIX even when
  the local shell is Windows; do not pass a Windows drive path as a remote path.
- The cross-platform validator is:
  ```bash
  python3 scripts/validate.py
  ```
- `bash scripts/validate.sh` is a thin wrapper. On Windows, use Git Bash or WSL
  if you want the optional `bash -n` syntax check; without bash, the Python
  validator skips that check and still validates the repository.

This checks scripts and bundled inputs only; it never compiles or runs GROMACS
locally.

MIT licensed.

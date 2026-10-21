# scnet-gromacs

English | [中文](README_CN.md)

Current release: 0.4.0

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
- scheduler completion and workload exit status.

The CPU run is the oracle. A GPU run is an integration and runtime check, not a
claim of bitwise equivalence or production performance. Floating-point
differences must be reported with tolerances and physical sanity checks.

The bundled cases are only smoke tests. They do not establish multi-node
scaling, PME decomposition behavior, GPU-aware MPI, PMPI variants or
production-size accuracy.

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
GROMACS_BINARY     binary name, default gmx_mpi
GROMACS_GPU_MODE   cpu or hip, default cpu
GROMACS_GPU_PME    1 to add -pme gpu, default 0; only for a PME-enabled case
GROMACS_EXPECT_GPU_ARCH  optional expected gfx name, e.g. gfx906
GROMACS_EXPECT_VERSION   optional expected GROMACS version, e.g. 2026.3
GROMACS_NPME       optional -npme value; only for a real multi-rank job
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
the job really has multiple ranks.

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
the same time grid and finite `Potential`, `Kinetic En.` and `Temperature`
columns. It applies, per data point:

```text
|CPU - HIP| <= atol + rtol * max(|CPU|, |HIP|)
```

Defaults are `atol=0.05 kJ/mol` for energy terms, `atol=0.5 K` for temperature
and `rtol=1e-3`. These defaults are a smoke-level contract, not a production
accuracy specification. A pass is evidence of numerical consistency for this
tiny case, not a claim that CPU and GPU trajectories are bitwise identical.

The checker needs the `inputs.sha256` file written by the current smoke script.
Runs from older script versions do not contain it.

## Measured scope on Kunshan

The installed Kunshan module was exercised on gfx906 with GROMACS 2026.3,
GCC 16.2, OpenMPI 5.0.11, DTK 26.04, HIP 6.3.26113 and rocFFT 1.0.28. Both the
Argon CPU/HIP smoke and the ion-pair PME CPU/HIP smoke completed with
`status=passed` and passed the tolerance checker. The PME run selected one GPU
and reported PME work on the GPU. The OpenAPI-first runner was also exercised
end to end on both cases, including remote upload, submission, wait, artifact
download and comparison. These are single-node, single-rank, 20-step smoke
results; they do not cover performance or larger systems.

## DCU porting lessons retained

This is a mature application validation, not a new kernel port. The reusable
DCU lessons are still important: use the target node as the source of truth,
record the architecture (`gfx906` here), keep a CPU numerical oracle, separate
runtime/device checks from correctness, preserve finite/invariant checks, and
return nonzero workload and scheduler statuses on failures. Do not transfer
CUDA, ROCm or newer-GPU claims to DTK without a target probe.

## Local validation

```bash
bash scripts/validate.sh
```

This checks scripts and bundled inputs only; it never compiles or runs GROMACS
locally.

MIT licensed.

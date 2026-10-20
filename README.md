# scnet-gromacs

English | [中文](README_CN.md)

Current release: 0.1.1

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
  case; add PME GPU options only when the system actually uses PME;
- finite energy output and a compact final-state checksum;
- scheduler completion and workload exit status.

The CPU run is the oracle. A GPU run is an integration and runtime check, not a
claim of bitwise equivalence or production performance. Floating-point
differences must be reported with tolerances and physical sanity checks.

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
GROMACS_RUN_ROOT   unique writable run root
```

Do not infer GPU support from a module name alone. The compute-node probe must
show visible devices and the binary must report HIP support.

The smoke harness checks the GROMACS 2026.x completion message
`Writing final coordinates.` (and accepts the older `Finished mdrun` wording),
parses multi-column `energy.xvg` data, and records a final checksum. A scheduler
`COMPLETED` state is not sufficient unless the workload also writes
`status=passed`.

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

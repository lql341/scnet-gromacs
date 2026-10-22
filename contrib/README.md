# Optional orchestration

The core validation path is the compute-node workflow:

- `scripts/gromacs_module_probe.sh`
- `scripts/gromacs_argon_smoke.sbatch`
- `scripts/compare_gromacs_energy.py`

You can drive those scripts with `scnet-hpc` OpenAPI, another scheduler client,
or an existing site workflow. They are the evidence-producing artifacts.

`run_openapi.py` is an optional convenience wrapper. It uses the embedded
OpenAPI adapter copied from the scnet-hashcat reference (derived from
scnet-hpc) to create a fresh remote directory, upload the scripts and case,
preflight the queue/walltime, submit CPU/HIP jobs, wait, check job details,
download artifacts and run the tolerance checker. On failure it best-effort
downloads available application artifacts and scheduler stdout/stderr into the
local download directory. It does not implement a separate transport or
credential stack, and does not require an installed scnet-hpc CLI.

It is deliberately outside `scripts/` so the core compute-node path stays small
and stable. If `scnet-hpc` changes its CLI, update this wrapper only; the
compute-node scripts and their evidence contract do not change.

The wrapper is Python 3.8+ standard library and runs on Windows, macOS or Linux.
Remote paths are POSIX; `--run-root` is normalized to POSIX even from a Windows
local shell. SCNet compute jobs themselves always run Linux bash.

The embedded adapter reads the shared credential store and environment
variables directly. `scnet-hpc` remains optional for first-use setup, SSH and
deployment. `scripts/vendor-manifest.json` records the adapter source and
checksums; `scripts/validate.py` verifies them.

The profile may select a site module, a private module path, or a user-owned
binary plus environment script. For multi-node runs it supports `NODES`,
`MPI_RANKS`, `MPI_RANKS_PER_NODE` and `SCHEDULER_OPTIONS`. Keep MPI transport/HCA
settings in the profile (`MPI_ENV_*`); they are site-specific.

# Optional orchestration

The core validation path is the compute-node workflow:

- `scripts/gromacs_module_probe.sh`
- `scripts/gromacs_argon_smoke.sbatch`
- `scripts/compare_gromacs_energy.py`

You can drive those scripts with `scnet-hpc` OpenAPI, another scheduler client,
or an existing site workflow. They are the evidence-producing artifacts.

`run_openapi.py` is an optional convenience wrapper. It calls the installed
`scnet-hpc` CLI with `--backend openapi` to create a fresh remote directory,
upload the scripts and case, submit CPU/HIP jobs, wait, check job details,
download artifacts and run the tolerance checker. It does not implement a
second transport or credential layer.

It is deliberately outside `scripts/` so the core compute-node path stays small
and stable. If `scnet-hpc` changes its CLI, update this wrapper only; the
compute-node scripts and their evidence contract do not change.

The wrapper looks for `scnet-hpc` in the sibling `../scnet-hpc` directory first,
then in `SCNET_HPC_ROOT`, `~/.codex/skills/scnet-hpc` and
`~/.claude/skills/scnet-hpc`. Pass `--scnet-hpc` to override the lookup.

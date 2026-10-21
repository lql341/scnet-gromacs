# GROMACS performance reference catalog

This directory is **not loaded as skill context** and is not part of the
correctness gate. Use it only when the task is performance characterization.

`catalog.json` lists public GROMACS benchmark classes and the measurement fields
to record. It intentionally contains no committed performance numbers: values
depend on the site, module build, topology, precision, GPU count and run length.
Confirm the exact upstream benchmark-suite revision before comparing runs.

Record target measurements in a private file outside the repository (for
example `benchmarks/measurements.local.json`) with these fields:

```text
case_id, gromacs_version, target, nodes, mpi_ranks, omp_threads,
gpus, walltime, ns_per_day, command, scope
```

Publish only a sanitized summary with versions, architecture, case, resource
tuple, measured value and untested boundaries. Do not publish node names, job
IDs, private paths or raw scheduler logs.

## Scope rules

- The bundled 8-atom and ion-pair cases validate execution and numerical
  consistency; they are not performance benchmarks.
- Multi-GPU performance requires a representative system and a stated baseline.
- If scaling is poor, state the measured reason (system size, communication,
  PME decomposition, GPU-aware MPI, load imbalance, I/O) instead of omitting it.
- A performance result does not extend to other systems, precisions or clusters.

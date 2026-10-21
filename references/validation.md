# GROMACS validation model

## Target facts

The current Kunshan module inventory includes GROMACS 2026.3 variants:

- `gromacs/2026.3` and `gromacs/2026.3-dtk26.04-z100` use self-built GCC
  16.2/OpenMPI 5.0.11 with DTK 26.04, HIP and rocFFT for gfx906.
- `gromacs/2026.3-pmpi` and its DTK/Z100 variant use platform OpenMPI 4.1.5.

The upstream documentation currently describes GROMACS 2026.4. This is a
patch-level difference; validate the existing 2026.3 binary before considering
a rebuild.

## Case contract

There are two bundled cases:

- `cases/argon8` is the deterministic no-charge CPU/HIP smoke. It fixes atom
  count, box, timestep and step count and uses `-nb gpu` in HIP mode.
- `cases/ionpair_pme` is a net-neutral eight-ion PME case. It uses
  `coulombtype = PME`, `-nb gpu -pme gpu` in HIP mode, and exists only to
  exercise the PME GPU path. It is not a performance or production-accuracy
  case.

The CPU run is the oracle. Record the exact `gmx_mpi --version`, command line,
resource tuple, scheduler state, exit code, input checksums, energy summary and
final checksum.

For HIP mode, record visible devices, `GMX_GPU`, HIP runtime and target
architecture. For the PME case, require the explicit log line
`PME tasks will do all aspects on the GPU`; a generic GPU/HIP mention is not
enough.

## CPU/HIP tolerance contract

Compare the two energy time series with
`scripts/compare_gromacs_energy.py`. Both runs must have `status=passed`, the
same `inputs.sha256` content and the same time grid. Apply per data point:

```text
|CPU - HIP| <= atol + rtol * max(|CPU|, |HIP|)
```

Defaults are `atol=0.05 kJ/mol` for `Potential` and `Kinetic En.`,
`atol=0.5 K` for `Temperature`, and `rtol=1e-3`. These values are a smoke-level
contract. A pass is not a bitwise-equality claim and does not extend to larger
systems, longer trajectories, other precisions or other architectures.

## Observed harness pitfalls

- GROMACS 2026.3 reports successful completion as `Writing final coordinates.`,
  so a checker that only searches for `Finished mdrun` can reject a successful
  run.
- `gmx energy` writes time plus one column per selected term. Check numeric
  fields on data rows rather than assuming a two-column file.
- Atom-name case mismatches can turn a warning into a fatal `grompp` failure;
  keep the `.gro` and topology names consistent.
- An MPI build rejects thread-MPI-only `-ntmpi` arguments. Use the MPI
  launcher/resource contract and `-ntomp` for this smoke.
- On a single MPI rank, `-pme gpu -npme 1` is a fatal request for a parallel
  simulation. Use `-pme gpu` without `-npme`; add `-npme` only when the job has
  multiple MPI ranks. The PME log line then distinguishes PP and PME GPU tasks.
- The installed HIP build can print a non-fatal `dummy_kernel` launch-bounds
  warning before mdrun. Judge success from the explicit device/PME selection,
  completion marker, finite energy values and `status=passed`, not from the
  absence of warnings.
- The CPU/HIP comparison is a tolerance check over a 21-frame, 20-step run.
  Do not turn a pass into a production accuracy or performance claim.

The measured Kunshan module observation is GROMACS 2026.3 with GCC 16.2,
OpenMPI 5.0.11, HIP/DTK 26.04, rocFFT 1.0.28 and gfx906. The upstream current
release is 2026.4, so this skill validates the installed 2026.3 module rather
than treating a patch-level difference as a rebuild requirement.

## DCU porting checklist

Apply the generic DCU principles even when validating a mature application:

- target-node probe before capability claims;
- explicit CPU oracle and tolerance contract;
- physical invariants and finite-value checks;
- separate host/device data movement and diagnostic traces;
- visible test registration and nonzero failure propagation;
- scheduler state plus workload exit status;
- record untested boundaries (multi-node scaling, PME decomposition,
  production-size systems, precision drift).

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

The bundled Argon case fixes atom count, box, timestep and step count. The CPU
run is the oracle. Record the exact `gmx_mpi --version`, command line, resource
tuple, scheduler state, exit code, energy summary and final checksum.

For HIP mode, record visible devices, `GMX_GPU`, HIP runtime and target
architecture. The bundled no-charge Argon case uses `-nb gpu`; forcing
`-pme gpu` on a system without PME electrostatics is a real GROMACS input
error. Add `-pme gpu -npme 1` only to a PME-enabled case. Do not claim
performance from a tiny case.

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

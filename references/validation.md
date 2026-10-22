# GROMACS validation model

## Target facts

The reference inventory follows one user-level module per application version:
`gromacs/2026.3-dtk26.04-z100` and `gromacs/2026.4-dtk26.04-z100`.
Backend, MPI and launcher variants are build/profile choices, not separate
module names. Legacy aliases may exist on a
site but are not part of the standard.

The canonical 2026.4 reference module uses the official 2026.4 source with
OpenMPI 5.0.11 + UCX + HIP and rocFFT for gfx906. PMPI is an optional
compatibility profile, not a module. The upstream documentation may describe a
newer release; validate the provided module before considering a rebuild.

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
final checksum. The smoke checker records the selected energy terms so that PME
runs include `Coulomb (SR)`, `Coul. recip.` and `LJ (SR)` in addition to the
global terms.

For HIP mode, record visible devices, `GMX_GPU`, HIP runtime and target
architecture. An optional `GROMACS_EXPECT_GPU_ARCH` (for example `gfx906` on
Z100) makes the smoke fail when `rocminfo` does not show that architecture. For
the PME case, require the explicit log line
`PME tasks will do all aspects on the GPU`; a generic GPU/HIP mention is not
enough.

## OpenAPI execution path

`contrib/run_openapi.py` is optional orchestration over the core compute-node
scripts. It uses the embedded OpenAPI adapter (the scnet-hashcat reference,
derived from scnet-hpc) for remote mkdir, upload, submit, bounded wait, detailed
job check and explicit artifact download. It does not use SSH, and it refuses to
reuse an existing remote run root or local download directory. `scnet-hpc` is
optional for first-use setup, SSH and deployment, not a runtime skill dependency.

The runner reads a private profile copied from `clusters/_template.conf` or
accepts explicit queue/module/resource arguments. A profile `GPU_ARCH` value is
passed to the HIP job as an optional architecture gate; it does not replace the
actual device probe. For Hygon Z100 it passes the
DCU count to OpenAPI only for the HIP job; the actual node probe still decides
whether gfx906 is visible and whether PP/PME work runs on the device. A profile
is a site hint, not live evidence.

`--mode both` submits CPU and HIP, downloads both result sets and runs the
tolerance checker. The scheduler state, platform exit status and workload
`status=passed` are still checked separately.

For the 2026.4 PMPI compatibility profile, validation covered single-rank CPU/HIP,
two-rank CPU PME, two-GPU PME and two-node/four-rank/four-GPU execution with
`mpirun` plus OB1 launcher arguments. PMPI multi-node also needed a hostfile and
explicit `ib0` TCP/OOB interface selection. A larger 134,177-atom ADH reference
run is recorded in the performance observations; it scales better than the tiny
cases but remains sublinear and is not a production benchmark.

## Blank-account baseline

Do not assume the maintainer's modules, prefixes or modulefiles. A blank SCNet
account must provide a site module or a user-owned build through
`GROMACS_MODULE`, `GROMACS_MODULEPATH`, `GROMACS_BINARY` and/or
`GROMACS_ENV_SCRIPT`. The probe and version gate run before any capability claim.
Coverage declared in [version-coverage.md](version-coverage.md) is evidence from
the reference environment, not a bundled dependency.

SCNet compute nodes are Linux. The local agent may be Windows, macOS or Linux.
Keep remote paths POSIX, even when the local shell is Windows. The Python
orchestration/comparison scripts are cross-platform; use `python3 scripts/validate.py`
for local checks. `bash -n` syntax checking is optional and requires bash
(Git Bash/WSL on Windows).

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

## Adapting to a new GROMACS version

Treat a new module as a new target, not a drop-in replacement:

1. Probe the module on a compute node and record `gmx_mpi --version`, compiler,
   MPI, HIP/DTK, rocFFT, GPU support and architecture.
2. Set `GROMACS_EXPECT_VERSION` in the private profile to the intended version.
   The smoke job writes `status=failed_version` and exits nonzero if the loaded
   binary differs. For a candidate build, point `GROMACS_MODULEPATH` at a private
   modulefile directory; do not modify site modules.
3. Re-run the Argon CPU and HIP cases. Check the completion marker, GPU
   selection, finite energies and scheduler/workload status. If a log marker
   changed, update the checker from observed evidence rather than guessing.
4. Re-run the PME case. Confirm that PME work is still executed on the GPU and
   that the single-rank `-pme gpu`/`-npme` behavior is unchanged. If the new
   version rejects or changes an option, record the exact fatal message and
   update the case or documented scope.
5. Re-baseline the CPU/HIP tolerance only with measured values and a written
   rationale. Keep the old profile/evidence until the new run passes.
6. Update the profile module id, expected version, CHANGELOG and measured-scope
   notes. Do not silently widen tolerances or claim support from a version
   string alone.

A 2026.4 reference build from the official source was validated through a private
module path on Argon and PME CPU/HIP, two-node/four-GPU execution and the version
gate. It is not a site module and is not evidence that a blank account has it.
Candidate builds may need local toolchain compatibility work; keep that work
private and do not commit site paths or build logs.

On this DTK 26.04 site, the 2026.4 build used GCC 13.3 as the HIP host toolchain;
GCC 16.2 with the DTK Clang 17 HIP compiler hit a libstdc++ header
incompatibility. CMake 4.4.3 also needed a toolchain file to propagate the
`amd_comgr`/HSA paths into the HIP try-compile. Treat these as build-environment
findings, not as module-validation results.

The bundled `.gro`, topology and `md.mdp` are intentionally minimal. If a new
release deprecates an mdp option, `grompp` is the authority; change the case
only with a recorded before/after result.

## Multi-rank, multi-GPU and PMPI

Multi-rank execution is explicit: MPI rank count, OpenMP threads per rank,
launcher and optional separate PME rank count are recorded. A PME case with more
than one rank uses `-npme 1` and the detailed log must show the separate PME rank.
HIP validation uses one DCU per rank; the log must show the requested selected
GPU count. None of these facts is inferred from the requested allocation.

Observed on Kunshan:

- the self-built OpenMPI 5 module connected ranks with `mpirun`; `srun` in that
  environment launched singleton ranks for GROMACS;
- HCOLL can fail in handler setup on the ROCm/UCX path; keep it disabled for
  GROMACS multi-rank (`OMPI_MCA_coll=^hcoll`). The reference OpenMPI 5 module
  already sets this.
- the PMPI module's platform OpenMPI 4.1.5 is not Slurm-PMI enabled. Its
  multi-rank path needed `mpirun` plus an MPI transport override. The reliable
  form was launcher arguments (`--mca pml ob1 --mca btl self,vader,tcp`), not
  only an environment variable. Cross-node PMPI also needed a hostfile and
  `--mca btl_tcp_if_include ib0 --mca oob_tcp_if_include ib0`; otherwise it
  tried the management network and hung. PMPI/OB1 multi-node measured 21.4
  ns/day versus 41.3 ns/day for the OpenMPI 5 UCX path on the same 200-step
  Lysozyme run;
- forced GPU-aware MPI completed on the two-rank/two-GPU micro-case, but that is
  not evidence of GPU-aware performance or correctness at scale. On a short
  71,844-atom Lysozyme run, forced GPU-aware MPI was much slower than the default
  path; measure before enabling it. The default reference UCX build is configured
  without ROCm, so GPU-aware MPI is unavailable there.
- a ROCm-enabled UCX/OpenMPI build was also tested. GROMACS reported
  `MPI (GPU-aware: HIP)` and used direct GPU communication, but performance was
  far below host-staged (about 1.7 ns/day cross-node and 0.97 ns/day single-node,
  versus 43.5/43.1 ns/day). A restricted `UCX_TLS=rocm_ipc,sm,self,tcp` run
  reached 18.1 ns/day, still below host staging. The larger 134,177-atom ADH
  case was also about 50x slower with GPU-aware communication (0.57 versus 28.7
  ns/day), so the problem is not only small system size. Keep GPU-aware MPI off
  by default until the ROCm/UCX/mlx5 path is tuned.
- on this reference cluster, multi-node OpenMPI 5 needed `srun` with
  `SLURM_MPI_TYPE=pmix`, and the allocation had to be balanced with
  `#SBATCH --ntasks-per-node=...`. Without balance, ranks concentrated on one
  node and GROMACS failed its GPU task assignment.
- default UCX selected a non-working HCA on the cross-node path
  (`ibv_create_ah`/invalid argument). Restricting `UCX_NET_DEVICES` to the working
  HCA made UCX pass and outperform OB1/TCP. OB1 is a fallback, not a universal
  best practice; keep the transport/HCA choice site-configurable.

These are site observations. Record the launcher, MPI transport and exact rank
topology with any multi-rank result.

## Performance reference

`benchmarks/catalog.json` is a public catalog of benchmark classes and
measurement fields. It is not loaded as skill context and contains no committed
performance values. Performance work requires a representative system, a stated
baseline and an explanation when multi-GPU scaling is poor. The bundled micro
cases validate execution and numerical consistency only.

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
than treating a patch-level difference as a rebuild requirement. The
OpenAPI-first runner was exercised end to end on the Argon and PME cases, with
CPU/HIP comparisons passing on separate scheduler jobs.

## DCU porting checklist

Apply the generic DCU principles even when validating a mature application:

- target-node probe before capability claims;
- explicit CPU oracle and tolerance contract;
- physical invariants and finite-value checks;
- separate host/device data movement and diagnostic traces;
- visible test registration and nonzero failure propagation;
- scheduler state plus workload exit status;
- record untested boundaries (larger multi-node scaling, production-size
  systems, precision drift, other fabrics and account baselines, GPU-aware
  production performance).

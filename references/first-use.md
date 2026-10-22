# First use

This skill can be used offline for input checks, but a real SCNet job requires
account activation, credentials and a prepared GROMACS module.

## 1. Account and resources

- A SCNet account alone is not enough: the target region and queue must be
  enabled for the account. AK/SK does not activate compute resources.
- New users should read the SCNet beginner guide linked from
  `scnet-hpc/references/first-use.md`.
- Obtain OpenAPI AK/SK from **个人中心 → 访问控制**. Use the HPC OpenAPI
  authorization file, not a model-service API key.
- SSH credentials are separate and are needed only for SSH deployment or
  diagnosis; the normal OpenAPI path does not use SSH.

## 2. Credentials without sharing secrets

Use one of:

```text
SCNET_OPENAPI_USER
SCNET_OPENAPI_ACCESS_KEY
SCNET_OPENAPI_SECRET_KEY
```

or the shared `scnet-hpc-openapi` OS credential store. If `scnet-hpc` is
installed, run in your own terminal:

```bash
python3 "<scnet-hpc>/scripts/scnet.py" setup new --mode openapi
python3 "<scnet-hpc>/scripts/scnet.py" setup status
```

Never send AK/SK, private keys or credential files to the agent/chat, and never
write them into `clusters/*.conf`.

## 3. Local readiness

```bash
python3 scripts/doctor.py
python3 scripts/doctor.py --require-openapi   # nonzero unless runner is ready
python3 scripts/doctor.py --online --cluster <profile>   # scnet-hpc read-only doctor
```

`doctor.py` never reads secret values or submits jobs. `--online` delegates only
to the read-only `scnet-hpc doctor`.

## 4. GROMACS module

- Set `GROMACS_MODULE` (one module per version and target) or:
  ```text
  GROMACS_MODULE=""
  GROMACS_BINARY=/absolute/path/to/gmx_mpi
  GROMACS_ENV_SCRIPT=/absolute/path/to/env.sh
  ```
- Module deployment is separate from account activation. Selecting a queue does
  not prove the module or DCU runtime is deployed.
- Run `scripts/gromacs_module_probe.sh` on an allocated compute node before a
  real validation.

## 5. First job

- `contrib/run_openapi.py` is optional and calls an installed `scnet-hpc` CLI.
  Users load only `scnet-gromacs`; `scnet-hpc` is not a second skill to load.
- If `scnet-hpc` is unavailable, drive the core scripts with the site's scheduler
  client or install the CLI.
- Start with a CPU smoke, then HIP/PME, then multi-rank. Do not submit a large or
  multi-node job until the first-use checks and module probe pass.

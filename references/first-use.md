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
# Preferred: use the same profile as the runner.
python3 scripts/doctor.py --profile clusters/<profile>.conf --json

# Explicit values without a profile.
python3 scripts/doctor.py --region <region> --cpu-queue <queue> --json

# Fail unless credentials and local region/queue configuration are present.
python3 scripts/doctor.py --profile clusters/<profile>.conf --require-openapi

# Optional online check; requires scnet-hpc >=0.6.15 so the selected region
# and queues are passed to the read-only doctor.
python3 scripts/doctor.py --profile clusters/<profile>.conf --online --cluster <hpc-profile> --json

# Offline plan; no client, credentials or remote calls.
python3 contrib/run_openapi.py --profile clusters/<profile>.conf \
  --run-root /absolute/new/remote/run-root --case argon8 --mode cpu --dry-run
```

`doctor.py` never reads secret values or submits jobs. It reports three separate
states:

- `credentials`: present or missing;
- `configuration`: region and CPU/DCU queue declared or incomplete;
- `remote`: `unknown` offline, `verified` only after a successful `--online`
  read-only `scnet-hpc doctor`.

`openapi_ready` and `--require-openapi` cover local prerequisites only. They do
not prove account activation, module deployment or device availability.

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

- `contrib/run_openapi.py` is optional and uses the embedded OpenAPI adapter.
  Users load only `scnet-gromacs`; `scnet-hpc` is optional for setup/SSH and is
  not a second skill to load. A named `--cluster` profile must exist; the runner
  never silently falls back to a shared default region.
- If `scnet-hpc` is unavailable, the embedded adapter still supports normal
  OpenAPI runs; the core scripts can also be driven by a site scheduler client.
- Start with a CPU smoke, then HIP/PME, then multi-rank. Do not submit a large or
  multi-node job until the first-use checks and module probe pass.

#!/usr/bin/env python3
"""Read-only local readiness check for the optional OpenAPI runner.

It does not authenticate, contact SCNet, read secret values, or submit a job.
Use --online to delegate the authenticated read-only check to scnet-hpc.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
ENV_KEYS = (
    "SCNET_OPENAPI_USER",
    "SCNET_OPENAPI_ACCESS_KEY",
    "SCNET_OPENAPI_SECRET_KEY",
)


def find_scnet_hpc(explicit=None):
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if os.environ.get("SCNET_HPC_ROOT"):
        candidates.append(Path(os.environ["SCNET_HPC_ROOT"]).expanduser())
    candidates.extend(
        [
            ROOT.parent / "scnet-hpc",
            Path.home() / ".codex" / "skills" / "scnet-hpc",
            Path.home() / ".claude" / "skills" / "scnet-hpc",
            Path.home() / ".agents" / "skills" / "scnet-hpc",
        ]
    )
    for candidate in candidates:
        if candidate.is_file() and candidate.name == "scnet.py":
            return candidate
        cli = candidate / "scripts" / "scnet.py"
        if cli.is_file():
            return cli
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scnet-hpc", help="scnet-hpc root or scnet.py")
    parser.add_argument("--cluster", help="scnet-hpc profile name for --online")
    parser.add_argument("--online", action="store_true", help="run scnet-hpc doctor")
    parser.add_argument(
        "--require-openapi",
        action="store_true",
        help="exit nonzero unless the local OpenAPI runner prerequisites are ready",
    )
    args = parser.parse_args(argv)

    print("python={}.{}.{}".format(*sys.version_info[:3]))
    cli = find_scnet_hpc(args.scnet_hpc)
    if cli:
        print("scnet_hpc=found: {}".format(cli))
        try:
            version = subprocess.run(
                [sys.executable, str(cli), "--version"],
                text=True,
                capture_output=True,
                timeout=20,
            )
            if version.returncode == 0:
                print("scnet_hpc_version={}".format(version.stdout.strip()))
        except (OSError, subprocess.TimeoutExpired):
            print("scnet_hpc_version=unavailable")
    else:
        print("scnet_hpc=not_found")

    present = [key for key in ENV_KEYS if os.environ.get(key)]
    if len(present) == len(ENV_KEYS):
        print("credentials_env=complete")
    elif present:
        print("credentials_env=incomplete: {}".format(", ".join(present)))
    else:
        print("credentials_env=not_set")

    shared = "unknown"
    if cli:
        try:
            status = subprocess.run(
                [sys.executable, str(cli), "setup", "status"],
                text=True,
                capture_output=True,
                timeout=30,
            )
            text = (status.stdout or "") + (status.stderr or "")
            lower = text.lower()
            configured = (
                status.returncode == 0
                and ("实际凭据来源" in text or "credential source" in lower)
                and "未配置" not in text
                and "not configured" not in lower
            )
            if configured:
                shared = "configured"
        except (OSError, subprocess.TimeoutExpired):
            pass
    print("credentials_shared_store={}".format(shared))

    module = os.environ.get("GROMACS_MODULE", "gromacs/2026.3-dtk26.04-z100")
    print("gromacs_module={}".format(module or "(empty: user binary mode)"))
    print("gromacs_binary={}".format(os.environ.get("GROMACS_BINARY", "gmx_mpi")))
    if os.environ.get("GROMACS_ENV_SCRIPT"):
        print("gromacs_env_script={}".format(os.environ["GROMACS_ENV_SCRIPT"]))

    if len(present) == len(ENV_KEYS) or shared == "configured":
        ready = "ready"
    elif cli is not None:
        ready = "unknown"
    else:
        ready = "not_ready"
    print("openapi_local_prerequisites={}".format(ready))
    print("first_use=references/first-use.md")

    if ready != "ready":
        print("next:")
        if cli is None:
            print("  install scnet-hpc or set SCNET_HPC_ROOT")
        if len(present) != len(ENV_KEYS) and shared != "configured":
            print("  configure credentials in your own terminal:")
            print("    <scnet-hpc>/scripts/scnet.py setup new --mode openapi")
            print("  or export SCNET_OPENAPI_USER/ACCESS_KEY/SECRET_KEY")
        if cli is not None and shared == "unknown":
            print("  run: <scnet-hpc>/scripts/scnet.py setup status")
        print("  activate the SCNet region/queue; AK/SK alone does not activate resources")
        print("  deploy or select the GROMACS module before submitting a job")

    if args.online:
        if cli is None:
            print("online=skipped: scnet-hpc not found", file=sys.stderr)
            return 2
        command = [sys.executable, str(cli), "--backend", "openapi"]
        if args.cluster:
            command.extend(["--cluster", args.cluster])
        command.append("doctor")
        completed = subprocess.run(command, text=True)
        return completed.returncode

    return 2 if args.require_openapi and ready != "ready" else 0


if __name__ == "__main__":
    sys.exit(main())

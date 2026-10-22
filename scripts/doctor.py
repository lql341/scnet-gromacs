#!/usr/bin/env python3
"""Read-only local readiness check for first use.

It does not authenticate, submit a job or print secret values. It inspects only
local configuration/credential presence. Use --online to delegate the
authenticated read-only check to scnet-hpc.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from scnet_credentials import CredentialError, load_openapi_credentials

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


def probe(explicit=None):
    status = {
        "python": "{}.{}.{}".format(*sys.version_info[:3]),
        "scnet_hpc": {"found": False, "path": None, "version": None},
        "credentials": {
            "source": "missing",
            "env_keys_present": [],
            "store_error": None,
        },
        "gromacs": {
            "module": os.environ.get(
                "GROMACS_MODULE", "gromacs/2026.3-dtk26.04-z100"
            ),
            "binary": os.environ.get("GROMACS_BINARY", "gmx_mpi"),
            "env_script": os.environ.get("GROMACS_ENV_SCRIPT"),
        },
        "first_use": "references/first-use.md",
        "next_steps": [],
    }

    cli = find_scnet_hpc(explicit)
    if cli:
        status["scnet_hpc"]["found"] = True
        status["scnet_hpc"]["path"] = str(cli)
        try:
            version = subprocess.run(
                [sys.executable, str(cli), "--version"],
                text=True,
                capture_output=True,
                timeout=20,
            )
            if version.returncode == 0:
                status["scnet_hpc"]["version"] = version.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass

    present = [key for key in ENV_KEYS if os.environ.get(key)]
    status["credentials"]["env_keys_present"] = present
    if len(present) == len(ENV_KEYS):
        status["credentials"]["source"] = "environment"
    else:
        try:
            credentials, _ = load_openapi_credentials()
        except CredentialError as exc:
            status["credentials"]["store_error"] = str(exc)
            credentials = None
        if credentials:
            status["credentials"]["source"] = "shared_store"

    ready = status["credentials"]["source"] != "missing"
    status["openapi_ready"] = ready
    if not ready:
        if not status["scnet_hpc"]["found"]:
            status["next_steps"].append(
                "install scnet-hpc or set SCNET_HPC_ROOT for first-use setup/SSH"
            )
        status["next_steps"].extend(
            [
                "configure credentials in your own terminal: "
                "<scnet-hpc>/scripts/scnet.py setup new --mode openapi",
                "or export SCNET_OPENAPI_USER/ACCESS_KEY/SECRET_KEY",
                "activate the SCNet region/queue; AK/SK alone does not activate resources",
                "deploy or select the GROMACS module before submitting a job",
            ]
        )
    elif not status["scnet_hpc"]["found"]:
        status["next_steps"].append(
            "scnet-hpc is not installed; scnet-hpc is optional for first-use setup/SSH"
        )
    return status


def render(status):
    lines = [
        "python={}".format(status["python"]),
        "scnet_hpc={}: {}".format(
            "found" if status["scnet_hpc"]["found"] else "not_found",
            status["scnet_hpc"]["path"] or "(optional)",
        ),
    ]
    if status["scnet_hpc"]["version"]:
        lines.append("scnet_hpc_version={}".format(status["scnet_hpc"]["version"]))
    lines.extend(
        [
            "credentials_env={}".format(
                "complete"
                if len(status["credentials"]["env_keys_present"])
                == len(ENV_KEYS)
                else (
                    "incomplete: "
                    + ", ".join(status["credentials"]["env_keys_present"])
                    if status["credentials"]["env_keys_present"]
                    else "not_set"
                )
            ),
            "credentials_source={}".format(status["credentials"]["source"]),
            "gromacs_module={}".format(status["gromacs"]["module"]),
            "gromacs_binary={}".format(status["gromacs"]["binary"]),
            "openapi_local_prerequisites={}".format(
                "ready" if status["openapi_ready"] else "not_ready"
            ),
            "first_use={}".format(status["first_use"]),
        ]
    )
    if status["gromacs"]["env_script"]:
        lines.append("gromacs_env_script={}".format(status["gromacs"]["env_script"]))
    if status["next_steps"]:
        lines.append("next:")
        lines.extend("  " + step for step in status["next_steps"])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scnet-hpc", help="scnet-hpc root or scnet.py")
    parser.add_argument("--cluster", help="scnet-hpc profile name for --online")
    parser.add_argument("--online", action="store_true", help="run scnet-hpc doctor")
    parser.add_argument("--json", action="store_true", help="emit machine-readable status")
    parser.add_argument(
        "--require-openapi",
        action="store_true",
        help="exit nonzero unless the local OpenAPI runner prerequisites are ready",
    )
    args = parser.parse_args(argv)

    status = probe(args.scnet_hpc)
    if args.json:
        print(json.dumps(status, indent=2, ensure_ascii=False))
    else:
        print(render(status))

    if args.online:
        if not status["scnet_hpc"]["found"]:
            print("online=skipped: scnet-hpc not found", file=sys.stderr)
            return 2
        command = [
            sys.executable,
            status["scnet_hpc"]["path"],
            "--backend",
            "openapi",
        ]
        if args.cluster:
            command.extend(["--cluster", args.cluster])
        command.append("doctor")
        return subprocess.run(command, text=True).returncode

    return 2 if args.require_openapi and not status["openapi_ready"] else 0


if __name__ == "__main__":
    sys.exit(main())

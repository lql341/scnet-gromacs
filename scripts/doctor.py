#!/usr/bin/env python3
"""Read-only local readiness check for first use.

It does not authenticate, submit a job or print secret values. It inspects only
local configuration/credential presence. Use --online to delegate the
authenticated read-only check to scnet-hpc and merge its result into one JSON
envelope.
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
from gromacs_profile import (
    ProfileError,
    load_profile,
    resolve_profile,
    resolve_settings,
)
from scnet_credentials import CredentialError, load_openapi_credentials

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1
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


def _profile_config(args):
    config = {
        "source": "none",
        "profile": None,
        "profile_error": None,
    }
    try:
        path = resolve_profile(
            ROOT,
            cluster=args.cluster,
            explicit=args.profile,
            env=os.environ.get("GROMACS_PROFILE"),
        )
        config["profile"] = str(path) if path else None
        if path:
            config["source"] = "profile"
            config.update(load_profile(path))
    except ProfileError as exc:
        config["profile_error"] = str(exc)
    return config


def _configuration(args):
    profile = _profile_config(args)
    settings = resolve_settings(args, profile)
    region = settings["region"]
    cpu_queue = settings["cpu_queue"]
    hip_queue = settings["hip_queue"]
    cpu_module = settings["cpu_module"]
    hip_module = settings["hip_module"]
    if cpu_module:
        module = cpu_module
        module_status = "declared"
    elif hip_module:
        module = hip_module
        module_status = "declared"
    else:
        module = "gromacs/2026.3-dtk26.04-z100"
        module_status = "default_unverified"
    binary = settings["binary"]
    if not binary:
        binary = "gmx_mpi"
        binary_status = "default_unverified"
    else:
        binary_status = "declared"
    ready = bool(
        region and (cpu_queue or hip_queue) and not profile["profile_error"]
    )
    return {
        "source": profile["source"],
        "profile": profile["profile"],
        "profile_error": profile["profile_error"],
        "region": region,
        "cpu_queue": cpu_queue,
        "hip_queue": hip_queue,
        "module": module,
        "cpu_module": cpu_module,
        "hip_module": hip_module,
        "module_status": module_status,
        "binary": binary,
        "binary_status": binary_status,
        "env_script": settings["env_script"],
        "ready": ready,
    }


def _credentials():
    status = {
        "present": False,
        "source": "missing",
        "env_keys_present": [],
        "store_error": None,
    }
    present = [key for key in ENV_KEYS if os.environ.get(key)]
    status["env_keys_present"] = present
    if len(present) == len(ENV_KEYS):
        status["present"] = True
        status["source"] = "environment"
        return status
    try:
        credentials, _ = load_openapi_credentials()
    except CredentialError as exc:
        status["store_error"] = str(exc)
        return status
    if credentials:
        status["present"] = True
        status["source"] = "shared_store"
    return status


def _next_steps(credentials, configuration, scnet_hpc_found):
    if not credentials["present"]:
        return "credentials", [
            "configure OpenAPI credentials in your own terminal: "
            "<scnet-hpc>/scripts/scnet.py setup new --mode openapi, or export "
            "SCNET_OPENAPI_USER/ACCESS_KEY/SECRET_KEY"
        ]
    if not configuration["ready"]:
        return "configuration", [
            "set OPENAPI_REGION_ID and CPU_PARTITION/DCU_PARTITION in a private "
            "profile and pass --profile, or pass --region and --cpu-queue/--hip-queue"
        ]
    if not scnet_hpc_found:
        return None, [
            "scnet-hpc is optional for first-use setup/SSH; "
            "pass --online when it is available to verify the remote account"
        ]
    return None, [
        "local prerequisites are ready; run --online to verify the remote "
        "account, region and queue before submitting"
    ]


def probe(explicit=None, args=None):
    args = args or argparse.Namespace(
        profile=None, cluster=None, region=None, cpu_queue=None, hip_queue=None
    )
    status = {
        "schema_version": SCHEMA_VERSION,
        "python": "{}.{}.{}".format(*sys.version_info[:3]),
        "scnet_hpc": {"found": False, "path": None, "version": None},
        "credentials": _credentials(),
        "configuration": _configuration(args),
        "readiness": {
            "credentials": "missing",
            "configuration": "incomplete",
            "remote": "unknown",
        },
        "openapi_ready": False,
        "primary_blocker": None,
        "next_steps": [],
        "first_use": "references/first-use.md",
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

    credentials = status["credentials"]
    configuration = status["configuration"]
    status["readiness"]["credentials"] = (
        "ready" if credentials["present"] else "missing"
    )
    status["readiness"]["configuration"] = (
        "ready" if configuration["ready"] else "incomplete"
    )
    status["openapi_ready"] = bool(
        credentials["present"] and configuration["ready"]
    )
    blocker, steps = _next_steps(
        credentials, configuration, status["scnet_hpc"]["found"]
    )
    status["primary_blocker"] = blocker
    status["next_steps"] = steps
    return status


def render(status):
    configuration = status["configuration"]
    lines = [
        "schema_version={}".format(status["schema_version"]),
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
            "credentials={} source={}".format(
                "ready" if status["credentials"]["present"] else "missing",
                status["credentials"]["source"],
            ),
            "configuration={} source={} region={} cpu_queue={} hip_queue={}".format(
                "ready" if configuration["ready"] else "incomplete",
                configuration["source"],
                configuration["region"] or "(unset)",
                configuration["cpu_queue"] or "(unset)",
                configuration["hip_queue"] or "(unset)",
            ),
            "gromacs_module={} ({})".format(
                configuration["module"], configuration["module_status"]
            ),
            "gromacs_binary={} ({})".format(
                configuration["binary"], configuration["binary_status"]
            ),
            "readiness_remote={}".format(status["readiness"]["remote"]),
            "openapi_local_prerequisites={}".format(
                "ready" if status["openapi_ready"] else "not_ready"
            ),
        ]
    )
    if configuration["profile"]:
        lines.append("profile={}".format(configuration["profile"]))
    if configuration["profile_error"]:
        lines.append("profile_error={}".format(configuration["profile_error"]))
    if configuration["env_script"]:
        lines.append("gromacs_env_script={}".format(configuration["env_script"]))
    if status["primary_blocker"]:
        lines.append("primary_blocker={}".format(status["primary_blocker"]))
    if status["next_steps"]:
        lines.append("next:")
        lines.extend("  " + step for step in status["next_steps"])
    return "\n".join(lines)


def _online_status(status, explicit, cluster):
    if not status["scnet_hpc"]["found"]:
        return {"ok": False, "error": "scnet-hpc not found"}, 2
    configuration = status["configuration"]
    region = configuration.get("region")
    queues = []
    for value in (configuration.get("cpu_queue"), configuration.get("hip_queue")):
        if value and value not in queues:
            queues.append(str(value))
    if not region:
        return {"ok": False, "error": "no resolved OpenAPI region"}, 2
    if not queues:
        return {"ok": False, "error": "no resolved CPU/DCU queue"}, 2
    command = [
        sys.executable,
        status["scnet_hpc"]["path"],
        "--backend",
        "openapi",
        "--region",
        str(region),
    ]
    if cluster:
        command.extend(["--cluster", cluster])
    for queue in queues:
        command.extend(["--queue", queue])
    command.extend(["--json", "doctor"])
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}, 2
    try:
        payload = json.loads(completed.stdout)
    except ValueError:
        return {
            "ok": False,
            "error": "scnet-hpc doctor did not return JSON",
            "returncode": completed.returncode,
        }, (completed.returncode or 2)
    data = payload.get("data")
    if not isinstance(data, dict):
        return {
            "ok": False,
            "error": "scnet-hpc doctor response has no data object",
            "returncode": completed.returncode,
        }, (completed.returncode or 2)
    checks = data.get("checks")
    if (
        not isinstance(checks, list)
        or not checks
        or not all(
            isinstance(item, dict)
            and "name" in item
            and isinstance(item.get("ok"), bool)
            for item in checks
        )
    ):
        return {
            "ok": False,
            "error": "scnet-hpc doctor checks are malformed",
            "returncode": completed.returncode,
        }, (completed.returncode or 2)
    healthy = (
        completed.returncode == 0
        and payload.get("ok") is True
        and data.get("ok") is True
    )
    online = {
        "ok": healthy,
        "returncode": completed.returncode,
        "region": str(region),
        "queues": queues,
        "checks": [
            {"name": item.get("name"), "ok": bool(item.get("ok"))}
            for item in checks
        ],
    }
    if not healthy:
        online["error"] = (
            "scnet-hpc doctor reported unhealthy state"
            if completed.returncode == 0
            else "scnet-hpc doctor exited nonzero"
        )
    return online, (0 if healthy else (completed.returncode or 2))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scnet-hpc", help="scnet-hpc root or scnet.py")
    parser.add_argument("--profile", type=Path, help="local GROMACS profile")
    parser.add_argument("--cluster", help="local profile name; also used by --online")
    parser.add_argument("--region", help="explicit OpenAPI region")
    parser.add_argument("--cpu-queue", help="explicit CPU queue")
    parser.add_argument("--hip-queue", help="explicit DCU/HIP queue")
    parser.add_argument("--online", action="store_true", help="run scnet-hpc doctor")
    parser.add_argument("--json", action="store_true", help="emit machine-readable status")
    parser.add_argument(
        "--require-openapi",
        action="store_true",
        help="exit nonzero unless local OpenAPI prerequisites are ready",
    )
    args = parser.parse_args(argv)

    status = probe(args.scnet_hpc, args)
    online = None
    online_rc = 0
    if args.online:
        online, online_rc = _online_status(status, args.scnet_hpc, args.cluster)
        status["online"] = online
        if online.get("ok"):
            status["readiness"]["remote"] = "verified"
        elif online.get("returncode") is not None:
            status["readiness"]["remote"] = "failed"
        else:
            status["readiness"]["remote"] = "unknown"

    if args.json:
        print(json.dumps(status, indent=2, ensure_ascii=False))
    else:
        print(render(status))
        if online is not None:
            print(
                "online={} ({})".format(
                    "ok" if online.get("ok") else "failed",
                    online.get("error") or "scnet-hpc doctor",
                )
            )

    if args.online and not online.get("ok"):
        return online_rc or 2
    return 2 if args.require_openapi and not status["openapi_ready"] else 0


if __name__ == "__main__":
    sys.exit(main())

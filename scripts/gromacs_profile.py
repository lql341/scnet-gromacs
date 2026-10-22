#!/usr/bin/env python3
"""Shared GROMACS cluster-profile parsing and lookup.

The profile is a shell-like key=value file.  It is intentionally not executed,
so a profile can be reviewed without running site-specific code.
"""
from pathlib import Path
import shlex


class ProfileError(Exception):
    """A requested profile is missing or unreadable."""


def load_profile(path):
    values = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ProfileError("cannot read profile {}: {}".format(path, exc)) from exc
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        key = key.strip()
        try:
            parts = shlex.split(raw_value, comments=True, posix=True)
        except ValueError:
            continue
        if not key or not parts:
            continue
        values[key] = " ".join(parts)
    return values


def resolve_profile(root, cluster=None, explicit=None, env=None):
    """Return a profile path, or None when no explicit profile was requested.

    A named cluster that does not resolve to ``clusters/<name>.conf`` is an
    error, never a silent fallback to a shared default region.
    """
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ProfileError("profile not found: {}".format(path))
        return path
    if cluster:
        path = Path(root) / "clusters" / "{}.conf".format(cluster)
        if not path.is_file():
            raise ProfileError(
                "cluster profile not found: {}; pass --profile, --region, "
                "or create clusters/{}.conf".format(path, cluster)
            )
        return path
    if env:
        path = Path(env).expanduser()
        if not path.is_file():
            raise ProfileError("profile from environment not found: {}".format(path))
        return path
    return None


def resolve_settings(args, profile, env=None):
    """Resolve GROMACS settings with one precedence for doctor and runner.

    Precedence is explicit CLI > environment > profile > default.  This function
    only resolves non-secret values; it never reads credentials or contacts SCNet.
    """
    import os

    env = env if env is not None else os.environ

    def pick(cli_value, env_key, profile_key, default=None):
        if cli_value is not None:
            return cli_value
        value = env.get(env_key)
        if value not in (None, ""):
            return value
        value = profile.get(profile_key)
        if value not in (None, ""):
            return value
        return default

    cpu_module = getattr(args, "cpu_module", None)
    if cpu_module is None:
        cpu_module = (
            env.get("GROMACS_CPU_MODULE")
            or env.get("GROMACS_MODULE")
            or profile.get("GROMACS_MODULE")
        )
    hip_module = getattr(args, "hip_module", None)
    if hip_module is None:
        hip_module = (
            env.get("GROMACS_GPU_MODULE")
            or env.get("GROMACS_MODULE")
            or profile.get("GROMACS_GPU_MODULE")
        )
    if hip_module is None:
        hip_module = cpu_module
    return {
        "region": pick(
            getattr(args, "region", None),
            "SCNET_OPENAPI_REGION_ID",
            "OPENAPI_REGION_ID",
        ),
        "cpu_queue": pick(
            getattr(args, "cpu_queue", None),
            "GROMACS_CPU_QUEUE",
            "CPU_PARTITION",
        ),
        "hip_queue": pick(
            getattr(args, "hip_queue", None),
            "GROMACS_HIP_QUEUE",
            "DCU_PARTITION",
        ),
        "cpu_module": cpu_module,
        "hip_module": hip_module,
        "binary": pick(
            getattr(args, "binary", None),
            "GROMACS_BINARY",
            "GROMACS_BINARY",
        ),
        "env_script": pick(
            getattr(args, "env_script", None),
            "GROMACS_ENV_SCRIPT",
            "GROMACS_ENV_SCRIPT",
        ),
    }

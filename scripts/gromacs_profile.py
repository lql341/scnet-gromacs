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

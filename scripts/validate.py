#!/usr/bin/env python3
"""Cross-platform static validation for this skill repository.

This checks repository files only. It never runs GROMACS or contacts a cluster.
Remote execution is Linux; the local agent may be Windows, macOS or Linux.
Bash syntax checking is performed only when a bash executable is available.
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PRIVATE_PATH = re.compile(r"/public/home/|/home/[A-Za-z0-9_.-]+/")
SCAN_SUFFIXES = {
    ".md",
    ".sh",
    ".sbatch",
    ".py",
    ".conf",
    ".json",
    ".gro",
    ".top",
    ".mdp",
    ".yaml",
    ".yml",
    ".txt",
}
SKIP_SCAN = {
    ROOT / "scripts" / "validate.py",
    ROOT / "scripts" / "validate.sh",
}


def check_shell_syntax():
    if os.name == "nt":
        print(
            "Windows host: skipped bash syntax check; remote execution uses Linux bash",
            file=sys.stderr,
        )
        return
    bash = shutil.which("bash")
    if not bash:
        print(
            "bash not found; skipped shell syntax check "
            "(remote execution still uses Linux bash)",
            file=sys.stderr,
        )
        return
    for pattern in ("scripts/*.sh", "scripts/*.sbatch"):
        for script in sorted(ROOT.glob(pattern)):
            subprocess.run([bash, "-n", str(script)], check=True)


def check_python_syntax():
    for relative in (
        "scripts/compare_gromacs_energy.py",
        "scripts/doctor.py",
        "contrib/run_openapi.py",
        "scripts/validate.py",
    ):
        path = ROOT / relative
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


def check_case_files():
    for relative in (
        "cases/argon8/argon.gro",
        "cases/argon8/topol.top",
        "cases/argon8/md.mdp",
        "cases/ionpair_pme/ionpair.gro",
        "cases/ionpair_pme/topol.top",
        "cases/ionpair_pme/md.mdp",
        "benchmarks/catalog.json",
        "benchmarks/observations.md",
        "references/version-coverage.md",
    ):
        path = ROOT / relative
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError("missing or empty file: {}".format(relative))


def check_catalog():
    with (ROOT / "benchmarks" / "catalog.json").open(encoding="utf-8") as stream:
        data = json.load(stream)
    if data.get("schema_version") != 1 or not data.get("cases"):
        raise ValueError("benchmarks/catalog.json has no cases")


def scan_private_paths():
    for path in ROOT.rglob("*"):
        if any(part in {".git", "out"} for part in path.parts):
            continue
        if path in SKIP_SCAN or not path.is_file():
            continue
        if path.suffix.lower() not in SCAN_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if PRIVATE_PATH.search(text):
            raise ValueError("private absolute path found in {}".format(path))


def main():
    try:
        check_shell_syntax()
        check_python_syntax()
        check_case_files()
        check_catalog()
        scan_private_paths()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print("repository validation failed: {}".format(exc), file=sys.stderr)
        return 1
    print("repository validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

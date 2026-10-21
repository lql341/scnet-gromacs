#!/usr/bin/env python3
"""OpenAPI-first runner for the bundled GROMACS smoke cases.

Remote directory creation, upload, submission, waiting and artifact download
all go through the installed scnet-hpc CLI with ``--backend openapi``. This
runner does not use SSH and does not implement its own credential or transport
layer. Use SSH only for separate, bounded diagnosis when OpenAPI cannot expose
the needed fact.

Examples:
    python3 contrib/run_openapi.py --cluster kseshell \
      --run-root /absolute/new/run-root --case argon8 --mode both

    python3 contrib/run_openapi.py --cluster kseshell \
      --run-root /absolute/new/run-root --case ionpair_pme --mode both
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

CASES = {
    "argon8": {
        "gro": "argon.gro",
        "deffnm": "argon",
        "pme": False,
    },
    "ionpair_pme": {
        "gro": "ionpair.gro",
        "deffnm": "ionpair",
        "pme": True,
    },
}

SMOKE_SCRIPTS = (
    "gromacs_argon_smoke.sbatch",
    "gromacs_module_probe.sh",
    "compare_gromacs_energy.py",
)

REQUIRED_ARTIFACTS = (
    "result.txt",
    "version.txt",
    "inputs.sha256",
    "energy.xvg",
    "mdrun.log",
    "grompp.log",
)

OPTIONAL_ARTIFACTS = ("device.txt",)


class RunnerError(Exception):
    """Raised when the runner cannot establish a required fact."""


def repo_root():
    return Path(__file__).resolve().parent.parent


def find_scnet_hpc(explicit):
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env_root = os.environ.get("SCNET_HPC_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser())
    candidates.extend(
        [
            repo_root().parent / "scnet-hpc",
            Path.home() / ".codex" / "skills" / "scnet-hpc",
            Path.home() / ".claude" / "skills" / "scnet-hpc",
        ]
    )
    for candidate in candidates:
        if candidate.is_file() and candidate.name == "scnet.py":
            return candidate
        cli = candidate / "scripts" / "scnet.py"
        if cli.is_file():
            return cli
    raise RunnerError(
        "scnet-hpc CLI not found; pass --scnet-hpc or set SCNET_HPC_ROOT"
    )


def load_profile(path):
    values = {}
    for raw in path.read_text().splitlines():
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


class Scnet:
    def __init__(self, cli, cluster, region):
        self.base = [
            sys.executable,
            str(cli),
            "--backend",
            "openapi",
            "--cluster",
            cluster,
        ]
        if region:
            self.base.extend(["--region", region])
        self.base.append("--json")

    def run(self, *args):
        command = self.base + [str(arg) for arg in args]
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if completed.returncode != 0:
            raise RunnerError(
                "scnet-hpc failed ({}): {}".format(
                    completed.returncode,
                    (completed.stderr or completed.stdout).strip(),
                )
            )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RunnerError(
                "scnet-hpc did not return JSON: {}".format(completed.stdout.strip())
            ) from exc
        if not payload.get("ok", False):
            raise RunnerError(
                "scnet-hpc {} failed: {} {}".format(
                    args[0],
                    payload.get("error_code"),
                    payload.get("error"),
                )
            )
        return payload.get("data")


def remote_children(scnet, path):
    data = scnet.run("files", "--path", str(path), "--limit", "500")
    return {
        item["name"]: item
        for item in (data or {}).get("files", [])
        if item.get("name")
    }


def ensure_unique_run_root(scnet, run_root):
    if not str(run_root).startswith("/"):
        raise RunnerError("--run-root must be an absolute POSIX path")
    if "\n" in str(run_root) or "\r" in str(run_root):
        raise RunnerError("--run-root must not contain newlines")
    parent = run_root.parent
    try:
        names = remote_children(scnet, parent)
    except RunnerError:
        scnet.run("mkdir", "--parents", str(parent))
        names = {}
    if run_root.name in names:
        raise RunnerError(
            "remote run root already exists; choose a new directory: {}".format(
                run_root
            )
        )


def upload_tree(scnet, local_scripts, local_case, remote_scripts, remote_case):
    for name in SMOKE_SCRIPTS:
        source = local_scripts / name
        if not source.is_file():
            raise RunnerError("missing local script: {}".format(source))
        scnet.run("upload", str(source), str(remote_scripts))
    for source in sorted(local_case.iterdir()):
        if source.is_file():
            scnet.run("upload", str(source), str(remote_case))


def build_command(
    case,
    mode,
    run_root,
    remote_scripts,
    remote_case,
    module,
    gpu_arch,
    expect_version,
):
    env = {
        "GROMACS_RUN_ROOT": str(run_root / "results-{}".format(case)),
        "GROMACS_MODULE": module,
        "GROMACS_BINARY": "gmx_mpi",
        "GROMACS_GPU_MODE": mode,
    }
    if expect_version:
        env["GROMACS_EXPECT_VERSION"] = expect_version
    case_info = CASES[case]
    if mode == "hip" and gpu_arch:
        env["GROMACS_EXPECT_GPU_ARCH"] = gpu_arch
    if case_info["pme"]:
        env["GROMACS_CASE_ROOT"] = str(remote_case)
        env["GROMACS_CASE_GRO"] = case_info["gro"]
        env["GROMACS_DEFFNM"] = case_info["deffnm"]
        if mode == "hip":
            env["GROMACS_GPU_PME"] = "1"
    lines = [
        "export {}={}".format(key, shlex.quote(value))
        for key, value in env.items()
    ]
    lines.append(
        "bash {}".format(
            shlex.quote(str(remote_scripts / "gromacs_argon_smoke.sbatch"))
        )
    )
    return "\n".join(lines)


def submit_mode(
    scnet,
    case,
    mode,
    run_root,
    remote_scripts,
    remote_case,
    queue,
    module,
    gpu_arch,
    expect_version,
    cpus,
    dcus,
    walltime,
):
    command = build_command(
        case,
        mode,
        run_root,
        remote_scripts,
        remote_case,
        module,
        gpu_arch,
        expect_version,
    )
    args = [
        "submit",
        "--name",
        "scnet-gmx-{}-{}".format(case, mode),
        "--command",
        command,
        "--work-dir",
        str(run_root),
        "--queue",
        queue,
        "--nodes",
        "1",
        "--cpus",
        str(cpus),
        "--walltime",
        walltime,
    ]
    if mode == "hip":
        args.extend(["--dcus", str(dcus)])
    data = scnet.run(*args)
    try:
        return int(data["job_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RunnerError("submit returned no job id: {!r}".format(data)) from exc


def wait_job(scnet, job_id, timeout, interval):
    deadline = time.time() + timeout
    while time.time() < deadline:
        chunk = max(1, min(600, int(deadline - time.time())))
        data = scnet.run(
            "wait",
            str(job_id),
            "--wait-timeout",
            str(chunk),
            "--interval",
            str(interval),
        )
        state = (data or {}).get("state")
        if state in ("COMPLETED", "FAILED", "CANCELLED"):
            return state
        if not (data or {}).get("timed_out"):
            return state
    raise RunnerError(
        "wait timeout for job {}; the job may still be active".format(job_id)
    )


def confirm_job(scnet, job_id, timeout, interval):
    state = wait_job(scnet, job_id, timeout, interval)
    if state != "COMPLETED":
        raise RunnerError(
            "job {} reached state {!r}, not COMPLETED".format(job_id, state)
        )
    details = scnet.run("--details", "job", str(job_id))
    exit_status = (details or {}).get("platform_exit_status")
    if exit_status != 0:
        raise RunnerError(
            "job {} completed with platform_exit_status={!r}".format(
                job_id, exit_status
            )
        )


def download_and_check(scnet, remote_run, local_run, mode, artifacts):
    names = remote_children(scnet, remote_run)
    missing = [name for name in artifacts if name not in names]
    if missing:
        raise RunnerError(
            "remote run {} is missing artifacts: {}".format(
                remote_run, ", ".join(missing)
            )
        )
    local_run.mkdir(parents=True, exist_ok=False)
    for name in artifacts:
        scnet.run("download", str(remote_run / name), str(local_run / name))
    for name in OPTIONAL_ARTIFACTS:
        if name in names:
            scnet.run("download", str(remote_run / name), str(local_run / name))

    result = {}
    for line in (local_run / "result.txt").read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep:
            result[key.strip()] = value.strip()
    if result.get("status") != "passed":
        raise RunnerError(
            "{} did not report status=passed".format(local_run / "result.txt")
        )
    if result.get("mode") != mode:
        raise RunnerError(
            "{} reports mode={!r}, expected {!r}".format(
                local_run / "result.txt", result.get("mode"), mode
            )
        )
    return local_run


def compare_runs(local_scripts, cpu_run, hip_run, report):
    command = [
        sys.executable,
        str(local_scripts / "compare_gromacs_energy.py"),
        str(cpu_run),
        str(hip_run),
        "--report",
        str(report),
    ]
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise RunnerError(
            "CPU/HIP comparison failed: {}".format(
                (completed.stderr or completed.stdout).strip()
            )
        )
    return completed.stdout


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run GROMACS smoke cases through scnet-hpc OpenAPI."
    )
    parser.add_argument("--cluster", required=True, help="scnet-hpc profile name")
    parser.add_argument(
        "--run-root", required=True, type=Path, help="new absolute remote run root"
    )
    parser.add_argument(
        "--case", choices=sorted(CASES), default="argon8", help="bundled case"
    )
    parser.add_argument(
        "--mode", choices=("cpu", "hip", "both"), default="cpu", help="backend modes"
    )
    parser.add_argument("--profile", type=Path, help="GROMACS cluster profile")
    parser.add_argument("--scnet-hpc", help="scnet-hpc skill root or scnet.py")
    parser.add_argument("--cpu-queue")
    parser.add_argument("--hip-queue")
    parser.add_argument("--cpu-module")
    parser.add_argument("--hip-module")
    parser.add_argument("--cpus", type=int)
    parser.add_argument("--dcus", type=int)
    parser.add_argument("--walltime")
    parser.add_argument("--download-dir", type=Path)
    parser.add_argument("--wait-timeout", type=int, default=600)
    parser.add_argument("--interval", type=int, default=15)
    args = parser.parse_args(argv)

    try:
        root = repo_root()
        local_scripts = root / "scripts"
        local_case = root / "cases" / args.case
        if not local_case.is_dir():
            raise RunnerError("local case directory is missing: {}".format(local_case))

        profile = {}
        profile_path = args.profile.expanduser() if args.profile else None
        if profile_path is None:
            candidate = root / "clusters" / "{}.conf".format(args.cluster)
            if candidate.is_file():
                profile_path = candidate
        if profile_path is not None:
            if not profile_path.is_file():
                raise RunnerError("profile not found: {}".format(profile_path))
            profile = load_profile(profile_path)

        cpu_queue = args.cpu_queue or profile.get("CPU_PARTITION")
        hip_queue = args.hip_queue or profile.get("DCU_PARTITION")
        cpu_module = args.cpu_module or profile.get("GROMACS_MODULE")
        hip_module = args.hip_module or profile.get("GROMACS_GPU_MODULE")
        gpu_arch = profile.get("GPU_ARCH")
        expect_version = profile.get("GROMACS_EXPECT_VERSION")
        try:
            cpus = args.cpus or int(profile.get("CPUS_PER_JOB", "2"))
            dcus = args.dcus or int(profile.get("DCUS_PER_JOB", "1"))
        except ValueError as exc:
            raise RunnerError("profile CPU/DCU values must be integers") from exc
        walltime = args.walltime or profile.get("WALLTIME", "00:15:00")

        modes = ("cpu", "hip") if args.mode == "both" else (args.mode,)
        if "cpu" in modes and (not cpu_queue or not cpu_module):
            raise RunnerError(
                "CPU mode needs --cpu-queue and --cpu-module or a profile"
            )
        if "hip" in modes and (not hip_queue or not hip_module):
            raise RunnerError(
                "HIP mode needs --hip-queue and --hip-module or a profile"
            )
        if args.wait_timeout < 1:
            raise RunnerError("--wait-timeout must be positive")

        cli = find_scnet_hpc(args.scnet_hpc)
        scnet = Scnet(cli, args.cluster, profile.get("OPENAPI_REGION_ID"))
        run_root = args.run_root.expanduser()

        download_dir = args.download_dir
        if download_dir is None:
            download_dir = root / "out" / run_root.name
        download_dir = download_dir.expanduser()
        if download_dir.exists():
            raise RunnerError(
                "local download directory already exists; choose a new one: {}".format(
                    download_dir
                )
            )

        ensure_unique_run_root(scnet, run_root)

        remote_repo = run_root / "repo"
        remote_scripts = remote_repo / "scripts"
        remote_case = remote_repo / "cases" / args.case
        for path in (remote_scripts, remote_case):
            scnet.run("mkdir", "--parents", str(path))
        upload_tree(
            scnet, local_scripts, local_case, remote_scripts, remote_case
        )
        download_dir.mkdir(parents=True)

        jobs = []
        try:
            for mode in modes:
                queue = cpu_queue if mode == "cpu" else hip_queue
                module = cpu_module if mode == "cpu" else hip_module
                job_id = submit_mode(
                    scnet,
                    args.case,
                    mode,
                    run_root,
                    remote_scripts,
                    remote_case,
                    queue,
                    module,
                    gpu_arch,
                    expect_version,
                    cpus,
                    dcus,
                    walltime,
                )
                jobs.append((mode, job_id))
                print(
                    "submitted {} {} job {}".format(args.case, mode, job_id),
                    file=sys.stderr,
                )
        except RunnerError as exc:
            submitted = ", ".join(
                "{}={}".format(mode, job_id) for mode, job_id in jobs
            )
            raise RunnerError(
                "{}; submitted jobs: {}; remote root: {}".format(
                    exc, submitted or "none", run_root
                )
            ) from exc

        errors = []
        local_runs = {}
        for mode, job_id in jobs:
            try:
                confirm_job(scnet, job_id, args.wait_timeout, args.interval)
                remote_run = (
                    run_root
                    / "results-{}".format(args.case)
                    / "argon-{}-{}".format(mode, job_id)
                )
                local_run = download_dir / "{}-{}-{}".format(
                    args.case, mode, job_id
                )
                local_runs[mode] = download_and_check(
                    scnet,
                    remote_run,
                    local_run,
                    mode,
                    REQUIRED_ARTIFACTS,
                )
            except RunnerError as exc:
                errors.append("{} job {}: {}".format(mode, job_id, exc))
                print(
                    "{} job {} needs attention: {}".format(mode, job_id, exc),
                    file=sys.stderr,
                )

        if errors:
            raise RunnerError(
                "; ".join(errors)
                + "; remote root: {}".format(run_root)
            )

        comparison = None
        if "cpu" in local_runs and "hip" in local_runs:
            report = download_dir / "comparison-{}.txt".format(args.case)
            comparison = compare_runs(
                local_scripts, local_runs["cpu"], local_runs["hip"], report
            )
            print(comparison, file=sys.stderr)

        print("run_root={}".format(run_root))
        print("case={}".format(args.case))
        for mode, job_id in jobs:
            print(
                "{}: job={} state=COMPLETED platform_exit_status=0 "
                "result=passed local={}".format(
                    mode, job_id, local_runs.get(mode, "")
                )
            )
        if comparison is not None:
            print("comparison=passed report={}".format(report))
        return 0
    except (RunnerError, OSError) as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

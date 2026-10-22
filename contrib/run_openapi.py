#!/usr/bin/env python3
"""OpenAPI-first runner for the bundled GROMACS smoke cases.

Remote directory creation, upload, submission, waiting and artifact download
all go through the embedded OpenAPI adapter vendored from scnet-hpc via the
scnet-hashcat reference adapter. The runner does not use SSH and does not require
an installed scnet-hpc CLI for normal OpenAPI runs. Use scnet-hpc only for
first-use setup, SSH, deployment or broader diagnosis.

Examples:
    python3 contrib/run_openapi.py --profile clusters/<profile>.conf \
      --run-root /absolute/new/run-root --case argon8 --mode both

    python3 contrib/run_openapi.py --region <region> --cpu-queue <queue> \
      --run-root /absolute/new/run-root --case ionpair_pme --mode both
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from gromacs_profile import (
    ProfileError,
    load_profile,
    resolve_profile,
    resolve_settings,
)
from scnet_lite import Client, ClientError, default_region

CASES = {
    "argon8": {
        "gro": "argon.gro",
        "deffnm": "argon",
        "pme": False,
        "energy_terms": "Potential,Kinetic-En.,Temperature,LJ-(SR)",
    },
    "ionpair_pme": {
        "gro": "ionpair.gro",
        "deffnm": "ionpair",
        "pme": True,
        "energy_terms": (
            "Potential,Kinetic-En.,Temperature,"
            "Coulomb-(SR),Coul.-recip.,LJ-(SR)"
        ),
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


def remote_root(value):
    """Return a POSIX remote path even when the local agent is Windows."""
    text = str(value).replace("\\", "/")
    if not text.startswith("/"):
        raise RunnerError("--run-root must be an absolute POSIX remote path")
    return PurePosixPath(text)


class Scnet:
    """Embedded OpenAPI adapter; no scnet-hpc CLI or SSH dependency."""

    def __init__(self, region):
        self.client = Client()
        self.region = region or default_region()

    def run(self, *args):
        try:
            return self._dispatch([str(arg) for arg in args])
        except ClientError as exc:
            raise RunnerError(
                "{} (run python3 scripts/doctor.py; see references/first-use.md)".format(
                    exc
                )
            ) from exc

    def _dispatch(self, args):
        if not args:
            raise RunnerError("empty adapter operation")
        operation = args[0]
        if operation == "files":
            path = _option(args, "--path")
            limit = int(_option(args, "--limit", "200"))
            return self.client.ls(path, self.region, limit=limit)
        if operation == "mkdir":
            return self.client.mkdir(args[-1], self.region, parents=True)
        if operation == "upload":
            if len(args) != 3:
                raise RunnerError("upload expects local_path remote_dir")
            return self.client.upload(args[1], args[2], self.region)
        if operation == "queues":
            return self.client.queues(self.region)
        if operation == "download":
            if len(args) != 3:
                raise RunnerError("download expects remote_path local_path")
            return self.client.download(args[1], args[2], self.region)
        if operation == "wait":
            job_id = args[1]
            timeout = int(_option(args, "--wait-timeout", "600"))
            interval = int(_option(args, "--interval", "15"))
            try:
                job = self.client.wait(job_id, self.region, interval, timeout)
                return {"state": job.get("state"), "timed_out": False, "job": job}
            except ClientError as exc:
                if "still" in str(exc).lower() or "timeout" in str(exc).lower():
                    return {"state": "RUNNING", "timed_out": True}
                raise
        if operation == "--details" and len(args) >= 3 and args[1] == "job":
            return self.client.job(args[2], self.region)
        if operation == "job":
            return self.client.job(args[1], self.region)
        if operation == "submit":
            options = {}
            scheduler_options = []
            index = 1
            while index < len(args):
                key = args[index]
                if key == "--scheduler-option":
                    scheduler_options.append(args[index + 1])
                    index += 2
                    continue
                if not key.startswith("--") or index + 1 >= len(args):
                    raise RunnerError("invalid submit option: " + key)
                options[key[2:].replace("-", "_")] = args[index + 1]
                index += 2
            options["scheduler_options"] = scheduler_options
            options["region"] = self.region
            for key in ("nodes", "cpus", "dcus"):
                if key in options:
                    options[key] = int(options[key])
            return self.client.submit(options)
        raise RunnerError("unsupported embedded adapter operation: " + operation)


def _option(args, name, default=None):
    try:
        index = args.index(name)
    except ValueError:
        return default
    if index + 1 >= len(args):
        raise RunnerError("missing value for " + name)
    return args[index + 1]


def remote_children(scnet, path):
    data = scnet.run("files", "--path", str(path), "--limit", "500")
    return {
        item["name"]: item
        for item in (data or {}).get("files", [])
        if item.get("name")
    }


def _is_not_found_error(exc):
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "404",
            "not found",
            "does not exist",
            "no such file",
            "不存在",
        )
    )


def ensure_unique_run_root(scnet, run_root):
    if not str(run_root).startswith("/"):
        raise RunnerError("--run-root must be an absolute POSIX path")
    if "\n" in str(run_root) or "\r" in str(run_root):
        raise RunnerError("--run-root must not contain newlines")
    parent = run_root.parent
    try:
        names = remote_children(scnet, parent)
    except RunnerError as exc:
        if not _is_not_found_error(exc):
            raise
        scnet.run("mkdir", "--parents", str(parent))
        # Do not trust the mkdir result alone: re-read the parent and fail on
        # any error rather than treating an unknown state as an empty directory.
        names = remote_children(scnet, parent)
    if run_root.name in names:
        raise RunnerError(
            "remote run root already exists; choose a new directory: {}".format(
                run_root
            )
        )


def case_sources(root, case):
    """Return (local source, remote filename) pairs for a bundled case.

    The repository layout is ``cases/<case>/<file>``. The WorkBuddy package
    uses a flat ``cases/<case>.<ext>`` layout to satisfy its two-level import
    limit. Both layouts are accepted here.
    """
    directory = root / "cases" / case
    if directory.is_dir():
        return [
            (path, path.name)
            for path in sorted(directory.iterdir())
            if path.is_file()
        ]
    mapping = {
        CASES[case]["gro"]: root / "cases" / (case + ".gro"),
        "md.mdp": root / "cases" / (case + ".mdp"),
        "topol.top": root / "cases" / (case + ".top"),
    }
    if all(path.is_file() for path in mapping.values()):
        return [(path, name) for name, path in mapping.items()]
    return []


def upload_tree(scnet, local_scripts, case_files, remote_scripts, remote_case):
    for name in SMOKE_SCRIPTS:
        source = local_scripts / name
        if not source.is_file():
            raise RunnerError("missing local script: {}".format(source))
        scnet.run("upload", str(source), str(remote_scripts))
    with tempfile.TemporaryDirectory() as tmp:
        for source, remote_name in case_files:
            staged = Path(tmp) / remote_name
            shutil.copyfile(source, staged)
            scnet.run("upload", str(staged), str(remote_case))


def build_command(case, mode, run_root, remote_scripts, remote_case, settings):
    case_info = CASES[case]
    env = {
        "GROMACS_RUN_ROOT": str(run_root / "results-{}".format(case)),
        "GROMACS_MODULE": settings["module"],
        "GROMACS_BINARY": settings["binary"],
        "GROMACS_GPU_MODE": mode,
        "GROMACS_ENERGY_TERMS": case_info["energy_terms"],
        "GROMACS_MPI_RANKS": str(settings["ranks"]),
        "GROMACS_MPI_RANKS_PER_NODE": str(settings["ranks_per_node"]),
        "GROMACS_OMP_THREADS": str(settings["omp_threads"]),
        "GROMACS_MPI_LAUNCHER": settings["launcher"],
        "GROMACS_MPI_LAUNCHER_ARGS": settings["launcher_args"],
    }
    if settings["expect_version"]:
        env["GROMACS_EXPECT_VERSION"] = settings["expect_version"]
    if settings["module_path"]:
        env["GROMACS_MODULEPATH"] = settings["module_path"]
    if settings["env_script"]:
        env["GROMACS_ENV_SCRIPT"] = settings["env_script"]
    if mode == "hip":
        if settings["gpu_arch"]:
            env["GROMACS_EXPECT_GPU_ARCH"] = settings["gpu_arch"]
        env["GROMACS_EXPECT_GPU_COUNT"] = str(settings["dcus"])
    for key, value in settings["mpi_env"].items():
        env[key] = value
    if settings["force_gpu_aware"]:
        env["GROMACS_FORCE_GPU_AWARE_MPI"] = "1"
    if settings["require_gpu_aware"]:
        env["GROMACS_REQUIRE_GPU_AWARE_MPI"] = "1"
    if case_info["pme"]:
        env["GROMACS_CASE_ROOT"] = str(remote_case)
        env["GROMACS_CASE_GRO"] = case_info["gro"]
        env["GROMACS_DEFFNM"] = case_info["deffnm"]
        if mode == "hip":
            env["GROMACS_GPU_PME"] = "1"
        if settings["ranks"] > 1:
            env["GROMACS_NPME"] = settings["npme"] or "1"
        elif settings["npme"]:
            env["GROMACS_NPME"] = settings["npme"]
    elif settings["npme"]:
        env["GROMACS_NPME"] = settings["npme"]
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


def submit_mode(scnet, case, mode, run_root, remote_scripts, remote_case, settings):
    command = build_command(
        case, mode, run_root, remote_scripts, remote_case, settings
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
        settings["queue"],
        "--nodes",
        str(settings["nodes"]),
        "--cpus",
        str(settings["cpus"]),
        "--walltime",
        settings["walltime"],
    ]
    if mode == "hip":
        args.extend(["--dcus", str(settings["dcus"])])
    for option in settings["scheduler_options"]:
        args.extend(["--scheduler-option", option])
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


def parse_walltime(value):
    days = 0
    text = str(value)
    if "-" in text:
        day_text, text = text.split("-", 1)
        days = int(day_text)
    parts = text.split(":")
    if len(parts) == 2:
        hours, minutes, seconds = int(parts[0]), int(parts[1]), 0
    elif len(parts) == 3:
        hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
    else:
        raise RunnerError("walltime must use HH:MM:SS or D-HH:MM:SS")
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def preflight_queue(scnet, queue, walltime):
    data = scnet.run("queues")
    if not isinstance(data, list):
        raise RunnerError("queue preflight returned no queue list")
    match = next(
        (item for item in data if item.get("partition") == queue), None
    )
    if match is None:
        raise RunnerError("queue {!r} is not visible to this account".format(queue))
    max_walltime = int(match.get("max_walltime") or 0)
    requested = parse_walltime(walltime)
    if max_walltime and requested > max_walltime:
        raise RunnerError(
            "requested walltime {} exceeds queue limit {} seconds".format(
                walltime, max_walltime
            )
        )
    print(
        "preflight queue={} free_nodes={} max_walltime={}".format(
            queue, match.get("free_nodes", "?"), max_walltime
        ),
        file=sys.stderr,
    )


def download_artifacts(scnet, remote_run, local_run, artifacts, optional):
    names = remote_children(scnet, remote_run)
    local_run.mkdir(parents=True, exist_ok=True)
    for name in artifacts + optional:
        if name not in names:
            continue
        destination = local_run / name
        if destination.exists():
            continue
        scnet.run("download", str(remote_run / name), str(destination))
    return [name for name in artifacts if name not in names]


def download_scheduler_logs(scnet, run_root, job_id, local_run):
    names = remote_children(scnet, run_root)
    target = local_run / "scheduler"
    target.mkdir(parents=True, exist_ok=True)
    stdout = "std.out.{}".format(job_id)
    stderr = "std.err.{}".format(job_id)
    for name in names:
        is_job_log = (
            name.startswith("job_")
            and name.endswith(".log")
            and str(job_id) in name
        )
        if name not in (stdout, stderr) and not is_job_log:
            continue
        destination = target / name
        if not destination.exists():
            scnet.run("download", str(run_root / name), str(destination))


def read_result(local_run):
    result = {}
    path = local_run / "result.txt"
    if not path.is_file():
        return result
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep:
            result[key.strip()] = value.strip()
    return result


def check_result(local_run, result, mode):
    if result.get("status") != "passed":
        raise RunnerError(
            "{} reports status={!r}".format(
                local_run / "result.txt", result.get("status")
            )
        )
    if result.get("mode") != mode:
        raise RunnerError(
            "{} reports mode={!r}, expected {!r}".format(
                local_run / "result.txt", result.get("mode"), mode
            )
        )


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
        description="Run GROMACS smoke cases through the embedded OpenAPI adapter."
    )
    parser.add_argument(
        "--cluster",
        help="local cluster profile name (clusters/<name>.conf)",
    )
    parser.add_argument(
        "--region",
        help="explicit OpenAPI region; overrides OPENAPI_REGION_ID in the profile",
    )
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
    parser.add_argument("--cpu-queue")
    parser.add_argument("--hip-queue")
    parser.add_argument("--cpu-module")
    parser.add_argument("--hip-module")
    parser.add_argument("--binary")
    parser.add_argument("--env-script")
    parser.add_argument("--cpus", type=int)
    parser.add_argument("--dcus", type=int)
    parser.add_argument("--nodes", type=int)
    parser.add_argument("--mpi-ranks", type=int)
    parser.add_argument("--ranks-per-node", type=int)
    parser.add_argument("--omp-threads", type=int)
    parser.add_argument("--mpi-launcher")
    parser.add_argument("--mpi-launcher-args")
    parser.add_argument("--npme")
    parser.add_argument("--force-gpu-aware", action="store_true")
    parser.add_argument("--require-gpu-aware", action="store_true")
    parser.add_argument("--walltime")
    parser.add_argument("--download-dir", type=Path)
    parser.add_argument("--wait-timeout", type=int, default=600)
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the offline plan; do not create a client or touch the remote",
    )
    args = parser.parse_args(argv)

    try:
        root = repo_root()
        local_scripts = root / "scripts"
        case_files = case_sources(root, args.case)
        if not case_files:
            raise RunnerError(
                "local case files are missing for {} under cases/".format(args.case)
            )

        try:
            profile_path = resolve_profile(
                root,
                cluster=args.cluster,
                explicit=args.profile,
                env=os.environ.get("GROMACS_PROFILE"),
            )
        except ProfileError as exc:
            raise RunnerError(str(exc)) from exc
        try:
            profile = load_profile(profile_path) if profile_path else {}
        except ProfileError as exc:
            raise RunnerError(str(exc)) from exc

        resolved = resolve_settings(args, profile)
        region = resolved["region"]
        if not region:
            raise RunnerError(
                "no OpenAPI region configured; pass --region or set "
                "OPENAPI_REGION_ID in the profile"
            )

        cpu_queue = resolved["cpu_queue"]
        hip_queue = resolved["hip_queue"]
        cpu_module = resolved["cpu_module"] or ""
        hip_module = resolved["hip_module"] or cpu_module
        if not cpu_module:
            cpu_module = hip_module
        binary = resolved["binary"] or "gmx_mpi"
        env_script = resolved["env_script"] or ""
        gpu_arch = profile.get("GPU_ARCH")
        expect_version = profile.get("GROMACS_EXPECT_VERSION")
        module_path = profile.get("GROMACS_MODULEPATH", "")
        try:
            ranks = args.mpi_ranks or int(profile.get("MPI_RANKS", "1"))
            nodes = args.nodes or int(profile.get("NODES", "1"))
            if args.ranks_per_node is not None:
                ranks_per_node = args.ranks_per_node
            elif profile.get("MPI_RANKS_PER_NODE"):
                ranks_per_node = int(profile["MPI_RANKS_PER_NODE"])
            else:
                ranks_per_node = ranks if nodes == 1 else 0
            omp_threads = args.omp_threads or int(
                profile.get("OMP_THREADS", "2")
            )
            cpus = args.cpus or int(
                profile.get(
                    "CPUS_PER_JOB", str(ranks * omp_threads)
                )
            )
            dcus = args.dcus or int(profile.get("DCUS_PER_JOB", "1"))
        except ValueError as exc:
            raise RunnerError("profile CPU/DCU/MPI values must be integers") from exc
        walltime = args.walltime or profile.get("WALLTIME", "00:15:00")
        launcher = args.mpi_launcher or profile.get("MPI_LAUNCHER", "srun")
        launcher_args = args.mpi_launcher_args or profile.get(
            "MPI_LAUNCHER_ARGS", ""
        )
        npme = args.npme or profile.get("NPME", "")
        mpi_env = {}
        for key, value in profile.items():
            if not key.startswith("MPI_ENV_"):
                continue
            name = key[len("MPI_ENV_") :]
            if not name or not name.replace("_", "a").isalnum():
                raise RunnerError("invalid MPI_ENV_ key: {}".format(key))
            mpi_env[name] = value
        scheduler_options = [
            option.strip()
            for option in profile.get("SCHEDULER_OPTIONS", "").split(";")
            if option.strip()
        ]
        if nodes > 1 and not scheduler_options:
            scheduler_options = [
                "#SBATCH --ntasks-per-node={}".format(
                    ranks_per_node * omp_threads
                )
            ]
        force_gpu_aware = args.force_gpu_aware or profile.get(
            "FORCE_GPU_AWARE_MPI", "0"
        ).lower() in ("1", "true", "yes")
        require_gpu_aware = args.require_gpu_aware or profile.get(
            "REQUIRE_GPU_AWARE_MPI", "0"
        ).lower() in ("1", "true", "yes")

        if ranks < 1 or omp_threads < 1 or nodes < 1:
            raise RunnerError("MPI ranks, nodes and OpenMP threads must be positive")
        if ranks_per_node < 1:
            raise RunnerError(
                "multi-node runs need --ranks-per-node or MPI_RANKS_PER_NODE"
            )
        if ranks > nodes * ranks_per_node:
            raise RunnerError(
                "MPI ranks {} exceed {} nodes * {} ranks/node".format(
                    ranks, nodes, ranks_per_node
                )
            )
        if cpus < ranks * omp_threads:
            raise RunnerError(
                "CPU request {} is smaller than ranks*threads={}*{}".format(
                    cpus, ranks, omp_threads
                )
            )
        if npme and ranks <= 1:
            raise RunnerError("--npme requires --mpi-ranks greater than one")
        if force_gpu_aware:
            require_gpu_aware = True

        modes = ("cpu", "hip") if args.mode == "both" else (args.mode,)
        if "hip" in modes and dcus != ranks_per_node:
            raise RunnerError(
                "HIP validation requires one DCU per MPI rank per node "
                "(ranks_per_node={}, dcus={})".format(ranks_per_node, dcus)
            )
        if "cpu" in modes and not cpu_queue:
            raise RunnerError(
                "CPU mode needs --cpu-queue or a CPU queue in the profile"
            )
        if "hip" in modes and not hip_queue:
            raise RunnerError(
                "HIP mode needs --hip-queue or a DCU queue in the profile"
            )
        if args.wait_timeout < 1:
            raise RunnerError("--wait-timeout must be positive")

        settings_by_mode = {}
        for mode in modes:
            settings_by_mode[mode] = {
                "queue": cpu_queue if mode == "cpu" else hip_queue,
                "module": cpu_module if mode == "cpu" else hip_module,
                "binary": binary,
                "env_script": env_script,
                "gpu_arch": gpu_arch,
                "expect_version": expect_version,
                "module_path": module_path,
                "nodes": nodes,
                "ranks": ranks,
                "ranks_per_node": ranks_per_node,
                "omp_threads": omp_threads,
                "launcher": launcher,
                "launcher_args": launcher_args,
                "npme": npme,
                "mpi_env": mpi_env,
                "force_gpu_aware": force_gpu_aware,
                "require_gpu_aware": require_gpu_aware,
                "cpus": cpus,
                "dcus": dcus,
                "scheduler_options": scheduler_options,
                "walltime": walltime,
            }

        run_root = remote_root(args.run_root.expanduser())
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

        uploads = [str(local_scripts / name) for name in SMOKE_SCRIPTS]
        uploads.extend(str(source) for source, _ in case_files)
        if args.dry_run:
            plan = {
                "dry_run": True,
                "case": args.case,
                "modes": list(modes),
                "region": region,
                "profile": str(profile_path) if profile_path else None,
                "run_root": str(run_root),
                "download_dir": str(download_dir),
                "resources": {
                    "nodes": nodes,
                    "ranks": ranks,
                    "ranks_per_node": ranks_per_node,
                    "omp_threads": omp_threads,
                    "cpus": cpus,
                    "dcus": dcus,
                },
                "modes_config": settings_by_mode,
                "uploads": uploads,
            }
            print(json.dumps(plan, indent=2, ensure_ascii=False))
            return 0

        scnet = Scnet(region)

        if not args.skip_preflight:
            preflight_queues = set()
            if "cpu" in modes:
                preflight_queues.add(cpu_queue)
            if "hip" in modes:
                preflight_queues.add(hip_queue)
            for queue in sorted(preflight_queues):
                preflight_queue(scnet, queue, walltime)

        ensure_unique_run_root(scnet, run_root)

        remote_repo = run_root / "repo"
        remote_scripts = remote_repo / "scripts"
        remote_case = remote_repo / "cases" / args.case
        for path in (remote_scripts, remote_case):
            scnet.run("mkdir", "--parents", str(path))
        upload_tree(
            scnet, local_scripts, case_files, remote_scripts, remote_case
        )
        download_dir.mkdir(parents=True)

        jobs = []
        try:
            for mode in modes:
                settings = settings_by_mode[mode]
                job_id = submit_mode(
                    scnet,
                    args.case,
                    mode,
                    run_root,
                    remote_scripts,
                    remote_case,
                    settings,
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
        artifacts = REQUIRED_ARTIFACTS + (
            "energy.log",
            "{}.log".format(CASES[args.case]["deffnm"]),
        )
        for mode, job_id in jobs:
            remote_run = (
                run_root
                / "results-{}".format(args.case)
                / "argon-{}-{}".format(mode, job_id)
            )
            local_run = download_dir / "{}-{}-{}".format(
                args.case, mode, job_id
            )
            try:
                state = wait_job(scnet, job_id, args.wait_timeout, args.interval)
                details = scnet.run("--details", "job", str(job_id))
                exit_status = (details or {}).get("platform_exit_status")
                missing = download_artifacts(
                    scnet,
                    remote_run,
                    local_run,
                    artifacts,
                    OPTIONAL_ARTIFACTS,
                )
                download_scheduler_logs(
                    scnet, run_root, job_id, local_run
                )
                if state != "COMPLETED":
                    raise RunnerError(
                        "state={!r}, platform_exit_status={!r}".format(
                            state, exit_status
                        )
                    )
                if exit_status != 0:
                    raise RunnerError(
                        "platform_exit_status={!r}".format(exit_status)
                    )
                if missing:
                    raise RunnerError(
                        "missing artifacts: {}".format(", ".join(missing))
                    )
                result = read_result(local_run)
                check_result(local_run, result, mode)
                local_runs[mode] = local_run
            except RunnerError as exc:
                errors.append("{} job {}: {}".format(mode, job_id, exc))
                print(
                    "{} job {} needs attention: {}; artifacts={}".format(
                        mode, job_id, exc, local_run
                    ),
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

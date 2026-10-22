import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "contrib"))

import doctor  # noqa: E402
import run_openapi  # noqa: E402


def namespace(**overrides):
    values = {
        "profile": None,
        "cluster": None,
        "region": None,
        "cpu_queue": None,
        "hip_queue": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class DoctorTests(unittest.TestCase):
    def test_dummy_credentials_are_not_runner_ready(self):
        with mock.patch.object(
            doctor, "_credentials", return_value={
                "present": True,
                "source": "environment",
                "env_keys_present": list(doctor.ENV_KEYS),
                "store_error": None,
            }
        ), mock.patch.object(doctor, "find_scnet_hpc", return_value=None):
            status = doctor.probe(args=namespace())
        self.assertFalse(status["openapi_ready"])
        self.assertEqual(status["primary_blocker"], "configuration")
        self.assertEqual(status["readiness"]["remote"], "unknown")

    def test_profile_makes_local_prerequisites_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile.conf"
            profile.write_text(
                'OPENAPI_REGION_ID="test-region"\n'
                'CPU_PARTITION="cpu"\n'
                'DCU_PARTITION="dcu"\n'
                'GROMACS_MODULE="gromacs/test-dtk-z100"\n'
            )
            with mock.patch.object(
                doctor, "_credentials", return_value={
                    "present": True,
                    "source": "shared_store",
                    "env_keys_present": [],
                    "store_error": None,
                }
            ), mock.patch.object(doctor, "find_scnet_hpc", return_value=None):
                status = doctor.probe(args=namespace(profile=profile))
        self.assertTrue(status["openapi_ready"])
        self.assertIsNone(status["primary_blocker"])
        self.assertEqual(status["configuration"]["region"], "test-region")
        self.assertEqual(status["configuration"]["cpu_queue"], "cpu")

    def test_missing_credentials_is_first_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile.conf"
            profile.write_text(
                'OPENAPI_REGION_ID="test-region"\n'
                'CPU_PARTITION="cpu"\n'
            )
            with mock.patch.object(
                doctor, "_credentials", return_value={
                    "present": False,
                    "source": "missing",
                    "env_keys_present": [],
                    "store_error": None,
                }
            ), mock.patch.object(doctor, "find_scnet_hpc", return_value=None):
                status = doctor.probe(args=namespace(profile=profile))
        self.assertFalse(status["openapi_ready"])
        self.assertEqual(status["primary_blocker"], "credentials")

    def test_json_status_never_prints_secret_values(self):
        secrets = {
            "SCNET_OPENAPI_USER": "user-secret-value",
            "SCNET_OPENAPI_ACCESS_KEY": "access-secret-value",
            "SCNET_OPENAPI_SECRET_KEY": "secret-secret-value",
        }
        with mock.patch.dict("os.environ", secrets, clear=False), mock.patch.object(
            doctor, "find_scnet_hpc", return_value=None
        ):
            status = doctor.probe(args=namespace())
        rendered = json.dumps(status)
        for value in secrets.values():
            self.assertNotIn(value, rendered)

    def test_online_json_is_merged_without_plain_text(self):
        payload = {
            "ok": True,
            "data": {
                "ok": True,
                "checks": [
                    {"name": "openapi_credentials", "ok": True},
                    {"name": "openapi_region", "ok": True},
                ],
            },
        }
        completed = mock.Mock(
            returncode=0, stdout=json.dumps(payload), stderr=""
        )
        status = {
            "scnet_hpc": {"found": True, "path": "/fake/scnet.py"},
            "configuration": {
                "region": "region-a",
                "cpu_queue": "cpu-a",
                "hip_queue": "dcu-a",
            },
        }
        with mock.patch.object(doctor.subprocess, "run", return_value=completed) as run:
            online, rc = doctor._online_status(status, None, "profile")
        self.assertEqual(rc, 0)
        self.assertTrue(online["ok"])
        self.assertEqual(
            [item["name"] for item in online["checks"]],
            ["openapi_credentials", "openapi_region"],
        )
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--region") + 1], "region-a")
        self.assertEqual(command.count("--queue"), 2)
        self.assertIn("cpu-a", command)
        self.assertIn("dcu-a", command)

    def test_online_doctor_inner_failure_is_not_verified(self):
        payload = {
            "ok": True,
            "data": {
                "ok": False,
                "checks": [{"name": "openapi_connection", "ok": False}],
            },
        }
        completed = mock.Mock(
            returncode=1, stdout=json.dumps(payload), stderr=""
        )
        status = {
            "scnet_hpc": {"found": True, "path": "/fake/scnet.py"},
            "configuration": {
                "region": "region-a",
                "cpu_queue": "cpu-a",
                "hip_queue": None,
            },
        }
        with mock.patch.object(doctor.subprocess, "run", return_value=completed):
            online, rc = doctor._online_status(status, None, None)
        self.assertFalse(online["ok"])
        self.assertEqual(rc, 1)

    def test_online_doctor_with_data_ok_false_returns_nonzero_cli(self):
        payload = {
            "ok": True,
            "data": {
                "ok": False,
                "checks": [{"name": "openapi_connection", "ok": False}],
            },
        }
        completed = mock.Mock(
            returncode=0, stdout=json.dumps(payload), stderr=""
        )
        status = {
            "scnet_hpc": {"found": True, "path": "/fake/scnet.py"},
            "configuration": {
                "region": "region-a",
                "cpu_queue": "cpu-a",
                "hip_queue": None,
            },
            "readiness": {"remote": "unknown"},
        }
        output = io.StringIO()
        with mock.patch.object(
            doctor, "probe", return_value=status
        ), mock.patch.object(
            doctor.subprocess, "run", return_value=completed
        ), contextlib.redirect_stdout(output):
            rc = doctor.main(["--online", "--json"])
        self.assertNotEqual(rc, 0)
        envelope = json.loads(output.getvalue())
        self.assertFalse(envelope["online"]["ok"])
        self.assertNotEqual(envelope["readiness"]["remote"], "verified")

    def test_online_uses_resolved_region_not_profile_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile.conf"
            profile.write_text(
                'OPENAPI_REGION_ID="region-b"\n'
                'CPU_PARTITION="cpu-b"\n'
                'DCU_PARTITION="dcu-b"\n'
            )
            args = namespace(profile=profile, region="region-a")
            with mock.patch.object(
                doctor, "_credentials", return_value={
                    "present": True,
                    "source": "shared_store",
                    "env_keys_present": [],
                    "store_error": None,
                }
            ), mock.patch.object(doctor, "find_scnet_hpc", return_value=Path("/fake/scnet.py")):
                status = doctor.probe(args=args)
            payload = {
                "ok": True,
                "data": {"ok": True, "checks": [{"name": "openapi_connection", "ok": True}]},
            }
            completed = mock.Mock(
                returncode=0, stdout=json.dumps(payload), stderr=""
            )
            with mock.patch.object(doctor.subprocess, "run", return_value=completed) as run:
                online, rc = doctor._online_status(status, None, None)
        self.assertEqual(rc, 0)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--region") + 1], "region-a")
        self.assertNotIn("region-b", command)

    def test_environment_overrides_profile_consistently(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = root / "profile.conf"
            profile.write_text(
                'OPENAPI_REGION_ID="profile-region"\n'
                'CPU_PARTITION="profile-cpu"\n'
                'GROMACS_MODULE="profile-module"\n'
                'GROMACS_BINARY="profile-binary"\n'
                'CPUS_PER_JOB=2\n'
            )
            env = {
                "GROMACS_MODULE": "env-module",
                "GROMACS_BINARY": "env-binary",
            }
            with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(
                doctor, "_credentials", return_value={
                    "present": True,
                    "source": "environment",
                    "env_keys_present": list(doctor.ENV_KEYS),
                    "store_error": None,
                }
            ), mock.patch.object(doctor, "find_scnet_hpc", return_value=None):
                status = doctor.probe(args=namespace(profile=profile))
            output = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=False), contextlib.redirect_stdout(output):
                rc = run_openapi.main(
                    [
                        "--profile",
                        str(profile),
                        "--run-root",
                        "/remote/new-run",
                        "--download-dir",
                        str(root / "download"),
                        "--case",
                        "argon8",
                        "--mode",
                        "cpu",
                        "--dry-run",
                    ]
                )
            plan = json.loads(output.getvalue())
        self.assertEqual(rc, 0)
        self.assertEqual(status["configuration"]["cpu_module"], "env-module")
        self.assertEqual(status["configuration"]["binary"], "env-binary")
        self.assertEqual(plan["modes_config"]["cpu"]["module"], "env-module")
        self.assertEqual(plan["modes_config"]["cpu"]["binary"], "env-binary")

    def test_online_missing_queue_binding_is_failure(self):
        payload = {
            "ok": True,
            "data": {
                "ok": False,
                "checks": [
                    {"name": "openapi_queue_binding", "ok": False},
                ],
            },
        }
        completed = mock.Mock(
            returncode=1, stdout=json.dumps(payload), stderr=""
        )
        status = {
            "scnet_hpc": {"found": True, "path": "/fake/scnet.py"},
            "configuration": {
                "region": "region-a",
                "cpu_queue": "missing-queue",
                "hip_queue": None,
            },
        }
        with mock.patch.object(doctor.subprocess, "run", return_value=completed):
            online, rc = doctor._online_status(status, None, None)
        self.assertFalse(online["ok"])
        self.assertNotEqual(rc, 0)


class RunRootTests(unittest.TestCase):
    def test_permission_error_is_not_treated_as_missing_parent(self):
        class FakeScnet:
            def __init__(self):
                self.calls = []

            def run(self, *args):
                self.calls.append(args)

        scnet = FakeScnet()
        with mock.patch.object(
            run_openapi,
            "remote_children",
            side_effect=run_openapi.RunnerError("permission denied"),
        ):
            with self.assertRaises(run_openapi.RunnerError):
                run_openapi.ensure_unique_run_root(
                    scnet, run_openapi.PurePosixPath("/remote/run")
                )
        self.assertEqual(scnet.calls, [])

    def test_missing_parent_is_created_then_verified(self):
        class FakeScnet:
            def __init__(self):
                self.calls = []

            def run(self, *args):
                self.calls.append(args)

        scnet = FakeScnet()
        with mock.patch.object(
            run_openapi,
            "remote_children",
            side_effect=[run_openapi.RunnerError("404 not found"), {}],
        ):
            run_openapi.ensure_unique_run_root(
                scnet, run_openapi.PurePosixPath("/remote/run")
            )
        self.assertEqual(scnet.calls, [("mkdir", "--parents", "/remote")])

    def test_existing_run_root_is_rejected(self):
        class FakeScnet:
            def run(self, *args):
                raise AssertionError("mkdir must not run")

        with mock.patch.object(
            run_openapi, "remote_children", return_value={"run": {}}
        ):
            with self.assertRaises(run_openapi.RunnerError):
                run_openapi.ensure_unique_run_root(
                    FakeScnet(), run_openapi.PurePosixPath("/remote/run")
                )


class DryRunTests(unittest.TestCase):
    def test_dry_run_does_not_create_a_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = root / "profile.conf"
            profile.write_text(
                'OPENAPI_REGION_ID="test-region"\n'
                'CPU_PARTITION="cpu"\n'
                'GROMACS_MODULE="gromacs/test-dtk-z100"\n'
                'CPUS_PER_JOB=2\n'
            )
            output = io.StringIO()
            with mock.patch.object(
                run_openapi,
                "Scnet",
                side_effect=AssertionError("dry-run must not create a client"),
            ), contextlib.redirect_stdout(output):
                rc = run_openapi.main(
                    [
                        "--profile",
                        str(profile),
                        "--run-root",
                        "/remote/new-run",
                        "--download-dir",
                        str(root / "download"),
                        "--case",
                        "argon8",
                        "--mode",
                        "cpu",
                        "--dry-run",
                    ]
                )
            plan = json.loads(output.getvalue())
        self.assertEqual(rc, 0)
        self.assertTrue(plan["dry_run"])
        self.assertEqual(plan["region"], "test-region")
        self.assertEqual(plan["modes_config"]["cpu"]["queue"], "cpu")

    def test_missing_cluster_profile_is_an_error(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = run_openapi.main(
                [
                    "--cluster",
                    "does-not-exist",
                    "--run-root",
                    "/remote/new-run",
                    "--dry-run",
                ]
            )
        self.assertEqual(rc, 1)
        self.assertIn("cluster profile not found", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

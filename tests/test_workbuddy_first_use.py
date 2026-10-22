import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import workbuddy_first_use as wb  # noqa: E402


def status(**overrides):
    data = {
        "openapi_ready": False,
        "readiness": {"credentials": "missing", "configuration": "incomplete", "remote": "unknown"},
        "primary_blocker": "credentials",
        "credentials": {"present": False, "source": "missing"},
        "configuration": {
            "ready": False,
            "region": None,
            "cpu_queue": None,
            "hip_queue": None,
        },
        "scnet_hpc": {"found": True, "path": "/opt/scnet-hpc/scripts/scnet.py"},
    }
    data.update(overrides)
    return data


class WorkBuddyFirstUseTests(unittest.TestCase):
    def assert_card_shape(self, card):
        self.assertEqual(card["tool"], "AskUserQuestion")
        self.assertLessEqual(len(card["question"]["header"]), 12)
        self.assertGreaterEqual(len(card["question"]["options"]), 2)
        self.assertLessEqual(len(card["question"]["options"]), 4)

    def test_account_is_first(self):
        card = wb.next_card(status())
        self.assertEqual(card["next"], "account")
        self.assert_card_shape(card)

    def test_credentials_after_account(self):
        card = wb.next_card(status(), account_confirmed=True)
        self.assertEqual(card["next"], "credentials")
        self.assertIn("setup new --mode openapi", card["terminal_command"])
        self.assert_card_shape(card)

    def test_online_question_when_local_ready(self):
        card = wb.next_card(
            status(
                openapi_ready=True,
                readiness={"credentials": "ready", "configuration": "ready", "remote": "unknown"},
                primary_blocker=None,
                credentials={"present": True, "source": "shared_store"},
                configuration={
                    "ready": True,
                    "region": "region-a",
                    "cpu_queue": "cpu-a",
                    "hip_queue": "dcu-a",
                },
            ),
            account_confirmed=True,
        )
        self.assertEqual(card["next"], "online")
        self.assert_card_shape(card)

    def test_failed_online_is_blocked(self):
        card = wb.next_card(
            status(
                openapi_ready=True,
                readiness={"credentials": "ready", "configuration": "ready", "remote": "failed"},
                credentials={"present": True, "source": "shared_store"},
                configuration={
                    "ready": True,
                    "region": "region-a",
                    "cpu_queue": "cpu-a",
                    "hip_queue": "dcu-a",
                },
                online={"ok": False, "error": "queue binding failed"},
            ),
            account_confirmed=True,
            online_requested=True,
        )
        self.assertEqual(card["next"], "blocked")
        self.assertNotEqual(card.get("question", {}).get("header"), "verified")

    def test_verified_online_is_ready(self):
        card = wb.next_card(
            status(
                openapi_ready=True,
                readiness={"credentials": "ready", "configuration": "ready", "remote": "verified"},
                credentials={"present": True, "source": "shared_store"},
                configuration={
                    "ready": True,
                    "region": "region-a",
                    "cpu_queue": "cpu-a",
                    "hip_queue": "dcu-a",
                },
                online={"ok": True, "checks": []},
            ),
            account_confirmed=True,
            online_requested=True,
        )
        self.assertEqual(card["next"], "ready")
        self.assertIsNone(card["question"])

    def test_status_file_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doctor.json"
            path.write_text(json.dumps(status()), encoding="utf-8")
            card = wb.next_card(status(), account_confirmed=True)
            self.assertEqual(card["next"], "credentials")


if __name__ == "__main__":
    unittest.main()

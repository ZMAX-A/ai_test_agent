import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.training_memory import (
    TrainingMemory,
    training_case_hash,
)


def evaluation(success=True, evidence=True):
    return {
        "case_id": "A",
        "task_name": "任务",
        "module": "首页",
        "run_index": 1,
        "success": success,
        "evidence_backed": evidence,
        "unsupported_pass": success and not evidence,
        "recovered": False,
        "action_count": 1,
        "failed_action_count": 0,
        "recovery_count": 0,
        "critic_revision_count": 0,
        "verification_count": 1 if evidence else 0,
        "evidence_count": 1 if evidence else 0,
        "model_calls": 1,
        "event_count": 1,
        "duration_seconds": 0.1,
        "error": "" if success else "failed",
        "created_at": "now",
    }


def case(case_id="A"):
    return {
        "case_id": case_id,
        "case_name": "查看首页",
        "module": "首页",
        "priority": "P0",
        "risk": "read_only",
        "start_url": "https://example.test/login",
        "steps": ["查看首页"],
    }


def result(secret=""):
    return {
        "trace": [{
            "goal": f"输入 {secret}" if secret else "查看首页",
            "all_actions": [{
                "action": "fill" if secret else "click",
                "parameters": {"value": secret} if secret else {"role": "link"},
            }],
            "completion_evidence": ["页面可见"],
        }],
        "results": [],
    }


class TrainingMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "memory.db"
        self.memory = TrainingMemory(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_requires_two_independent_verified_successes_for_promotion(self):
        first = self.memory.record_attempt("run-1", "source", case(), evaluation(), result())
        self.assertEqual(first["experience_status"], "candidate")
        self.assertEqual(self.memory.promoted_case_ids("source"), set())
        self.assertEqual(
            self.memory.promoted_context("example.test", "首页"), ""
        )
        second = self.memory.record_attempt("run-2", "source", case(), evaluation(), result())
        self.assertEqual(second["experience_status"], "promoted")
        self.assertEqual(
            self.memory.promoted_case_ids("source"), {"A"}
        )
        context = json.loads(
            self.memory.promoted_context("example.test", "首页")
        )
        self.assertEqual(context[0]["case_id"], "A")

    def test_current_policy_hash_filters_stale_experience(self):
        current_case = case()
        self.memory.record_attempt(
            "run-1", "source", current_case, evaluation(), result()
        )
        self.memory.record_attempt(
            "run-2", "source", current_case, evaluation(), result()
        )
        current_hash = training_case_hash(current_case)
        self.assertEqual(
            self.memory.promoted_case_ids("source", {"A": "stale"}), set()
        )
        self.assertEqual(
            self.memory.promoted_case_ids("source", {"A": current_hash}), {"A"}
        )
        self.assertEqual(self.memory.promoted_context(
            "example.test", source_hash="source",
            allowed_case_hashes=("stale",),
        ), "")

    def test_failed_or_unsupported_attempt_never_becomes_hint(self):
        self.memory.record_attempt(
            "run-1", "source", case("F"), evaluation(False, False), result()
        )
        self.memory.record_attempt(
            "run-2", "source", case("U"), evaluation(True, False), result()
        )
        self.assertEqual(self.memory.promoted_context("example.test", "首页"), "")
        self.assertEqual(self.memory.successful_case_ids("source"), set())

    def test_failure_after_promotion_quarantines_experience(self):
        self.memory.record_attempt("run-1", "source", case(), evaluation(), result())
        self.memory.record_attempt("run-2", "source", case(), evaluation(), result())
        state = self.memory.record_attempt(
            "run-3", "source", case(), evaluation(False, False), result()
        )
        self.assertEqual(state["experience_status"], "quarantined")
        self.assertEqual(self.memory.promoted_context("example.test", "首页"), "")

    def test_duplicate_run_id_is_idempotent(self):
        self.memory.record_attempt(
            "run-1", "source", case(), evaluation(), result()
        )
        self.memory.record_attempt(
            "run-2", "source", case(), evaluation(), result()
        )
        replay = self.memory.record_attempt(
            "run-2",
            "source",
            case(),
            evaluation(False, False),
            result(),
        )
        self.assertEqual(replay["outcome"], "passed_verified")
        self.assertEqual(replay["experience_status"], "promoted")
        self.assertEqual(replay["verified_failures"], 0)
        self.assertEqual(
            self.memory.stats("source")["attempts"]["passed_verified"], 2
        )

    def test_promoted_context_can_be_isolated_by_source(self):
        self.memory.record_attempt(
            "run-1", "old-source", case(), evaluation(), result()
        )
        self.memory.record_attempt(
            "run-2", "old-source", case(), evaluation(), result()
        )
        self.assertEqual(
            self.memory.promoted_context(
                "example.test", source_hash="new-source"
            ),
            "",
        )

    def test_persisted_payload_redacts_credentials_and_personal_data(self):
        secret = "training-secret-password"
        with patch("config.settings.settings.LOGIN_PASSWORD", secret), patch.dict(
            os.environ, {"CRED_INVALID_PASSWORD": "invalid-secret"}, clear=False
        ):
            self.memory.record_attempt(
                "run-1", "source", case(), evaluation(),
                result(secret + " 13800138000 invalid-secret"),
            )
        raw = self.db.read_bytes().decode("utf-8", errors="ignore")
        self.assertNotIn(secret, raw)
        self.assertNotIn("invalid-secret", raw)
        self.assertNotIn("13800138000", raw)
        self.assertIn("credential.password", raw)


    def test_goal_action_mismatch_is_not_promotable(self):
        mismatched = {
            "trace": [{
                "goal": "点击顾客档案菜单",
                "all_actions": [{
                    "action": "scroll",
                    "parameters": {"direction": "down"},
                }],
                "completion_evidence": ["动作后URL发生变化"],
            }],
            "results": [],
        }
        state = self.memory.record_attempt(
            "run-1", "source", case(), evaluation(), mismatched
        )
        self.assertEqual(state["outcome"], "unpromotable_pass")
        self.assertEqual(state["experience_status"], "candidate")
        self.assertEqual(
            self.memory.promoted_context("example.test", "首页"), ""
        )


if __name__ == "__main__":
    unittest.main()
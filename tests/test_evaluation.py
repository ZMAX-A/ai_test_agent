import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from config.settings import settings
from web_agent.evaluation import (
    EvaluationRecord,
    EvaluationSuite,
    format_summary,
    report_passed,
    summarize,
)


def _result(
    success=True,
    verification=True,
    evidence=None,
    failed_action=False,
    replanned=False,
    critic_revision=False,
    model_calls=2,
):
    evidence = ["url=/customer"] if evidence is None else evidence
    events = []
    if failed_action:
        events.append(
            {
                "event": "action_executed",
                "payload": {"success": False},
            }
        )
    if replanned:
        events.append({"event": "plan_revised", "payload": {}})
    if critic_revision:
        events.append({"event": "action_revised", "payload": {}})
    verification_data = (
        {"passed": success, "evidence": evidence} if verification else {}
    )
    return {
        "success": success,
        "results": [
            {
                "success": success,
                "msg": "ok" if success else "failed",
                "verification": verification_data,
            }
        ],
        "trace": [
            {
                "all_actions": [{"action": "click"}, {"action": "finish"}],
                "agent_events": events,
            }
        ],
        "collaboration": {
            "model_calls": model_calls,
            "event_count": len(events),
        },
    }


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.case = {
            "case_id": "customer-profile",
            "case_name": "Customer profile",
            "module": "customer",
        }

    def test_success_requires_verifier_evidence(self):
        supported = EvaluationRecord.from_result(
            self.case, _result(), 1.25
        )
        unsupported = EvaluationRecord.from_result(
            self.case, _result(verification=False), 1.0
        )
        self.assertTrue(supported.evidence_backed)
        self.assertFalse(supported.unsupported_pass)
        self.assertTrue(unsupported.unsupported_pass)

    def test_every_step_requires_its_own_verifier_evidence(self):
        result = _result()
        result["results"].append({
            "success": True,
            "msg": "missing verification",
            "verification": {},
        })
        result["trace"].append({"all_actions": [], "agent_events": []})
        record = EvaluationRecord.from_result(self.case, result, 1.0)
        self.assertFalse(record.evidence_backed)
        self.assertTrue(record.unsupported_pass)

    def test_truncated_result_fails_declared_step_gate(self):
        case = dict(self.case, expected_step_count=2)
        record = EvaluationRecord.from_result(case, _result(), 1.0)
        self.assertFalse(record.evidence_backed)
        self.assertTrue(record.unsupported_pass)

    def test_duplicate_rows_in_one_run_are_not_reproducibility(self):
        records = [
            EvaluationRecord.from_result(self.case, _result(), 1.0, 1),
            EvaluationRecord.from_result(self.case, _result(), 1.0, 1),
        ]
        summary = summarize(records)
        self.assertEqual(summary["repeated_case_count"], 0)
        self.assertIsNone(summary["reproducibility_rate"])

    def test_recovery_is_measured_from_failed_action_and_replan(self):
        record = EvaluationRecord.from_result(
            self.case,
            _result(failed_action=True, replanned=True),
            2.0,
        )
        self.assertTrue(record.recovery_attempted)
        self.assertTrue(record.recovered)
        self.assertEqual(record.failed_action_count, 1)
        self.assertEqual(record.recovery_count, 1)
        self.assertEqual(record.critic_revision_count, 0)

    def test_critic_revision_is_not_misreported_as_failure_recovery(self):
        record = EvaluationRecord.from_result(
            self.case,
            _result(critic_revision=True),
            1.0,
        )
        self.assertFalse(record.recovery_attempted)
        self.assertEqual(record.critic_revision_count, 1)

    def test_summary_tracks_reproducibility_and_cost(self):
        records = [
            EvaluationRecord.from_result(self.case, _result(), 1.0, 1),
            EvaluationRecord.from_result(self.case, _result(), 3.0, 2),
        ]
        summary = summarize(records)
        self.assertEqual(summary["pass_rate"], 1.0)
        self.assertEqual(summary["reproducibility_rate"], 1.0)
        self.assertEqual(summary["average_actions"], 2.0)
        self.assertEqual(summary["average_model_calls"], 2.0)
        self.assertEqual(summary["average_critic_revisions"], 0.0)
        self.assertEqual(summary["average_duration_seconds"], 2.0)

    def test_single_run_does_not_claim_reproducibility(self):
        summary = summarize(
            [EvaluationRecord.from_result(self.case, _result(), 1.0)]
        )
        self.assertIsNone(summary["reproducibility_rate"])

    def test_report_is_written_atomically_as_utf8_json(self):
        suite = EvaluationSuite("baseline")
        suite.record(self.case, _result(), 1.0)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "report.json"
            report = suite.write(target)
            loaded = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(loaded["schema_version"], 1)
        self.assertEqual(loaded["suite"], "baseline")
        self.assertEqual(report["summary"]["successful_runs"], 1)
        self.assertTrue(report_passed(report))
        self.assertIn("Evidence-backed pass rate", format_summary(report))

    def test_report_redacts_credentials_from_task_and_error(self):
        secret = "evaluation-secret"
        case = dict(
            self.case,
            case_id=f"case-{secret}",
            case_name=f"Task {secret}",
        )
        failed = _result(success=False)
        failed["results"][0]["msg"] = f"Login failed: {secret}"
        with patch.object(settings, "LOGIN_PASSWORD", secret):
            record = EvaluationRecord.from_result(case, failed, 1.0)
        self.assertNotIn(secret, record.case_id)
        self.assertNotIn(secret, record.task_name)
        self.assertNotIn(secret, record.error)
        self.assertIn("{{credential.password}}", record.error)

    def test_unsupported_pass_fails_quality_gate(self):
        suite = EvaluationSuite("quality-gate")
        suite.record(self.case, _result(verification=False), 0.5)
        self.assertFalse(report_passed(suite.report()))


if __name__ == "__main__":
    unittest.main()

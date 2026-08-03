import unittest
from types import SimpleNamespace

from agents.critic_agent import CriticAgent
from agents.replanner_agent import ReplannerAgent
from core.task_world_model import TaskWorldModel


class DeliberativeWorldModelTests(unittest.TestCase):
    def test_failed_action_creates_hypothesis_and_requests_replan(self):
        model = TaskWorldModel("1", "进入顾客档案")
        model.begin_goal("点击顾客档案")
        model.record_action(
            {"action": "click", "parameters": {"role": "link", "name": "顾客档案"}},
            {"success": False, "error_type": "ELEMENT_NOT_FOUND", "message": "not found"},
        )
        self.assertTrue(model.should_replan())
        self.assertIn("定位证据", model.hypotheses[-1].hypothesis)

    def test_replan_is_not_repeated_without_new_action(self):
        model = TaskWorldModel("1", "目标")
        model.begin_goal("步骤")
        model.record_action(
            {"action": "click", "parameters": {"role": "button"}},
            {"success": False, "error_type": "TIMEOUT", "message": "timeout"},
        )
        model.record_replan(ReplannerAgent.fallback_plan(model.compact_snapshot()))
        self.assertFalse(model.should_replan())

    def test_verifier_evidence_is_kept_as_fact(self):
        model = TaskWorldModel("1", "目标")
        model.begin_goal("进入 /customer")
        verification = SimpleNamespace(
            passed=True,
            confidence=0.98,
            evidence=["URL包含目标路径: /customer"],
            reason="完成",
        )
        model.record_verification(verification, action={"action": "goto"})
        self.assertEqual(model.evidence[-1].source, "verifier")
        self.assertIn("/customer", model.evidence[-1].claim)

    def test_world_model_redacts_input_values(self):
        model = TaskWorldModel("1", "目标")
        model.begin_goal("输入密码")
        model.record_action(
            {"action": "fill", "parameters": {"role": "textbox", "value": "secret"}},
            {"success": True, "message": "ok"},
        )
        self.assertEqual(model.actions[-1].parameters["value"], "<redacted:6>")

    def test_critic_preflight_blocks_invalid_action_without_model(self):
        result = CriticAgent.preflight({"action": "shell", "parameters": {}})
        self.assertFalse(result.approved)
        self.assertEqual(result.confidence, 1.0)

    def test_critic_preflight_approves_low_impact_fill(self):
        result = CriticAgent.preflight({
            "action": "fill",
            "parameters": {"role": "textbox", "value": "demo"},
        })
        self.assertTrue(result.approved)


if __name__ == "__main__":
    unittest.main()

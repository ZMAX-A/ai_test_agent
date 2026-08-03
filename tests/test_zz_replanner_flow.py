import unittest
from unittest.mock import patch

import runner.multi_agent_runner as base_runner
from agents.tool_aware_executor_agent import ToolAwareExecutorAgent
from runner.reasoning_runtime_activation import current_world_model


class ReplannerFlowTests(unittest.TestCase):
    def test_failed_action_triggers_replanner_before_next_proposal(self):
        board = base_runner.TaskBlackboard("replan-1", "任务", "进入顾客档案")
        world = current_world_model()
        world.begin_goal("点击顾客档案")
        world.record_action(
            {"action": "click", "parameters": {"role": "link", "name": "顾客档案"}},
            {"success": False, "error_type": "ELEMENT_NOT_FOUND", "message": "not found"},
        )
        agent = base_runner.ExecutorAgent()

        def fake_replan(_context, _snapshot):
            agent.replanner.last_model_call_count = 0
            return {
                "diagnosis": "定位证据失效",
                "next_strategy": "重新读取ARIA并使用不同定位证据",
                "avoid": ["重复旧定位"],
                "success_probe": "检查URL或显式断言",
            }

        agent.replanner.replan = fake_replan
        proposal = {
            "thought": "改用页面中已观察到的按钮",
            "action": "fill",
            "parameters": {"role": "textbox", "value": "demo"},
        }
        context = {
            "step_goal": "点击顾客档案",
            "page_url": "https://example.test/",
            "page_title": "首页",
            "page_state": "link 顾客列表; textbox 搜索",
            "last_result": "not found",
            "reasoning_state": "{}",
            "tried_strategies": "旧定位失败",
        }
        with patch.object(ToolAwareExecutorAgent, "ask", return_value=proposal):
            result = agent.ask(context)

        self.assertEqual(result, proposal)
        self.assertEqual(world.replans[-1]["diagnosis"], "定位证据失效")
        self.assertTrue(any(event.role == "replanner" for event in board.events))
        self.assertFalse(world.should_replan())


if __name__ == "__main__":
    unittest.main()

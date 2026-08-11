import tempfile
import unittest
from pathlib import Path

import openpyxl

from core.training_memory import TrainingMemory
from loader.curriculum_loader import load_curriculum
from web_agent.training import TrainingOptions, run_training, select_curriculum
from web_agent.training import _is_holdout


HEADERS = [
    "用例ID", "起始网址", "模块", "测试场景", "优先级", "前置条件",
    "操作步骤", "期望结果", "是否执行",
]


class FakeRunner:
    calls = []

    def run_case(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "success": True,
            "results": [{
                "success": True,
                "msg": "ok",
                "verification": {"passed": True, "evidence": ["页面可见"]},
            }],
            "trace": [{
                "goal": kwargs["steps"][-1]["goal"],
                "all_actions": [{"action": "click", "parameters": {"role": "link"}}],
                "completion_evidence": ["页面可见"],
                "agent_events": [],
            }],
            "collaboration": {"model_calls": 1, "event_count": 1},
        }

class CompleteFakeRunner(FakeRunner):
    def run_case(self, **kwargs):
        self.calls.append(kwargs)
        steps = kwargs["steps"]
        action_names = [
            "fill", "fill", "select_option",
        ] + ["click"] * max(0, len(steps) - 3)
        return {
            "success": True,
            "results": [
                {
                    "success": True,
                    "msg": "ok",
                    "verification": {"passed": True, "evidence": ["verified"]},
                }
                for _step in steps
            ],
            "trace": [
                {
                    "goal": step["goal"],
                    "all_actions": [{"action": action_names[index], "parameters": {}}],
                    "completion_evidence": ["verified"],
                    "agent_events": [],
                }
                for index, step in enumerate(steps)
            ],
            "collaboration": {"model_calls": 1, "event_count": 1},
        }


class TrainingTests(unittest.TestCase):
    def test_sensitive_modules_are_fail_closed(self):
        from web_agent.runner import SENSITIVE_MODULES

        self.assertIn("顾客列表", SENSITIVE_MODULES)
        self.assertIn("顾客详情", SENSITIVE_MODULES)
        self.assertIn("影像阅览", SENSITIVE_MODULES)
    def test_train_is_a_first_class_command(self):
        from web_agent.commands import _normalized_argv, build_parser

        self.assertEqual(_normalized_argv(["train"]), ["train"])
        args = build_parser().parse_args(["train"])
        self.assertEqual(args.file, "test_cases/webagent_test_case.xlsx")
        self.assertEqual(args.holdout_percent, 15)
        self.assertEqual(args.repeat, 1)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workbook = self.root / "cases.xlsx"
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.title = "自动化测试用例"
        sheet.append(HEADERS)
        sheet.append([
            "SAFE", "https://example.test/login", "首页", "查看首页", "P0",
            "已登录成功", "查看首页", "首页可见", "是",
        ])
        sheet.append([
            "WRITE", "", "顾客详情", "修改资料", "P0",
            "已登录，进入顾客详情页", "修改姓名并保存", "保存成功", "是",
        ])
        sheet.append([
            "DELETE", "", "案例库", "删除案例", "P0",
            "已登录", "删除案例", "删除成功", "否",
        ])
        book.save(self.workbook)
        book.close()
        FakeRunner.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def test_selection_is_fail_closed_for_writes_and_disabled_rows(self):
        catalog = load_curriculum(self.workbook)
        selected, skipped = select_curriculum(
            catalog, TrainingOptions(include_holdout=True)
        )
        self.assertEqual([case.case_id for case in selected], ["SAFE"])
        reasons = {item["case_id"]: item["reason"] for item in skipped}
        self.assertEqual(reasons["WRITE"], "capability_gap")
        self.assertEqual(reasons["DELETE"], "source_disabled")

    def test_explicit_case_does_not_bypass_holdout(self):
        from dataclasses import replace

        catalog = load_curriculum(self.workbook)
        candidate_id = next(
            f"HOLDOUT-{index}"
            for index in range(1000)
            if _is_holdout(f"HOLDOUT-{index}", 50)
        )
        catalog.cases = [
            replace(catalog.cases[0], case_id=candidate_id)
        ]
        selected, skipped = select_curriculum(
            catalog,
            TrainingOptions(case_ids=(candidate_id,), holdout_percent=50),
        )
        self.assertEqual(selected, [])
        self.assertTrue(any(
            item["case_id"] == candidate_id and item["reason"] == "holdout"
            for item in skipped
        ))
        selected, _skipped = select_curriculum(
            catalog,
            TrainingOptions(case_ids=(candidate_id,), include_holdout=True),
        )
        self.assertEqual([item.case_id for item in selected], [candidate_id])

    def test_verified_replay_promotes_experience_and_injects_login_setup(self):
        report = run_training(
            str(self.workbook),
            TrainingOptions(
                case_ids=("SAFE",),
                repeat=2,
                holdout_percent=0,
                headless=True,
            ),
            output=str(self.root / "report.json"),
            memory_db=str(self.root / "memory.db"),
            runner_factory=lambda _headless: CompleteFakeRunner(),
        )
        self.assertEqual(report["summary"]["passed_verified"], 2)
        self.assertEqual(report["memory"]["experiences"]["promoted"], 1)
        self.assertEqual(len(FakeRunner.calls), 2)
        goals = [step["goal"] for step in FakeRunner.calls[0]["steps"]]
        self.assertIn("{{credential.username}}", goals[0])
        self.assertIn("{{credential.password}}", goals[1])
        self.assertEqual(FakeRunner.calls[0]["experience_context"], "")
        self.assertTrue((self.root / "report.json").is_file())
        resumed = run_training(
            str(self.workbook),
            TrainingOptions(
                case_ids=("SAFE",),
                holdout_percent=0,
                headless=True,
                resume=True,
            ),
            output=str(self.root / "resume.json"),
            memory_db=str(self.root / "memory.db"),
            runner_factory=lambda _headless: self.fail(
                "resume must not rerun promoted cases"
            ),
        )
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(resumed["summary"]["executed"], 0)
        self.assertEqual(resumed["selection"]["selected_count"], 0)
        self.assertTrue(any(
            item["reason"] == "resume_promoted"
            for item in resumed["selection"]["skipped"]
        ))
        self.assertEqual(len(FakeRunner.calls), 2)


    def test_quarantined_case_is_not_retried_by_default(self):
        catalog = load_curriculum(self.workbook)
        safe = next(case for case in catalog.cases if case.case_id == "SAFE")
        memory_path = self.root / "quarantine.db"
        memory = TrainingMemory(memory_path)
        failed = {
            "success": False,
            "evidence_backed": False,
            "action_count": 1,
            "verification_count": 0,
            "duration_seconds": 0.1,
            "error": "assertion failed",
        }
        for run_id in ("failed-1", "failed-2"):
            memory.record_attempt(
                run_id, catalog.source_hash, safe, failed, {"trace": []}
            )

        report = run_training(
            str(self.workbook),
            TrainingOptions(case_ids=("SAFE",), holdout_percent=0),
            output=str(self.root / "quarantine.json"),
            memory_db=str(memory_path),
            runner_factory=lambda _headless: self.fail(
                "quarantined case must not start a browser"
            ),
        )
        self.assertEqual(report["selection"]["selected_count"], 0)
        self.assertTrue(any(
            item["reason"] == "quarantined"
            for item in report["selection"]["skipped"]
        ))

    def test_truncated_success_never_promotes_experience(self):
        report = run_training(
            str(self.workbook),
            TrainingOptions(
                case_ids=("SAFE",),
                holdout_percent=0,
                headless=True,
            ),
            output=str(self.root / "truncated.json"),
            memory_db=str(self.root / "truncated.db"),
            runner_factory=lambda _headless: FakeRunner(),
        )
        self.assertEqual(report["summary"]["unsupported_pass"], 1)
        self.assertEqual(report["memory"]["experiences"]["candidate"], 1)


    def test_validation_does_not_start_browser(self):
        report = run_training(
            str(self.workbook),
            TrainingOptions(case_ids=("SAFE",), holdout_percent=0),
            output=str(self.root / "validate.json"),
            memory_db=str(self.root / "unused.db"),
            validate_only=True,
            runner_factory=lambda _headless: self.fail("browser must not start"),
        )
        self.assertEqual(report["status"], "validated")
        self.assertEqual(report["summary"]["executed"], 0)
        self.assertFalse((self.root / "unused.db").exists())


if __name__ == "__main__":
    unittest.main()
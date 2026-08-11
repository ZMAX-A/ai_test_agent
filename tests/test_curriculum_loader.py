import tempfile
import unittest
from pathlib import Path

import openpyxl

from loader.curriculum_loader import (
    compile_acceptance, load_curriculum, split_steps,
)


HEADERS = [
    "用例ID", "起始网址", "模块", "测试场景", "优先级", "前置条件",
    "操作步骤", "期望结果", "是否执行",
]


class CurriculumLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "cases.xlsx"

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, rows):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "自动化测试用例"
        sheet.append(HEADERS)
        for row in rows:
            sheet.append(row)
        workbook.save(self.path)
        workbook.close()

    def test_splits_newlines_and_inline_numbered_steps(self):
        self.assertEqual(
            split_steps("1.打开页面 2.点击按钮\n3.查看结果"),
            ("打开页面", "点击按钮", "查看结果"),
        )

    def test_inherits_url_and_normalizes_priority(self):
        self._write([
            ["A", "https://example.test/login", "首页", "首页", "P0", "", "打开", "可见", "是"],
            ["B", "", "首页", "搜索", "p1", "", "点击搜索", "结果可见", "是"],
            ["C", "", "首页", "筛选", "中", "", "点击筛选", "结果可见", "是"],
        ])
        catalog = load_curriculum(self.path)
        self.assertEqual(
            [case.start_url for case in catalog.cases],
            ["https://example.test/login"] * 3,
        )
        self.assertEqual(
            [case.priority for case in catalog.cases],
            ["P0", "P1", "P2"],
        )

    def test_records_errors_gaps_and_disabled_destructive_case(self):
        self._write([
            ["A", "", "顾客列表", "查找存在的用户", "P1", "已登录", "点击顾客", "", "是"],
            ["B", "", "顾客详情", "删除影像", "P1", "已登录", "点击删除", "删除成功", "否"],
            ["C", "", "首页", "邮箱搜索", "P1", "已登录", "输入 customer@example.com", "显示：结果", "是"],
        ])
        catalog = load_curriculum(self.path, "https://example.test/login")
        self.assertTrue(any(issue.code == "missing_expected" for issue in catalog.errors))
        self.assertTrue(catalog.cases[0].capability_gaps)
        self.assertEqual(catalog.cases[1].risk, "destructive")
        self.assertFalse(catalog.cases[1].enabled)
        self.assertTrue(any(
            "明文邮箱" in item
            for item in catalog.cases[2].capability_gaps
        ))

    def test_compiles_logged_in_case_and_negative_credential_reference(self):
        self._write([
            ["A", "https://example.test/login", "首页", "查看首页", "P0", "已登录", "查看首页", "首页可见", "是"],
            ["B", "", "账号登录", "登录失败-错误密码", "P1", "打开登录页面",
             "1.输入正确账号 2.输入错误密码 3.点击登录", "提示错误", "是"],
        ])
        catalog = load_curriculum(self.path)
        logged_in = catalog.cases[0].runner_steps()
        self.assertIn("{{credential.username}}", logged_in[0]["goal"])
        self.assertIn("{{credential.password}}", logged_in[1]["goal"])
        negative = catalog.cases[1].runner_steps()
        self.assertIn("{{credential.invalid.password}}", negative[3]["goal"])
        self.assertEqual(negative[-1]["success_criteria"], "提示错误")


    def test_compiles_customer_list_precondition_as_setup_navigation(self):
        self._write([[
            "A", "https://example.test/login", "顾客列表", "筛选",
            "P1", "已登录并进入顾客列表页", "点击筛选", "展示结果", "是",
        ]])
        case = load_curriculum(self.path).cases[0]
        goals = [step["goal"] for step in case.runner_steps()]
        self.assertEqual(goals[4], "点击顾客档案菜单")
        self.assertEqual(goals[-1], "点击筛选")

        redundant = list(case.steps)
        redundant.insert(0, "进入顾客档案列表")
        from dataclasses import replace
        optimized = replace(case, steps=tuple(redundant))
        optimized_goals = [step["goal"] for step in optimized.runner_steps()]
        self.assertEqual(optimized_goals.count("点击顾客档案菜单"), 1)
        self.assertNotIn("进入顾客档案列表", optimized_goals)

    def test_compiles_display_and_navigation_acceptance(self):
        self.assertEqual(
            compile_acceptance("展示：顾客档案、美际学院、案例管理、设置"),
            {"text_contains": ["顾客档案", "美际学院", "案例管理", "设置"]},
        )
        self.assertEqual(
            compile_acceptance("跳转到顾客档案列表页"),
            {"url_changed": True, "text_contains": ["顾客档案"]},
        )
        self.assertEqual(
            compile_acceptance("URL 包含 /customer/U，跳转成功"),
            {"url_contains": ["/customer/U"]},
        )
        self.assertEqual(
            compile_acceptance("卡片包含：姓名、年龄、详情按钮"),
            "卡片包含：姓名、年龄、详情按钮",
        )


if __name__ == "__main__":
    unittest.main()
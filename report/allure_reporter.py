"""
Allure 报告封装
使用 allure-python-commons 原生 API，不依赖 pytest。
通过 AllureReporter + AllureFileLogger 管理完整生命周期，
生成的 allure-results 目录可被 allure CLI / Jenkins 插件解析。

用法:
    report = AllureReport("allure-results")
    report.start_test("测试名称", feature="模块", story="URL")
    report.start_step("步骤描述")
    # ... 执行测试 ...
    report.stop_step(status="passed")
    # 失败时挂载附件:
    report.attach_screenshot(page, "失败截图")
    report.attach_text(html_content, "页面DOM", AttachmentType.HTML)
    report.stop_test(status="passed")
"""

import os
import allure_commons
from allure_commons.reporter import AllureReporter
from allure_commons.logger import AllureFileLogger
from allure_commons.model2 import (
    TestResult,
    TestStepResult,
    Status,
    StatusDetails,
    Label,
)
from allure_commons.types import AttachmentType, LabelType
from allure_commons.utils import uuid4, now, host_tag, thread_tag


class AllureReport:
    """Allure 报告生命周期管理器，封装 AllureReporter + AllureFileLogger"""

    def __init__(self, report_dir: str = "allure-results", clean: bool = False):
        self.report_dir = os.path.abspath(report_dir)

        # 内存项目追踪器
        self.reporter = AllureReporter()

        # 文件写入器 —— 监听 report_result / report_attached_file 等钩子
        self.file_logger = AllureFileLogger(self.report_dir, clean)
        allure_commons.plugin_manager.register(self.file_logger)

        self._test_uuid: str | None = None
        self._step_uuid: str | None = None

    # ── Test 生命周期 ──────────────────────────────────

    def start_test(self, name: str, feature: str | None = None,
                   story: str | None = None) -> "AllureReport":
        """开始一个测试用例，设置标签"""
        self._test_uuid = uuid4()
        test = TestResult(
            uuid=self._test_uuid,
            name=name,
            fullName=name,
            start=now(),
            labels=[
                Label(name=LabelType.FRAMEWORK, value="custom"),
                Label(name=LabelType.LANGUAGE, value="python"),
                Label(name=LabelType.HOST, value=host_tag()),
                Label(name=LabelType.THREAD, value=thread_tag()),
            ],
        )
        if feature:
            test.labels.append(Label(name=LabelType.FEATURE, value=feature))
        if story:
            test.labels.append(Label(name=LabelType.STORY, value=story))
        self.reporter.schedule_test(self._test_uuid, test)
        print(f"  [ALLURE] 测试开始: {name}")
        return self

    def stop_test(self, status: str = Status.PASSED) -> "AllureReport":
        """结束测试，写入 allure-results/*-result.json"""
        if self._test_uuid:
            test = self.reporter.get_test(self._test_uuid)
            if test:
                test.stop = now()
                if test.status is None:
                    test.status = status
                self.reporter.close_test(self._test_uuid)
            else:
                print(f"  [ALLURE] [WARN] 测试 {self._test_uuid} 已丢失")
            self._test_uuid = None
            print(f"  [ALLURE] 测试结束，结果已写入 {self.report_dir}")
        return self

    # ── Step 生命周期 ──────────────────────────────────

    def start_step(self, title: str) -> "AllureReport":
        """开始一个执行步骤"""
        self._step_uuid = uuid4()
        step = TestStepResult(name=title, start=now())
        self.reporter.start_step(self._test_uuid, self._step_uuid, step)
        return self

    def stop_step(self, status: str = Status.PASSED,
                  message: str | None = None,
                  trace: str | None = None) -> "AllureReport":
        """结束当前步骤，可设置状态与错误详情"""
        if self._step_uuid:
            details = None
            if message or trace:
                details = StatusDetails(message=message, trace=trace)
            self.reporter.stop_step(
                self._step_uuid,
                stop=now(),
                status=status,
                statusDetails=details,
            )
            self._step_uuid = None
        return self

    # ── 附件 ──────────────────────────────────────────

    def attach_screenshot(self, page, name: str = "截图") -> "AllureReport":
        """
        截取 Playwright 页面并挂载为 PNG 附件。
        临时截图写入 report_dir 后自动清理。
        """
        tmp = os.path.join(self.report_dir, f"._attach_{uuid4()}.png")
        try:
            page.screenshot(path=tmp)
            self.reporter.attach_file(
                uuid4(), tmp,
                name=name,
                attachment_type=AttachmentType.PNG,
                parent_uuid=self._test_uuid,
            )
        except Exception:
            pass  # 截图失败不干扰流程
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        return self

    def attach_text(self, body: str, name: str = "文本",
                    attachment_type=AttachmentType.TEXT) -> "AllureReport":
        """挂载文本附件"""
        if body:
            self.reporter.attach_data(
                uuid4(), body,
                name=name,
                attachment_type=attachment_type,
                parent_uuid=self._test_uuid,
            )
        return self

"""多 Agent v4：生成标准用例时消除前置条件已覆盖的登录步骤。"""

from __future__ import annotations

import runner.multi_agent_runner as base_runner

# 导入 v3 以安装认证恢复推理和安全执行器。
from runner.collaborative_runner_v3 import CollaborativeTestRunnerV3


LOGIN_SETUP_KEYWORDS = (
    "打开登录", "登录页面", "用户名输入", "账号输入",
    "密码输入", "输入用户名", "输入账号", "输入密码", "点击登录",
)


def filter_login_setup_trace(trace: list[dict], preconditions: str) -> list[dict]:
    if "登录" not in (preconditions or ""):
        return trace
    filtered = [
        entry for entry in trace
        if not any(keyword in entry.get("goal", "") for keyword in LOGIN_SETUP_KEYWORDS)
    ]
    # 防止过度过滤：没有业务动作时仍保留原始轨迹供诊断。
    return filtered or trace


_original_generate_and_save = base_runner.case_generator.generate_and_save


def _generate_business_trace_only(*args, **kwargs):
    trace = kwargs.get("trace")
    preconditions = kwargs.get("preconditions", "")
    if trace is not None:
        kwargs["trace"] = filter_login_setup_trace(trace, preconditions)
    return _original_generate_and_save(*args, **kwargs)


base_runner.case_generator.generate_and_save = _generate_business_trace_only


class CollaborativeTestRunnerV4(CollaborativeTestRunnerV3):
    pass

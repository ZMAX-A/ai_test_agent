from config.settings import settings


class SelfHealer:
    """自愈降级控制器：判断是否重试、是否切换感知链路、全局熔断保护

    职责边界：
    - 单步骤内的失败计数 + 重试判断（纵向）
    - 跨步骤的连续失败计数 → 全局熔断（横向）
    - 感知链路降级（Aria → Visual）
    - API调用次数追踪
    """

    def __init__(self):
        # ── 单步骤状态（reset_step 时重置） ──
        self.step_fail_count = 0
        self.use_visual = False

        # ── 全局状态（整个测试周期保持） ──
        self.consecutive_step_fails = 0
        """连续失败的步骤数（跨步骤），达到阈值熔断"""
        self.fuse_blown = False
        """熔断开关，触发后跳过剩余所有步骤"""
        self.api_call_count = 0
        """本测试全局 LLM API 调用次数"""

    # ── 熔断状态 ──────────────────────────────────────────────

    @property
    def is_fuse_blown(self) -> bool:
        """全局熔断是否已触发"""
        return self.fuse_blown

    @property
    def api_budget_exhausted(self) -> bool:
        """API调用额度是否耗尽"""
        return self.api_call_count >= settings.MAX_API_CALLS

    def check_fuse(self) -> bool:
        """每次步骤开始前调用：检查是否应触发熔断"""
        if self.fuse_blown:
            return True
        if self.consecutive_step_fails >= settings.CONSECUTIVE_STEP_FAIL_LIMIT:
            self.fuse_blown = True
            print(f"[WARN]  全局熔断触发：连续 {self.consecutive_step_fails} 个步骤失败 ≥ 阈值 {settings.CONSECUTIVE_STEP_FAIL_LIMIT}")
            return True
        if self.api_budget_exhausted:
            self.fuse_blown = True
            print(f"[WARN]  全局熔断触发：API调用次数 {self.api_call_count} ≥ 上限 {settings.MAX_API_CALLS}")
            return True
        return False

    # ── 单步骤重试 ────────────────────────────────────────────

    def record_fail(self):
        """记录一次步骤内执行失败"""
        self.step_fail_count += 1
        if self.step_fail_count >= settings.MAX_STEP_RETRY:
            self.use_visual = True

    def reset_step(self):
        """重置单步骤状态（每步开始时调用）"""
        self.step_fail_count = 0
        self.use_visual = False

    def should_retry(self) -> bool:
        """判断当前步骤是否应继续重试"""
        return self.step_fail_count < settings.MAX_STEP_RETRY + 1

    # ── 跨步骤计数（供 runner 每步结束后调用） ────────────────

    def record_step_success(self):
        """步骤成功后清空连续失败计数"""
        self.consecutive_step_fails = 0

    def record_step_fail(self):
        """步骤失败后递增连续失败计数，触发熔断检查"""
        self.consecutive_step_fails += 1
        self.check_fuse()

    def record_api_call(self):
        """记录一次 LLM API 调用（Planner 或 Executor）"""
        self.api_call_count += 1

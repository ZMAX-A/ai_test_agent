"""对日志中的输入值进行脱敏的 Playwright 执行器。"""

from contextlib import redirect_stdout
from io import StringIO

from executor.playwright_exec import PlaywrightExecutor


class SecurePlaywrightExecutor(PlaywrightExecutor):
    def execute(self, action_info: dict) -> dict:
        action = action_info.get("action", "")
        params = dict(action_info.get("parameters", {}))
        safe_params = dict(params)
        if safe_params.get("value") not in (None, ""):
            safe_params["value"] = f"<redacted:{len(str(safe_params['value']))}>"
        print(f"[BOT] {action} | {safe_params}")
        # 基础执行器当前会打印原始 params；在安全入口中捕获这部分输出。
        with redirect_stdout(StringIO()):
            return super().execute(action_info)

import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # LLM配置
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")

    # 视觉模型配置
    VL_API_KEY = os.getenv("VL_API_KEY", "")
    VL_BASE_URL = os.getenv("VL_BASE_URL", "")
    VL_MODEL = os.getenv("VL_MODEL", "")

    # 模型调用必须有硬超时，避免浏览器和测试任务无限挂起。
    LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", 90))
    LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", 1))

    # 执行配置
    PAGE_TIMEOUT = int(os.getenv("PAGE_TIMEOUT", 60000))
    ACTION_TIMEOUT = int(os.getenv("ACTION_TIMEOUT", 30000))
    NAVIGATION_SETTLE_MS = int(os.getenv("NAVIGATION_SETTLE_MS", 2000))
    """页面导航完成后的稳定等待时间，便于异步内容渲染和有头观察"""
    MAX_GLOBAL_STEPS = int(os.getenv("MAX_GLOBAL_STEPS", 30))
    MAX_REASONING_ROUNDS = int(os.getenv("MAX_REASONING_ROUNDS", 10))
    """探索模式单个目标允许的 Observe-Act-Verify 最大轮数"""
    EXPLORE_TASK_TIMEOUT_SECONDS = int(os.getenv("EXPLORE_TASK_TIMEOUT_SECONDS", 300))
    """单条探索用例的总时限，覆盖所有步骤和模型调用"""
    MAX_STEP_RETRY = int(os.getenv("MAX_STEP_RETRY", 2))

    # ── 硬性熔断阈值 ──
    CONSECUTIVE_STEP_FAIL_LIMIT = int(os.getenv("CONSECUTIVE_STEP_FAIL_LIMIT", 3))
    """连续N个步骤全部失败，触发全局熔断，终止整个测试"""
    MAX_API_CALLS = int(os.getenv("MAX_API_CALLS", 50))
    """单次测试全局API调用次数上限，防止意外消耗过多额度"""

    # ── 缓存生命周期 ──
    CACHE_TTL_DAYS = int(os.getenv("CACHE_TTL_DAYS", 7))
    """元素缓存在硬盘上的存活天数，超期自动作废"""

    # ── 登录凭证 ──
    LOGIN_URL = os.getenv("LOGIN_URL", "")
    LOGIN_USERNAME = os.getenv("LOGIN_USERNAME", "")
    LOGIN_PASSWORD = os.getenv("LOGIN_PASSWORD", "")

    # ── 标准用例库路径 ──
    STANDARD_XLSX_PATH = os.getenv(
        "STANDARD_XLSX_PATH",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "test_cases", "standard.xlsx")
    )
    EXPLORE_XLSX_PATH = os.getenv(
        "EXPLORE_XLSX_PATH",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "test_cases", "explore_cases.xlsx")
    )
    GENERATED_SCRIPTS_DIR = os.getenv(
        "GENERATED_SCRIPTS_DIR",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "generated_scripts")
    )

    @staticmethod
    def get_credential(key: str = "") -> dict:
        """
        按 credential_key 获取登录凭证。
        空 key 返回默认 LOGIN_USERNAME/LOGIN_PASSWORD。
        key='prod' 则读取 CRED_PROD_USERNAME / CRED_PROD_PASSWORD。
        """
        if not key:
            return {
                "username": os.getenv("LOGIN_USERNAME", ""),
                "password": os.getenv("LOGIN_PASSWORD", ""),
            }
        prefix = f"CRED_{key.upper()}"
        return {
            "username": os.getenv(f"{prefix}_USERNAME", ""),
            "password": os.getenv(f"{prefix}_PASSWORD", ""),
        }

settings = Settings()

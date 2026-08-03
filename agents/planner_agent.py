from openai import OpenAI
from config.settings import settings
from utils.json_utils import safe_parse_json
from agents.base_agent import BaseAgent
from core.reasoning_engine import normalize_plan

class PlannerAgent(BaseAgent):
    """规划Agent：将自然语言测试需求拆解为标准化步骤数组"""
    def __init__(self):
        self.client = OpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=settings.LLM_MAX_RETRIES,
        )
        self.model_name = settings.LLM_MODEL
        self.prompt_template = """
你是专业测试用例设计师，将用户的自然语言测试需求拆解为有序的测试步骤数组。

重要原则：
1. 每个步骤为原子操作，包含 step、goal、success_criteria（可观察、可验证的完成条件）
2. **避免冗余步骤**：如果输入内容后页面会自动跳转/搜索（如百度、Google搜索框填写后自动出结果），不要在"填写"步骤后额外加"点击搜索按钮"步骤
3. 如果确实需要点击触发搜索，使用 goto 动作类型作为跳转信号
4. 只输出纯JSON数组，不要任何解释、markdown、多余文字
5. 可选动作类型：goto、fill、click、assert_text、assert_url、scroll、finish
6. 步骤粒度要细，避免一步包含多个操作

输出格式示例：
[
    {"step":1,"goal":"打开百度首页","success_criteria":"当前URL为百度首页"},
    {"step":2,"goal":"在搜索框输入世界杯","success_criteria":"搜索框的值为世界杯"},
    {"step":3,"goal":"验证搜索结果","success_criteria":"页面标题或结果区包含世界杯"}
]

用户需求：{user_task}
"""

    def ask(self, context: dict) -> dict:
        user_task = context.get("user_task", "")
        try:
            prompt = self.prompt_template.replace("{user_task}", user_task)
            resp = self.client.chat.completions.create(
                model=settings.LLM_MODEL,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = resp.choices[0].message.content
            steps = normalize_plan(safe_parse_json(raw))
        except Exception as e:
            print(f"[FAIL] Planner LLM调用失败: {e}")
            steps = []
        return {"steps": steps}

"""
Pydantic 动作 Schema — 强校验 + 自校正

LLM 输出的动作 JSON 通过此模块校验，不合法时自动反馈错误原因，
要求 LLM 修正后重新输出（最多 2 次自校正）。
"""
from typing import Optional, Literal, Union
from pydantic import BaseModel, Field, model_validator
import re


# ═══════════════════════════════════════════════
#  白名单动作枚举
# ═══════════════════════════════════════════════
ALLOWED_ACTIONS = Literal[
    "click", "fill", "select_option",
    "assert_text", "assert_url", "assert_title", "assert_visual",
    "scroll", "scroll_to_element",
    "go_back", "refresh", "goto",
    "close_popup",
    "get_element_attr", "get_page_info",
    "finish",
]


# ═══════════════════════════════════════════════
#  动作参数模型
# ═══════════════════════════════════════════════

class ClickParams(BaseModel):
    locator_strategy: str = "role"
    role: str = ""
    name: Optional[str] = None
    index: Optional[int] = None
    som_index: Optional[int] = None

    @model_validator(mode="after")
    def check_locator(self):
        if not self.role and self.som_index is None:
            raise ValueError("click 必须提供 role 或 som_index")
        return self


class FillParams(BaseModel):
    locator_strategy: str = "role"
    role: str = ""
    name: Optional[str] = None
    index: Optional[int] = None
    som_index: Optional[int] = None
    value: str = ""

    @model_validator(mode="after")
    def check_locator(self):
        if not self.role and self.som_index is None:
            raise ValueError("fill 必须提供 role 或 som_index")
        if not self.value:
            raise ValueError("fill 必须提供 value")
        return self


class SelectOptionParams(BaseModel):
    locator_strategy: str = "role"
    role: str = "combobox"
    name: Optional[str] = None
    index: Optional[int] = None
    som_index: Optional[int] = None
    option_text: str = ""


class AssertTextParams(BaseModel):
    locator_strategy: str = "role"
    role: str = ""
    name: Optional[str] = None
    index: Optional[int] = None
    expect_text: str = ""

    @model_validator(mode="after")
    def check(self):
        if not self.role:
            raise ValueError("assert_text 必须提供 role")
        if not self.expect_text:
            raise ValueError("assert_text 必须提供 expect_text")
        return self


class AssertUrlParams(BaseModel):
    expect_url_contains: str = ""


class AssertTitleParams(BaseModel):
    expect_title_contains: str = ""


class AssertVisualParams(BaseModel):
    expect_desc: str = ""


class ScrollParams(BaseModel):
    direction: Literal["down", "up"] = "down"


class ScrollToElementParams(BaseModel):
    locator_strategy: str = "role"
    role: str = ""
    name: Optional[str] = None
    index: Optional[int] = None


class GoBackParams(BaseModel):
    pass


class RefreshParams(BaseModel):
    pass


class GotoParams(BaseModel):
    url: str = ""

    @model_validator(mode="after")
    def check_url(self):
        if not self.url:
            raise ValueError("goto 必须提供 url")
        return self


class ClosePopupParams(BaseModel):
    pass


class GetElementAttrParams(BaseModel):
    locator_strategy: str = "role"
    role: str = ""
    name: Optional[str] = None
    attr_name: str = "innerText"


class GetPageInfoParams(BaseModel):
    pass


class FinishParams(BaseModel):
    result: str = "success"


# ═══════════════════════════════════════════════
#  顶层动作模型
# ═══════════════════════════════════════════════

class ActionModel(BaseModel):
    thought: str = ""
    action: ALLOWED_ACTIONS
    parameters: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_parameters(self):
        action = self.action
        params = self.parameters

        if params.get("role") and params.get("som_index") is not None:
            raise ValueError("role(+index) 与 som_index 必须二选一，不能同时提供")

        param_models = {
            "click": ClickParams,
            "fill": FillParams,
            "select_option": SelectOptionParams,
            "assert_text": AssertTextParams,
            "assert_url": AssertUrlParams,
            "assert_title": AssertTitleParams,
            "assert_visual": AssertVisualParams,
            "scroll": ScrollParams,
            "scroll_to_element": ScrollToElementParams,
            "go_back": GoBackParams,
            "refresh": RefreshParams,
            "goto": GotoParams,
            "close_popup": ClosePopupParams,
            "get_element_attr": GetElementAttrParams,
            "get_page_info": GetPageInfoParams,
            "finish": FinishParams,
        }

        model_cls = param_models.get(action)
        if model_cls is None:
            raise ValueError(f"未知动作类型: {action}")

        try:
            validated = model_cls(**params)
            self.parameters = validated.model_dump()
        except Exception as e:
            raise ValueError(f"参数校验失败 [{action}]: {e}")

        return self


# ═══════════════════════════════════════════════
#  清洗 + 校验工具
# ═══════════════════════════════════════════════

def clean_llm_output(raw_text: str) -> str:
    """清洗 LLM 输出：去 markdown、去多余文本、只提取 JSON"""
    if not raw_text:
        return ""
    clean = raw_text.strip()
    # 去 markdown 代码块
    clean = re.sub(r"```(?:json|python)?\s*", "", clean)
    clean = re.sub(r"```\s*", "", clean)
    clean = clean.strip()
    # 如果整段不是以 { 开头，尝试提取第一个 JSON 对象
    if not clean.startswith("{"):
        m = re.search(r"\{.*\}", clean, re.DOTALL)
        if m:
            clean = m.group(0)
    return clean


def validate_action(action_json: dict, max_retries: int = 2) -> dict | None:
    """
    校验并返回合法的 action dict。
    不合法返回 None（调用方应处理重试逻辑）。
    """
    try:
        validated = ActionModel(**action_json)
        return validated.model_dump()
    except Exception as e:
        return None


def get_validation_error(action_json: dict) -> str:
    """返回校验错误的可读描述（用于反馈给 LLM）"""
    try:
        ActionModel(**action_json)
        return ""
    except Exception as e:
        return f"动作校验失败: {e}\n请检查 action 是否为白名单动作、parameters 参数是否完整且类型正确。\n白名单动作: {', '.join(ActionModel.model_fields['action'].annotation.__args__)}"


def get_schema_prompt_hint() -> str:
    """生成动作 Schema 提示文本（嵌入 ExecutorAgent prompt）"""
    return """
【动作输出 Schema 约束】
必须输出严格的 JSON，每个动作的必填参数如下：
- click: role(必填) 或 som_index, name+index可选
- fill: role(必填) 或 som_index, value(必填), name+index可选
- select_option: role=combobox, option_text(要选的文本)
- assert_text: role(必填), expect_text(必填)
- assert_url: expect_url_contains(必填)
- assert_title: expect_title_contains(必填)
- assert_visual: expect_desc(必填)
- scroll: direction="down"|"up"
- scroll_to_element: role(必填)
- go_back: 无参数
- refresh: 无参数
- goto: url(必填, 要导航的完整URL)
- close_popup: 无参数, 自动关闭弹窗/提示框
- get_element_attr: role(必填), attr_name(默认innerText)
- get_page_info: 无参数, 返回{url, title}
- finish: result="success"或"fail:原因"
输出格式: {"thought":"思考","action":"动作名","parameters":{...}}
只输出JSON，不要markdown包覆，不要多余文字。
"""

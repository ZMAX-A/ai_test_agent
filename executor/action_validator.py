"""动作校验器：对LLM输出的Action JSON进行Schema强校验，拦截脏数据进入执行层

白名单动作机制（架构强制）：
LLM仅可输出固定动作集合，校验器确保每个字段符合规范后再进入 Playwright 执行层。
"""

from typing import Optional

# ── 白名单动作 Schema ──────────────────────────────────────
# required: 至少提供其中之一的参数
# any_of:  多选一组（如 role/name 与 som_index 二选一）
ACTION_SCHEMA: dict = {
    "click": {
        "required": [],
        "any_of": [("role",), ("som_index",)],
        "optional": ["locator_strategy", "name", "index"],
        "description": "点击元素",
    },
    "fill": {
        "required": ["value"],
        "any_of": [("role",), ("som_index",)],
        "optional": ["locator_strategy", "name", "index"],
        "description": "输入框中填入文本",
    },
    "assert_text": {
        "required": ["expect_text"],
        "any_of": [("role",)],
        "optional": ["locator_strategy", "name", "index"],
        "description": "断言元素文本包含预期文字",
    },
    "assert_url": {
        "required": ["expect_url_contains"],
        "any_of": [],
        "optional": [],
        "description": "断言当前URL包含字符串",
    },
    "assert_title": {
        "required": ["expect_title_contains"],
        "any_of": [],
        "optional": [],
        "description": "断言页面标题包含字符串",
    },
    "assert_visual": {
        "required": ["expect_desc"],
        "any_of": [],
        "optional": [],
        "description": "视觉断言：截图比预期描述",
    },
    "scroll": {
        "required": ["direction"],
        "any_of": [],
        "optional": [],
        "description": "页面滚动（down/up）",
    },
    "select_option": {
        "required": [],
        "any_of": [("role",), ("som_index",)],
        "optional": ["locator_strategy", "name", "index", "option_text"],
        "description": "点击下拉框(combobox)并选择指定文本的选项",
    },
    "go_back": {
        "required": [], "any_of": [], "optional": [],
        "description": "返回上一页",
    },
    "refresh": {
        "required": [], "any_of": [], "optional": [],
        "description": "刷新当前页面",
    },
    "goto": {
        "required": ["url"],
        "any_of": [], "optional": [],
        "description": "直接导航到指定URL",
    },
    "scroll_to_element": {
        "required": [],
        "any_of": [("role",), ("som_index",)],
        "optional": ["locator_strategy", "name", "index"],
        "description": "滚动到目标元素可视区域",
    },
    "close_popup": {
        "required": [], "any_of": [], "optional": [],
        "description": "自动识别并关闭弹窗/提示/广告",
    },
    "get_element_attr": {
        "required": [],
        "any_of": [("role",), ("som_index",)],
        "optional": ["locator_strategy", "name", "index", "attr_name"],
        "description": "读取指定元素的属性值",
    },
    "get_page_info": {
        "required": [], "any_of": [], "optional": [],
        "description": "获取当前页面URL和标题",
    },
    "finish": {
        "required": [],
        "any_of": [],
        "optional": ["result"],
        "description": "标记当前步骤完成",
    },
}

ALLOWED_ACTIONS = set(ACTION_SCHEMA.keys())
LOCATOR_FIELDS = {"locator_strategy", "role", "name", "som_index"}
PLAN_ONLY_ACTIONS = {"goto"}


def validate_action(action_info: dict) -> tuple[bool, str]:
    """校验 LLM 输出动作是否合法

    Args:
        action_info: LLM 输出的字典，含 action / parameters / thought 等键

    Returns:
        (True, "") 或 (False, "错误描述")
    """
    if not isinstance(action_info, dict):
        return False, f"动作不是字典类型: {type(action_info).__name__}"

    action = action_info.get("action")
    params = action_info.get("parameters", {})

    # ── 检查 action 名称 ──
    if not action or not isinstance(action, str):
        return False, "缺少 action 字段或非字符串"
    if action not in ALLOWED_ACTIONS:
        if action in PLAN_ONLY_ACTIONS:
            return False, f"动作 '{action}' 仅用于 Planner 规划阶段，Executor 不可执行"
        return False, f"不支持的动作 '{action}'，允许列表: {', '.join(sorted(ALLOWED_ACTIONS))}"

    # ── finish 动作无需额外参数检查 ──
    if action == "finish":
        return True, ""

    # ── parameters 必须是字典 ──
    if not isinstance(params, dict):
        return False, f"parameters 必须是字典，得到 {type(params).__name__}"

    if params.get("role") and params.get("som_index") is not None:
        return False, "role(+index) 与 som_index 是两种定位方式，必须二选一，不能同时提供"

    # ── 检查未知参数（白名单之外的字段） ──
    schema = ACTION_SCHEMA[action]
    allowed_param_keys = set(schema["required"] + schema["optional"])
    for group in schema.get("any_of", []):
        allowed_param_keys.update(group)
    allowed_param_keys.add("value")  # fill 的值字段

    unknown_keys = set(params.keys()) - allowed_param_keys
    if unknown_keys:
        return False, f"parameter 包含未知字段: {', '.join(sorted(unknown_keys))}"

    # ── 检查 any_of 多选一 ──
    any_of_groups = schema.get("any_of", [])
    if any_of_groups:
        matched = False
        for group in any_of_groups:
            if all(k in params for k in group):
                matched = True
                break
        if not matched:
            group_descs = [" + ".join(g) for g in any_of_groups]
            return False, f"动作 '{action}' 需要提供以下至少一组参数: {' | '.join(group_descs)}"

    # ── 类型校验 ──
    for key, val in params.items():
        if key == "som_index":
            try:
                int(val)
            except (ValueError, TypeError):
                return False, f"som_index 必须是数字，得到 {val!r}"
        elif key == "direction" and val not in ("down", "up"):
            return False, f"scroll direction 必须是 'down' 或 'up'，得到 {val!r}"

    return True, ""


def format_schema_hint() -> str:
    """生成 Schema 说明文本，可嵌入 LLM prompt 帮助模型输出合法 JSON"""
    lines = ["【动作输出约束】"]
    for action, schema in ACTION_SCHEMA.items():
        parts = [f"  - {action}"]
        if schema["required"]:
            parts.append(f"必填: {', '.join(schema['required'])}")
        if schema.get("any_of"):
            groups = [" + ".join(g) for g in schema["any_of"]]
            parts.append(f"（{' ｜ '.join(groups)} 至少一组）")
        if schema["optional"]:
            parts.append(f"可选: {', '.join(schema['optional'])}")
        lines.append("; ".join(parts))
    return "\n".join(lines)

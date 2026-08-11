"""
标准用例生成器 — 输出17列格式（16列定义 + 实际结果），匹配标准库

将探索 trace 转为标准用例，写入 standard.xlsx。
每行一个用例，包含 元素定位器 / 操作类型 / 输入数据 / 断言类型 / 验证点 等完整字段。
"""

import os, sys, json, re
from datetime import datetime
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from case import case_manager


def generate_standard_case(
    trace: list[dict],
    case_id: str,
    case_name: str,
    module: str = "",
    start_url: str = "",
    preconditions: str = "",
    expected: str | dict = "",
) -> dict:
    """
    从探索 trace 转为 text 项目兼容的 16 列标准用例 dict。
    每个 trace 条目只取最后成功的核心动作，忽略失败尝试和噪声。
    """
    locators = []
    operations = []
    input_data_parts = []
    assert_type = ""
    verify_point = ""
    generated_expected = ""
    steps_desc = []

    need_login = preconditions and ("登录" in preconditions or not preconditions.startswith("已"))

    for i, entry in enumerate(trace, 1):
        goal = entry.get("goal", "")
        all_actions = entry.get("all_actions", [])

        # 跳过登录相关步骤（回归时 auto-login 已处理）
        if need_login and any(kw in goal for kw in
                              ("打开登录",)):
            continue

        steps_desc.append(f"{i}.{goal}")

        # 每个 trace 条目只取最后一个核心动作（即成功的那一个）
        last_core = None
        for a in all_actions:
            ak = a.get("action", "")
            if ak in ("finish", "get_page_info", "close_popup", "scroll"):
                continue
            last_core = a

        if not last_core:
            continue

        act = last_core
        act_type = act.get("action", "")
        params = act.get("parameters", {})

        # 取探索时记录的 CSS 选择器（trace 级覆盖）
        trace_css = entry.get("css_selector", "")
        if trace_css:
            act["css_selector"] = trace_css

        if act_type == "click":
            css = act.get("css_selector", "") or _role_to_css(params, act_type)
            locators.append(css)
            operations.append("click")

        elif act_type == "fill":
            value_ref = str(params.get("value", ""))
            if any(token in value_ref for token in (
                "credential.password", "credential.invalid.password"
            )):
                css = "input[type='password']"
            elif any(token in value_ref for token in (
                "credential.username", "credential.invalid.username"
            )):
                css = "input[type='text']"
            else:
                css = act.get("css_selector", "") or _role_to_css(params, act_type)
            locators.append(css)
            operations.append("input")
            input_data_parts.append(params.get("value", ""))

        elif act_type == "select_option":
            css = act.get("css_selector", "") or ".ant-select-selector"
            locators.append(css)
            operations.append("select")
            option = params.get("option_text", "")
            input_data_parts.append(option)

        elif act_type == "goto":
            loc = params.get("url", start_url)
            operations.append("nav")
            locators.append(loc)
            # goto 目标URL自动作为断言验证点
            if "/customer" in loc:
                verify_point = "/customer"
                assert_type = "url_contains"

        elif act_type.startswith("assert_"):
            a_type = act_type.replace("assert_", "")
            assert_type = _map_assert_type(a_type)
            vp = (
                params.get("expect_url_contains", "")
                or params.get("expect_title_contains", "")
                or params.get("expect_text", "")
                or params.get("expect_desc", "")
            )
            if vp:
                verify_point = vp
            if a_type in ("text",) and params.get("expect_text"):
                generated_expected = params["expect_text"]

        elif act_type == "get_page_info":
            operations.append("check")
            locators.append("")

    acceptance = expected
    if isinstance(acceptance, str) and acceptance.strip().startswith("{"):
        try:
            acceptance = json.loads(acceptance)
        except Exception:
            pass
    if isinstance(acceptance, dict):
        url_values = acceptance.get("url_contains", [])
        if not isinstance(url_values, list):
            url_values = [url_values] if url_values else []
        if url_values:
            verify_point = str(url_values[0])
            assert_type = "url_contains"
        elif acceptance.get("url_changed"):
            final_url = next((
                str(entry.get("page_url", ""))
                for entry in reversed(trace)
                if entry.get("page_url")
            ), "")
            final_path = urlparse(final_url).path.rstrip("/")
            if final_path:
                verify_point = final_path
                assert_type = "url_contains"
            elif "/login" in start_url:
                verify_point = "/login"
                assert_type = "url_not_contains"
        text_values = acceptance.get("text_contains", [])
        if not isinstance(text_values, list):
            text_values = [text_values] if text_values else []
        text_values = [str(value) for value in text_values if value]
        if text_values:
            generated_expected = "、".join(text_values)
            if not verify_point:
                verify_point = " | ".join(text_values)
                assert_type = (
                    "text_contains_all" if len(text_values) > 1
                    else "text_contains"
                )
    elif acceptance:
        generated_expected = str(acceptance)
        if "登录成功" in generated_expected:
            verify_point = "/login"
            assert_type = "url_not_contains"
        elif not verify_point:
            verify_point = generated_expected
            assert_type = "text_contains"
    return {
        "用例ID": case_id,
        "case_id": case_id,
        "模块": module or "通用",
        "module": module or "通用",
        "status": "active",
        "start_url": start_url,
        "测试场景": case_name,
        "测试点": (steps_desc[-1] if steps_desc else ""),
        "优先级": "P1",
        "前置条件": preconditions or "已登录",
        "操作步骤": "\n".join(steps_desc),
        "元素定位器": " | ".join(locators),
        "操作类型": " | ".join(operations),
        "输入数据": " | ".join(input_data_parts),
        "期望结果": generated_expected or "成功",
        "验证点": verify_point,
        "断言类型": assert_type or "url_contains",
        "超时(秒)": "5",
        "备注": "探索模式自动生成",
    }


def _role_to_css(params: dict, action: str = "") -> str:
    """role+name → CSS 选择器"""
    role = params.get("role", "")
    name = params.get("name", "")
    idx = params.get("index", "")

    if role == "textbox":
        if idx in (1, "1"):
            return "input[type='password']"
        return "input[type='text']"
    elif role == "button":
        if name:
            return f"button:has-text('{name}')"
        return "button"
    elif role == "link":
        if name:
            return f"a:has-text('{name}')"
        return "a"
    elif role == "combobox":
        return ".ant-select-selector"
    elif role == "searchbox":
        return "input[type='search']"
    elif role == "checkbox":
        return "input[type='checkbox']"
    elif params.get("som_index"):
        if action in ("fill", "input"):
            return "input, textarea, [contenteditable]"
        elif action == "click":
            return "button, a, [role=button], [role=link]"
        return "input, button, a, textarea, select"
    elif name:
        return f"*:has-text('{name}')"
    return role or "input, button, a, textarea, select"


def _map_assert_type(at: str) -> str:
    return {
        "url": "url_contains",
        "url_contains": "url_contains",
        "title": "title_contains",
        "title_contains": "title_contains",
        "text": "text_contains",
        "text_contains": "text_contains",
        "visual": "visual_match",
    }.get(at, "url_contains")


def generate_and_save(
    trace: list[dict],
    case_id: str,
    case_name: str,
    module: str = "",
    preconditions: str = "",
    start_url: str = "",
    expected: str | dict = "",
) -> str:
    """生成标准用例并同时写入 JSON 和 Excel，返回 JSON 路径"""
    case = generate_standard_case(
        trace=trace,
        case_id=case_id,
        expected=expected,
        case_name=case_name,
        module=module,
        start_url=start_url,
        preconditions=preconditions,
    )

    json_path = case_manager.save_case(case)
    if json_path:
        print(f"  [CASE] JSON已保存: {json_path}")

    try:
        from standard.store import get_store
        store = get_store()
        store.save_case(case)
        print(f"  [STORE] Excel已写入: {store.filepath}")
    except Exception as e:
        print(f"  [WARN] Excel写入失败: {e}")

    return json_path

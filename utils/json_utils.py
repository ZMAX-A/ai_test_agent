"""JSON 解析工具 — 健壮处理 LLM 输出的各种格式问题"""
import re
import json


def _repair_embedded_quotes(json_str: str) -> str:
    """修复 LLM 输出 JSON 中未转义的中文引号

    LLM 经常在 thought 字段里直接写 "中文文本"（ASCII 双引号），
    导致 JSON 解析失败。此函数在解析前预处理这些引号。
    """
    # 情况1: 中文字符之间的引号 — 肯定需要转义
    json_str = re.sub(
        r'([一-鿿＀-￯])"([一-鿿＀-￯])',
        r'\1\\"\2', json_str
    )
    # 情况2: 中文字符后跟引号后跟非JSON结构字符
    json_str = re.sub(
        r'([一-鿿＀-￯])"(?![,:\}\]]|\s*[,:\}\]])',
        r'\1\\"', json_str
    )
    # 情况3: 非JSON结构字符后跟引号后跟中文字符
    json_str = re.sub(
        r'(?<![,:\{\}\[\]\s])"([一-鿿＀-￯])',
        r'\\"\1', json_str
    )
    return json_str


def _find_json_boundary(text: str, start_char: str = "{", end_char: str = "}") -> int:
    """智能查找JSON边界的括号计数法。

    改进：字符串内的引号不会错误切换状态，
    只有引号后紧跟 , : } ] 之一时才视为字符串结束符。
    """
    start_idx = text.find(start_char)
    if start_idx == -1:
        return -1

    depth = 0
    in_string = False
    escape_next = False
    i = start_idx

    while i < len(text):
        ch = text[i]

        if escape_next:
            escape_next = False
            i += 1
            continue

        if ch == '\\':
            escape_next = True
            i += 1
            continue

        if ch == '"':
            if not in_string:
                in_string = True
            else:
                # 检查这个引号是否真的是字符串结束符
                # 看后面的有效字符
                j = i + 1
                while j < len(text) and text[j] in ' \t\n\r':
                    j += 1
                if j < len(text) and text[j] in (',', ':', '}', ']'):
                    in_string = False
                # 否则是内嵌引号，保持 in_string = True
            i += 1
            continue

        if in_string:
            i += 1
            continue

        if ch == start_char:
            depth += 1
        elif ch == end_char:
            depth -= 1
            if depth == 0:
                return i

        i += 1

    return -1


def safe_parse_json(raw_text: str) -> dict | list:
    """容错解析 LLM 返回的 JSON（兼容 dict 和 array），处理 markdown、换行、多余文本"""

    if not raw_text or not isinstance(raw_text, str):
        raise ValueError(f"输入为空或非字符串: {type(raw_text).__name__}")

    clean = raw_text.strip()

    # 1. 去除 markdown 代码块标记
    clean = re.sub(r"```(?:json|python)?\s*", "", clean)
    clean = re.sub(r"```\s*$", "", clean)
    clean = clean.strip()

    # 2. 尝试直接解析
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    # 2b. 修复中文引号后重试
    try:
        repaired = _repair_embedded_quotes(clean)
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # 3. 改进的边界查找 + 修复
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start_idx = clean.find(start_char)
        if start_idx == -1:
            continue

        end_idx = _find_json_boundary(clean, start_char, end_char)
        if end_idx > start_idx:
            candidate = clean[start_idx:end_idx + 1]
            # 尝试多层修复
            for attempt in [candidate, _repair_embedded_quotes(candidate)]:
                try:
                    return json.loads(attempt)
                except json.JSONDecodeError:
                    try:
                        fixed = re.sub(r',\s*}', '}', attempt)
                        fixed = re.sub(r',\s*]', ']', fixed)
                        return json.loads(fixed)
                    except json.JSONDecodeError:
                        continue

    # 4. 终极手段：暴力替换
    try:
        brutal = re.sub(r'(?<![,\{\}\[\]:\s])"(?![,\{\}\[\]:\s\n\r])', r'\\"', clean)
        return json.loads(brutal)
    except (json.JSONDecodeError, Exception):
        pass

    raise ValueError(f"无法解析JSON内容: {raw_text[:200]}")

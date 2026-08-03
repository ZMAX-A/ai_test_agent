"""
标准用例管理器

标准用例 JSON 格式定义 + 本地用例库管理。
用例库路径：./case_library/，按模块分子目录。

格式示例（case_library/搜索功能/TC001.json）：
    {
      "case_id": "TC001",
      "name": "百度搜索世界杯",
      "module": "搜索功能",
      "version": 1,
      "status": "active",
      "preconditions": "",
      "start_url": "https://www.baidu.com",
      "source_task": "百度搜索世界杯",
      "created_at": "2026-07-16T10:00:00",
      "updated_at": "2026-07-16T10:00:00",
      "steps": [
        {
          "step": 1,
          "goal": "打开百度首页",
          "action": "goto",
          "parameters": {"url": "https://www.baidu.com"},
          "asserts": [{"type": "url_contains", "target": "baidu"}]
        },
        {
          "step": 2,
          "goal": "在搜索框输入世界杯",
          "action": "fill",
          "parameters": {"role": "searchbox", "value": "世界杯"},
          "asserts": []
        },
        {
          "step": 3,
          "goal": "点击百度一下按钮",
          "action": "click",
          "parameters": {"role": "button", "name": "百度一下"},
          "asserts": [{"type": "text_exists", "target": "世界杯"}]
        }
      ]
    }
"""

import json
import os
import glob
from datetime import datetime

# ── 用例状态枚举 ──
STATUS_ACTIVE = "active"           # 正常可用
STATUS_DRAFT = "draft"             # 草稿（待审核）
STATUS_DEPRECATED = "deprecated"   # 已失效
STATUS_NEEDS_UPDATE = "needs_update"  # 待更新

# ── 用例库根目录 ──
LIBRARY_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "case_library")

# ── Excel 标准用例库（可选） ──
try:
    from standard.store import StandardCaseStore, get_store
    HAS_STORE = True
except ImportError:
    HAS_STORE = False


def _use_excel() -> bool:
    """判断是否优先使用 Excel 存储（standard.xlsx 存在且可读写）"""
    if not HAS_STORE:
        return False
    try:
        store = get_store()
        return os.path.isfile(store.filepath) and store.get_stats().get("total", 0) > 0
    except Exception:
        return False


# ═══════════════════════════════════════════════
#  路径工具
# ═══════════════════════════════════════════════

def _module_dir(module: str = "") -> str:
    if module:
        safe = module.strip().replace("/", "_").replace("\\", "_")
        return os.path.join(LIBRARY_ROOT, safe)
    return LIBRARY_ROOT


def _case_path(case_id: str, module: str = "") -> str:
    return os.path.join(_module_dir(module), f"{case_id}.json")


def _ensure_library():
    os.makedirs(LIBRARY_ROOT, exist_ok=True)


# ═══════════════════════════════════════════════
#  CRUD
# ═══════════════════════════════════════════════

def save_case(case: dict) -> str:
    """保存标准用例到 case_library，自动设置时间戳"""
    _ensure_library()
    case_id = case.get("case_id", "") or case.get("用例ID", "")
    if not case_id:
        raise ValueError("case_id 不能为空")

    module = case.get("module", "") or case.get("模块", "")
    path = _case_path(case_id, module)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    now = datetime.now().isoformat(timespec="seconds")
    case["updated_at"] = now
    if "created_at" not in case:
        case["created_at"] = now

    with open(path, "w", encoding="utf-8") as f:
        json.dump(case, f, ensure_ascii=False, indent=2)
    return path


def load_case(case_id: str, module: str = "") -> dict | None:
    """按 case_id 加载用例，可选指定 module 加速查找。
    优先从 standard.xlsx 读取。
    """
    # 优先 Excel
    if _use_excel():
        try:
            store = get_store()
            case = store.load_case(case_id)
            if case:
                return case
        except Exception:
            pass

    # Fallback JSON
    direct = _case_path(case_id, module)
    if os.path.isfile(direct):
        with open(direct, "r", encoding="utf-8") as f:
            return json.load(f)

    # 未指定 module 时遍历所有目录
    for fp in glob.glob(os.path.join(LIBRARY_ROOT, "**", f"{case_id}.json"), recursive=True):
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def find_cases(module: str = "", status: str = "") -> list[dict]:
    """查询用例，支持按模块和状态过滤。
    优先从 standard.xlsx 读取，fallback 到 JSON case_library/。
    """
    # 优先 Excel
    if _use_excel():
        try:
            store = get_store()
            cases = store.load_cases(module=module)
            # 当前 Excel 协议没有状态列，库内用例统一视作 active。
            return cases if not status or status == STATUS_ACTIVE else []
        except Exception:
            pass

    # Fallback JSON
    _ensure_library()
    root = _module_dir(module)
    if not os.path.isdir(root):
        return []

    cases = []
    pattern = os.path.join(root, "*.json") if module else os.path.join(root, "**", "*.json")
    for fp in sorted(glob.glob(pattern, recursive=True)):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                case = json.load(f)
            if status and case.get("status", STATUS_ACTIVE) != status:
                continue
            case_module = case.get("module", "") or case.get("模块", "")
            if module and case_module != module:
                continue
            cases.append(case)
        except (json.JSONDecodeError, OSError):
            continue
    return cases


def delete_case(case_id: str, module: str = "") -> bool:
    """删除用例"""
    path = _case_path(case_id, module)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


# ═══════════════════════════════════════════════
#  状态标记
# ═══════════════════════════════════════════════

def set_status(case_id: str, status: str, module: str = "") -> bool:
    """设置用例状态"""
    case = load_case(case_id, module)
    if not case:
        return False
    case["status"] = status
    save_case(case)
    return True


def mark_active(case_id: str, module: str = "") -> bool:
    return set_status(case_id, STATUS_ACTIVE, module)


def mark_deprecated(case_id: str, module: str = "") -> bool:
    return set_status(case_id, STATUS_DEPRECATED, module)


def mark_needs_update(case_id: str, module: str = "") -> bool:
    return set_status(case_id, STATUS_NEEDS_UPDATE, module)


# ═══════════════════════════════════════════════
#  统计与浏览
# ═══════════════════════════════════════════════

def list_modules() -> list[str]:
    """列出所有模块名"""
    _ensure_library()
    modules = []
    for entry in sorted(os.listdir(LIBRARY_ROOT)):
        sub = os.path.join(LIBRARY_ROOT, entry)
        if os.path.isdir(sub):
            modules.append(entry)
    return modules


def get_stats() -> dict:
    """获取用例库统计"""
    _ensure_library()
    total = 0
    by_status = {}
    by_module = {}
    for fp in glob.glob(os.path.join(LIBRARY_ROOT, "**", "*.json"), recursive=True):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                case = json.load(f)
            total += 1
            s = case.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1
            m = case.get("module", "__root__")
            by_module[m] = by_module.get(m, 0) + 1
        except Exception:
            continue
    return {"total": total, "by_status": by_status, "by_module": by_module}

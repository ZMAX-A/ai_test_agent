"""探索智能体的确定性推理控制层。

LLM 负责提出候选动作；本模块负责维护工作记忆、去重策略、分类失败，并对
``finish(success)`` 做证据门禁。这样模型不能仅凭自述把步骤标记为成功。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse


MUTATING_ACTIONS = {
    "click", "fill", "select_option", "goto", "close_popup",
    "go_back", "refresh", "scroll", "scroll_to_element",
}
ASSERT_ACTIONS = {"assert_text", "assert_url", "assert_title", "assert_visual"}
OBSERVE_ACTIONS = {"get_page_info", "get_element_attr"}


def normalize_plan(raw_steps: Any) -> list[dict]:
    """把模型计划压缩成稳定、去重且可执行的步骤协议。"""
    if isinstance(raw_steps, dict):
        raw_steps = raw_steps.get("steps", [])
    if not isinstance(raw_steps, list):
        return []

    normalized: list[dict] = []
    seen: set[str] = set()
    for item in raw_steps:
        if isinstance(item, str):
            goal, criteria = item.strip(), ""
        elif isinstance(item, dict):
            goal = str(item.get("goal", "")).strip()
            criteria = str(
                item.get("success_criteria") or item.get("assert") or ""
            ).strip()
        else:
            continue
        if not goal:
            continue
        key = re.sub(r"\s+", "", goal).lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append({
            "step": len(normalized) + 1,
            "goal": goal,
            "success_criteria": criteria,
        })
    return normalized


@dataclass
class Attempt:
    round_num: int
    action: str
    signature: str
    success: bool
    error_type: str
    message: str
    observation_fingerprint: str
    url_before: str = ""
    url_after: str = ""


@dataclass
class StepReasoningState:
    """单个测试步骤的紧凑工作记忆和完成证据。"""

    goal: str
    success_criteria: str = ""
    max_rounds: int = 10
    attempts: list[Attempt] = field(default_factory=list)
    current_url: str = ""
    current_title: str = ""
    current_observation: str = ""
    observation_fingerprint: str = ""
    unchanged_observations: int = 0
    lessons: list[str] = field(default_factory=list)

    def observe(self, page_state: str, url: str = "", title: str = "") -> None:
        normalized = re.sub(r"\s+", " ", page_state or "").strip()
        raw = f"{url}\n{title}\n{normalized}"
        fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        if fingerprint == self.observation_fingerprint:
            self.unchanged_observations += 1
        else:
            self.unchanged_observations = 0
        self.observation_fingerprint = fingerprint
        self.current_url = url
        self.current_title = title
        self.current_observation = normalized[:4000]

    @staticmethod
    def action_signature(action: dict) -> str:
        payload = {
            "action": action.get("action", ""),
            "parameters": action.get("parameters", {}),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def repeated_on_same_observation(self, action: dict) -> bool:
        """同一页面快照下不允许重复完全相同的动作。"""
        # finish 是完成声明，不是页面操作；新证据产生后必须允许再次申请完成。
        if action.get("action") == "finish":
            return False
        signature = self.action_signature(action)
        return any(
            attempt.signature == signature
            and attempt.observation_fingerprint == self.observation_fingerprint
            for attempt in self.attempts
        )

    def deterministic_action(self) -> dict | None:
        """从目标中的明确导航证据生成零模型动作。

        只处理目标明确要求“打开/进入/访问/直接访问”的 URL，避免把普通文本中的
        路径误当作导航指令。
        """
        goal_text = f"{self.goal} {self.success_criteria}"
        if not any(k in goal_text for k in ("打开", "进入", "跳转", "访问", "直接访问")):
            return None

        absolute = re.search(r"https?://[^\s，。)）]+", goal_text)
        if absolute:
            target = absolute.group(0)
        else:
            path_match = re.search(r"\/[A-Za-z0-9_./-]+", goal_text)
            parsed = urlparse(self.current_url)
            if not path_match or not parsed.scheme or not parsed.netloc:
                return None
            target = f"{parsed.scheme}://{parsed.netloc}{path_match.group(0)}"

        if self.current_url.rstrip("/") == target.rstrip("/"):
            return None
        return {
            "thought": f"控制器从明确目标URL生成确定性导航: {target}",
            "action": "goto",
            "parameters": {"url": target},
        }

    def repair_action(self, action: dict) -> tuple[dict, list[str]]:
        """依据目标中的序号补全无歧义的 role 定位 index。"""
        repaired = json.loads(json.dumps(action, ensure_ascii=False))
        params = repaired.get("parameters", {})
        notes: list[str] = []
        if (
            repaired.get("action") in {"fill", "click", "select_option", "assert_text"}
            and params.get("role")
            and not params.get("name")
            and "index" not in params
            and params.get("som_index") is None
        ):
            match = re.search(r"第\s*(\d+|[一二三四五六七八九十])\s*个", self.goal)
            if match:
                raw = match.group(1)
                chinese_numbers = {
                    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
                }
                ordinal = int(raw) if raw.isdigit() else chinese_numbers[raw]
                params["index"] = max(0, ordinal - 1)
                notes.append(f"根据目标“第{raw}个”自动补全 index={params['index']}")
        return repaired, notes

    def record(self, round_num: int, action: dict, result: dict,
               url_before: str = "", url_after: str = "") -> None:
        self.attempts.append(Attempt(
            round_num=round_num,
            action=action.get("action", ""),
            signature=self.action_signature(action),
            success=bool(result.get("success")),
            error_type=str(result.get("error_type", "")),
            message=str(result.get("message", ""))[:300],
            observation_fingerprint=self.observation_fingerprint,
            url_before=url_before,
            url_after=url_after,
        ))
        if url_after:
            self.current_url = url_after

    def _goal_url_evidence(self) -> list[str]:
        text = f"{self.goal} {self.success_criteria}"
        evidence = []
        for absolute in re.findall(r"https?://[^\s，。)）]+", text):
            if self.current_url.rstrip("/") == absolute.rstrip("/"):
                evidence.append(f"当前URL等于目标URL: {absolute}")
        path_text = re.sub(r"https?://[^\s，。)）]+", "", text)
        for path in re.findall(r"\/[A-Za-z0-9_./-]+", path_text):
            if path in self.current_url:
                evidence.append(f"当前URL包含目标路径: {path}")
        return evidence

    def completion_evidence(self) -> list[str]:
        evidence = self._goal_url_evidence()
        successful = [a for a in self.attempts if a.success]
        contract_text = self.success_criteria or self.goal

        # “包含X”类完成条件可以直接由当前标题/语义快照提供证据。
        for match in re.findall(
            r"(?:包含|显示|出现|可见)[：: ]*[‘'\"“]?([^，。；;'\"”]{1,30})",
            contract_text,
        ):
            expected = match.strip()
            if expected and (
                expected in self.current_title
                or expected in self.current_observation
                or expected in self.current_url
            ):
                evidence.append(f"当前页面证据包含: {expected}")

        if any(a.action in ASSERT_ACTIONS for a in successful):
            evidence.append("显式断言动作执行成功")
        if any(keyword in contract_text for keyword in ("输入", "填入", "填写", "值为")):
            if any(a.action == "fill" for a in successful):
                evidence.append("输入动作执行成功")
        if "点击" in contract_text and any(a.action == "click" for a in successful):
            evidence.append("目标点击动作执行成功")
        if any(keyword in contract_text for keyword in ("选择", "下拉")):
            if any(a.action == "select_option" for a in successful):
                evidence.append("目标选择动作执行成功")
        if any(keyword in contract_text for keyword in ("打开", "进入", "跳转", "访问")):
            if any(
                a.success and a.action in {"goto", "click"}
                and a.url_after and a.url_after != a.url_before
                for a in self.attempts
            ):
                evidence.append("导航动作成功且URL发生变化")

        # 没有明确动作类型的目标，至少要求一个产生效果的写操作成功。
        verification_goal = any(k in contract_text for k in ("验证", "断言", "确认", "检查", "显示", "可见", "包含"))
        if (not self.success_criteria and not verification_goal and not evidence
                and any(a.action in MUTATING_ACTIONS for a in successful)):
            evidence.append("与目标相关的页面操作执行成功")
        return evidence

    def can_finish_success(self) -> tuple[bool, str]:
        evidence = self.completion_evidence()
        if evidence:
            return True, "；".join(evidence)
        return False, "尚无可验证的完成证据；需要先执行目标动作或显式断言"

    def should_use_visual(self) -> bool:
        recent_failures = sum(1 for a in self.attempts[-3:] if not a.success)
        return recent_failures >= 2 or self.unchanged_observations >= 2

    def next_directive(self) -> str:
        if not self.attempts:
            return "先基于当前页面证据选择最小、可验证的动作；不要猜测页面外元素。"
        last = self.attempts[-1]
        if last.success:
            allowed, evidence = self.can_finish_success()
            if allowed:
                return f"已有完成证据（{evidence}）。若目标确已达成，立即 finish；否则执行显式断言。"
            return "动作成功不等于目标完成。检查页面变化并执行验证动作，不要重复刚才的动作。"
        if last.error_type in {"ELEMENT_NOT_FOUND", "NOT_VISIBLE"}:
            return "重新观察当前页面，检查弹窗/iframe/滚动位置，并改用不同定位证据。"
        if last.error_type in {"TIMEOUT", "NOT_ENABLED"}:
            return "检查页面是否正确、元素是否被遮挡或尚未就绪；优先消除前置障碍。"
        return "根据结构化失败原因提出不同假设；禁止在相同页面状态重复同一动作。"

    def prompt_context(self, round_num: int) -> str:
        allowed, finish_reason = self.can_finish_success()
        history = [
            {
                "round": a.round_num,
                "action": a.action,
                "success": a.success,
                "error": a.error_type,
                "result": a.message[:100],
                "url_changed": bool(a.url_after and a.url_after != a.url_before),
            }
            for a in self.attempts[-5:]
        ]
        return json.dumps({
            "round": f"{round_num}/{self.max_rounds}",
            "goal": self.goal,
            "success_criteria": self.success_criteria or "未显式提供；必须以动作结果或页面证据验证",
            "current_url": self.current_url,
            "current_title": self.current_title,
            "recent_attempts": history,
            "historical_lessons": self.lessons[-3:],
            "finish_allowed": allowed,
            "finish_evidence": finish_reason,
            "controller_directive": self.next_directive(),
        }, ensure_ascii=False, indent=2)

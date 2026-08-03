"""元素长期记忆缓存：存储历史成功定位策略，辅助失败时兜底重试

生命周期：
- 被动失效：每条缓存写入时带时间戳，超过 TTL 自动作废
- 主动失效：缓存命中但 Playwright 执行报错时，立即作废该条目降级为 LLM 实时推理
"""

import json
import os
import time
from typing import Optional
from urllib.parse import urlparse

from config.settings import settings

CACHE_FILE = os.path.join(os.path.dirname(__file__), "element_cache.json")


class ElementCache:
    """页面元素长期记忆缓存

    以 (goal_text, base_url) 为复合键，缓存成功定位过的元素定位策略。
    base_url 仅含 protocol+host+path，去除查询参数以支持同站点跨页匹配。
    """

    def __init__(self, cache_path: str = CACHE_FILE):
        self.cache_path = cache_path
        self._data: dict = self._load()

    # ── 持久化 ──────────────────────────────────────────────

    @staticmethod
    def _base_url(url: str) -> str:
        processed = urlparse(url)
        path = processed.path.rstrip("/") or "/"
        return f"{processed.scheme}://{processed.netloc}{path}"

    @staticmethod
    def _now() -> float:
        return time.time()

    def _load(self) -> dict:
        if not os.path.exists(self.cache_path):
            return {}
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

        # ── 启动时清扫过期条目 ──
        ttl_seconds = settings.CACHE_TTL_DAYS * 86400
        now = self._now()
        purged = 0
        alive = {}
        for key, entry in data.items():
            created = entry.get("created_at", 0)
            if created and (now - created) > ttl_seconds:
                purged += 1
                continue
            alive[key] = entry

        if purged:
            self._data = alive
            self._save()
        return alive

    def _save(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    # ── 完整动作缓存（缓存直通：跳过感知+LLM） ───────────

    def get_action(self, goal_text: str, url: str = "") -> Optional[dict]:
        """获取缓存的完整动作指令 JSON。

        查询匹配 goal_text 和 url 的缓存条目，返回完整动作 JSON。
        已过期或已降级的条目自动跳过。无有效缓存返回 None。
        """
        base = self._base_url(url) if url else ''
        ttl_seconds = settings.CACHE_TTL_DAYS * 86400
        now = self._now()

        candidates = []
        for key, entry in list(self._data.items()):
            if entry.get('goal', '') != goal_text:
                continue
            if entry.get('degraded'):
                continue
            created = entry.get('created_at', 0)
            if created and (now - created) > ttl_seconds:
                del self._data[key]
                self._save()
                continue
            stored_base = entry.get('base_url', '')
            score = 2 if stored_base == base else 1
            candidates.append((score, entry))

        if not candidates:
            return None
        candidates.sort(key=lambda x: (x[0], x[1].get('created_at', 0)), reverse=True)
        return candidates[0][1].get('action')

    def set_action(self, goal_text: str, url: str, action: dict):
        """缓存完整动作指令（action + parameters）。"""
        base = self._base_url(url)
        key = f'{goal_text}|{base}'

        self._data[key] = {
            'goal': goal_text,
            'base_url': base,
            'url': url,
            'action': action,
            'created_at': self._now(),
            'degraded': False,
        }
        self._save()

    def delete_action(self, goal_text: str, url: str):
        """删除指定缓存条目（缓存执行失败时调用）。"""
        base = self._base_url(url)
        key = f'{goal_text}|{base}'
        if key in self._data:
            del self._data[key]
            self._save()

    # ── 旧版策略缓存（向下兼容） ────────────────────────────

    def get(self, goal_text: str, url: str = "") -> Optional[dict]:
        """查询历史成功定位策略，已过期或已降级的条目自动跳过"""
        base = self._base_url(url) if url else ""
        ttl_seconds = settings.CACHE_TTL_DAYS * 86400
        now = self._now()

        candidates = []
        for key, entry in list(self._data.items()):
            if entry.get("goal", "") != goal_text:
                continue

            # ── 主动失效标记：degraded=true 的条目直接跳过 ──
            if entry.get("degraded"):
                continue

            # ── 被动失效：TTL 检查 ──
            created = entry.get("created_at", 0)
            if created and (now - created) > ttl_seconds:
                del self._data[key]
                self._save()
                continue

            stored_base = entry.get("base_url", "")
            if stored_base and stored_base == base:
                candidates.append((2, entry))
            else:
                candidates.append((1, entry))

        if not candidates:
            return None
        candidates.sort(key=lambda x: (x[0], x[1].get("hit_count", 0)), reverse=True)
        return candidates[0][1].get("strategy")

    # ── 记录 ─────────────────────────────────────────────────

    def record(self, goal_text: str, url: str, strategy: dict, success: bool = True):
        """记录成功定位策略"""
        if not success:
            return

        base = self._base_url(url)
        key = f"{goal_text}|{base}"
        existing = self._data.get(key, {})

        self._data[key] = {
            "goal": goal_text,
            "base_url": base,
            "url": url,
            "strategy": existing.get("strategy", strategy),
            "hit_count": existing.get("hit_count", 0) + 1,
            "created_at": existing.get("created_at", self._now()),
            "degraded": False,
        }
        self._save()

    # ── 主动作废 ─────────────────────────────────────────────

    def invalidate(self, goal_text: str, url: str):
        """主动作废一条缓存（命中后执行失败时调用）"""
        base = self._base_url(url)
        key = f"{goal_text}|{base}"
        if key in self._data:
            self._data[key]["degraded"] = True
            self._data[key]["hit_count"] = max(0, self._data[key].get("hit_count", 1) - 1)
            self._save()
            print(f"[CACHE] 缓存已作废: {goal_text} @ {base}")

    def clear(self):
        """清空所有缓存（测试环境重置用）"""
        self._data = {}
        if os.path.exists(self.cache_path):
            os.remove(self.cache_path)

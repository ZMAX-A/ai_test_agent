"""
记忆管理器（Memory Manager）

基于 SQLite 的持久化记忆系统，支持两种记忆类型：
  1. 流程记忆（Flow Memory）：记住成功执行过的任务步骤序列
  2. 失败记忆（Fail Memory）：记住失败过的步骤及原因

每次测试运行后自动学习，下次遇到相同/相似任务时直接复用经验。
"""

import sqlite3
import json
import os
from difflib import SequenceMatcher
from datetime import datetime


class MemoryManager:
    """记忆管理器 — 短期记忆（session）+ 长期记忆（SQLite）"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), "test_memory.db")
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._session_memory: dict = {}  # 短期记忆
        self._init_db()

    # ── 数据库基础 ──────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS flow_memory (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                system      TEXT NOT NULL,          -- 域名（如 www.baidu.com）
                task_desc   TEXT NOT NULL,          -- 任务描述
                steps       TEXT NOT NULL,          -- 步骤序列 JSON
                success_count INTEGER DEFAULT 1,
                total_count   INTEGER DEFAULT 1,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(system, task_desc)
            );
            CREATE TABLE IF NOT EXISTS fail_memory (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                system      TEXT NOT NULL,
                step_goal   TEXT NOT NULL,
                page_url    TEXT DEFAULT '',
                fail_reason TEXT DEFAULT '',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_flow_lookup
                ON flow_memory(system, task_desc);
            CREATE INDEX IF NOT EXISTS idx_fail_lookup
                ON fail_memory(system, step_goal);
        """)
        conn.commit()
        conn.close()

    # ═══════════════════════════════════════════════
    #  短期记忆（Session Memory）
    # ═══════════════════════════════════════════════

    def remember(self, key: str, value) -> None:
        """记录一条短期记忆（仅本次会话有效）"""
        self._session_memory[key] = value

    def recall(self, key: str, default=None):
        """读取短期记忆"""
        return self._session_memory.get(key, default)

    def clear_session(self):
        """清空短期记忆"""
        self._session_memory.clear()

    # ═══════════════════════════════════════════════
    #  流程记忆（Flow Memory）
    # ═══════════════════════════════════════════════

    def record_flow(self, system: str, task_desc: str, steps: list) -> None:
        """记录或更新一个成功的执行流程

        Args:
            system: 系统标识（通常传域名）
            task_desc: 任务描述（如 "百度搜索世界杯"）
            steps: 步骤列表
        """
        steps_json = json.dumps(steps, ensure_ascii=False)
        conn = self._get_conn()
        existing = conn.execute(
            "SELECT id, success_count, total_count FROM flow_memory WHERE system=? AND task_desc=?",
            (system, task_desc),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE flow_memory
                   SET steps=?, success_count=success_count+1,
                       total_count=total_count+1, last_used_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (steps_json, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO flow_memory (system, task_desc, steps) VALUES (?, ?, ?)",
                (system, task_desc, steps_json),
            )
        conn.commit()
        conn.close()
        print(f"  [MEMORY] 流程已记忆: {task_desc[:40]}")

    def find_flow(self, system: str, task_desc: str,
                  min_similarity: float = 0.85) -> dict | None:
        """查找历史执行流程

        先精确匹配，再模糊匹配（SequenceMatcher）。
        返回 dict（含 steps 字段）或 None。

        Args:
            system: 系统标识（域名）
            task_desc: 任务描述
            min_similarity: 模糊匹配最低相似度 0.0~1.0
        """
        conn = self._get_conn()

        # 1. 精确匹配
        row = conn.execute(
            "SELECT * FROM flow_memory WHERE system=? AND task_desc=?",
            (system, task_desc),
        ).fetchone()
        if row:
            conn.close()
            result = dict(row)
            result["steps"] = json.loads(result["steps"])
            return result

        # 2. 模糊匹配：遍历所有该系统的流程，找相似度最高的
        all_rows = conn.execute(
            """SELECT * FROM flow_memory
               WHERE system=?
               ORDER BY success_count DESC, last_used_at DESC""",
            (system,),
        ).fetchall()
        conn.close()

        best = None
        best_ratio = 0.0
        for row in all_rows:
            ratio = SequenceMatcher(None, task_desc, row["task_desc"]).ratio()
            if ratio > best_ratio and ratio >= min_similarity:
                best_ratio = ratio
                best = dict(row)

        if best:
            best["steps"] = json.loads(best["steps"])
            print(f"  [MEMORY] 模糊匹配流程 (相似度 {best_ratio:.0%}): {best['task_desc']}")
        return best

    def get_flow_stats(self) -> list[dict]:
        """获取所有流程记忆统计"""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT system, task_desc, success_count, total_count,
                      last_used_at
               FROM flow_memory
               ORDER BY last_used_at DESC LIMIT 30"""
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ═══════════════════════════════════════════════
    #  失败记忆（Fail Memory）
    # ═══════════════════════════════════════════════

    def record_failure(self, system: str, step_goal: str,
                       page_url: str = "", fail_reason: str = "") -> None:
        """记录一次步骤失败"""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO fail_memory (system, step_goal, page_url, fail_reason) VALUES (?, ?, ?, ?)",
            (system, step_goal, page_url, fail_reason),
        )
        conn.commit()
        conn.close()

    def get_failures(self, system: str, step_goal: str) -> list[dict]:
        """查询某步骤的历史失败记录（最近5条）"""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT * FROM fail_memory
               WHERE system=? AND step_goal=?
               ORDER BY created_at DESC LIMIT 5""",
            (system, step_goal),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_fail_stats(self) -> list[dict]:
        """获取失败记忆统计"""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT system, step_goal, fail_reason, created_at
               FROM fail_memory
               ORDER BY created_at DESC LIMIT 20"""
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

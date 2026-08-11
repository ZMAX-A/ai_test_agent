"""SQLite memory that promotes only independently verified Web-agent traces."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable
from urllib.parse import urlparse

from core.credential_vault import CredentialVault


SCHEMA_VERSION = 1
TRAINING_POLICY_VERSION = 10


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _field(case: Any, name: str, default: Any = "") -> Any:
    if isinstance(case, dict):
        return case.get(name, default)
    return getattr(case, name, default)


def _case_payload(case: Any) -> dict:
    if hasattr(case, "to_dict"):
        return case.to_dict()
    if is_dataclass(case):
        return asdict(case)
    return dict(case)


def _sanitize_text(value: str) -> str:
    return CredentialVault().sanitize_text(str(value or ""))


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    return value


def training_case_hash(case: Any) -> str:
    """Fingerprint a curriculum case together with the active safety policy."""

    payload = _sanitize(_case_payload(case))
    payload["_training_policy_version"] = TRAINING_POLICY_VERSION
    return sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _compact_trace(result: dict) -> list[dict]:
    compact = []
    for item in result.get("trace", []) or []:
        compact.append({
            "goal": item.get("goal", ""),
            "actions": [
                {
                    "action": action.get("action", ""),
                    "parameters": action.get("parameters", {}),
                }
                for action in (item.get("all_actions", []) or [])
            ],
            "evidence": item.get("completion_evidence", []) or [],
        })
    return _sanitize(compact)


def _trace_aligned(trace: list[dict]) -> bool:
    if not trace:
        return False
    for step in trace:
        if not step.get("evidence"):
            return False
        goal = str(step.get("goal", "")).replace(" ", "")
        actions = {
            str(item.get("action", ""))
            for item in step.get("actions", [])
        }
        required = ""
        if any(token in goal for token in ("输入", "填入", "填写")):
            required = "fill"
        elif "选择" in goal:
            required = "select_option"
        elif "点击" in goal:
            required = "click"
        if required and required not in actions:
            return False
    return True


class TrainingMemory:
    """Durable attempts plus a fail-closed candidate/promoted state."""

    def __init__(self, path: str | Path = "memory/web_agent_training.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS training_attempts (
                    run_id TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    case_hash TEXT NOT NULL,
                    system TEXT NOT NULL,
                    module TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    evidence_backed INTEGER NOT NULL,
                    duration_seconds REAL NOT NULL,
                    record_json TEXT NOT NULL,
                    trace_json TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, case_id)
                );
                CREATE INDEX IF NOT EXISTS idx_attempt_source
                    ON training_attempts(source_hash, case_id, outcome);
                CREATE TABLE IF NOT EXISTS training_experiences (
                    source_hash TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    case_hash TEXT NOT NULL,
                    system TEXT NOT NULL,
                    module TEXT NOT NULL,
                    case_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    verified_successes INTEGER NOT NULL DEFAULT 0,
                    verified_failures INTEGER NOT NULL DEFAULT 0,
                    trace_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (source_hash, case_id)
                );
                """
            )
            connection.execute(
                """UPDATE training_attempts SET outcome='infra_error'
                   WHERE outcome='failed' AND evidence_backed=0
                   AND error LIKE 'TimeoutError: Page.goto%'"""
            )
            for row in connection.execute(
                "SELECT rowid, trace_json FROM training_attempts "
                "WHERE outcome='passed_verified'"
            ).fetchall():
                try:
                    aligned = _trace_aligned(json.loads(row["trace_json"]))
                except Exception:
                    aligned = False
                if not aligned:
                    connection.execute(
                        "UPDATE training_attempts "
                        "SET outcome='unpromotable_pass' WHERE rowid=?",
                        (row["rowid"],),
                    )
            for experience in connection.execute(
                "SELECT source_hash, case_id, case_hash, status "
                "FROM training_experiences"
            ).fetchall():
                counts = connection.execute(
                    """SELECT
                           SUM(CASE WHEN outcome='passed_verified' THEN 1 ELSE 0 END) successes,
                           SUM(CASE WHEN outcome='failed' THEN 1 ELSE 0 END) failures
                       FROM training_attempts
                       WHERE source_hash=? AND case_id=? AND case_hash=?""",
                    (
                        experience["source_hash"],
                        experience["case_id"],
                        experience["case_hash"],
                    ),
                ).fetchone()
                successes = int(counts["successes"] or 0)
                failures = int(counts["failures"] or 0)
                status = (
                    "quarantined"
                    if experience["status"] == "quarantined" or failures >= 2
                    else "promoted"
                    if successes >= 2 and failures == 0
                    else "candidate"
                )
                connection.execute(
                    """UPDATE training_experiences
                       SET status=?, verified_successes=?, verified_failures=?
                       WHERE source_hash=? AND case_id=?""",
                    (
                        status, successes, failures,
                        experience["source_hash"], experience["case_id"],
                    ),
                )

    def record_attempt(
        self,
        run_id: str,
        source_hash: str,
        case: Any,
        evaluation: Any,
        result: dict,
    ) -> dict:
        record = asdict(evaluation) if is_dataclass(evaluation) else dict(evaluation)
        trace = _compact_trace(result)
        success = bool(record.get("success"))
        evidence_backed = bool(record.get("evidence_backed"))
        error_text = str(record.get("error", ""))
        infra_error = (
            not success
            and not int(record.get("action_count", 0) or 0)
            and not int(record.get("verification_count", 0) or 0)
            and any(marker in error_text for marker in (
                "TimeoutError: Page.goto", "BrowserType.launch",
                "TargetClosedError", "ConnectionError",
            ))
        )
        outcome = (
            "passed_verified"
            if success and evidence_backed and _trace_aligned(trace)
            else "unpromotable_pass"
            if success and evidence_backed
            else "unsupported_pass" if success
            else "infra_error" if infra_error
            else "failed"
        )
        case_id = str(_field(case, "case_id", "unnamed"))
        case_hash = training_case_hash(case)
        start_url = str(_field(case, "start_url", ""))
        system = urlparse(start_url).netloc or "unknown"
        module = _sanitize_text(str(_field(case, "module", "")))
        case_name = _sanitize_text(str(_field(case, "case_name", case_id)))
        error = _sanitize_text(str(record.get("error", "")))[:500]
        record_json = json.dumps(_sanitize(record), ensure_ascii=False, sort_keys=True)
        trace_json = json.dumps(trace, ensure_ascii=False, sort_keys=True)

        with self._connect() as connection:
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO training_attempts
                (run_id, source_hash, case_id, case_hash, system, module,
                 priority, risk, outcome, success, evidence_backed,
                 duration_seconds, record_json, trace_json, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run_id), str(source_hash), case_id, case_hash, system, module,
                    str(_field(case, "priority", "")),
                    str(_field(case, "risk", "")),
                    outcome, int(success), int(evidence_backed),
                    float(record.get("duration_seconds", 0.0) or 0.0),
                    record_json, trace_json, error, _now(),
                ),
            )
            if inserted.rowcount == 0:
                persisted = connection.execute(
                    "SELECT outcome FROM training_attempts "
                    "WHERE run_id=? AND case_id=?",
                    (str(run_id), case_id),
                ).fetchone()
                experience = connection.execute(
                    "SELECT status, verified_successes, verified_failures "
                    "FROM training_experiences "
                    "WHERE source_hash=? AND case_id=?",
                    (source_hash, case_id),
                ).fetchone()
                return {
                    "case_id": case_id,
                    "outcome": str(persisted["outcome"]),
                    "experience_status": (
                        str(experience["status"])
                        if experience else "candidate"
                    ),
                    "verified_successes": (
                        int(experience["verified_successes"])
                        if experience else 0
                    ),
                    "verified_failures": (
                        int(experience["verified_failures"])
                        if experience else 0
                    ),
                }

            counts = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN outcome='passed_verified' THEN 1 ELSE 0 END) successes,
                    SUM(CASE WHEN outcome='failed' THEN 1 ELSE 0 END) failures
                FROM training_attempts
                WHERE source_hash=? AND case_id=? AND case_hash=?
                """,
                (source_hash, case_id, case_hash),
            ).fetchone()
            successes = int(counts["successes"] or 0)
            failures = int(counts["failures"] or 0)
            previous = connection.execute(
                """SELECT status, case_hash FROM training_experiences
                   WHERE source_hash=? AND case_id=?""",
                (source_hash, case_id),
            ).fetchone()
            same_version = bool(previous and previous["case_hash"] == case_hash)
            previous_status = previous["status"] if same_version else ""
            if previous_status == "quarantined":
                status = "quarantined"
            elif previous_status == "promoted" and outcome == "failed":
                status = "quarantined"
            elif failures >= 2:
                status = "quarantined"
            elif successes >= 2 and failures == 0:
                status = "promoted"
            else:
                status = "candidate"
            best_trace = trace_json if outcome == "passed_verified" else "[]"
            if same_version and not best_trace.strip("[]"):
                old = connection.execute(
                    "SELECT trace_json FROM training_experiences WHERE source_hash=? AND case_id=?",
                    (source_hash, case_id),
                ).fetchone()
                best_trace = old["trace_json"]
            connection.execute(
                """
                INSERT INTO training_experiences
                (source_hash, case_id, case_hash, system, module, case_name,
                 status, verified_successes, verified_failures, trace_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_hash, case_id) DO UPDATE SET
                    case_hash=excluded.case_hash,
                    system=excluded.system,
                    module=excluded.module,
                    case_name=excluded.case_name,
                    status=excluded.status,
                    verified_successes=excluded.verified_successes,
                    verified_failures=excluded.verified_failures,
                    trace_json=excluded.trace_json,
                    updated_at=excluded.updated_at
                """,
                (
                    source_hash, case_id, case_hash, system, module, case_name,
                    status, successes, failures, best_trace, _now(),
                ),
            )
        return {
            "case_id": case_id,
            "outcome": outcome,
            "experience_status": status,
            "verified_successes": successes,
            "verified_failures": failures,
        }

    def successful_case_ids(self, source_hash: str) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT case_id FROM training_attempts
                WHERE source_hash=? AND outcome='passed_verified'
                """,
                (source_hash,),
            ).fetchall()
        return {str(row["case_id"]) for row in rows}

    def promoted_case_ids(
        self,
        source_hash: str,
        case_hashes: dict[str, str] | None = None,
    ) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT case_id, case_hash FROM training_experiences
                   WHERE source_hash=? AND status='promoted'""",
                (source_hash,),
            ).fetchall()
        return {
            str(row["case_id"])
            for row in rows
            if case_hashes is None
            or case_hashes.get(str(row["case_id"])) == str(row["case_hash"])
        }

    def quarantined_case_ids(
        self,
        source_hash: str,
        case_hashes: dict[str, str] | None = None,
    ) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT case_id, case_hash FROM training_experiences
                   WHERE source_hash=? AND status='quarantined'""",
                (source_hash,),
            ).fetchall()
        return {
            str(row["case_id"])
            for row in rows
            if case_hashes is None
            or case_hashes.get(str(row["case_id"])) == str(row["case_hash"])
        }

    def promoted_context(
        self, system: str, module: str = "", limit: int = 3,
        source_hash: str = "",
        allowed_case_hashes: Iterable[str] | None = None,
    ) -> str:
        query = """
            SELECT case_id, case_name, module, trace_json
            FROM training_experiences
            WHERE system=? AND status='promoted' AND verified_failures=0
        """
        params: list[Any] = [system]
        if source_hash:
            query += " AND source_hash=?"
            params.append(source_hash)
        if allowed_case_hashes is not None:
            hashes = tuple(dict.fromkeys(
                str(value) for value in allowed_case_hashes if value
            ))
            if not hashes:
                return ""
            placeholders = ",".join("?" for _item in hashes)
            query += f" AND case_hash IN ({placeholders})"
            params.extend(hashes)
        if module:
            query += " AND module=?"
            params.append(module)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        hints = [
            {
                "case_id": row["case_id"],
                "case_name": row["case_name"],
                "module": row["module"],
                "verified_trace": json.loads(row["trace_json"]),
            }
            for row in rows
        ]
        return json.dumps(hints, ensure_ascii=False, separators=(",", ":")) if hints else ""

    def stats(
        self,
        source_hash: str = "",
        allowed_case_hashes: Iterable[str] | None = None,
    ) -> dict:
        conditions: list[str] = []
        params: list[Any] = []
        if source_hash:
            conditions.append("source_hash=?")
            params.append(source_hash)
        if allowed_case_hashes is not None:
            hashes = tuple(dict.fromkeys(
                str(value) for value in allowed_case_hashes if value
            ))
            if not hashes:
                return {"attempts": {}, "experiences": {}}
            placeholders = ",".join("?" for _item in hashes)
            conditions.append(f"case_hash IN ({placeholders})")
            params.extend(hashes)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self._connect() as connection:
            attempts = connection.execute(
                f"SELECT outcome, COUNT(*) count FROM training_attempts{where} GROUP BY outcome",
                tuple(params),
            ).fetchall()
            experiences = connection.execute(
                f"SELECT status, COUNT(*) count FROM training_experiences{where} GROUP BY status",
                tuple(params),
            ).fetchall()
        return {
            "attempts": {row["outcome"]: int(row["count"]) for row in attempts},
            "experiences": {row["status"]: int(row["count"]) for row in experiences},
        }


__all__ = [
    "SCHEMA_VERSION", "TRAINING_POLICY_VERSION", "TrainingMemory",
    "training_case_hash",
]

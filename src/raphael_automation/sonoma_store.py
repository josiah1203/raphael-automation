"""Trimmed SonomaApiStore copy for automations workflows."""

from __future__ import annotations

import os
import secrets
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SonomaApiStore:
    def __init__(self, db_path: Path | None = None):
        from raphael_contracts import db as rdb

        self._postgres = rdb.is_postgres()
        if self._postgres:
            rdb.ensure_migrations()
            self.db_path = Path("postgres")
            self._ensure_eol_scans_postgres()
        else:
            default_db = Path(os.environ.get("RAPHAEL_AUTOMATION_DB", "/tmp/raphael-automation.db"))
            self.db_path = db_path or default_db
            self._init_sqlite()
        self._seed_defaults()

    def _connect_sqlite(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def _init_sqlite(self) -> None:
        with self._connect_sqlite() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS automations (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_run_status TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS automation_runs (
                    id TEXT PRIMARY KEY,
                    automation_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    duration_ms INTEGER,
                    started_at TEXT NOT NULL,
                    error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS eol_scans (
                    id TEXT PRIMARY KEY,
                    module_id TEXT NOT NULL,
                    automation_id TEXT,
                    status TEXT NOT NULL DEFAULT 'scheduled',
                    scheduled_at TEXT NOT NULL,
                    metadata TEXT
                )
                """
            )

    def _ensure_eol_scans_postgres(self) -> None:
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS eol_scans (
                id TEXT PRIMARY KEY,
                module_id TEXT NOT NULL,
                automation_id TEXT,
                status TEXT NOT NULL DEFAULT 'scheduled',
                scheduled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb
            )
            """
        )
        self._execute("CREATE INDEX IF NOT EXISTS idx_eol_scans_module ON eol_scans (module_id)")

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        if self._postgres:
            from raphael_contracts.db import pg_execute

            pg_execute(sql, params)
            return
        with self._connect_sqlite() as conn:
            conn.execute(sql, params)
            conn.commit()

    def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> Any | None:
        if self._postgres:
            from raphael_contracts.db import pg_fetchone

            return pg_fetchone(sql, params)
        with self._connect_sqlite() as conn:
            return conn.execute(sql, params).fetchone()

    def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
        if self._postgres:
            from raphael_contracts.db import pg_fetchall

            return pg_fetchall(sql, params)
        with self._connect_sqlite() as conn:
            return conn.execute(sql, params).fetchall()

    def _seed_defaults(self) -> None:
        row = self._fetchone("SELECT COUNT(*) AS cnt FROM automations")
        auto_count = row["cnt"] if isinstance(row, dict) else row[0]
        if auto_count == 0:
            now = _utc_now()
            defaults = [
                ("auto-drc", "DRC on commit", "on_commit", "Run DRC + net connectivity check", True, "succeeded", now),
                (
                    "auto-release",
                    "Release export on merge",
                    "on_merge",
                    "Export Gerber + BOM to release bucket",
                    True,
                    "succeeded",
                    now,
                ),
                ("auto-eol", "EOL component monitor", "scheduled", "Scan BOM for EOL parts (weekly)", True, "running", now),
            ]
            for auto in defaults:
                self._insert_automation(*auto)
            run_defaults = [
                ("run-1", "auto-drc", "DRC: USB-PD input", "succeeded", "On commit", 245000, now, None),
                ("run-2", "auto-release", "Gerber export: v2.3", "succeeded", "On merge", 364000, now, None),
                ("run-3", "auto-eol", "EOL scan: power-board-v2", "running", "Scheduled", None, now, None),
            ]
            for run in run_defaults:
                self._insert_run(*run)

    def _insert_automation(
        self,
        auto_id: str,
        name: str,
        trigger_type: str,
        action: str,
        enabled: bool,
        last_run_status: str | None,
        created_at: str,
    ) -> None:
        if self._postgres:
            self._execute(
                """
                INSERT INTO automations (id, name, trigger_type, action, enabled, last_run_status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (auto_id, name, trigger_type, action, enabled, last_run_status, created_at),
            )
        else:
            self._execute(
                """
                INSERT OR IGNORE INTO automations (id, name, trigger_type, action, enabled, last_run_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (auto_id, name, trigger_type, action, 1 if enabled else 0, last_run_status, created_at),
            )

    def _insert_run(
        self,
        run_id: str,
        automation_id: str,
        name: str,
        status: str,
        trigger: str,
        duration_ms: int | None,
        started_at: str,
        error: str | None,
    ) -> None:
        if self._postgres:
            self._execute(
                """
                INSERT INTO automation_runs (id, automation_id, name, status, trigger, duration_ms, started_at, error)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (run_id, automation_id, name, status, trigger, duration_ms, started_at, error),
            )
        else:
            self._execute(
                """
                INSERT OR IGNORE INTO automation_runs (id, automation_id, name, status, trigger, duration_ms, started_at, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, automation_id, name, status, trigger, duration_ms, started_at, error),
            )

    def create_automation(self, name: str, trigger_type: str, action: str) -> dict[str, Any]:
        auto_id = f"auto-{name.lower().replace(' ', '-')[:24]}-{int(datetime.now(timezone.utc).timestamp()) % 100000}"
        now = _utc_now()
        if self._postgres:
            self._execute(
                """
                INSERT INTO automations (id, name, trigger_type, action, enabled, last_run_status, created_at)
                VALUES (%s, %s, %s, %s, TRUE, NULL, %s)
                """,
                (auto_id, name, trigger_type, action, now),
            )
        else:
            self._execute(
                """
                INSERT INTO automations (id, name, trigger_type, action, enabled, last_run_status, created_at)
                VALUES (?, ?, ?, ?, 1, NULL, ?)
                """,
                (auto_id, name, trigger_type, action, now),
            )
        items = self.list_automations()
        return next((a for a in items if a["id"] == auto_id), {})

    def list_automations(self) -> list[dict[str, Any]]:
        rows = self._fetchall(
            "SELECT id, name, trigger_type, action, enabled, last_run_status, created_at FROM automations ORDER BY created_at"
        )
        return [self._automation_row(r) for r in rows]

    @staticmethod
    def _automation_row(row: Any) -> dict[str, Any]:
        if isinstance(row, dict):
            return {
                "id": row["id"],
                "name": row["name"],
                "trigger_type": row["trigger_type"],
                "action": row["action"],
                "enabled": bool(row["enabled"]),
                "last_run_status": row.get("last_run_status"),
                "created_at": str(row.get("created_at") or ""),
            }
        return {
            "id": row[0],
            "name": row[1],
            "trigger_type": row[2],
            "action": row[3],
            "enabled": bool(row[4]),
            "last_run_status": row[5],
            "created_at": row[6],
        }

    def patch_automation(self, automation_id: str, enabled: bool) -> dict[str, Any] | None:
        if self._postgres:
            self._execute("UPDATE automations SET enabled = %s WHERE id = %s", (enabled, automation_id))
        else:
            self._execute("UPDATE automations SET enabled = ? WHERE id = ?", (1 if enabled else 0, automation_id))
        items = self.list_automations()
        return next((a for a in items if a["id"] == automation_id), None)

    def get_automation(self, automation_id: str) -> dict[str, Any] | None:
        return next((a for a in self.list_automations() if a["id"] == automation_id), None)

    def record_run(
        self,
        automation_id: str,
        name: str,
        status: str,
        trigger: str,
        duration_ms: int | None = 100,
        error: str | None = None,
    ) -> dict[str, Any]:
        run_id = f"run-{secrets.token_hex(8)}"
        now = _utc_now()
        if self._postgres:
            self._execute(
                """
                INSERT INTO automation_runs (id, automation_id, name, status, trigger, duration_ms, started_at, error)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (run_id, automation_id, name, status, trigger, duration_ms, now, error),
            )
            self._execute("UPDATE automations SET last_run_status = %s WHERE id = %s", (status, automation_id))
        else:
            self._execute(
                """
                INSERT INTO automation_runs (id, automation_id, name, status, trigger, duration_ms, started_at, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, automation_id, name, status, trigger, duration_ms, now, error),
            )
            self._execute("UPDATE automations SET last_run_status = ? WHERE id = ?", (status, automation_id))
        return {
            "id": run_id,
            "automation_id": automation_id,
            "name": name,
            "status": status,
            "trigger": trigger,
            "started_at": now,
            "duration_ms": duration_ms,
            "error": error,
        }

    def list_automation_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        if self._postgres:
            rows = self._fetchall(
                """
                SELECT id, automation_id, name, status, trigger, duration_ms, started_at, error
                FROM automation_runs ORDER BY started_at DESC LIMIT %s
                """,
                (limit,),
            )
        else:
            rows = self._fetchall(
                """
                SELECT id, automation_id, name, status, trigger, duration_ms, started_at, error
                FROM automation_runs ORDER BY started_at DESC LIMIT ?
                """,
                (limit,),
            )
        return [self._run_row(r) for r in rows]

    def record_eol_scan(
        self,
        module_id: str,
        automation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scan_id = f"eol-{secrets.token_hex(8)}"
        now = _utc_now()
        meta = metadata or {}
        if self._postgres:
            self._execute(
                """
                INSERT INTO eol_scans (id, module_id, automation_id, status, scheduled_at, metadata)
                VALUES (%s, %s, %s, 'scheduled', %s, %s::jsonb)
                """,
                (scan_id, module_id, automation_id, now, json.dumps(meta)),
            )
        else:
            self._execute(
                """
                INSERT INTO eol_scans (id, module_id, automation_id, status, scheduled_at, metadata)
                VALUES (?, ?, ?, 'scheduled', ?, ?)
                """,
                (scan_id, module_id, automation_id, now, json.dumps(meta)),
            )
        return {
            "id": scan_id,
            "module_id": module_id,
            "automation_id": automation_id,
            "status": "scheduled",
            "scheduled_at": now,
            "metadata": meta,
        }

    def list_eol_scans(self, limit: int = 50) -> list[dict[str, Any]]:
        if self._postgres:
            rows = self._fetchall(
                """
                SELECT id, module_id, automation_id, status, scheduled_at, metadata
                FROM eol_scans ORDER BY scheduled_at DESC LIMIT %s
                """,
                (limit,),
            )
        else:
            rows = self._fetchall(
                """
                SELECT id, module_id, automation_id, status, scheduled_at, metadata
                FROM eol_scans ORDER BY scheduled_at DESC LIMIT ?
                """,
                (limit,),
            )
        return [self._eol_scan_row(r) for r in rows]

    @staticmethod
    def _run_row(row: Any) -> dict[str, Any]:
        if isinstance(row, dict):
            return {
                "id": row["id"],
                "automation_id": row["automation_id"],
                "name": row["name"],
                "status": row["status"],
                "trigger": row["trigger"],
                "duration_ms": row.get("duration_ms"),
                "started_at": str(row.get("started_at") or ""),
                "error": row.get("error"),
            }
        return {
            "id": row[0],
            "automation_id": row[1],
            "name": row[2],
            "status": row[3],
            "trigger": row[4],
            "duration_ms": row[5],
            "started_at": row[6],
            "error": row[7],
        }

    @staticmethod
    def _eol_scan_row(row: Any) -> dict[str, Any]:
        if isinstance(row, dict):
            meta = row.get("metadata") or {}
            if isinstance(meta, str):
                meta = json.loads(meta or "{}")
            return {
                "id": row["id"],
                "module_id": row["module_id"],
                "automation_id": row.get("automation_id"),
                "status": row["status"],
                "scheduled_at": str(row.get("scheduled_at") or ""),
                "metadata": meta,
            }
        return {
            "id": row[0],
            "module_id": row[1],
            "automation_id": row[2],
            "status": row[3],
            "scheduled_at": row[4],
            "metadata": json.loads(row[5] or "{}"),
        }

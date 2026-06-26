"""Automations store — migrated from sonoma_api."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AutomationsStore:
    def __init__(self, db_path: Path | None = None) -> None:
        path = db_path or Path(os.environ.get("RAPHAEL_AUTOMATION_DB", "/tmp/raphael-automation.db"))
        self.db_path = path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS automations (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_run_status TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS automation_runs (
                    id TEXT PRIMARY KEY,
                    automation_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    duration_ms INTEGER,
                    started_at TEXT NOT NULL,
                    error TEXT
                );
                """
            )
            self._seed()

    def _seed(self) -> None:
        if self.list_automations():
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.executemany(
                "INSERT INTO automations (id, name, trigger_type, action, enabled, last_run_status, created_at) VALUES (?, ?, ?, ?, 1, 'succeeded', ?)",
                [
                    ("auto-drc", "DRC on commit", "on_commit", "Run DRC + net connectivity check", now),
                    ("auto-release", "Release export on merge", "on_merge", "Export Gerber + BOM", now),
                ],
            )
            conn.executemany(
                "INSERT INTO automation_runs (id, automation_id, name, status, trigger, duration_ms, started_at, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("run-1", "auto-drc", "DRC: USB-PD input", "succeeded", "On commit", 245000, now, None),
                    ("run-2", "auto-release", "Gerber export: v2.3", "succeeded", "On merge", 364000, now, None),
                ],
            )

    def list_automations(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, name, trigger_type, action, enabled, last_run_status, created_at FROM automations ORDER BY created_at"
            ).fetchall()
        return [
            {
                "id": r[0], "name": r[1], "trigger_type": r[2], "action": r[3],
                "enabled": bool(r[4]), "last_run_status": r[5], "created_at": r[6],
            }
            for r in rows
        ]

    def create_automation(self, name: str, trigger_type: str, action: str) -> dict[str, Any]:
        auto_id = f"auto-{int(datetime.now(timezone.utc).timestamp())}"
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO automations (id, name, trigger_type, action, enabled, created_at) VALUES (?, ?, ?, ?, 1, ?)",
                (auto_id, name, trigger_type, action, now),
            )
        return next((a for a in self.list_automations() if a["id"] == auto_id), {})

    def toggle(self, automation_id: str, enabled: bool) -> dict[str, Any] | None:
        with self._conn() as conn:
            conn.execute("UPDATE automations SET enabled = ? WHERE id = ?", (1 if enabled else 0, automation_id))
        return next((a for a in self.list_automations() if a["id"] == automation_id), None)

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, automation_id, name, status, trigger, duration_ms, started_at, error FROM automation_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"id": r[0], "automation_id": r[1], "name": r[2], "status": r[3], "trigger": r[4],
             "duration_ms": r[5], "started_at": r[6], "error": r[7]}
            for r in rows
        ]

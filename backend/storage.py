"""Хранилище состояния: in-memory + опциональный SQLite-снимок.

По умолчанию демо работает полностью в памяти. Если задать
``RISK_PERSIST=1`` (или путь к файлу), состояние сохраняется в SQLite
и восстанавливается при старте. Этого достаточно для сценария
«оркестратор упал — очередь не потерялась».
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from backend.core.models import (
    Lock,
    PrioritySettings,
    Process,
    ProcessStatus,
    utcnow,
)

logger = logging.getLogger(__name__)

MAX_CONFLICTS = 500
MAX_EVENTS = 300


class Storage:
    def __init__(self, persist_path: str | Path | None = None) -> None:
        self.processes: dict[str, Process] = {}
        self.locks: list[Lock] = []
        self.conflicts: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.settings = PrioritySettings()
        self.persist_path = Path(persist_path) if persist_path else None

    # ------------------------------------------------------------------
    # Журналы
    # ------------------------------------------------------------------
    def log_event(
        self,
        kind: str,
        message: str,
        process_id: str | None = None,
        actor: str = "system",
    ) -> dict[str, Any]:
        event = {
            "id": f"e-{uuid.uuid4().hex[:8]}",
            "at": utcnow().isoformat(),
            "kind": kind,
            "message": message,
            "process_id": process_id,
            "actor": actor,
        }
        self.events.append(event)
        if len(self.events) > MAX_EVENTS:
            del self.events[: len(self.events) - MAX_EVENTS]
        return event

    def log_conflict(
        self,
        *,
        kind: str,
        resource_key: str,
        process_id: str,
        process_name: str,
        blocked_by: str | None,
        blocked_by_name: str | None,
        message: str,
        resolution: str = "Процесс заблокирован до освобождения ресурса",
    ) -> dict[str, Any]:
        conflict = {
            "id": f"c-{uuid.uuid4().hex[:8]}",
            "at": utcnow().isoformat(),
            "kind": kind,
            "resource_key": resource_key,
            "process_id": process_id,
            "process_name": process_name,
            "blocked_by": blocked_by,
            "blocked_by_name": blocked_by_name,
            "message": message,
            "resolution": resolution,
        }
        self.conflicts.append(conflict)
        if len(self.conflicts) > MAX_CONFLICTS:
            del self.conflicts[: len(self.conflicts) - MAX_CONFLICTS]
        return conflict

    # ------------------------------------------------------------------
    # Снимки
    # ------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        return {
            "processes": [p.to_dict() for p in self.processes.values()],
            "settings": self.settings.to_dict(),
            "conflicts": self.conflicts,
            "events": self.events,
            "saved_at": utcnow().isoformat(),
        }

    def reset(self) -> None:
        self.processes.clear()
        self.locks.clear()
        self.conflicts.clear()
        self.events.clear()
        self.settings = PrioritySettings()
        self.log_event("reset", "Состояние оркестратора сброшено")
        self.save()

    def save(self) -> None:
        if not self.persist_path:
            return
        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self.snapshot(), ensure_ascii=False)
            with closing(sqlite3.connect(self.persist_path)) as conn:
                with conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS snapshot (
                            id INTEGER PRIMARY KEY CHECK (id = 1),
                            payload TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        """
                        INSERT INTO snapshot (id, payload, updated_at)
                        VALUES (1, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            payload = excluded.payload,
                            updated_at = excluded.updated_at
                        """,
                        (payload, utcnow().isoformat()),
                    )
        except Exception:  # pragma: no cover - защита демо от I/O-ошибок
            logger.exception("Не удалось сохранить состояние в %s", self.persist_path)

    def restore(self) -> bool:
        if not self.persist_path or not self.persist_path.exists():
            return False
        try:
            with closing(sqlite3.connect(self.persist_path)) as conn:
                with conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS snapshot (
                            id INTEGER PRIMARY KEY CHECK (id = 1),
                            payload TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                        """
                    )
                row = conn.execute(
                    "SELECT payload FROM snapshot WHERE id = 1"
                ).fetchone()
            if not row:
                return False
            data = json.loads(row[0])
            self.processes = {
                item["id"]: Process.from_dict(item)
                for item in data.get("processes", [])
            }
            self.settings = PrioritySettings.from_dict(data.get("settings"))
            self.conflicts = list(data.get("conflicts", []))
            self.events = list(data.get("events", []))
            self.locks = []
            # После рестарта незавершённые процессы возвращаются в очередь.
            for process in self.processes.values():
                if process.status is ProcessStatus.RUNNING:
                    process.status = ProcessStatus.QUEUED
                    process.started_at = None
                    process.progress = 0.0
            self.log_event("restore", "Состояние восстановлено из SQLite")
            return True
        except Exception:  # pragma: no cover
            logger.exception("Не удалось восстановить состояние из %s", self.persist_path)
            return False

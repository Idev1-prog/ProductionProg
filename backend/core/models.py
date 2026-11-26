"""Доменные модели оркестратора.

Модуль не знает про FastAPI и Streamlit: только dataclasses и enum'ы.
Это позволяет использовать ядро в тестах и переиспользовать в других адаптерах.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


def utcnow() -> datetime:
    """Единая точка получения текущего времени (UTC, aware)."""

    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return as_utc(datetime.fromisoformat(value))


def as_utc(value: datetime | None) -> datetime | None:
    """Приводит datetime к aware UTC (naive считается UTC)."""

    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class FlowType(str, Enum):
    """Поток запуска процесса."""

    MANUAL = "manual"
    AUTO = "auto"


class ProcessStatus(str, Enum):
    QUEUED = "queued"
    BLOCKED = "blocked"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class OpType(str, Enum):
    READ = "read"
    WRITE = "write"


@dataclass
class Resource:
    """Конкретный ресурс/партиция, к которой обращается процесс."""

    key: str
    mode: OpType = OpType.WRITE
    service: str = "risk-db"

    def __post_init__(self) -> None:
        if not isinstance(self.mode, OpType):
            self.mode = OpType(self.mode)

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "mode": self.mode.value, "service": self.service}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Resource":
        return cls(
            key=str(data["key"]),
            mode=OpType(data.get("mode", "write")),
            service=str(data.get("service", "risk-db")),
        )


@dataclass
class Lock:
    """Блокировка ресурса, удерживаемая выполняющимся процессом."""

    resource_key: str
    process_id: str
    mode: OpType
    acquired_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if not isinstance(self.mode, OpType):
            self.mode = OpType(self.mode)
        self.acquired_at = as_utc(self.acquired_at) or utcnow()

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_key": self.resource_key,
            "process_id": self.process_id,
            "mode": self.mode.value,
            "acquired_at": _iso(self.acquired_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Lock":
        return cls(
            resource_key=str(data["resource_key"]),
            process_id=str(data["process_id"]),
            mode=OpType(data.get("mode", "write")),
            acquired_at=_parse_dt(data.get("acquired_at")) or utcnow(),
        )


@dataclass
class PrioritySettings:
    """Настраиваемые веса приоритетов (конфигуратор UI)."""

    manual_base: float = 1000.0
    sla_weight: float = 60.0
    urgency_weight: float = 30.0
    starvation_weight: float = 10.0
    max_running: int = 3
    tick_interval: float = 0.5

    def to_dict(self) -> dict[str, float | int]:
        return {
            "manual_base": self.manual_base,
            "sla_weight": self.sla_weight,
            "urgency_weight": self.urgency_weight,
            "starvation_weight": self.starvation_weight,
            "max_running": self.max_running,
            "tick_interval": self.tick_interval,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PrioritySettings":
        data = data or {}
        defaults = cls()
        return cls(
            manual_base=float(data.get("manual_base", defaults.manual_base)),
            sla_weight=float(data.get("sla_weight", defaults.sla_weight)),
            urgency_weight=float(data.get("urgency_weight", defaults.urgency_weight)),
            starvation_weight=float(
                data.get("starvation_weight", defaults.starvation_weight)
            ),
            max_running=int(data.get("max_running", defaults.max_running)),
            tick_interval=float(data.get("tick_interval", defaults.tick_interval)),
        )


@dataclass
class Process:
    """Процесс расчёта: метаданные + текущее состояние выполнения."""

    id: str
    name: str
    flow: FlowType
    resources: list[Resource]
    urgency: int = 5
    duration_sec: float = 10.0
    sla_deadline: datetime = field(
        default_factory=lambda: utcnow() + timedelta(minutes=10)
    )
    priority: float = 0.0
    status: ProcessStatus = ProcessStatus.QUEUED
    created_at: datetime = field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    paused_at: datetime | None = None
    progress: float = 0.0
    attempts: int = 0
    blocked_by: list[str] = field(default_factory=list)
    blocked_reason: str = ""
    conflict_signature: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.flow, FlowType):
            self.flow = FlowType(self.flow)
        if not isinstance(self.status, ProcessStatus):
            self.status = ProcessStatus(self.status)
        self.sla_deadline = as_utc(self.sla_deadline) or utcnow()
        self.created_at = as_utc(self.created_at) or utcnow()
        self.started_at = as_utc(self.started_at)
        self.finished_at = as_utc(self.finished_at)
        self.paused_at = as_utc(self.paused_at)

    # ------------------------------------------------------------------
    # Производные величины
    # ------------------------------------------------------------------
    def wait_seconds(self, now: datetime | None = None) -> float:
        """Сколько процесс ждал в очереди до старта (или ждёт сейчас)."""

        now = now or utcnow()
        anchor = self.started_at or self.finished_at or now
        return max(0.0, (anchor - self.created_at).total_seconds())

    def elapsed_seconds(self, now: datetime | None = None) -> float:
        if not self.started_at:
            return 0.0
        now = now or utcnow()
        anchor = self.finished_at or now
        return max(0.0, (anchor - self.started_at).total_seconds())

    def to_dict(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or utcnow()
        return {
            "id": self.id,
            "name": self.name,
            "flow": self.flow.value,
            "status": self.status.value,
            "priority": round(self.priority, 3),
            "urgency": self.urgency,
            "duration_sec": self.duration_sec,
            "progress": round(min(1.0, max(0.0, self.progress)), 3),
            "attempts": self.attempts,
            "resources": [r.to_dict() for r in self.resources],
            "created_at": _iso(self.created_at),
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "paused_at": _iso(self.paused_at),
            "sla_deadline": _iso(self.sla_deadline),
            "blocked_by": list(self.blocked_by),
            "blocked_reason": self.blocked_reason,
            "conflict_signature": self.conflict_signature,
            "meta": dict(self.meta),
            "wait_sec": round(self.wait_seconds(now), 1),
            "elapsed_sec": round(self.elapsed_seconds(now), 1),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Process":
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            flow=FlowType(data["flow"]),
            resources=[Resource.from_dict(r) for r in data.get("resources", [])],
            urgency=int(data.get("urgency", 5)),
            duration_sec=float(data.get("duration_sec", 10.0)),
            sla_deadline=_parse_dt(data.get("sla_deadline")) or utcnow(),
            priority=float(data.get("priority", 0.0)),
            status=ProcessStatus(data.get("status", "queued")),
            created_at=_parse_dt(data.get("created_at")) or utcnow(),
            started_at=_parse_dt(data.get("started_at")),
            finished_at=_parse_dt(data.get("finished_at")),
            paused_at=_parse_dt(data.get("paused_at")),
            progress=float(data.get("progress", 0.0)),
            attempts=int(data.get("attempts", 0)),
            blocked_by=list(data.get("blocked_by", [])),
            blocked_reason=str(data.get("blocked_reason", "")),
            conflict_signature=str(data.get("conflict_signature", "")),
            meta=dict(data.get("meta", {})),
        )

"""Pydantic-контракты API (заморозка после 0:30 по регламенту хакатона)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ResourceIn(BaseModel):
    key: str = Field(min_length=1, max_length=200, examples=["dm_credit.portfolio"])
    mode: Literal["read", "write"] = "write"
    service: str = Field(default="risk-db", max_length=100)


class ResourceOut(BaseModel):
    key: str
    mode: str
    service: str


class ProcessCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    flow: Literal["manual", "auto"] = "auto"
    urgency: int = Field(default=5, ge=1, le=10)
    duration_sec: float = Field(default=10.0, gt=0, le=600)
    sla_in_sec: float | None = Field(
        default=600.0,
        ge=0,
        description="Дедлайн SLA относительно момента создания, сек",
    )
    sla_deadline: datetime | None = Field(
        default=None,
        description="Абсолютный дедлайн; имеет приоритет над sla_in_sec",
    )
    resources: list[ResourceIn] = Field(min_length=1)
    meta: dict[str, Any] = Field(default_factory=dict)


class ProcessOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    flow: str
    status: str
    priority: float
    urgency: int
    duration_sec: float
    progress: float
    attempts: int
    resources: list[ResourceOut]
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    paused_at: datetime | None = None
    sla_deadline: datetime
    blocked_by: list[str] = Field(default_factory=list)
    blocked_reason: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)
    wait_sec: float = 0.0
    elapsed_sec: float = 0.0


class SettingsIn(BaseModel):
    manual_base: float = Field(default=1000.0, ge=1000, le=10000)
    sla_weight: float = Field(default=60.0, ge=0, le=1000)
    urgency_weight: float = Field(default=30.0, ge=0, le=1000)
    starvation_weight: float = Field(default=10.0, ge=0, le=1000)
    max_running: int = Field(default=3, ge=1, le=100)
    tick_interval: float = Field(default=0.5, ge=0.1, le=60)


class SettingsOut(SettingsIn):
    pass


class GanttEntry(BaseModel):
    id: str
    name: str
    flow: str
    status: str
    start: datetime
    end: datetime
    priority: float
    progress: float
    duration_sec: float
    resources: str
    blocked_reason: str = ""


class ConflictOut(BaseModel):
    id: str
    at: datetime
    kind: str
    resource_key: str
    process_id: str
    process_name: str
    blocked_by: str | None = None
    blocked_by_name: str | None = None
    message: str
    resolution: str


class StateOut(BaseModel):
    now: datetime
    settings: SettingsOut
    counts: dict[str, int]
    processes: list[ProcessOut]
    queue: list[ProcessOut]
    running: list[ProcessOut]
    conflicts: list[ConflictOut]
    events: list[dict[str, Any]]
    resource_load: list[dict[str, Any]]
    metrics: dict[str, Any]


class ScenarioIn(BaseModel):
    name: str = Field(default="Сценарий", max_length=200)
    description: str = ""
    settings: SettingsIn | None = None
    processes: list[ProcessCreate] = Field(min_length=1)


class ResetOut(BaseModel):
    ok: bool
    message: str


class HealthOut(BaseModel):
    status: str
    service: str
    now: datetime

"""Ядро оркестратора: постановка процессов, тик планировщика, состояние."""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta
from functools import wraps
from typing import Any, Iterable, Callable, TypeVar

from backend.core import conflicts as conflict_utils
from backend.core.models import (
    FlowType,
    Lock,
    OpType,
    PrioritySettings,
    Process,
    ProcessStatus,
    Resource,
    utcnow,
)
from backend.core.priority import rank_processes, score_process, sla_score
from backend.core.state_machine import transition
from backend.core.worker import Worker
from backend.storage import Storage

TERMINAL_STATUSES = {
    ProcessStatus.COMPLETED,
    ProcessStatus.CANCELLED,
    ProcessStatus.FAILED,
}

T = TypeVar("T")


def synchronized(method: Callable[..., T]) -> Callable[..., T]:
    """Сериализует доступ к состоянию: тик-цикл и API работают в разных потоках."""

    @wraps(method)
    def wrapper(self: "Orchestrator", *args: Any, **kwargs: Any) -> T:
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class Orchestrator:
    def __init__(self, storage: Storage, worker: Worker | None = None) -> None:
        self.storage = storage
        self.worker = worker or Worker()
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Свойства и утилиты
    # ------------------------------------------------------------------
    @property
    def settings(self) -> PrioritySettings:
        return self.storage.settings

    def _new_id(self) -> str:
        return f"p-{uuid.uuid4().hex[:8]}"

    def _get(self, process_id: str) -> Process:
        process = self.storage.processes.get(process_id)
        if process is None:
            raise KeyError(f"Процесс {process_id} не найден")
        return process

    def _running(self) -> list[Process]:
        return [
            p
            for p in self.storage.processes.values()
            if p.status is ProcessStatus.RUNNING
        ]

    def _release_locks(self, process_id: str) -> None:
        self.storage.locks = [
            lock for lock in self.storage.locks if lock.process_id != process_id
        ]

    @staticmethod
    def _coerce_resources(resources: Iterable[Resource | dict[str, Any]]) -> list[Resource]:
        result: list[Resource] = []
        for resource in resources:
            if isinstance(resource, Resource):
                result.append(resource)
            elif isinstance(resource, dict):
                result.append(
                    Resource(
                        key=str(resource["key"]),
                        mode=OpType(resource.get("mode", "write")),
                        service=str(resource.get("service", "risk-db")),
                    )
                )
            else:  # pragma: no cover - защита от неверного типа
                raise ValueError(f"Некорректный ресурс: {resource!r}")
        return conflict_utils.normalize_resources(result)

    # ------------------------------------------------------------------
    # Постановка процессов
    # ------------------------------------------------------------------
    @synchronized
    def add_process(
        self,
        *,
        name: str,
        flow: FlowType | str,
        resources: Iterable[Resource | dict[str, Any]],
        urgency: int = 5,
        duration_sec: float = 10.0,
        sla_deadline=None,
        meta: dict[str, Any] | None = None,
    ) -> Process:
        flow_enum = flow if isinstance(flow, FlowType) else FlowType(flow)
        normalized = self._coerce_resources(resources)
        if not normalized:
            raise ValueError("Процесс должен обращаться хотя бы к одному ресурсу")
        if not name.strip():
            raise ValueError("Имя процесса не может быть пустым")

        process = Process(
            id=self._new_id(),
            name=name.strip(),
            flow=flow_enum,
            resources=normalized,
            urgency=max(1, min(10, int(urgency))),
            duration_sec=max(0.5, float(duration_sec)),
            sla_deadline=sla_deadline or (utcnow() + timedelta(minutes=10)),
            meta=dict(meta or {}),
        )
        process.priority = score_process(process, self.settings)
        self.storage.processes[process.id] = process
        self.storage.log_event(
            "process_added",
            f"Процесс «{process.name}» добавлен в очередь ({flow_enum.value})",
            process.id,
        )

        if process.flow is FlowType.MANUAL:
            self._preempt_for_manual(process)

        self.tick()
        self.storage.save()
        return process

    def _preempt_for_manual(self, manual: Process) -> None:
        """Ручной поток вытесняет автоматические процессы с общими ресурсами."""

        for other in list(self._running()):
            if other.flow is not FlowType.AUTO:
                continue
            overlap = conflict_utils.resources_overlap(manual, other)
            if not overlap:
                continue

            self._release_locks(other.id)
            transition(other, ProcessStatus.BLOCKED)
            other.started_at = None
            other.progress = 0.0
            other.blocked_by = [manual.id]
            other.blocked_reason = f"Вытеснен ручным процессом «{manual.name}»"
            other.conflict_signature = ""

            self.storage.log_conflict(
                kind="OVERRIDE",
                resource_key=overlap[0],
                process_id=other.id,
                process_name=other.name,
                blocked_by=manual.id,
                blocked_by_name=manual.name,
                message=(
                    f"OVERRIDE: ручной процесс «{manual.name}» вытеснил "
                    f"автоматический «{other.name}» с ресурса «{overlap[0]}»"
                ),
                resolution="Автоматический процесс остановлен и возвращён в очередь",
            )
            self.storage.log_event(
                "preempted",
                f"«{other.name}» вытеснен ручным «{manual.name}»",
                other.id,
            )

    # ------------------------------------------------------------------
    # Планировщик
    # ------------------------------------------------------------------
    @synchronized
    def tick(self) -> None:
        now = utcnow()
        self._finish_due(now)
        self._refresh_progress(now)
        self._refresh_priorities(now)

        running_count = len(self._running())
        max_running = max(1, int(self.settings.max_running))
        candidates = [
            p
            for p in self.storage.processes.values()
            if p.status in (ProcessStatus.QUEUED, ProcessStatus.BLOCKED)
        ]
        candidates = rank_processes(candidates, self.settings, now)

        for process in candidates:
            if running_count >= max_running:
                break
            conflicts = conflict_utils.find_conflicts(process, self.storage.locks)
            if conflicts:
                self._block(process, conflicts)
                continue
            self._start(process, now)
            running_count += 1

    def _finish_due(self, now) -> None:
        for process in list(self._running()):
            expected_end = self.worker.expected_end(process)
            if expected_end is None or now < expected_end:
                continue
            self._release_locks(process.id)
            transition(process, ProcessStatus.COMPLETED)
            process.finished_at = now
            process.progress = 1.0
            process.blocked_by = []
            process.blocked_reason = ""
            self.storage.log_event(
                "completed",
                f"Процесс «{process.name}» завершён",
                process.id,
            )

    def _refresh_progress(self, now) -> None:
        """Продвигает выполнение процессов по времени между тиками."""

        for process in self._running():
            process.progress = self.worker.progress(process, now)

    def _refresh_priorities(self, now) -> None:
        for process in self.storage.processes.values():
            if process.status in (
                ProcessStatus.QUEUED,
                ProcessStatus.BLOCKED,
                ProcessStatus.RUNNING,
            ):
                process.priority = score_process(process, self.settings, now)

    def _start(self, process: Process, now) -> None:
        transition(process, ProcessStatus.RUNNING)
        process.started_at = now
        process.finished_at = None
        process.paused_at = None
        process.progress = 0.0
        process.attempts += 1
        process.blocked_by = []
        process.blocked_reason = ""
        process.conflict_signature = ""
        for resource in process.resources:
            self.storage.locks.append(
                Lock(
                    resource_key=resource.key,
                    process_id=process.id,
                    mode=resource.mode,
                    acquired_at=now,
                )
            )
        self.storage.log_event(
            "started",
            f"Процесс «{process.name}» получил ресурсы и выполняется",
            process.id,
        )

    def _block(self, process: Process, conflicts: list[Any]) -> None:
        if process.status is ProcessStatus.RUNNING:
            self._release_locks(process.id)
        transition(process, ProcessStatus.BLOCKED)

        signature = conflict_utils.conflict_signature(process, conflicts)
        blocker_ids = sorted(
            {bid for conflict in conflicts for bid in conflict.blocker_ids}
        )
        process.blocked_by = blocker_ids
        process.blocked_reason = "; ".join(conflict.message for conflict in conflicts)
        if signature == process.conflict_signature:
            return
        process.conflict_signature = signature

        for conflict in conflicts:
            for blocker_id in conflict.blocker_ids:
                blocker = self.storage.processes.get(blocker_id)
                self.storage.log_conflict(
                    kind=conflict.kind,
                    resource_key=conflict.resource_key,
                    process_id=process.id,
                    process_name=process.name,
                    blocked_by=blocker_id,
                    blocked_by_name=blocker.name if blocker else blocker_id,
                    message=conflict.message,
                )
        self.storage.log_event(
            "blocked",
            f"Процесс «{process.name}» заблокирован: {process.blocked_reason}",
            process.id,
        )

    # ------------------------------------------------------------------
    # Управление жизненным циклом
    # ------------------------------------------------------------------
    @synchronized
    def pause(self, process_id: str) -> Process:
        process = self._get(process_id)
        now = utcnow()
        if process.status is ProcessStatus.RUNNING:
            process.progress = self.worker.progress(process, now)
            self._release_locks(process.id)
            transition(process, ProcessStatus.PAUSED)
        elif process.status in (ProcessStatus.QUEUED, ProcessStatus.BLOCKED):
            transition(process, ProcessStatus.PAUSED)
        else:
            raise ValueError(
                f"Нельзя поставить на паузу процесс в статусе {process.status.value}"
            )
        process.paused_at = now
        self.storage.log_event(
            "paused", f"Процесс «{process.name}» поставлен на паузу", process.id
        )
        self.storage.save()
        return process

    @synchronized
    def resume(self, process_id: str) -> Process:
        process = self._get(process_id)
        if process.status is not ProcessStatus.PAUSED:
            raise ValueError("Возобновить можно только процесс на паузе")
        process.started_at = None
        process.finished_at = None
        process.paused_at = None
        process.progress = 0.0
        process.conflict_signature = ""
        process.blocked_by = []
        process.blocked_reason = ""
        transition(process, ProcessStatus.QUEUED)
        self.storage.log_event(
            "resumed", f"Процесс «{process.name}» возвращён в очередь", process.id
        )
        self.tick()
        self.storage.save()
        return process

    @synchronized
    def cancel(self, process_id: str) -> Process:
        process = self._get(process_id)
        if process.status in TERMINAL_STATUSES:
            raise ValueError(
                f"Нельзя отменить процесс в статусе {process.status.value}"
            )
        self._release_locks(process.id)
        transition(process, ProcessStatus.CANCELLED)
        process.finished_at = utcnow()
        process.blocked_by = []
        process.blocked_reason = ""
        self.storage.log_event(
            "cancelled", f"Процесс «{process.name}» отменён", process.id
        )
        self.storage.save()
        return process

    @synchronized
    def restart(self, process_id: str) -> Process:
        process = self._get(process_id)
        self._release_locks(process.id)
        process.status = ProcessStatus.QUEUED
        process.created_at = utcnow()
        process.started_at = None
        process.finished_at = None
        process.paused_at = None
        process.progress = 0.0
        process.blocked_by = []
        process.blocked_reason = ""
        process.conflict_signature = ""
        process.priority = score_process(process, self.settings)
        self.storage.log_event(
            "restarted", f"Процесс «{process.name}» перезапущен", process.id
        )
        self.tick()
        self.storage.save()
        return process

    # ------------------------------------------------------------------
    # Настройки
    # ------------------------------------------------------------------
    @synchronized
    def update_settings(self, data: dict[str, Any]) -> PrioritySettings:
        # Валидация идёт на копии: при ошибке текущие настройки не портятся.
        settings = PrioritySettings(**self.storage.settings.to_dict())
        numeric_fields = (
            "manual_base",
            "sla_weight",
            "urgency_weight",
            "starvation_weight",
            "tick_interval",
        )
        for field_name in numeric_fields:
            if data.get(field_name) is not None:
                setattr(settings, field_name, float(data[field_name]))
        if data.get("max_running") is not None:
            settings.max_running = int(data["max_running"])

        if settings.manual_base < 1000.0:
            raise ValueError("manual_base не может быть меньше 1000")
        for weight_name in ("sla_weight", "urgency_weight", "starvation_weight"):
            if getattr(settings, weight_name) < 0:
                raise ValueError(f"{weight_name} не может быть отрицательным")
        settings.max_running = max(1, min(100, settings.max_running))
        settings.tick_interval = max(0.1, min(60.0, settings.tick_interval))

        self.storage.settings = settings
        self._refresh_priorities(utcnow())
        self.storage.log_event(
            "settings_updated",
            "Обновлены веса приоритетов: "
            + ", ".join(f"{k}={v}" for k, v in settings.to_dict().items()),
        )
        self.storage.save()
        return settings

    @synchronized
    def reset(self) -> None:
        self.storage.reset()

    # ------------------------------------------------------------------
    # Чтение состояния
    # ------------------------------------------------------------------
    @synchronized
    def get_state(self) -> dict[str, Any]:
        now = utcnow()
        processes = sorted(
            self.storage.processes.values(), key=lambda p: p.created_at
        )
        counts = {status.value: 0 for status in ProcessStatus}
        for process in processes:
            counts[process.status.value] += 1

        queue = rank_processes(
            [
                p
                for p in processes
                if p.status in (ProcessStatus.QUEUED, ProcessStatus.BLOCKED)
            ],
            self.settings,
            now,
        )
        running = sorted(
            self._running(), key=lambda p: p.started_at or p.created_at
        )
        conflicts = list(reversed(self.storage.conflicts))
        events = list(reversed(self.storage.events))

        started = [p for p in processes if p.started_at is not None]
        avg_wait = (
            sum(p.wait_seconds(now) for p in started) / len(started) if started else 0.0
        )
        max_wait = max(
            (p.wait_seconds(now) for p in queue),
            default=0.0,
        )
        sla_at_risk = sum(
            1
            for p in processes
            if p.flow is FlowType.AUTO
            and p.status
            in (
                ProcessStatus.QUEUED,
                ProcessStatus.BLOCKED,
                ProcessStatus.RUNNING,
            )
            and sla_score(p.sla_deadline, now) >= 80.0
        )

        metrics = {
            "total": len(processes),
            "completed": counts[ProcessStatus.COMPLETED.value],
            "failed": counts[ProcessStatus.FAILED.value],
            "cancelled": counts[ProcessStatus.CANCELLED.value],
            "running": counts[ProcessStatus.RUNNING.value],
            "queued": counts[ProcessStatus.QUEUED.value],
            "blocked": counts[ProcessStatus.BLOCKED.value],
            "paused": counts[ProcessStatus.PAUSED.value],
            "manual_total": sum(1 for p in processes if p.flow is FlowType.MANUAL),
            "auto_total": sum(1 for p in processes if p.flow is FlowType.AUTO),
            "conflicts_total": len(self.storage.conflicts),
            "sla_at_risk": sla_at_risk,
            "avg_wait_sec": round(avg_wait, 1),
            "max_wait_sec": round(max_wait, 1),
            "utilization_pct": round(
                min(100.0, len(running) / max(1, self.settings.max_running) * 100.0), 1
            ),
        }

        return {
            "now": now.isoformat(),
            "settings": self.settings.to_dict(),
            "counts": counts,
            "processes": [p.to_dict(now) for p in processes],
            "queue": [p.to_dict(now) for p in queue],
            "running": [p.to_dict(now) for p in running],
            "conflicts": conflicts,
            "events": events,
            "resource_load": self._resource_load(),
            "metrics": metrics,
        }

    def _resource_load(self) -> list[dict[str, Any]]:
        load: dict[str, dict[str, Any]] = {}
        for process in self._running():
            for resource in process.resources:
                entry = load.setdefault(
                    resource.key,
                    {
                        "key": resource.key,
                        "service": resource.service,
                        "readers": 0,
                        "writers": 0,
                        "processes": [],
                    },
                )
                if resource.mode is OpType.WRITE:
                    entry["writers"] += 1
                else:
                    entry["readers"] += 1
                entry["processes"].append(process.name)
        return sorted(load.values(), key=lambda item: item["key"])

    @synchronized
    def get_gantt(self) -> list[dict[str, Any]]:
        now = utcnow()
        entries: list[dict[str, Any]] = []
        for process in sorted(
            self.storage.processes.values(), key=lambda p: p.created_at
        ):
            if process.started_at is None:
                continue
            if process.finished_at is not None:
                end = process.finished_at
            elif process.status is ProcessStatus.RUNNING:
                end = self.worker.expected_end(process) or now
            elif process.paused_at is not None:
                end = process.paused_at
            else:
                end = now
            entries.append(
                {
                    "id": process.id,
                    "name": process.name,
                    "flow": process.flow.value,
                    "status": process.status.value,
                    "start": process.started_at.isoformat(),
                    "end": end.isoformat(),
                    "priority": round(process.priority, 3),
                    "progress": round(process.progress, 3),
                    "duration_sec": process.duration_sec,
                    "resources": ", ".join(
                        f"{r.key}:{r.mode.value}" for r in process.resources
                    ),
                    "blocked_reason": process.blocked_reason,
                }
            )
        return entries

    @synchronized
    def get_conflicts(self) -> list[dict[str, Any]]:
        return list(reversed(self.storage.conflicts))

    @synchronized
    def get_events(self) -> list[dict[str, Any]]:
        return list(reversed(self.storage.events))

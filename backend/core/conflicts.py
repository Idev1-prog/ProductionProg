"""Conflict Manager: обнаружение RAW/WAW по resource_key.

Блокировки гранулярные: ключ — произвольная строка, заданная вызывающей
системой (например, ``dm_credit.portfolio:2026-11-25``), а не вся БД.
Отдельного разбора таблиц, срезов и дат ядро не делает.

Семантика:
* read + read  -> совместимы;
* write + write -> WAW;
* write + read / read + write -> RAW (в отчёте журнала это одна
  «конфликтующая пара», чтобы не усложнять демо).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.core.models import Lock, OpType, Process, Resource


@dataclass
class ConflictInfo:
    resource_key: str
    kind: str  # RAW / WAW
    blocker_ids: list[str] = field(default_factory=list)
    message: str = ""


def find_conflicts(process: Process, locks: list[Lock]) -> list[ConflictInfo]:
    """Возвращает список конфликтов процесса с чужими активными блокировками."""

    by_key: dict[str, list[Lock]] = {}
    for lock in locks:
        if lock.process_id == process.id:
            continue
        by_key.setdefault(lock.resource_key, []).append(lock)

    conflicts: list[ConflictInfo] = []
    for resource in process.resources:
        existing = by_key.get(resource.key)
        if not existing:
            continue

        if resource.mode is OpType.READ:
            writers = [lock for lock in existing if lock.mode is OpType.WRITE]
            if not writers:
                continue
            kind = "RAW"
            blockers = writers
            message = (
                f"RAW: чтение «{resource.key}» ждёт завершения записи"
            )
        else:
            writers = [lock for lock in existing if lock.mode is OpType.WRITE]
            if writers:
                kind = "WAW"
                blockers = writers
                message = f"WAW: запись в «{resource.key}» уже выполняется"
            else:
                readers = [lock for lock in existing if lock.mode is OpType.READ]
                if not readers:
                    continue
                kind = "RAW"
                blockers = readers
                message = (
                    f"RAW: запись в «{resource.key}» ждёт завершения чтения"
                )

        blocker_ids = sorted({lock.process_id for lock in blockers})
        conflicts.append(
            ConflictInfo(
                resource_key=resource.key,
                kind=kind,
                blocker_ids=blocker_ids,
                message=message,
            )
        )

    return conflicts


def resources_overlap(first: Process, second: Process) -> list[str]:
    """Ключи, на которых два процесса несовместимы (для preemption)."""

    first_modes: dict[str, OpType] = {}
    for resource in first.resources:
        first_modes[resource.key] = resource.mode

    overlap: list[str] = []
    for resource in second.resources:
        mode = first_modes.get(resource.key)
        if mode is None:
            continue
        if mode is OpType.WRITE or resource.mode is OpType.WRITE:
            overlap.append(resource.key)
    return sorted(set(overlap))


def conflict_signature(process: Process, conflicts: list[ConflictInfo]) -> str:
    blockers = sorted({bid for conflict in conflicts for bid in conflict.blocker_ids})
    keys = sorted({conflict.resource_key for conflict in conflicts})
    return f"{process.id}|{','.join(blockers)}|{','.join(keys)}"


def normalize_resources(resources: list[Resource]) -> list[Resource]:
    """Схлопывает дубли ключей: write сильнее read, сервис сохраняется."""

    merged: dict[str, Resource] = {}
    for resource in resources:
        key = resource.key.strip()
        if not key:
            continue
        current = merged.get(key)
        if current is None:
            merged[key] = Resource(key=key, mode=resource.mode, service=resource.service)
            continue
        mode = (
            OpType.WRITE
            if current.mode is OpType.WRITE or resource.mode is OpType.WRITE
            else OpType.READ
        )
        service = resource.service or current.service
        merged[key] = Resource(key=key, mode=mode, service=service)
    return list(merged.values())

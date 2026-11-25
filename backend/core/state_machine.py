"""Машина состояний процесса.

Явная таблица переходов защищает от «телепортации» статусов
(например, completed -> running без restart).
"""

from __future__ import annotations

from backend.core.models import Process, ProcessStatus

S = ProcessStatus

TRANSITIONS: dict[ProcessStatus, set[ProcessStatus]] = {
    S.QUEUED: {S.BLOCKED, S.RUNNING, S.PAUSED, S.CANCELLED, S.FAILED},
    S.BLOCKED: {S.QUEUED, S.RUNNING, S.PAUSED, S.CANCELLED, S.FAILED},
    S.RUNNING: {S.COMPLETED, S.BLOCKED, S.PAUSED, S.CANCELLED, S.FAILED},
    S.PAUSED: {S.QUEUED, S.CANCELLED, S.FAILED},
    S.COMPLETED: set(),
    S.CANCELLED: set(),
    S.FAILED: set(),
}


class InvalidTransition(ValueError):
    """Попытка недопустимого перехода между статусами."""


def can_transition(current: ProcessStatus, target: ProcessStatus) -> bool:
    return target in TRANSITIONS.get(current, set())


def transition(process: Process, target: ProcessStatus) -> Process:
    if process.status == target:
        return process
    if not can_transition(process.status, target):
        raise InvalidTransition(
            f"Недопустимый переход {process.status.value} -> {target.value} "
            f"для процесса {process.id}"
        )
    process.status = target
    return process

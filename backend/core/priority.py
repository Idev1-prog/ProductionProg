"""Priority Engine.

Правила:
* ручной поток имеет абсолютный приоритет (manual_base >= 1000);
* автоматический поток сортируется по SLA, балльной срочности и «голоду»
  (сколько процесс уже ждёт).

Все веса приходят из настроек, поэтому UI-конфигуратор реально влияет
на порядок запуска без перезапуска сервиса.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from backend.core.models import (
    FlowType,
    PrioritySettings,
    Process,
    utcnow,
)

SLA_HORIZON_SEC = 600.0
STARVATION_HORIZON_SEC = 300.0


def sla_score(
    deadline: datetime | None,
    now: datetime | None = None,
    horizon_sec: float = SLA_HORIZON_SEC,
) -> float:
    """0..100: чем ближе дедлайн (или чем сильнее просрочен), тем выше."""

    if deadline is None:
        return 0.0
    now = now or utcnow()
    remaining = (deadline - now).total_seconds()
    if remaining <= 0:
        return 100.0
    if remaining >= horizon_sec:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (1.0 - remaining / horizon_sec)))


def starvation_score(
    created_at: datetime,
    now: datetime | None = None,
    horizon_sec: float = STARVATION_HORIZON_SEC,
) -> float:
    """0..100: защита от starvation — чем дольше ждём, тем выше балл."""

    now = now or utcnow()
    waited = max(0.0, (now - created_at).total_seconds())
    return max(0.0, min(100.0, 100.0 * waited / horizon_sec))


def score_process(
    process: Process,
    settings: PrioritySettings,
    now: datetime | None = None,
) -> float:
    now = now or utcnow()
    waited = max(0.0, (now - process.created_at).total_seconds())

    if process.flow is FlowType.MANUAL:
        # Абсолютный приоритет + небольшие tie-breaker'ы.
        return (
            max(1000.0, settings.manual_base)
            + process.urgency * 5.0
            + min(waited, 300.0) * 0.1
        )

    sla = sla_score(process.sla_deadline, now)
    starvation = starvation_score(process.created_at, now)
    return (
        settings.sla_weight * (sla / 100.0)
        + settings.urgency_weight * (process.urgency / 10.0)
        + settings.starvation_weight * (starvation / 100.0)
    )


def rank_processes(
    processes: Iterable[Process],
    settings: PrioritySettings,
    now: datetime | None = None,
) -> list[Process]:
    """Сортировка по убыванию приоритета, затем по времени создания (FIFO)."""

    now = now or utcnow()
    return sorted(
        processes,
        key=lambda p: (-score_process(p, settings, now), p.created_at, p.id),
    )

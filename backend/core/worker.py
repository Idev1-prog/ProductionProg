"""Симуляция выполнения процесса.

В MVP процесс не запускает реальный расчёт: тик-цикл продвигает прогресс
по времени, а ``asyncio.sleep`` в main.py задаёт частоту планировщика.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from backend.core.models import Process, ProcessStatus, utcnow


class Worker:
    def __init__(self, speed: float = 1.0) -> None:
        self.speed = max(0.1, speed)

    def effective_duration(self, process: Process) -> float:
        return max(0.1, process.duration_sec / self.speed)

    def expected_end(self, process: Process) -> datetime | None:
        if process.started_at is None:
            return None
        return process.started_at + timedelta(
            seconds=self.effective_duration(process)
        )

    def progress(self, process: Process, now: datetime | None = None) -> float:
        if process.status is ProcessStatus.COMPLETED:
            return 1.0
        if process.started_at is None:
            return 0.0
        now = now or utcnow()
        elapsed = max(0.0, (now - process.started_at).total_seconds())
        return max(0.0, min(1.0, elapsed / self.effective_duration(process)))

    async def sleep(self, seconds: float) -> None:
        """Используется фоновым tick-циклом."""

        await asyncio.sleep(max(0.05, seconds))

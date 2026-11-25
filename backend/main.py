"""Точка входа FastAPI + фоновый tick-цикл планировщика.

Запуск:
    uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import processes, settings, state
from backend.core.models import utcnow
from backend.core.orchestrator import Orchestrator
from backend.schemas import HealthOut
from backend.storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("risk_orchestrator")

ROOT_DIR = Path(__file__).resolve().parents[1]


def _persist_path() -> Path | None:
    value = os.getenv("RISK_PERSIST", "").strip()
    if not value or value in {"0", "false", "False"}:
        return None
    if value in {"1", "true", "True"}:
        return ROOT_DIR / "data" / "orchestrator.db"
    return Path(value)


storage = Storage(persist_path=_persist_path())
storage.restore()
orchestrator = Orchestrator(storage)


async def _tick_loop() -> None:
    logger.info("Tick-цикл запущен (interval=%.2fs)", orchestrator.settings.tick_interval)
    while True:
        try:
            orchestrator.tick()
        except Exception:  # pragma: no cover - демо не должно падать из-за одного тика
            logger.exception("Ошибка в tick-цикле")
        await orchestrator.worker.sleep(orchestrator.settings.tick_interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_tick_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        storage.save()
        logger.info("Tick-цикл остановлен")


app = FastAPI(
    title="Risk Orchestrator",
    description=(
        "Модуль-оркестратор запусков процессов системы оценки рисков: "
        "приоритеты, RAW/WAW-конфликты, Гант и конфигуратор."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.orchestrator = orchestrator

app.include_router(processes.router)
app.include_router(processes.scenario_router)
app.include_router(state.router)
app.include_router(settings.router)


@app.get("/", tags=["meta"])
def root() -> dict[str, str]:
    return {
        "service": "risk-orchestrator",
        "version": "0.1.0",
        "docs": "/docs",
        "state": "/state",
    }


@app.get("/health", response_model=HealthOut, tags=["meta"])
def health() -> HealthOut:
    return HealthOut(
        status="ok",
        service="risk-orchestrator",
        now=utcnow(),
    )

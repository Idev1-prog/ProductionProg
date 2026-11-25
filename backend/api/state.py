"""API состояния: снимок, Гант, журнал конфликтов, сброс демо."""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend.schemas import (
    ConflictOut,
    GanttEntry,
    ResetOut,
    StateOut,
)

router = APIRouter(tags=["state"])


@router.get("/state", response_model=StateOut)
def get_state(request: Request) -> StateOut:
    return StateOut(**request.app.state.orchestrator.get_state())


@router.get("/gantt", response_model=list[GanttEntry])
def get_gantt(request: Request) -> list[GanttEntry]:
    return [GanttEntry(**item) for item in request.app.state.orchestrator.get_gantt()]


@router.get("/conflicts", response_model=list[ConflictOut])
def get_conflicts(request: Request) -> list[ConflictOut]:
    return [
        ConflictOut(**item) for item in request.app.state.orchestrator.get_conflicts()
    ]


@router.get("/events")
def get_events(request: Request) -> list[dict]:
    return request.app.state.orchestrator.get_events()


@router.post("/reset", response_model=ResetOut)
def reset_state(request: Request) -> ResetOut:
    request.app.state.orchestrator.reset()
    return ResetOut(ok=True, message="Состояние оркестратора сброшено")

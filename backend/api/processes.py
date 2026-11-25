"""API процессов: создание, пауза, отмена, перезапуск, загрузка сценария."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, status

from backend.core.models import Process, Resource, utcnow
from backend.core.orchestrator import Orchestrator
from backend.schemas import (
    ProcessCreate,
    ProcessOut,
    ScenarioIn,
)

router = APIRouter(prefix="/processes", tags=["processes"])
scenario_router = APIRouter(tags=["scenario"])


def _orchestrator(request: Request) -> Orchestrator:
    return request.app.state.orchestrator


def _out(process: Process) -> ProcessOut:
    return ProcessOut(**process.to_dict())


def _deadline(payload: ProcessCreate):
    if payload.sla_deadline is not None:
        return payload.sla_deadline
    seconds = payload.sla_in_sec if payload.sla_in_sec is not None else 600.0
    return utcnow() + timedelta(seconds=seconds)


def _create(orchestrator: Orchestrator, payload: ProcessCreate) -> Process:
    return orchestrator.add_process(
        name=payload.name,
        flow=payload.flow,
        resources=[
            Resource(key=item.key, mode=item.mode, service=item.service)
            for item in payload.resources
        ],
        urgency=payload.urgency,
        duration_sec=payload.duration_sec,
        sla_deadline=_deadline(payload),
        meta=payload.meta,
    )


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, KeyError):
        detail = exc.args[0] if exc.args else str(exc)
        raise HTTPException(status_code=404, detail=str(detail)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("", response_model=ProcessOut, status_code=status.HTTP_201_CREATED)
def create_process(payload: ProcessCreate, request: Request) -> ProcessOut:
    try:
        return _out(_create(_orchestrator(request), payload))
    except (ValueError, KeyError) as exc:
        _raise_http(exc)
        raise  # pragma: no cover


@router.get("", response_model=list[ProcessOut])
def list_processes(request: Request) -> list[ProcessOut]:
    orchestrator = _orchestrator(request)
    processes = sorted(
        orchestrator.storage.processes.values(), key=lambda p: p.created_at
    )
    return [_out(process) for process in processes]


@router.get("/{process_id}", response_model=ProcessOut)
def get_process(process_id: str, request: Request) -> ProcessOut:
    try:
        return _out(_orchestrator(request)._get(process_id))
    except KeyError as exc:
        _raise_http(exc)
        raise  # pragma: no cover


@router.post("/{process_id}/pause", response_model=ProcessOut)
def pause_process(process_id: str, request: Request) -> ProcessOut:
    try:
        return _out(_orchestrator(request).pause(process_id))
    except (ValueError, KeyError) as exc:
        _raise_http(exc)
        raise  # pragma: no cover


@router.post("/{process_id}/resume", response_model=ProcessOut)
def resume_process(process_id: str, request: Request) -> ProcessOut:
    try:
        return _out(_orchestrator(request).resume(process_id))
    except (ValueError, KeyError) as exc:
        _raise_http(exc)
        raise  # pragma: no cover


@router.post("/{process_id}/cancel", response_model=ProcessOut)
def cancel_process(process_id: str, request: Request) -> ProcessOut:
    try:
        return _out(_orchestrator(request).cancel(process_id))
    except (ValueError, KeyError) as exc:
        _raise_http(exc)
        raise  # pragma: no cover


@router.post("/{process_id}/restart", response_model=ProcessOut)
def restart_process(process_id: str, request: Request) -> ProcessOut:
    try:
        return _out(_orchestrator(request).restart(process_id))
    except (ValueError, KeyError) as exc:
        _raise_http(exc)
        raise  # pragma: no cover


@scenario_router.post(
    "/scenario",
    response_model=list[ProcessOut],
    status_code=status.HTTP_201_CREATED,
)
def load_scenario(payload: ScenarioIn, request: Request) -> list[ProcessOut]:
    orchestrator = _orchestrator(request)
    try:
        if payload.settings is not None:
            orchestrator.update_settings(payload.settings.model_dump())
        created = [_create(orchestrator, item) for item in payload.processes]
    except (ValueError, KeyError) as exc:
        _raise_http(exc)
        raise  # pragma: no cover
    orchestrator.storage.log_event(
        "scenario_loaded",
        f"Загружен сценарий «{payload.name}»: {len(created)} процессов",
    )
    orchestrator.storage.save()
    return [_out(process) for process in created]


__all__ = ["router", "scenario_router"]

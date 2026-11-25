"""API настроек приоритетов."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend.schemas import SettingsIn, SettingsOut

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
def get_settings(request: Request) -> SettingsOut:
    return SettingsOut(**request.app.state.orchestrator.settings.to_dict())


@router.put("", response_model=SettingsOut)
def update_settings(payload: SettingsIn, request: Request) -> SettingsOut:
    try:
        settings = request.app.state.orchestrator.update_settings(
            payload.model_dump()
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SettingsOut(**settings.to_dict())

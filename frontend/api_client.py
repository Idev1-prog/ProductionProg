"""Тонкая обёртка httpx над API бэкенда."""

from __future__ import annotations

import os
from typing import Any

import httpx


class ApiError(RuntimeError):
    """Ошибка вызова API, пригодная для показа в UI."""


class RiskApiClient:
    def __init__(self, base_url: str | None = None, timeout: float = 10.0) -> None:
        self.base_url = (
            base_url or os.getenv("RISK_API_URL", "http://127.0.0.1:8000")
        ).rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ApiError(
                f"API недоступен по адресу {self.base_url}. "
                f"Запустите: uvicorn backend.main:app --port 8000 ({exc})"
            ) from exc

        if response.status_code >= 400:
            try:
                payload = response.json()
                detail = payload.get("detail", payload)
            except Exception:
                detail = response.text
            raise ApiError(f"{response.status_code}: {detail}")

        if not response.content:
            return None
        return response.json()

    # ------------------------------------------------------------------
    # Чтение
    # ------------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def get_state(self) -> dict[str, Any]:
        return self._request("GET", "/state")

    def get_gantt(self) -> list[dict[str, Any]]:
        return self._request("GET", "/gantt")

    def get_conflicts(self) -> list[dict[str, Any]]:
        return self._request("GET", "/conflicts")

    def get_processes(self) -> list[dict[str, Any]]:
        return self._request("GET", "/processes")

    def get_settings(self) -> dict[str, Any]:
        return self._request("GET", "/settings")

    # ------------------------------------------------------------------
    # Запись
    # ------------------------------------------------------------------
    def create_process(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/processes", json=payload)

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", "/settings", json=payload)

    def load_scenario(self, scenario: dict[str, Any]) -> list[dict[str, Any]]:
        return self._request("POST", "/scenario", json=scenario)

    def pause_process(self, process_id: str) -> dict[str, Any]:
        return self._request("POST", f"/processes/{process_id}/pause")

    def resume_process(self, process_id: str) -> dict[str, Any]:
        return self._request("POST", f"/processes/{process_id}/resume")

    def cancel_process(self, process_id: str) -> dict[str, Any]:
        return self._request("POST", f"/processes/{process_id}/cancel")

    def restart_process(self, process_id: str) -> dict[str, Any]:
        return self._request("POST", f"/processes/{process_id}/restart")

    def reset(self) -> dict[str, Any]:
        return self._request("POST", "/reset")

    def close(self) -> None:
        self._client.close()

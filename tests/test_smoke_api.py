"""Smoke-тест API: поднять приложение, залить сценарий, проверить статусы."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


def _process_payload(name: str = "Smoke process") -> dict:
    return {
        "name": name,
        "flow": "auto",
        "urgency": 5,
        "duration_sec": 30,
        "sla_in_sec": 120,
        "resources": [
            {"key": "dm_credit.portfolio", "mode": "write", "service": "risk-db"}
        ],
    }


def test_health_and_reset() -> None:
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        response = client.post("/reset")
        assert response.status_code == 200
        assert response.json()["ok"] is True


def test_smoke_process_lifecycle() -> None:
    with TestClient(app) as client:
        client.post("/reset")

        created = client.post("/processes", json=_process_payload())
        assert created.status_code == 201, created.text
        process = created.json()
        process_id = process["id"]
        assert process["flow"] == "auto"
        assert process["status"] in {"queued", "running"}

        state = client.get("/state")
        assert state.status_code == 200
        state_payload = state.json()
        assert any(item["id"] == process_id for item in state_payload["processes"])
        assert state_payload["metrics"]["total"] >= 1

        gantt = client.get("/gantt")
        assert gantt.status_code == 200
        assert isinstance(gantt.json(), list)

        conflicts = client.get("/conflicts")
        assert conflicts.status_code == 200
        assert isinstance(conflicts.json(), list)

        listed = client.get("/processes")
        assert listed.status_code == 200
        assert any(item["id"] == process_id for item in listed.json())

        paused = client.post(f"/processes/{process_id}/pause")
        assert paused.status_code == 200
        assert paused.json()["status"] == "paused"

        resumed = client.post(f"/processes/{process_id}/resume")
        assert resumed.status_code == 200
        assert resumed.json()["status"] in {"queued", "running"}

        cancelled = client.post(f"/processes/{process_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

        restarted = client.post(f"/processes/{process_id}/restart")
        assert restarted.status_code == 200
        assert restarted.json()["status"] in {"queued", "running"}

        missing = client.post("/processes/p-missing/pause")
        assert missing.status_code == 404


def test_scenario_loader_and_settings() -> None:
    with TestClient(app) as client:
        client.post("/reset")

        scenario = {
            "name": "Smoke scenario",
            "settings": {
                "manual_base": 1000,
                "sla_weight": 50,
                "urgency_weight": 40,
                "starvation_weight": 10,
                "max_running": 2,
                "tick_interval": 0.5,
            },
            "processes": [
                _process_payload("Auto one"),
                {
                    "name": "Manual one",
                    "flow": "manual",
                    "urgency": 9,
                    "duration_sec": 5,
                    "sla_in_sec": 60,
                    "resources": [
                        {
                            "key": "dm_credit.portfolio",
                            "mode": "write",
                            "service": "risk-db",
                        }
                    ],
                },
            ],
        }
        loaded = client.post("/scenario", json=scenario)
        assert loaded.status_code == 201, loaded.text
        assert len(loaded.json()) == 2

        settings = client.get("/settings")
        assert settings.status_code == 200
        assert settings.json()["max_running"] == 2

        updated = client.put(
            "/settings",
            json={
                "manual_base": 1200,
                "sla_weight": 70,
                "urgency_weight": 20,
                "starvation_weight": 10,
                "max_running": 3,
                "tick_interval": 0.5,
            },
        )
        assert updated.status_code == 200
        assert updated.json()["manual_base"] == 1200

        invalid = client.put(
            "/settings",
            json={
                "manual_base": 500,
                "sla_weight": 60,
                "urgency_weight": 30,
                "starvation_weight": 10,
                "max_running": 3,
                "tick_interval": 0.5,
            },
        )
        assert invalid.status_code == 422

"""Загрузка сценария в API через httpx.

Пример:
    python scripts/seed.py --reset --scenario data/scenario.json --watch 10
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]


def _resolve(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT_DIR / candidate


def _print_state(client: httpx.Client) -> None:
    state = client.get("/state").json()
    metrics = state["metrics"]
    print(
        "  running={running} queued={queued} blocked={blocked} "
        "completed={completed} conflicts={conflicts}".format(
            running=metrics["running"],
            queued=metrics["queued"],
            blocked=metrics["blocked"],
            completed=metrics["completed"],
            conflicts=metrics["conflicts_total"],
        )
    )
    for process in state["running"]:
        print(f"    RUN     {process['name']}")
    for process in state["queue"][:5]:
        print(
            f"    {process['status'].upper():7} {process['name']} "
            f"(priority={process['priority']:.2f})"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Загрузка сценария в Risk Orchestrator")
    parser.add_argument(
        "--api",
        default=os.getenv("RISK_API_URL", "http://127.0.0.1:8000"),
        help="Базовый URL API",
    )
    parser.add_argument(
        "--scenario",
        default="data/scenario.json",
        help="Путь к JSON-сценарию",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Сбросить состояние перед загрузкой",
    )
    parser.add_argument(
        "--watch",
        type=float,
        default=0.0,
        help="Сколько секунд наблюдать за состоянием после загрузки",
    )
    args = parser.parse_args()

    scenario_path = _resolve(args.scenario)
    if not scenario_path.exists():
        print(f"Файл не найден: {scenario_path}", file=sys.stderr)
        return 1

    try:
        scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Некорректный JSON: {exc}", file=sys.stderr)
        return 1

    try:
        with httpx.Client(base_url=args.api.rstrip("/"), timeout=15.0) as client:
            client.get("/health").raise_for_status()
            if args.reset:
                client.post("/reset").raise_for_status()
                print("Состояние сброшено")

            response = client.post("/scenario", json=scenario)
            if response.status_code >= 400:
                print(f"Ошибка API {response.status_code}: {response.text}", file=sys.stderr)
                return 1
            created = response.json()
            print(
                f"Загружен сценарий «{scenario.get('name', scenario_path.name)}»: "
                f"{len(created)} процессов"
            )
            _print_state(client)

            deadline = time.monotonic() + max(0.0, args.watch)
            while time.monotonic() < deadline:
                time.sleep(min(2.0, max(0.1, deadline - time.monotonic())))
                _print_state(client)
    except httpx.HTTPError as exc:
        print(f"API недоступен: {exc}", file=sys.stderr)
        print("Запустите: uvicorn backend.main:app --port 8000", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

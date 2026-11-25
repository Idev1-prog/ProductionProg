"""Пошаговый автоматический прогон демо перед жюри.

Пример:
    python scripts/demo_runner.py --delay 4
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
SCENARIOS = {
    "happy": "data/scenarios/01_happy_path.json",
    "waw": "data/scenarios/02_waw_conflict.json",
    "raw": "data/scenarios/03_raw_conflict.json",
    "override": "data/scenarios/04_manual_override.json",
    "main": "data/scenario.json",
}


def _load(client: httpx.Client, key: str) -> None:
    path = ROOT_DIR / SCENARIOS[key]
    scenario = json.loads(path.read_text(encoding="utf-8"))
    response = client.post("/scenario", json=scenario)
    response.raise_for_status()
    print(f"\n>>> Сценарий: {scenario['name']} ({len(response.json())} процессов)")


def _state(client: httpx.Client, conflicts: int = 0) -> None:
    state = client.get("/state").json()
    metrics = state["metrics"]
    print(
        "    running={running} queued={queued} blocked={blocked} "
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
    for process in state["queue"][:6]:
        print(
            f"    {process['status'].upper():7} {process['name']} "
            f"(priority={process['priority']:.2f})"
        )

    if conflicts:
        print("    Последние конфликты:")
        for item in client.get("/conflicts").json()[:conflicts]:
            print(
                f"      [{item['kind']}] {item['process_name']} <- "
                f"{item['blocked_by_name']} ({item['resource_key']})"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Демо-прогон Risk Orchestrator")
    parser.add_argument(
        "--api",
        default=os.getenv("RISK_API_URL", "http://127.0.0.1:8000"),
        help="Базовый URL API",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=4.0,
        help="Пауза между шагами, сек",
    )
    args = parser.parse_args()

    delay = max(1.0, args.delay)
    try:
        with httpx.Client(base_url=args.api.rstrip("/"), timeout=15.0) as client:
            client.get("/health").raise_for_status()

            print("=" * 72)
            print("ШАГ 1. Happy path: все ресурсы разные")
            print("=" * 72)
            client.post("/reset").raise_for_status()
            _load(client, "happy")
            time.sleep(delay)
            _state(client)

            print("\n" + "=" * 72)
            print("ШАГ 2. WAW: два WRITE в один resource_key")
            print("=" * 72)
            client.post("/reset").raise_for_status()
            _load(client, "waw")
            time.sleep(delay)
            _state(client, conflicts=2)

            print("\n" + "=" * 72)
            print("ШАГ 3. RAW: READ против WRITE")
            print("=" * 72)
            client.post("/reset").raise_for_status()
            _load(client, "raw")
            time.sleep(delay)
            _state(client, conflicts=2)

            print("\n" + "=" * 72)
            print("ШАГ 4. Manual override: ручной вытесняет автоматический")
            print("=" * 72)
            client.post("/reset").raise_for_status()
            _load(client, "override")
            time.sleep(max(1.0, delay / 2))
            _state(client, conflicts=2)

            print("\n" + "=" * 72)
            print("ШАГ 5. Основной сценарий: ночной цикл + ручные пересчёты")
            print("=" * 72)
            client.post("/reset").raise_for_status()
            _load(client, "main")
            time.sleep(delay)
            _state(client, conflicts=3)
            print("\nДемо завершено. UI: streamlit run frontend/app.py")
    except httpx.HTTPError as exc:
        print(f"API недоступен: {exc}", file=sys.stderr)
        print("Запустите: uvicorn backend.main:app --port 8000", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

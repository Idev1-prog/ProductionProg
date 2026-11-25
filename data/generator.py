"""Генератор синтетических сценариев для демо и нагрузочных прогонов.

Пример:
    python data/generator.py --count 40 --seed 42 --out data/scenarios/generated.json
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

SERVICES = ["risk-db", "market-db", "dwh", "calc-cluster"]
RESOURCE_KEYS = [
    "dm_credit.portfolio",
    "dm_credit.params",
    "dm_credit.collateral",
    "dm_market.positions",
    "dm_market.quotes",
    "dm_reserves.ecl",
    "dm_capital.rwa",
    "dm_ops.events",
    "dm_reports.night",
    "dm_reports.daily",
]


def generate_scenario(count: int = 30, seed: int = 42) -> dict:
    rng = random.Random(seed)
    processes = []

    for index in range(count):
        flow = "manual" if index % 5 == 0 else "auto"
        key_count = rng.randint(1, 3)
        keys = rng.sample(RESOURCE_KEYS, key_count)
        # Каждый четвёртый процесс намеренно претендует на «горячий» ресурс.
        if index % 4 == 0:
            keys = ["dm_credit.portfolio"] + [
                key for key in keys if key != "dm_credit.portfolio"
            ]
        resources = [
            {
                "key": key,
                "mode": "write" if rng.random() < 0.6 else "read",
                "service": rng.choice(SERVICES),
            }
            for key in keys
        ]
        urgency = rng.randint(7, 10) if flow == "manual" else rng.randint(1, 9)
        processes.append(
            {
                "name": (
                    f"Ручной пересчёт #{index + 1}"
                    if flow == "manual"
                    else f"Регламентный расчёт #{index + 1}"
                ),
                "flow": flow,
                "urgency": urgency,
                "duration_sec": rng.randint(8, 45),
                "sla_in_sec": rng.choice([60, 120, 180, 300, 600, 900]),
                "resources": resources,
                "meta": {
                    "synthetic": True,
                    "seed": seed,
                    "index": index,
                    "owner": "analyst" if flow == "manual" else "scheduler",
                },
            }
        )

    return {
        "name": f"Синтетический сценарий (seed={seed}, count={count})",
        "description": "Сгенерирован data/generator.py для проверки нагрузки и конфликтов",
        "settings": {
            "manual_base": 1000,
            "sla_weight": 60,
            "urgency_weight": 30,
            "starvation_weight": 10,
            "max_running": 4,
            "tick_interval": 0.5,
        },
        "processes": processes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Генератор сценариев Risk Orchestrator")
    parser.add_argument("--count", type=int, default=30, help="Количество процессов")
    parser.add_argument("--seed", type=int, default=42, help="Seed генератора")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/scenarios/generated.json"),
        help="Куда сохранить JSON",
    )
    args = parser.parse_args()

    if args.count < 1:
        parser.error("--count должен быть >= 1")

    scenario = generate_scenario(args.count, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(scenario, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Сценарий сохранён: {args.out} ({len(scenario['processes'])} процессов)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Юнит-тесты Priority Engine."""

from __future__ import annotations

from datetime import timedelta

from backend.core.models import (
    FlowType,
    OpType,
    PrioritySettings,
    Process,
    Resource,
    utcnow,
)
from backend.core.priority import rank_processes, score_process, sla_score


def make_process(
    *,
    process_id: str = "p-1",
    flow: FlowType = FlowType.AUTO,
    urgency: int = 5,
    sla_in_sec: float = 300,
    created_ago_sec: float = 0,
) -> Process:
    now = utcnow()
    return Process(
        id=process_id,
        name=f"process-{process_id}",
        flow=flow,
        resources=[Resource("dm_credit.portfolio", OpType.WRITE)],
        urgency=urgency,
        duration_sec=10,
        sla_deadline=now + timedelta(seconds=sla_in_sec),
        created_at=now - timedelta(seconds=created_ago_sec),
    )


def test_manual_always_beats_auto() -> None:
    settings = PrioritySettings()
    auto = make_process(
        flow=FlowType.AUTO,
        urgency=10,
        sla_in_sec=-60,  # уже просрочен
    )
    manual = make_process(
        flow=FlowType.MANUAL,
        urgency=1,
        sla_in_sec=3600,
    )
    assert score_process(manual, settings) > score_process(auto, settings)


def test_sooner_sla_has_higher_score() -> None:
    settings = PrioritySettings()
    soon = make_process(process_id="soon", sla_in_sec=30)
    later = make_process(process_id="later", sla_in_sec=590)
    assert score_process(soon, settings) > score_process(later, settings)


def test_higher_urgency_has_higher_score() -> None:
    settings = PrioritySettings(sla_weight=0, starvation_weight=0)
    high = make_process(process_id="high", urgency=9, sla_in_sec=300)
    low = make_process(process_id="low", urgency=2, sla_in_sec=300)
    assert score_process(high, settings) > score_process(low, settings)


def test_starvation_bonus_grows_with_wait() -> None:
    settings = PrioritySettings(sla_weight=0, urgency_weight=0)
    fresh = make_process(process_id="fresh", created_ago_sec=0)
    hungry = make_process(process_id="hungry", created_ago_sec=400)
    assert score_process(hungry, settings) > score_process(fresh, settings)


def test_sla_score_bounds() -> None:
    now = utcnow()
    assert sla_score(now - timedelta(seconds=1), now) == 100.0
    assert sla_score(now + timedelta(hours=1), now) == 0.0
    middle = sla_score(now + timedelta(seconds=300), now)
    assert 0.0 < middle < 100.0


def test_rank_processes_orders_by_score_then_fifo() -> None:
    settings = PrioritySettings()
    manual = make_process(process_id="manual", flow=FlowType.MANUAL, urgency=1)
    auto = make_process(process_id="auto", flow=FlowType.AUTO, urgency=1)
    ranked = rank_processes([auto, manual], settings)
    assert [process.id for process in ranked] == ["manual", "auto"]

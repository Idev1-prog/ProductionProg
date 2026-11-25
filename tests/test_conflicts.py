"""Юнит-тесты Conflict Manager (RAW/WAW)."""

from __future__ import annotations

from backend.core.conflicts import (
    find_conflicts,
    normalize_resources,
    resources_overlap,
)
from backend.core.models import (
    FlowType,
    Lock,
    OpType,
    Process,
    Resource,
)


def make_process(
    process_id: str,
    resources: list[Resource],
    flow: FlowType = FlowType.AUTO,
) -> Process:
    return Process(
        id=process_id,
        name=f"process-{process_id}",
        flow=flow,
        resources=resources,
        duration_sec=10,
    )


def lock(resource_key: str, process_id: str, mode: OpType) -> Lock:
    return Lock(resource_key=resource_key, process_id=process_id, mode=mode)


def test_read_read_is_compatible() -> None:
    process = make_process("reader-2", [Resource("dm_credit.portfolio", OpType.READ)])
    locks = [lock("dm_credit.portfolio", "reader-1", OpType.READ)]
    assert find_conflicts(process, locks) == []


def test_write_write_is_waw() -> None:
    process = make_process("writer-2", [Resource("dm_credit.portfolio", OpType.WRITE)])
    locks = [lock("dm_credit.portfolio", "writer-1", OpType.WRITE)]
    conflicts = find_conflicts(process, locks)
    assert len(conflicts) == 1
    assert conflicts[0].kind == "WAW"
    assert conflicts[0].blocker_ids == ["writer-1"]


def test_read_after_write_is_raw() -> None:
    process = make_process("reader", [Resource("dm_credit.portfolio", OpType.READ)])
    locks = [lock("dm_credit.portfolio", "writer", OpType.WRITE)]
    conflicts = find_conflicts(process, locks)
    assert len(conflicts) == 1
    assert conflicts[0].kind == "RAW"


def test_write_after_read_is_raw() -> None:
    process = make_process("writer", [Resource("dm_credit.portfolio", OpType.WRITE)])
    locks = [lock("dm_credit.portfolio", "reader", OpType.READ)]
    conflicts = find_conflicts(process, locks)
    assert len(conflicts) == 1
    assert conflicts[0].kind == "RAW"


def test_own_locks_are_ignored() -> None:
    process = make_process("same", [Resource("dm_credit.portfolio", OpType.WRITE)])
    locks = [lock("dm_credit.portfolio", "same", OpType.WRITE)]
    assert find_conflicts(process, locks) == []


def test_different_resources_do_not_conflict() -> None:
    process = make_process("p", [Resource("dm_ops.events", OpType.WRITE)])
    locks = [lock("dm_credit.portfolio", "other", OpType.WRITE)]
    assert find_conflicts(process, locks) == []


def test_resources_overlap_for_manual_preemption() -> None:
    auto = make_process("auto", [Resource("dm_credit.portfolio", OpType.WRITE)])
    manual = make_process(
        "manual",
        [Resource("dm_credit.portfolio", OpType.READ)],
        flow=FlowType.MANUAL,
    )
    assert resources_overlap(manual, auto) == ["dm_credit.portfolio"]


def test_normalize_resources_write_wins() -> None:
    resources = normalize_resources(
        [
            Resource("dm_credit.portfolio", OpType.READ),
            Resource("dm_credit.portfolio", OpType.WRITE),
        ]
    )
    assert len(resources) == 1
    assert resources[0].mode is OpType.WRITE

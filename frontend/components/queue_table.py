"""Таблицы очереди и журнала конфликтов."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def _resources(resources: list[dict]) -> str:
    return ", ".join(f"{item['key']}:{item['mode']}" for item in resources)


def _queue_frame(queue: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Позиция": index + 1,
                "Процесс": process["name"],
                "Поток": process["flow"],
                "Статус": process["status"],
                "Приоритет": round(float(process["priority"]), 2),
                "Срочность": process["urgency"],
                "Ожидание, c": process["wait_sec"],
                "Ресурсы": _resources(process["resources"]),
                "Кем заблокирован": ", ".join(process.get("blocked_by") or []),
                "Причина": process.get("blocked_reason", ""),
            }
            for index, process in enumerate(queue)
        ]
    )


def render(state: dict) -> None:
    st.subheader("Очередь выполнения")
    st.caption(
        "Сортировка: ручной поток → SLA/срочность/голод. "
        "Заблокированные процессы ждут освобождения resource_key."
    )
    queue = state.get("queue") or []
    if not queue:
        st.info("Очередь пуста.")
    else:
        st.dataframe(
            _queue_frame(queue),
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("Журнал конфликтов")
    st.caption("Все предотвращённые RAW/WAW, вытеснения ручным потоком и их причина.")
    conflicts = state.get("conflicts") or []
    if not conflicts:
        st.info("Конфликтов пока нет.")
        return

    frame = pd.DataFrame(conflicts)[
        [
            "at",
            "kind",
            "process_name",
            "blocked_by_name",
            "resource_key",
            "message",
            "resolution",
        ]
    ].rename(
        columns={
            "at": "Время",
            "kind": "Тип",
            "process_name": "Процесс",
            "blocked_by_name": "Блокирует",
            "resource_key": "Ресурс",
            "message": "Сообщение",
            "resolution": "Решение",
        }
    )
    st.dataframe(frame, use_container_width=True, hide_index=True)

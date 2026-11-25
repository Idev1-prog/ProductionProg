"""Дашборд: метрики, тепловая карта нагрузки, события."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st


def _metric_row(state: dict) -> None:
    metrics = state["metrics"]
    columns = st.columns(6)
    columns[0].metric("Всего процессов", metrics["total"])
    columns[1].metric("Выполняется", metrics["running"])
    columns[2].metric("В очереди", metrics["queued"])
    columns[3].metric("Заблокировано", metrics["blocked"])
    columns[4].metric("Завершено", metrics["completed"])
    columns[5].metric("Конфликты", metrics["conflicts_total"])

    columns = st.columns(4)
    columns[0].metric("Утилизация", f"{metrics['utilization_pct']}%")
    columns[1].metric("Среднее ожидание", f"{metrics['avg_wait_sec']} c")
    columns[2].metric("Макс. ожидание", f"{metrics['max_wait_sec']} c")
    columns[3].metric("SLA под риском", metrics["sla_at_risk"])


def _heatmap(state: dict) -> None:
    load = state.get("resource_load") or []
    if not load:
        st.info("Нет активных блокировок — тепловая карта появится при запуске процессов.")
        return

    df = pd.DataFrame(load)
    matrix = (
        df.set_index("key")[["readers", "writers"]]
        .rename(columns={"readers": "READ", "writers": "WRITE"})
        .T
    )
    fig = px.imshow(
        matrix,
        text_auto=True,
        aspect="auto",
        color_continuous_scale="YlOrRd",
        labels={"x": "Ресурс", "y": "Операция", "color": "Блокировки"},
    )
    fig.update_layout(
        height=max(260, 60 * len(matrix.index) + 140),
        margin=dict(l=10, r=10, t=30, b=10),
        coloraxis_showscale=False,
    )
    st.plotly_chart(fig, use_container_width=True)


def _running_progress(state: dict) -> None:
    running = state.get("running") or []
    if not running:
        return
    st.markdown("**Выполняются сейчас**")
    for process in running:
        progress = float(process.get("progress", 0.0))
        st.progress(
            progress,
            text=(
                f"{process['name']} · {process['flow']} · "
                f"priority {process['priority']:.1f} · {progress * 100:.0f}%"
            ),
        )


def render(state: dict) -> None:
    st.subheader("Оперативная картина")
    _metric_row(state)
    _running_progress(state)

    st.markdown("**Тепловая карта нагрузки на ресурсы**")
    st.caption("Строки — операции, столбцы — resource_key (таблица / срез / дата).")
    _heatmap(state)

    with st.expander("Журнал событий оркестратора"):
        events = state.get("events") or []
        if not events:
            st.info("Событий пока нет.")
        else:
            df = pd.DataFrame(events)[["at", "kind", "message"]]
            st.dataframe(df, use_container_width=True, hide_index=True)

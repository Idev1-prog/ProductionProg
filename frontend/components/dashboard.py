"""Дашборд: метрики, тепловая карта нагрузки, события."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"


def _is_dark() -> bool:
    """Определяет активную тему Streamlit (в bare-режиме — светлая)."""
    try:
        theme = st.context.theme or {}
        kind = theme.get("type") if hasattr(theme, "get") else None
        kind = kind or st.get_option("theme.base")
        return str(kind).lower() == "dark"
    except Exception:
        return False


def _heatmap_palette(dark: bool) -> dict:
    if dark:
        return {
            "surface": "#0e1117",
            "text": "#e2e8f0",
            "line": "#475569",
            "cell_text": "#f8fafc",
            "scale": [
                [0.0, "#1e293b"],
                [0.35, "#1e40af"],
                [0.7, "#3b82f6"],
                [1.0, "#b45309"],
            ],
        }
    return {
        "surface": "#ffffff",
        "text": "#0f172a",
        "line": "#cbd5e1",
        "cell_text": "#0f172a",
        "scale": [
            [0.0, "#f1f5f9"],
            [0.3, "#dbeafe"],
            [0.6, "#93c5fd"],
            [0.85, "#fbbf24"],
            [1.0, "#fb923c"],
        ],
    }


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
    columns[0].metric("Загруженность", f"{metrics['utilization_pct']}%")
    columns[1].metric("Среднее ожидание", f"{metrics['avg_wait_sec']} c")
    columns[2].metric("Макс. ожидание", f"{metrics['max_wait_sec']} c")
    columns[3].metric("SLA под риском", metrics["sla_at_risk"])


def _heatmap(state: dict, *, dark: bool = False) -> None:
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
    palette = _heatmap_palette(dark)
    resources = list(matrix.columns)
    operations = list(matrix.index)
    values = matrix.to_numpy()

    # Сервис и имена процессов берём из того же снимка state, чтобы tooltip
    # показывал контекст блокировки, а не только цифру.
    meta = df.set_index("key")
    custom = [
        [
            "<b>{}</b> · {}<br>Сервис: {}<br>Процессы: {}".format(
                resource,
                operation,
                meta.loc[resource].get("service") or "—",
                ", ".join(meta.loc[resource].get("processes") or []) or "—",
            )
            for resource in resources
        ]
        for operation in operations
    ]

    fig = go.Figure(
        go.Heatmap(
            z=values,
            x=resources,
            y=operations,
            customdata=custom,
            colorscale=palette["scale"],
            zmin=0,
            zmax=max(1, int(values.max())),
            xgap=4,
            ygap=4,
            texttemplate="%{z}",
            textfont=dict(family=FONT, size=13, color=palette["cell_text"]),
            hovertemplate="%{customdata}<extra></extra>",
            colorbar=dict(
                title=dict(
                    text="Блокировки",
                    side="right",
                    font=dict(color=palette["text"], size=11),
                ),
                tickfont=dict(color=palette["text"], size=10),
                outlinecolor=palette["line"],
                thickness=11,
                len=0.85,
            ),
        )
    )
    fig.update_layout(
        height=max(260, 60 * len(operations) + 150),
        font=dict(family=FONT, size=12, color=palette["text"]),
        paper_bgcolor=palette["surface"],
        plot_bgcolor=palette["surface"],
        margin=dict(l=10, r=10, t=34, b=10),
        hoverlabel=dict(
            bgcolor=palette["surface"],
            bordercolor=palette["line"],
            font=dict(family=FONT, size=12, color=palette["text"]),
        ),
    )
    fig.update_xaxes(
        side="top",
        title_text="",
        tickfont=dict(color=palette["text"]),
        linecolor=palette["line"],
        automargin=True,
    )
    fig.update_yaxes(
        autorange="reversed",
        title_text="",
        tickfont=dict(color=palette["text"], size=12),
        automargin=True,
    )
    st.plotly_chart(fig, theme=None, use_container_width=True)


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
    st.caption("Строки — операции READ/WRITE, столбцы — resource_key.")
    _heatmap(state, dark=_is_dark())

    with st.expander("Журнал событий оркестратора"):
        events = state.get("events") or []
        if not events:
            st.info("Событий пока нет.")
        else:
            df = pd.DataFrame(events)[["at", "kind", "message"]]
            st.dataframe(df, use_container_width=True, hide_index=True)

"""Диаграмма Ганта на Plotly."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

STATUS_COLORS = {
    "queued": "#94a3b8",
    "blocked": "#f59e0b",
    "running": "#3b82f6",
    "paused": "#a855f7",
    "completed": "#10b981",
    "cancelled": "#ef4444",
    "failed": "#dc2626",
}


def render(entries: list[dict]) -> None:
    st.subheader("Диаграмма Ганта")
    st.caption(
        "Цвет — статус процесса. Пунктир — текущий момент. "
        "Наведите курсор, чтобы увидеть приоритет и ресурсы."
    )

    if not entries:
        st.info("Пока нет запущенных процессов. Загрузите сценарий во вкладке «Управление».")
        return

    df = pd.DataFrame(entries)
    df["start"] = pd.to_datetime(df["start"], utc=True)
    df["end"] = pd.to_datetime(df["end"], utc=True)
    df["end"] = [
        max(end, start + pd.Timedelta(seconds=1))
        for start, end in zip(df["start"], df["end"])
    ]
    df = df.sort_values("start")

    fig = px.timeline(
        df,
        x_start="start",
        x_end="end",
        y="name",
        color="status",
        color_discrete_map=STATUS_COLORS,
        hover_data={
            "flow": True,
            "priority": ":.2f",
            "resources": True,
            "blocked_reason": True,
            "start": "|%H:%M:%S",
            "end": "|%H:%M:%S",
        },
    )
    fig.update_yaxes(autorange="reversed", title_text="")
    fig.update_xaxes(title_text="Время (UTC)")
    fig.update_layout(
        height=max(340, 46 * len(df) + 140),
        legend_title_text="Статус",
        margin=dict(l=10, r=10, t=30, b=10),
        bargap=0.25,
    )
    fig.add_vline(
        x=pd.Timestamp.now(tz="UTC"),
        line_width=1,
        line_dash="dot",
        line_color="#64748b",
    )
    st.plotly_chart(fig, use_container_width=True)

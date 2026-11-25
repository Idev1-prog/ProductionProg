"""Диаграмма Ганта: статусы, прогресс и текущий момент в одном таймлайне."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

STATUS_COLORS = {
    "queued": "#94a3b8",
    "blocked": "#f59e0b",
    "running": "#2563eb",
    "paused": "#8b5cf6",
    "completed": "#10b981",
    "cancelled": "#ef4444",
    "failed": "#b91c1c",
}

STATUS_LABELS = {
    "queued": "В очереди",
    "blocked": "Заблокирован",
    "running": "Выполняется",
    "paused": "На паузе",
    "completed": "Завершён",
    "cancelled": "Отменён",
    "failed": "Ошибка",
}

STATUS_ORDER = [
    "running",
    "queued",
    "blocked",
    "paused",
    "completed",
    "cancelled",
    "failed",
]

FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"


def _tooltip(row: pd.Series) -> str:
    """Собирает аккуратный tooltip для одной полосы."""
    lines = [
        f"<b>{row['name']}</b>",
        f"Статус: <b>{STATUS_LABELS.get(row['status'], row['status'])}</b>"
        f" · поток: {row['flow']}",
        f"Приоритет: {row['priority']:.1f} · готово: {row['progress'] * 100:.0f}%",
        f"Длительность: {row['duration_sec']:.0f} c",
        f"Ресурсы: {row['resources']}",
        f"Окно: {row['start']:%d.%m %H:%M:%S} → {row['end']:%d.%m %H:%M:%S} UTC",
    ]
    if row.get("blocked_reason"):
        lines.append(f"⛔ {row['blocked_reason']}")
    return "<br>".join(lines)


def build_figure(entries: list[dict]) -> go.Figure:
    """Строит Гант с цветами статусов, маркерами прогресса и линией «сейчас»."""
    df = pd.DataFrame(entries)
    df["start"] = pd.to_datetime(df["start"], utc=True)
    df["end"] = pd.to_datetime(df["end"], utc=True)
    df["end"] = [
        max(end, start + pd.Timedelta(seconds=1))
        for start, end in zip(df["start"], df["end"])
    ]
    df = df.sort_values("start", kind="stable").reset_index(drop=True)
    df["duration_ms"] = (df["end"] - df["start"]).dt.total_seconds() * 1000
    df["tooltip"] = df.apply(_tooltip, axis=1)

    fig = go.Figure()
    for status in STATUS_ORDER:
        subset = df[df["status"] == status]
        if subset.empty:
            continue
        fig.add_bar(
            y=subset["name"],
            x=subset["duration_ms"],
            base=subset["start"],
            orientation="h",
            name=STATUS_LABELS.get(status, status),
            width=0.62,
            marker=dict(
                color=STATUS_COLORS.get(status, "#64748b"),
                cornerradius=8,
                line=dict(
                    color="#0f172a",
                    width=[2 if flow == "manual" else 0 for flow in subset["flow"]],
                ),
                opacity=0.95,
            ),
            customdata=subset["tooltip"],
            hovertemplate="%{customdata}<extra></extra>",
        )

    # Белая точка на полосе показывает, насколько процесс уже выполнился.
    running = df[df["status"] == "running"]
    if not running.empty:
        progress_at = running["start"] + pd.to_timedelta(
            running["duration_ms"] * running["progress"], unit="ms"
        )
        fig.add_scatter(
            y=running["name"],
            x=progress_at,
            mode="markers",
            marker=dict(
                symbol="circle",
                size=9,
                color="#ffffff",
                line=dict(color="#1d4ed8", width=2),
            ),
            hoverinfo="skip",
            showlegend=False,
        )

    now = pd.Timestamp.now(tz="UTC")
    fig.add_vline(x=now, line_width=1.5, line_dash="dot", line_color="#64748b")
    fig.add_annotation(
        x=now,
        y=1,
        yref="paper",
        text="сейчас",
        showarrow=False,
        xanchor="left",
        yanchor="bottom",
        font=dict(size=11, color="#64748b"),
    )

    fig.update_layout(
        height=max(360, 52 * len(df) + 130),
        barmode="overlay",
        bargap=0.32,
        font=dict(family=FONT, size=12, color="#0f172a"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#ffffff",
        margin=dict(l=10, r=24, t=56, b=44),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            title_text="",
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=11),
        ),
        hoverlabel=dict(
            bgcolor="#ffffff",
            bordercolor="#cbd5e1",
            font=dict(family=FONT, size=12),
        ),
    )
    fig.update_xaxes(
        type="date",
        title_text="Время (UTC)",
        tickformat="%H:%M:%S",
        showgrid=True,
        gridcolor="#eef2f7",
        gridwidth=1,
        zeroline=False,
        showline=True,
        linecolor="#cbd5e1",
        ticks="outside",
        tickcolor="#cbd5e1",
        automargin=True,
    )
    fig.update_yaxes(
        autorange="reversed",
        title_text="",
        automargin=True,
        showgrid=False,
        tickfont=dict(size=12),
    )
    return fig


def render(entries: list[dict]) -> None:
    st.subheader("Диаграмма Ганта")
    st.caption(
        "Цвет — статус, тёмная обводка — ручной поток, белая точка на синей полосе — "
        "текущий прогресс, пунктир — момент запроса. Наведите на полосу для деталей."
    )

    if not entries:
        st.info("Пока нет запущенных процессов. Загрузите сценарий во вкладке «Управление».")
        return

    st.plotly_chart(build_figure(entries), use_container_width=True)

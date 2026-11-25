"""Конфигуратор весов приоритетов (no-code настройка)."""

from __future__ import annotations

import streamlit as st

from frontend.api_client import ApiError, RiskApiClient


def render(client: RiskApiClient, settings: dict) -> None:
    st.subheader("Веса приоритетов")
    st.caption(
        "Изменения применяются сразу: планировщик пересчитывает очередь "
        "на следующем тике, перезапуск не нужен."
    )

    with st.form("settings_form"):
        manual_base = st.slider(
            "База ручного приоритета",
            min_value=1000,
            max_value=5000,
            value=int(settings["manual_base"]),
            step=50,
            help="Всегда больше любого автоматического приоритета.",
        )
        sla_weight = st.slider(
            "Вес SLA",
            min_value=0,
            max_value=100,
            value=int(settings["sla_weight"]),
            step=5,
        )
        urgency_weight = st.slider(
            "Вес срочности",
            min_value=0,
            max_value=100,
            value=int(settings["urgency_weight"]),
            step=5,
        )
        starvation_weight = st.slider(
            "Вес защиты от голода",
            min_value=0,
            max_value=100,
            value=int(settings["starvation_weight"]),
            step=5,
            help="Чем дольше процесс ждёт, тем выше его балл.",
        )
        max_running = st.slider(
            "Параллельных процессов",
            min_value=1,
            max_value=10,
            value=int(settings["max_running"]),
            step=1,
        )
        tick_interval = st.slider(
            "Интервал планировщика, сек",
            min_value=0.1,
            max_value=5.0,
            value=float(settings["tick_interval"]),
            step=0.1,
        )
        saved = st.form_submit_button("Сохранить настройки", type="primary")

    if saved:
        try:
            client.update_settings(
                {
                    "manual_base": manual_base,
                    "sla_weight": sla_weight,
                    "urgency_weight": urgency_weight,
                    "starvation_weight": starvation_weight,
                    "max_running": max_running,
                    "tick_interval": tick_interval,
                }
            )
            st.toast("Настройки сохранены", icon="⚙️")
            st.rerun()
        except ApiError as exc:
            st.error(str(exc))

    st.divider()
    st.markdown(
        """
**Формула автоматического приоритета**

`score = sla_weight · SLA/100 + urgency_weight · urgency/10 + starvation_weight · wait/100`

**Ручной поток**

`score = manual_base + urgency · 5 + wait · 0.1`

Ручной поток всегда получает ресурсы первым, а при конфликте вытесняет
автоматический процесс (событие `OVERRIDE` в журнале конфликтов).
"""
    )

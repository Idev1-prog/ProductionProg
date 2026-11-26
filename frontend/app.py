"""Streamlit-приложение Risk Orchestrator.

Запуск:
    streamlit run frontend/app.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from frontend.api_client import ApiError, RiskApiClient  # noqa: E402
from frontend.components import (  # noqa: E402
    controls,
    dashboard,
    gantt,
    queue_table,
    settings_panel,
)

st.set_page_config(
    page_title="Risk Orchestrator",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🧠 Risk Orchestrator")
st.caption(
    "Оркестратор запусков процессов системы оценки рисков: "
    "приоритеты, RAW/WAW-конфликты, Гант и конфигуратор."
)

# ----------------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------------
st.sidebar.header("Подключение")
api_url = st.sidebar.text_input(
    "API URL",
    value=os.getenv("RISK_API_URL", "http://127.0.0.1:8000"),
)
client = RiskApiClient(api_url)

default_auto_refresh = os.getenv("RISK_AUTOREFRESH", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
auto_refresh = st.sidebar.toggle("Автообновление", value=default_auto_refresh)
refresh_sec = st.sidebar.slider(
    "Период обновления, сек", min_value=1.0, max_value=10.0, value=2.0, step=0.5
)

refresh_column, reset_column = st.sidebar.columns(2)
if refresh_column.button("🔄 Обновить", use_container_width=True):
    st.rerun()
if reset_column.button("🧹 Сбросить", use_container_width=True):
    try:
        client.reset()
        st.toast("Состояние сброшено", icon="🧹")
        st.rerun()
    except ApiError as exc:
        st.sidebar.error(str(exc))

st.sidebar.divider()
st.sidebar.caption(f"API: {client.base_url}")
st.sidebar.caption("Документация API: /docs")

# ----------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------
try:
    client.health()
    state = client.get_state()
    settings = client.get_settings()
    gantt_entries = client.get_gantt()
except ApiError as exc:
    st.error(str(exc))
    st.code(
        "uvicorn backend.main:app --reload --port 8000",
        language="powershell",
    )
    st.stop()

# ----------------------------------------------------------------------
# Tabs
# ----------------------------------------------------------------------
tab_dashboard, tab_gantt, tab_queue, tab_controls, tab_settings = st.tabs(
    [
        "📊 Дашборд",
        "📈 Гант",
        "🧾 Очередь и конфликты",
        "🎛️ Управление",
        "⚙️ Настройки",
    ]
)

with tab_dashboard:
    dashboard.render(state)

with tab_gantt:
    gantt.render(gantt_entries, now=state.get("now"))

with tab_queue:
    queue_table.render(state)

with tab_controls:
    controls.render(client, state)

with tab_settings:
    settings_panel.render(client, settings)

if auto_refresh:
    time.sleep(refresh_sec)
    st.rerun()

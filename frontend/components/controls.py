"""Кнопки управления: ручной запуск, пауза/отмена/рестарт, загрузка сценариев."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

from frontend.api_client import ApiError, RiskApiClient

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def parse_resources(text: str) -> list[dict[str, str]]:
    resources: list[dict[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Ключ может содержать двоеточия (например, срез по дате), поэтому
        # режим/сервис ищем по краям, а не по позиции второго токена.
        parts = [part.strip() for part in line.split(":")]
        modes = {"read", "write"}
        key = line.strip()
        mode = "write"
        service = "risk-db"

        if len(parts) >= 2 and parts[1] in modes:
            key = parts[0]
            mode = parts[1]
            if len(parts) >= 3 and parts[2]:
                service = parts[2]
        elif len(parts) >= 2 and parts[-1] in modes:
            key = ":".join(parts[:-1]).strip()
            mode = parts[-1]
        elif len(parts) >= 3 and parts[-2] in modes:
            key = ":".join(parts[:-2]).strip()
            mode = parts[-2]
            if parts[-1]:
                service = parts[-1]

        if not key:
            continue
        resources.append({"key": key, "mode": mode, "service": service})
    if not resources:
        raise ValueError("Укажите хотя бы один ресурс")
    return resources


def _manual_form(client: RiskApiClient) -> None:
    with st.form("manual_process_form", clear_on_submit=False):
        name = st.text_input(
            "Название процесса",
            value="Ручной пересчёт кредитного портфеля",
        )
        urgency = st.slider("Срочность (1–10)", 1, 10, 8)
        duration = st.number_input(
            "Длительность, сек", min_value=1.0, max_value=600.0, value=15.0, step=1.0
        )
        sla_in_sec = st.number_input(
            "SLA, сек от текущего момента",
            min_value=0.0,
            max_value=86400.0,
            value=120.0,
            step=30.0,
        )
        resources_text = st.text_area(
            "Ресурсы (key:mode:service, по одному в строке)",
            value="dm_credit.portfolio:write:risk-db\ndm_credit.params:read:risk-db",
            height=110,
        )
        submitted = st.form_submit_button(
            "Запустить ручной процесс", type="primary"
        )

    if not submitted:
        return
    try:
        payload: dict[str, Any] = {
            "name": name,
            "flow": "manual",
            "urgency": urgency,
            "duration_sec": duration,
            "sla_in_sec": sla_in_sec,
            "resources": parse_resources(resources_text),
        }
        client.create_process(payload)
        st.toast("Ручной процесс поставлен в очередь", icon="✅")
        st.rerun()
    except (ApiError, ValueError) as exc:
        st.error(str(exc))


def _manage_processes(client: RiskApiClient, state: dict) -> None:
    processes = state.get("processes") or []
    if not processes:
        st.info("Процессов пока нет — загрузите сценарий ниже.")
        return

    options = {
        f"{process['name']} · {process['status']} · {process['id']}": process["id"]
        for process in processes
    }
    selected_label = st.selectbox("Выберите процесс", list(options.keys()))
    process_id = options[selected_label]

    columns = st.columns(4)
    actions = [
        ("Пауза", client.pause_process, "⏸️"),
        ("Возобновить", client.resume_process, "▶️"),
        ("Отменить", client.cancel_process, "⛔"),
        ("Перезапустить", client.restart_process, "🔄"),
    ]
    for column, (label, action, icon) in zip(columns, actions):
        if column.button(f"{icon} {label}", use_container_width=True):
            try:
                action(process_id)
                st.toast(f"{label}: выполнено", icon=icon)
                st.rerun()
            except ApiError as exc:
                st.error(str(exc))


def _scenario_loader(client: RiskApiClient) -> None:
    paths = [DATA_DIR / "scenario.json"]
    scenarios_dir = DATA_DIR / "scenarios"
    if scenarios_dir.exists():
        paths.extend(sorted(scenarios_dir.glob("*.json")))
    paths = [path for path in paths if path.exists()]
    if not paths:
        st.warning("Каталог data/scenarios пуст.")
        return

    labels = {
        str(path.relative_to(DATA_DIR)): path
        for path in paths
    }
    selected = st.selectbox("Файл сценария", list(labels.keys()))
    reset_before = st.checkbox("Сбросить состояние перед загрузкой", value=True)
    if not st.button("Загрузить сценарий", use_container_width=True):
        return

    path = labels[selected]
    try:
        scenario = json.loads(path.read_text(encoding="utf-8"))
        if reset_before:
            client.reset()
        created = client.load_scenario(scenario)
        st.toast(f"Загружено процессов: {len(created)}", icon="📦")
        st.rerun()
    except (ApiError, OSError, json.JSONDecodeError, ValueError) as exc:
        st.error(f"Не удалось загрузить сценарий: {exc}")


def render(client: RiskApiClient, state: dict) -> None:
    st.subheader("Ручной запуск процесса")
    st.caption(
        "Ручной поток имеет абсолютный приоритет: он вытесняет автоматические "
        "процессы с теми же resource_key."
    )
    _manual_form(client)

    st.divider()
    st.subheader("Управление жизненным циклом")
    _manage_processes(client, state)

    st.divider()
    st.subheader("Демо-сценарии")
    _scenario_loader(client)

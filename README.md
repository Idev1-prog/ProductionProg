# Risk Orchestrator

Модуль-оркестратор запусков процессов для системы оценки рисков крупного банка.
Упорядочивает ночной регламентный поток и ручные пересчёты аналитиков,
предотвращает RAW/WAW-конфликты по данным, показывает очередь, нагрузку и
диаграмму Ганта, позволяет настраивать веса приоритетов без перезапуска.

> Демо-стенд: FastAPI + in-memory/SQLite + Streamlit + Plotly.
> Реальные расчёты не выполняются — длительность процесса симулируется.

---

## Что уже работает

- Приём процессов через REST API и загрузка JSON-сценариев.
- Priority Engine: ручной поток имеет абсолютный приоритет; автоматический
  сортируется по SLA, срочности и защите от starvation.
- Conflict Manager: гранулярные блокировки по `resource_key`, обнаружение
  RAW/WAW, журнал предотвращённых конфликтов.
- Вытеснение автоматического процесса ручным (`OVERRIDE`).
- Машина состояний: `queued → blocked → running → completed / cancelled / failed`,
  пауза, возобновление, отмена, перезапуск.
- Диаграмма Ганта, дашборд с heatmap нагрузки, таблицы очереди и конфликтов.
- Конфигуратор весов приоритетов и лимита параллельных процессов.
- Опциональная персистентность состояния в SQLite.
- Юнит-тесты приоритетов и конфликтов + smoke-тест API.

---

## Структура репозитория

```text
risk-orchestrator/
├── README.md                        # этот файл
├── requirements.txt
├── pytest.ini
├── .gitignore
├── .streamlit/
│   └── config.toml               # скрывает кнопку Deploy и developer-меню
│
├── backend/
│   ├── main.py                      # FastAPI + фоновый tick-цикл
│   ├── schemas.py                   # Pydantic-контракты
│   ├── storage.py                   # in-memory state / SQLite snapshot
│   ├── api/
│   │   ├── processes.py             # POST /processes, pause/cancel/restart
│   │   ├── state.py                 # GET /state, /gantt, /conflicts, /events
│   │   └── settings.py              # GET/PUT /settings
│   └── core/
│       ├── models.py                # Process, Resource, Lock, PrioritySettings
│       ├── orchestrator.py          # add_process(), tick(), get_state()
│       ├── priority.py              # Priority Engine
│       ├── conflicts.py             # Conflict Manager (RAW/WAW)
│       ├── state_machine.py         # статусы и переходы
│       └── worker.py                # симуляция выполнения
│
├── frontend/
│   ├── app.py                       # Streamlit: вкладки + автообновление
│   ├── api_client.py                # httpx-обёртка над API
│   └── components/
│       ├── gantt.py
│       ├── dashboard.py
│       ├── queue_table.py
│       ├── controls.py
│       └── settings_panel.py
│
├── data/
│   ├── scenario.json                # основной демо-сценарий
│   ├── scenarios/
│   │   ├── 01_happy_path.json
│   │   ├── 02_waw_conflict.json
│   │   ├── 03_raw_conflict.json
│   │   └── 04_manual_override.json
│   └── generator.py                 # генератор синтетики
│
├── scripts/
│   ├── seed.py                      # загрузка сценария в API
│   └── demo_runner.py               # пошаговый прогон демо
│
├── docs/
│   ├── api_contract.md
│   ├── architecture.md
│   ├── bottlenecks_ai_analysis.md
│   ├── demo_script.md
│   └── presentation/pitch_deck.pdf
│
└── tests/
    ├── test_priority.py
    ├── test_conflicts.py
    └── test_smoke_api.py
```

---

## Быстрый старт (Windows PowerShell)

Требуется Python 3.11+ (проверено на 3.11, целевой стек — 3.12).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Терминал 1 — API:

```powershell
uvicorn backend.main:app --reload --port 8000
```

Терминал 2 — UI:

```powershell
streamlit run frontend/app.py
```

- Swagger: <http://127.0.0.1:8000/docs>
- UI: <http://localhost:8501>

Если API живёт на другом адресе, задайте `RISK_API_URL` или поменяйте поле
«API URL» в сайдбаре Streamlit.

Кнопка Deploy и developer-меню Streamlit скрыты через `.streamlit/config.toml`
(`client.toolbarMode = "viewer"`) — интерфейс предназначен для внутреннего
банковского сервиса, а не для публикации в Streamlit Community Cloud.
Ручное обновление данных доступно кнопкой «Обновить» в сайдбаре.

### Загрузка сценария

```powershell
python scripts/seed.py --reset --scenario data/scenario.json --watch 10
```

### Полный демо-прогон

```powershell
python scripts/demo_runner.py --delay 4
```

### Генерация синтетики

```powershell
python data/generator.py --count 50 --seed 7 --out data/scenarios/generated.json
```

### Тесты

```powershell
pytest -q
```

### Персистентность (опционально)

```powershell
$env:RISK_PERSIST="1"
uvicorn backend.main:app --port 8000
```

Состояние сохраняется в `data/orchestrator.db` и восстанавливается при старте
(выполнявшиеся процессы возвращаются в очередь).

---

## Как это устроено

1. Процесс приходит в `POST /processes` или пачкой в `POST /scenario`.
2. Priority Engine считает балл:
   - ручной: `manual_base + urgency·5 + wait·0.1` (гарантированно > auto);
   - автоматический: `sla_weight·SLA/100 + urgency_weight·urgency/10 + starvation_weight·wait/100`.
3. Планировщик каждые `tick_interval` секунд:
   - завершает процессы, у которых истекло время;
   - пересчитывает приоритеты;
   - запускает лучшие процессы, если есть свободный слот;
   - проверяет блокировки по `resource_key` и переводит конфликтующие в `blocked`.
4. Ручной процесс при конфликте вытесняет автоматический: снимает его блокировки,
   возвращает в очередь и пишет `OVERRIDE` в журнал.
5. UI читает `/state`, `/gantt`, `/conflicts` и перерисовывается каждые N секунд.

Подробнее: [`docs/architecture.md`](docs/architecture.md),
контракт API: [`docs/api_contract.md`](docs/api_contract.md).

---

## Основные эндпоинты

| Метод | Путь | Назначение |
|---|---|---|
| `POST` | `/processes` | Создать процесс |
| `GET` | `/processes` | Список процессов |
| `POST` | `/processes/{id}/pause` | Пауза |
| `POST` | `/processes/{id}/resume` | Возобновить |
| `POST` | `/processes/{id}/cancel` | Отменить |
| `POST` | `/processes/{id}/restart` | Перезапустить |
| `POST` | `/scenario` | Загрузить сценарий целиком |
| `GET` | `/state` | Полный снимок состояния |
| `GET` | `/gantt` | Данные для диаграммы Ганта |
| `GET` | `/conflicts` | Журнал RAW/WAW/OVERRIDE |
| `GET/PUT` | `/settings` | Веса приоритетов |
| `POST` | `/reset` | Сброс демо-состояния |

---

## Ограничения MVP

- Выполнение процессов симулируется по таймеру, без реальных расчётов.
- Один экземпляр оркестратора; горизонтальное масштабирование не реализовано.
- Пауза/возобновление перезапускает выполнение с нуля (упрощение MVP).
- RBAC и audit trail ограничены журналом событий; авторизация не включена.
- SQLite-снимок — демонстрация персистентности, не production-хранилище.

---

## Роли в команде

| Область | Владелец | Каталоги |
|---|---|---|
| Ядро оркестрации | №1 | `backend/core/`, `tests/test_priority.py`, `tests/test_conflicts.py` |
| API и контракты | №2 | `backend/main.py`, `backend/schemas.py`, `backend/storage.py`, `backend/api/` |
| Frontend | №3 | `frontend/` |
| Данные, демо, docs | №4 | `data/`, `scripts/`, `docs/`, `tests/test_smoke_api.py`, `README.md` |

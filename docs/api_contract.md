# API Contract — Risk Orchestrator v0.1

> **Статус: заморожен после 0:30.** Изменения только через RFC-комментарий в PR
> и уведомление владельцев frontend/core. Базовый URL: `http://127.0.0.1:8000`.
> Swagger: `GET /docs`, OpenAPI: `GET /openapi.json`.

## 1. Общие правила

- Формат: JSON, UTF-8.
- Время: ISO-8601 с таймзоной (`2026-11-26T12:00:00+00:00`).
- Ошибки: `{"detail": "текст"}`.
- Коды: `200` успех, `201` создано, `400` бизнес-ошибка (недопустимый переход,
  нет ресурсов), `404` процесс не найден, `422` ошибка валидации Pydantic.
- CORS открыт для demo-стенда.

## 2. Модели

### 2.1. Resource

```json
{
  "key": "dm_credit.portfolio",
  "mode": "write",
  "service": "risk-db"
}
```

- `key` — гранулярный ресурс: таблица, срез, партиция или дата.
- `mode` — `read` | `write`.
- `service` — сервис/БД-владелец (для heatmap).

### 2.2. Process (вход, `ProcessCreate`)

```json
{
  "name": "Ночной расчёт кредитного риска",
  "flow": "auto",
  "urgency": 9,
  "duration_sec": 25,
  "sla_in_sec": 120,
  "resources": [
    {"key": "dm_credit.portfolio", "mode": "write", "service": "risk-db"}
  ],
  "meta": {"owner": "risk-night"}
}
```

| Поле | Тип | Обяз. | Ограничения |
|---|---|---|---|
| `name` | string | да | 1..160 |
| `flow` | string | нет | `manual` \| `auto`, по умолчанию `auto` |
| `urgency` | int | нет | 1..10, по умолчанию 5 |
| `duration_sec` | float | нет | >0..600, по умолчанию 10 |
| `sla_in_sec` | float\|null | нет | ≥0, по умолчанию 600; дедлайн от «сейчас» |
| `sla_deadline` | datetime\|null | нет | абсолютный дедлайн, приоритетнее `sla_in_sec` |
| `resources` | Resource[] | да | минимум 1 |
| `meta` | object | нет | свободные метаданные |

### 2.3. Process (выход, `ProcessOut`)

```json
{
  "id": "p-1a2b3c4d",
  "name": "Ночной расчёт кредитного риска",
  "flow": "auto",
  "status": "running",
  "priority": 72.4,
  "urgency": 9,
  "duration_sec": 25,
  "progress": 0.42,
  "attempts": 1,
  "resources": [{"key": "dm_credit.portfolio", "mode": "write", "service": "risk-db"}],
  "created_at": "2026-11-26T12:00:00+00:00",
  "started_at": "2026-11-26T12:00:00+00:00",
  "finished_at": null,
  "paused_at": null,
  "sla_deadline": "2026-11-26T12:02:00+00:00",
  "blocked_by": [],
  "blocked_reason": "",
  "meta": {"owner": "risk-night"},
  "wait_sec": 0.0,
  "elapsed_sec": 10.5
}
```

Статусы: `queued`, `blocked`, `running`, `paused`, `completed`, `cancelled`, `failed`.

### 2.4. Settings

```json
{
  "manual_base": 1000,
  "sla_weight": 60,
  "urgency_weight": 30,
  "starvation_weight": 10,
  "max_running": 3,
  "tick_interval": 0.5
}
```

- `manual_base` ∈ [1000, 10000] — гарантирует абсолютный приоритет ручного потока.
- Веса ∈ [0, 1000].
- `max_running` ∈ [1, 100].
- `tick_interval` ∈ [0.1, 60] сек.

### 2.5. Conflict

```json
{
  "id": "c-1a2b3c4d",
  "at": "2026-11-26T12:00:05+00:00",
  "kind": "WAW",
  "resource_key": "dm_credit.portfolio",
  "process_id": "p-2",
  "process_name": "Запись портфеля — пересчёт",
  "blocked_by": "p-1",
  "blocked_by_name": "Запись портфеля — регламент",
  "message": "WAW: запись в «dm_credit.portfolio» уже выполняется",
  "resolution": "Процесс заблокирован до освобождения ресурса"
}
```

`kind`: `RAW` | `WAW` | `OVERRIDE`.

---

## 3. Эндпоинты

### 3.1. `GET /health`

```json
{"status": "ok", "service": "risk-orchestrator", "now": "2026-11-26T12:00:00+00:00"}
```

### 3.2. `POST /processes` → `201 ProcessOut`

Создаёт процесс, сразу пересчитывает очередь и делает тик. Если процесс может
стартовать — в ответе будет `running`, иначе `queued`/`blocked`.

Ошибки: `400` (нет ресурсов/пустое имя), `422`.

### 3.3. `GET /processes` → `200 ProcessOut[]`

Все процессы, сортировка по `created_at`.

### 3.4. `GET /processes/{id}` → `200 ProcessOut`

`404`, если процесса нет.

### 3.5. Действия над процессом

| Метод | Путь | Результат |
|---|---|---|
| `POST` | `/processes/{id}/pause` | `paused`; running-процесс освобождает блокировки |
| `POST` | `/processes/{id}/resume` | `queued` (или `running` после тика) |
| `POST` | `/processes/{id}/cancel` | `cancelled`, блокировки сняты |
| `POST` | `/processes/{id}/restart` | `queued` (или `running` после тика) |

Ответ — `ProcessOut`. `400` при недопустимом переходе, `404` если не найден.

### 3.6. `POST /scenario` → `201 ProcessOut[]`

Загружает сценарий целиком. Если передан `settings` — сначала применяет их.

```json
{
  "name": "02 WAW conflict",
  "description": "Два WRITE в один resource_key",
  "settings": {"manual_base": 1000, "sla_weight": 60, "urgency_weight": 30,
               "starvation_weight": 10, "max_running": 3, "tick_interval": 0.5},
  "processes": [
    {"name": "Writer 1", "flow": "auto", "urgency": 9, "duration_sec": 25,
     "sla_in_sec": 90,
     "resources": [{"key": "dm_credit.portfolio", "mode": "write", "service": "risk-db"}]},
    {"name": "Writer 2", "flow": "auto", "urgency": 7, "duration_sec": 15,
     "sla_in_sec": 180,
     "resources": [{"key": "dm_credit.portfolio", "mode": "write", "service": "risk-db"}]}
  ]
}
```

### 3.7. `GET /state` → `200 StateOut`

```json
{
  "now": "2026-11-26T12:00:10+00:00",
  "settings": {"manual_base": 1000, "sla_weight": 60, "urgency_weight": 30,
               "starvation_weight": 10, "max_running": 3, "tick_interval": 0.5},
  "counts": {"queued": 2, "blocked": 1, "running": 2, "paused": 0,
             "completed": 3, "cancelled": 0, "failed": 0},
  "processes": [],
  "queue": [],
  "running": [],
  "conflicts": [],
  "events": [],
  "resource_load": [
    {"key": "dm_credit.portfolio", "service": "risk-db",
     "readers": 0, "writers": 1, "processes": ["Ночной расчёт"]}
  ],
  "metrics": {
    "total": 8, "completed": 3, "failed": 0, "cancelled": 0,
    "running": 2, "queued": 2, "blocked": 1, "paused": 0,
    "manual_total": 2, "auto_total": 6, "conflicts_total": 4,
    "sla_at_risk": 1, "avg_wait_sec": 1.2, "max_wait_sec": 4.8,
    "utilization_pct": 66.7
  }
}
```

- `queue` — `queued` + `blocked`, отсортированы по приоритету.
- `resource_load` — активные блокировки для heatmap.
- `events` — последние 300 событий, новые первыми.

### 3.8. `GET /gantt` → `200 GanttEntry[]`

Только процессы, которые уже стартовали. Для `running` поле `end` — ожидаемое
окончание, для `completed` — фактическое, для `paused` — момент паузы.

```json
{
  "id": "p-1",
  "name": "Ночной расчёт",
  "flow": "auto",
  "status": "running",
  "start": "2026-11-26T12:00:00+00:00",
  "end": "2026-11-26T12:00:25+00:00",
  "priority": 72.4,
  "progress": 0.42,
  "duration_sec": 25,
  "resources": "dm_credit.portfolio:write",
  "blocked_reason": ""
}
```

### 3.9. `GET /conflicts` → `200 Conflict[]`

Новые конфликты первыми.

### 3.10. `GET /events` → `200 object[]`

```json
{"id": "e-1", "at": "...", "kind": "started",
 "message": "Процесс «...» получил ресурсы и выполняется",
 "process_id": "p-1", "actor": "system"}
```

### 3.11. `GET /settings` → `200 Settings`

### 3.12. `PUT /settings` → `200 Settings`

Принимает полный объект `Settings`. `manual_base < 1000` → `422`.
Применяется сразу, очередь пересчитывается.

### 3.13. `POST /reset` → `200`

```json
{"ok": true, "message": "Состояние оркестратора сброшено"}
```

Сбрасывает процессы, блокировки, конфликты, события и настройки к дефолтным.

---

## 4. Пример полного сценария (curl)

```bash
curl -X POST http://127.0.0.1:8000/reset

curl -X POST http://127.0.0.1:8000/processes \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Ручной пересчёт",
    "flow": "manual",
    "urgency": 9,
    "duration_sec": 12,
    "sla_in_sec": 60,
    "resources": [{"key": "dm_credit.portfolio", "mode": "write", "service": "risk-db"}]
  }'

curl http://127.0.0.1:8000/state
curl http://127.0.0.1:8000/gantt
curl http://127.0.0.1:8000/conflicts
```

---

## 5. Совместимость

- Frontend использует только эндпоинты из этого документа.
- Добавление необязательных полей в ответ — обратно совместимо.
- Удаление/переименование полей и путей требует новой версии (`/v2`).
- `ProcessOut.status` — строковый enum; новые статусы добавляются только с
  обновлением UI и state machine.

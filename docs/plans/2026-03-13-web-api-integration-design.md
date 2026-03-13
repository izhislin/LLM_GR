# Дизайн: Веб-интерфейс + API-интеграция с Гравител ВАТС

**Дата:** 2026-03-13
**Статус:** Утверждён

## Цель

Забирать записи звонков из доменов ВАТС Гравител по API, обрабатывать через существующий pipeline (GigaAM + Qwen3-8B) и отображать результаты на простой веб-странице.

## Подход

**Монолит FastAPI + asyncio фоновые задачи (Подход A)**

Один процесс FastAPI на AI Lab сервере: webhook-приёмник, polling-scheduler, веб-UI, фоновая обработка через ThreadPoolExecutor. SQLite для хранения.

## Архитектура

```
                    ┌─────────────────────────────────────────┐
                    │              AI Lab Server               │
                    │                                         │
[Гравител АТС] ──webhook──▶ ┌──────────────┐                │
                    │        │  FastAPI App  │                │
Пользователь ──браузер──▶   │              │                │
                    │        │  - /webhook   │  ┌───────────┐│
                    │        │  - /api/*     │──│  SQLite    ││
                    │        │  - /ui/*      │  │  calls.db  ││
                    │        │  - scheduler  │  └───────────┘│
                    │        └──────┬───────┘                │
                    │               │                         │
                    │        ┌──────▼───────┐                │
                    │        │  Background   │                │
                    │        │  Worker Pool  │                │
                    │        │  (ThreadPool) │                │
                    │        └──────┬───────┘                │
                    │               │                         │
                    │        ┌──────▼───────┐                │
                    │        │  Pipeline     │                │
                    │        │  GigaAM+LLM  │                │
                    │        └──────────────┘                │
                    └─────────────────────────────────────────┘
```

## Новые модули

| Модуль | Назначение |
|---|---|
| `src/web/app.py` | FastAPI-приложение, роутинг, lifespan |
| `src/web/routes/webhook.py` | Приём webhook от АТС + валидация X-API-KEY |
| `src/web/routes/api.py` | REST API для фронтенда |
| `src/web/routes/ui.py` | HTML-страницы (Jinja2) |
| `src/web/templates/` | Jinja2 шаблоны |
| `src/web/static/` | CSS/JS |
| `src/gravitel_api.py` | Клиент Gravitel REST API |
| `src/worker.py` | Фоновый обработчик: очередь, скачивание, запуск pipeline |
| `src/db.py` | SQLite: схема, CRUD |

Существующие модули (`pipeline.py`, `transcriber.py`, `llm_analyzer.py`, `text_corrector.py`) — без изменений.

## Конфигурация доменов

Файл `config/domains.yaml`:

```yaml
domains:
  gravitel.aicall.ru:
    api_key_env: "GRAVITEL_API_KEY"
    profile: "gravitel"
    enabled: true
    polling_interval_min: 10
    filters:
      min_duration_sec: 20
      max_duration_sec: 1500
      call_types: ["in", "out"]
      only_with_record: true
      results: ["success"]
```

Секреты — в `.env`, конфиг ссылается на имя переменной окружения.

## Модель данных (SQLite)

### domains
| Поле | Тип | Описание |
|---|---|---|
| domain | TEXT PK | Домен ВАТС |
| last_polled_at | TEXT | Время последнего polling |
| last_poll_cursor | TEXT | Курсор для инкрементального polling |

### calls
| Поле | Тип | Описание |
|---|---|---|
| id | TEXT PK | UniqCallID от АТС |
| domain | TEXT | Домен |
| direction | TEXT | in/out |
| result | TEXT | success/missed/... |
| duration | INTEGER | Длительность, сек |
| wait | INTEGER | Ожидание до соединения, сек |
| started_at | TEXT | ISO8601 |
| client_number | TEXT | Номер клиента |
| operator_extension | TEXT | Внутренний номер оператора |
| operator_name | TEXT | Имя оператора (из справочника) |
| phone | TEXT | Номер АТС |
| record_url | TEXT | URL записи |
| source | TEXT | webhook/polling |
| received_at | TEXT | Когда получили |

### processing
| Поле | Тип | Описание |
|---|---|---|
| call_id | TEXT PK FK | ID звонка |
| status | TEXT | pending/downloading/processing/done/error/skipped |
| audio_path | TEXT | Локальный путь к mp3 |
| result_json | TEXT | JSON результат pipeline |
| error_message | TEXT | Текст ошибки |
| skip_reason | TEXT | Причина пропуска |
| retry_count | INTEGER | Число попыток |
| started_at | TEXT | Начало обработки |
| completed_at | TEXT | Конец обработки |
| processing_time_sec | REAL | Время обработки |

### operators
| Поле | Тип | Описание |
|---|---|---|
| domain | TEXT PK | Домен |
| extension | TEXT PK | Внутренний номер |
| name | TEXT | Имя сотрудника |
| synced_at | TEXT | Время синхронизации |

### departments
| Поле | Тип | Описание |
|---|---|---|
| domain | TEXT PK | Домен |
| id | INTEGER PK | ID отдела |
| extension | TEXT | Внутренний номер отдела |
| name | TEXT | Название отдела |
| synced_at | TEXT | Время синхронизации |

## API-эндпоинты

### Webhook (АТС → наш сервер)

```
POST /webhook/{domain}/history
     Header: X-API-KEY
     → валидация → дедупликация → фильтры → очередь
     ← 200 OK
```

### Polling (наш сервер → АТС)

```
POST https://crm.aicall.ru/v1/{domain}/history
     Header: X-API-KEY
     Body: { period/start/end, type, limit }
     Scheduler: каждые N мин (из конфига домена)
```

### REST API для UI

| Метод | Эндпоинт | Описание |
|---|---|---|
| GET | `/api/calls` | Список звонков (пагинация, фильтры) |
| GET | `/api/calls/{id}` | Детали + результат анализа |
| GET | `/api/stats` | Сводная статистика |
| POST | `/api/sync/{domain}` | Ручной запуск polling |
| GET | `/api/domains` | Список доменов и статус |

Фильтры `/api/calls`: domain, date_from, date_to, status, direction, operator, department, page, per_page.

### Синхронизация справочников

```
GET https://crm.aicall.ru/v1/{domain}/accounts → operators (UPSERT)
GET https://crm.aicall.ru/v1/{domain}/groups   → departments (UPSERT)
Периодичность: при старте + каждые 60 мин
```

## Веб-интерфейс

Две страницы:
- **Главная (`/`)** — таблица звонков с фильтрами (домен, период, статус, оператор, отдел), сводные метрики, кнопка ручной синхронизации, автообновление каждые 30 сек
- **Детали звонка (`/call/{id}`)** — метаданные, оценка качества, резюме, извлечённые данные, транскрипт

Технологии: Jinja2 + vanilla CSS/JS, без фреймворков.

## Фильтрация звонков

```
Звонок получен →
  record_url пустой?          → skipped: "no record"
  duration < min_duration?    → skipped: "too short"
  duration > max_duration?    → skipped: "too long"
  result не в списке?         → skipped: "result: missed"
  call_type не в списке?      → skipped: "type: missed"
  всё ок                     → pending
```

Skipped-звонки сохраняются в БД (видны в UI), но не обрабатываются.

## Обработка ошибок

- Неверный X-API-KEY → 401
- Неизвестный домен → 404
- Ошибка скачивания/обработки → retry (до 3 попыток, интервал 5 мин)
- Дубликаты → INSERT OR IGNORE
- Polling API недоступен → логируем, повторяем в следующий цикл

## Безопасность

- API-ключи в `.env` (не в git)
- Веб-UI: базовая HTTP-аутентификация
- Parameterized SQL queries
- HTTPS — позже через reverse proxy

## Деплой

- systemd-сервис (`ai-lab-web.service`)
- `uvicorn src.web.app:app --host 0.0.0.0 --port 8080`
- MikroTik: внешний порт 42367 → внутренний 8080
- `.env` для секретов

## Тестирование

Моки для всех внешних зависимостей, тесты работают без GPU/сети.

| Модуль | Моки |
|---|---|
| db.py | SQLite in-memory |
| gravitel_api.py | httpx responses |
| worker.py | pipeline, gravitel_api |
| webhook routes | db |
| api routes | db |

Ключевые тест-кейсы: webhook валидация/дедупликация, фильтрация по конфигу, retry-логика, API пагинация/фильтры, UPSERT справочников.

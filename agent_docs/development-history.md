# История разработки

Правило: хранить только последние 10 записей. При добавлении новой переносить старые в
`agent_docs/development-history-archive.md`. Архив читать при необходимости.

---

Краткий журнал итераций проекта.

## Записи

### 2026-03-15 — Исправление LLM-ошибок, stale detector, VAD threshold

- **LLM num_ctx:** Ollama обрезал промпт на 4096 токенов → добавлен `OLLAMA_NUM_CTX=32768` (Qwen3-8B max 40960). `format: "json"` включён по умолчанию (constraint mode).
- **Таймаут:** `OLLAMA_TIMEOUT` увеличен с 120 до 300 сек (для длинных на CPU). `MAX_RETRIES` увеличен с 2 до 3.
- **Stale detector:** `reset_stale_processing()` в db.py — сбрасывает записи в processing/downloading старше 15 мин. Вызывается в `_scheduler_loop()` перед `process_pending()`.
- **VAD threshold:** `VAD_NEW_CHUNK_THRESHOLD=0.05` (было 0.2) — снижен порог для коротких фраз («да», «угу»).
- **Тесты:** 144 passed (было 138, +3 db, +2 llm_analyzer, +1 transcriber assertion).
- **GPU:** подготовлены инструкции для перевода Ollama на GPU (серверная задача).

### 2026-03-13 — Деплой на AI Lab и доработка Web UI

- **Деплой:** git init + fetch на сервере, установлены fastapi/uvicorn/apscheduler/python-dotenv/python-multipart
- **`.env`:** настроен с реальным API-ключом Гравител, HF_TOKEN, отдельным webhook-ключом
- **Polling:** 200 звонков загружено (107 pending, 92 skipped, 1 processing), 35 операторов, 8 отделов
- **systemd:** user-level сервис `~/.config/systemd/user/ai-lab-web.service` + `loginctl enable-linger` (нет sudo)
- **Basic Auth:** middleware в FastAPI (`WEB_USERNAME`/`WEB_PASSWORD`), `secrets.compare_digest`, исключения для `/webhook/` и `/metrics`
- **Prometheus:** установлен `prometheus_client`, `start_metrics_server()` вызывается в FastAPI lifespan (не только CLI)
- **Webhook-ключ:** разделён на `GRAVITEL_API_KEY` (CRM) и `GRAVITEL_WEBHOOK_KEY` (АТС), добавлен `webhook_key_env` в `DomainConfig`
- **Web UI:**
  - Переписан `app.js:loadCallDetail()`: качество → цветные бары с комментариями, резюме → форматированный текст, данные → карточки, транскрипт → цветовая разметка оператор/клиент
  - Поддержка двух форматов `quality_score` от LLM: плоский (`greeting: 3`) и вложенный (`criteria.greeting.score: 8`)
  - Cache busting (`?v=2`) в `base.html`
- **Коррекция LLM-вывода:** `_correct_llm_output()` рекурсивно применяет text_corrector к строкам в JSON (Gravital → Гравител)
- **Имена операторов:** LEFT JOIN с таблицей operators в `list_calls()`, fallback через `get_operator_name()` в API detail
- **Коммиты:** 7 (4e335b6..fbd0dd3)
- **Доступ:** `http://212.24.45.138:42367/` (MikroTik 42367→8080), логин `ailab`

### 2026-03-13 — Web API интеграция (полная реализация)

- **Архитектура:** монолит FastAPI + asyncio + ThreadPoolExecutor. Webhook-приёмник + polling каждые 10 мин
- **Новые модули (8 файлов):**
  - `src/domain_config.py`: датаклассы `CallFilters`, `DomainConfig`, загрузка из `config/domains.yaml`
  - `src/gravitel_api.py`: async HTTP-клиент для CRM API Гравител (history, accounts, groups, download)
  - `src/call_filter.py`: фильтрация звонков по длительности, типу, наличию записи
  - `src/db.py`: SQLite-слой (5 таблиц, 16 CRUD-функций, `check_same_thread=False` для FastAPI)
  - `src/web/routes/webhook.py`: POST `/webhook/{domain}/history` (auth, dedup, filtering)
  - `src/web/routes/api.py`: REST API (`/api/calls`, `/api/stats`, `/api/domains`, etc.)
  - `src/worker.py`: `CallWorker` — скачивание записей + запуск pipeline
  - `src/web/app.py`: FastAPI lifespan, scheduler loop, directory sync, manual sync endpoint
- **Web UI:** Jinja2 + vanilla CSS/JS (base.html, index.html, call_detail.html, style.css, app.js)
  - Таблица звонков с фильтрами (домен, направление, статус, даты), пагинация, автообновление 30 сек
  - Страница деталей: метаданные, оценка качества, резюме, извлечённые данные, транскрипт
- **Тесты:** 139 тестов (было 34), все проходят. Покрытие: DB (41), API client (12), filter (9), webhook (6), REST API (8), worker (3), integration (2), domain config (11), остальное (47)
- **Config:** `config/domains.yaml`, `.env.example`, обновлён `.gitignore`
- **Дизайн:** `docs/plans/2026-03-13-web-api-integration-design.md`
- **План:** `docs/plans/2026-03-13-web-api-integration-plan.md`

### 2026-03-13 — Модуль базы данных (SQLite)

- Создан `src/db.py`: синхронный SQLite-слой для хранения звонков, обработки, операторов и отделов
- 5 таблиц: `domains`, `calls`, `processing`, `operators`, `departments`
- 3 индекса: `idx_calls_domain`, `idx_calls_started`, `idx_processing_status`
- 16 функций: `init_db`, `insert_call` (INSERT OR IGNORE), `get_call`, `list_calls` (JOIN + фильтры + пагинация), `get_calls_count`, `insert_processing`, `get_processing`, `update_processing_status` (auto started_at/completed_at/retry_count), `get_pending_calls`, `get_retryable_calls`, `upsert_operator`, `get_operator_name`, `list_operators`, `upsert_department`, `list_departments`, `update_domain_poll_time`
- Создан `tests/test_web/test_db.py`: 37 тестов (TDD), покрытие: init, CRUD, дубликаты, фильтры, пагинация, статусы, retry, операторы, отделы, поллинг доменов
- Все функции проверены через ручной интеграционный тест (pytest недоступен локально на macOS)

### 2026-03-13 — HTTP-клиент Gravitel API

- Создан `src/gravitel_api.py`: асинхронный HTTP-клиент (`httpx.AsyncClient`) для CRM API Гравител
- `GravitelClient`: init(domain, api_key, timeout), close(), 4 async-метода
- `fetch_history()`: POST с period/start/end/type/limit, возвращает список звонков
- `fetch_accounts()`, `fetch_groups()`: GET-запросы для справочников домена
- `download_record()`: скачивание файла записи с сохранением на диск (создаёт parent dirs)
- Все методы передают `X-API-KEY` заголовок и вызывают `raise_for_status()`
- Создан `tests/test_web/test_gravitel_api.py`: 12 тестов (TDD, AsyncMock + httpx.Response)
- Тесты: возврат данных, передача auth-заголовка, параметры запроса, сохранение файла, ошибки 401/500

### 2026-03-13 — Модуль фильтрации звонков

- Создан `src/call_filter.py`: функция `filter_call(call, filters)` — последовательная проверка звонка по фильтрам домена
- Проверки: наличие записи, мин/макс длительность, результат, тип звонка
- Использует `CallFilters` из `src/domain_config.py`
- Создан `tests/test_web/test_call_filter.py`: 9 тестов (TDD), всего 66 тестов — все проходят

### 2026-03-13 — Модуль конфигурации доменов

- Создан `src/domain_config.py`: датаклассы `CallFilters` и `DomainConfig`, функция `load_domains_config()`
- `CallFilters`: фильтрация звонков по длительности, типу, наличию записи, результату (дефолты для всех полей)
- `DomainConfig`: api_key_env, profile, enabled, polling_interval_min, filters
- `load_domains_config()`: загрузка из YAML (`config/domains.yaml`), поддержка частичных фильтров с дефолтами
- Создан `tests/test_domain_config.py`: 11 тестов (TDD), всего 57 тестов — все проходят

### 2026-03-13 — Prometheus-экспортёры на сервере

- Установлен `node_exporter` v1.7.0 (apt) — CPU, RAM, disk, network
- Установлен `nvidia_gpu_exporter` v1.4.1 (.deb, скачан локально и передан по SCP) — GPU util, memory, temp, power
- Ollama v0.17.7 не поддерживает встроенные Prometheus-метрики (`OLLAMA_METRICS` не существует), порт зарезервирован
- Маппинг MikroTik: 42363→9100, 42364→9835, 42365→8000, 42366→11434
- Документация: `agent_docs/guides/server-access.md` (секция «Мониторинг»)

### 2026-03-13 — Prometheus-метрики в пайплайне

- Создан `src/metrics.py`: 8 Prometheus-метрик (pipeline timing, RTF, файлы, Ollama tokens/sec, ретраи)
- `start_metrics_server()` — фоновый HTTP на `:8000/metrics`, `track_stage()` — context manager для замера этапов
- `llm_analyzer.py`: извлечение Ollama metadata (`eval_count`, `eval_duration`, `prompt_eval_count`), обновление счётчиков
- `pipeline.py`: 5 этапов обёрнуты в `track_stage`, обновление `pipeline_rtf` и `pipeline_files_total`
- Import guard (`try/except ImportError`) — `prometheus_client` опциональна, пайплайн работает без неё
- `requirements.txt`: добавлен `prometheus_client>=0.20`
- 9 новых тестов (`tests/test_metrics.py`), всего 46 тестов — все проходят

### 2026-03-13 — Улучшение качества анализа (Подход A)

- Уточнена целевая аудитория в AGENTS.md: сервис для клиентов Гравител (компании с ВАТС), не для собственного колл-центра
- `text_corrector.py`: добавлены паттерны для обрезанных слов GigaAM (`штри`→`штрих`, `добавочн`→`добавочный`)
- `profiles/gravitel.yaml`: добавлены термины (`софтфон`), расширен `llm_context` (домены, продукты)
- `llm_analyzer.py`: `analyze_dialogue()` принимает `llm_context` и добавляет его перед диалогом во все LLM-вызовы
- `pipeline.py`: передаёт `llm_context` из профиля в `analyze_dialogue()`
- **Промпты:**
  - `quality_score.md`: IVR-детекция (`is_ivr: true`), уточнены критерии greeting (перевод звонка), откалибрована шкала (7-8 = норма)
  - `summarize.md`: добавлены `call_type` и `action_items`
  - `extract_data.md`: добавлены `operator_name` и `department`
- 37 тестов (было 34), все проходят
- Дизайн: `docs/plans/2026-03-13-quality-improvements-design.md`

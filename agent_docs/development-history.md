# История разработки

Правило: хранить только последние 10 записей. При добавлении новой переносить старые в
`agent_docs/development-history-archive.md`. Архив читать при необходимости.

---

Краткий журнал итераций проекта.

## Записи

### 2026-03-31 — Исправление конфликта webhook/polling + ускорение очереди

- **Проблема:** С 27 марта pipeline не обрабатывал новые звонки. Все 553 звонка получали `skipped: no record`. Причина: после фикса webhook 26 марта звонки стали приходить сначала через webhook (с пустым `record_url`), а polling при обнаружении уже существующего ID пропускал обновление (`get_call() → continue`).
- **Фикс `_poll_domain`:** Вместо пропуска существующих звонков — обновление `record_url`, `duration` и других полей через новую функцию `update_call_from_polling()`. При успешном обновлении — переоценка фильтра и `reopen_processing()` (skipped → pending).
- **Новые функции в `db.py`:** `update_call_from_polling()` (обновляет только если `record_url` пуст), `reopen_processing()` (skipped → pending с очисткой `skip_reason`).
- **Бэкфилл при старте:** Одноразовый проход по истории за 7 дней при запуске приложения — safety net при перезапусках.
- **Ускорение очереди:** Scheduler loop теперь обрабатывает pending непрерывно (`while processed > 0`), без 10-мин пауз между пачками. Сократило время обработки 282 звонков с ~4.8ч до 1.6ч.
- **Результат:** 282 пропущенных звонка за 27–31 марта обработаны за 97 минут. Pipeline работает штатно.
- **Тесты:** 170 passed (+8 новых: update_call_from_polling × 4, reopen_processing × 4).
- **Отчёт:** `data/report_2026_03_31_pipeline_fix.html`.

### 2026-03-28 — OpenAI-compatible API + Open WebUI

- **OpenAI API прокси:** Новый роутер `src/web/routes/openai_compat.py` — реализация `POST /v1/chat/completions` и `GET /v1/models` в формате OpenAI Chat API. Проксирует запросы к Ollama. Поддерживает stream/sync режимы, параметры temperature/top_p/max_tokens.
- **Авторизация:** Bearer-токен через `LLM_API_KEY` в `.env` (timing-safe сравнение). Если ключ не задан — авторизация отключена. Маршруты `/v1/` исключены из Basic Auth middleware (своя авторизация по Bearer).
- **Open WebUI:** Добавлен `docker-compose.yml` для запуска Open WebUI (Docker) на порту 8091, подключён к Ollama. Внешний доступ через MikroTik `42371→8091`. Регистрация отключена (`ENABLE_SIGNUP=false`), пользователи создаются через Admin Panel.
- **Деплой:** Код на сервере, сервис перезапущен, Open WebUI запущен в Docker. API-ключ `LLM_API_KEY` сгенерирован на сервере.
- **Порты на сервере:** 8080 (FastAPI/AI Lab Web), 8090 (TTS API), 8091 (Open WebUI Docker).
- **Брендинг Open WebUI:** Favicon Gravitel (SVG + PNG 500x500 + 96x96) смонтирован через Docker volumes. Название задано через `WEBUI_NAME=Gravitel AI`. Custom CSS подключён через `custom.css` mount (пока пустой, готов к использованию).
- **Документация:** `agent_docs/guides/llm-api.md` — инструкция по API (токен, подключение, команды, примеры). HTML-версия: `docs/llm-api.html` в корпоративном стиле Gravitel.
- **Skill:** Глобальный skill `gravitel-branded-docs` (`~/.claude/skills/`) — генерация HTML-документации в корпоративном стиле. Slash-команда `/gravitel-doc`.
- **Конфигурация Open WebUI:** `config/open-webui-custom.css`, `config/open-webui-assets/` (favicon.svg, favicon.png, favicon-96x96.png).
- **Тесты:** 162 passed (+8 новых: auth, models, sync/stream completions, options passthrough, validation).

### 2026-03-26 — Исправление webhook: суффикс /event в URL

- **Проблема:** Гравител АТС добавляет суффикс `/event` или `/history` к webhook URL. Роут принимал только `/webhook/{domain}/history` → все входящие webhook-и получали 404.
- **Диагностика:** В логах uvicorn — десятки запросов от `84.252.128.122` на `/history/event` с 404. В БД — 0 webhook-звонков (все 2329 через polling).
- **Фикс:** Добавлен второй декоратор `@router.post("/webhook/{domain}/history/{event_type}")`. Дедупликация по `call_id` обрабатывает повторные события.
- **Результат:** Webhook-и от Гравител принимаются (200 OK), звонки попадают в БД с `source=webhook`.
- **Тесты:** 8 passed (+2 новых: `test_webhook_event_suffix`, `test_webhook_history_suffix`).

### 2026-03-18 — Улучшения UI: фильтры, сортировка, навигация

- **Фильтры списка:** оператор (dropdown с именами), поиск по номеру клиента (debounce 400мс), фильтр по оценке качества (от/до), кнопка «Сбросить» для очистки всех фильтров.
- **Сортировка:** клик по заголовкам столбцов (дата, длительность, оценка) с визуальными индикаторами ▲/▼.
- **Пресеты дат:** кнопки «Сегодня», «Вчера», «Неделя».
- **Тема звонка:** подстрока на всю ширину под основной строкой (вместо обрезанного столбца).
- **Клик по оператору:** фильтрация по оператору прямо из таблицы.
- **Имена операторов:** исправлен баг — `c.*` затенял `COALESCE` при `dict(row)`, заменён на явный список полей.
- **Пропущенные звонки:** направление `missed` → «✗ Пропущен» (красный) + опция в фильтре.
- **Навигация по блокам:** sticky-навбар на странице звонка с якорями (Метаданные, Оценка, Резюме, Данные, Запись).
- **Бэкенд:** `list_calls` и `get_calls_count` расширены параметрами `client_search`, `score_min`, `score_max`, `sort_by`, `sort_order`. SQL injection предотвращён через whitelist сортировки.
- **Тесты:** 152 passed (+5 новых API-тестов).

### 2026-03-18 — Аудиоплеер с синхронизацией транскрипта

- **Эндпоинт:** `GET /api/audio/{call_id}` — отдача MP3 через `FileResponse` с валидацией пути (defense-in-depth).
- **Pipeline:** Добавлено поле `transcript_segments` в JSON-результат — список `{speaker, text, start, end}` с коррекцией текста per-segment.
- **Фронтенд:** HTML5-аудиоплеер на странице деталей звонка. Кастомные элементы управления: play/pause, прогресс-бар, выбор скорости (0.75x–2x).
- **Синхронизация:** Подсветка текущей реплики при воспроизведении, автоскролл, клик по реплике → перемотка аудио.
- **Обратная совместимость:** Для существующих ~200 записей таймкоды парсятся из `[HH:MM:SS]` в тексте транскрипта (JS fallback).
- **Тесты:** 147 passed (+3 новых: audio endpoint × 2, pipeline transcript_segments × 1).

### 2026-03-17 — GPU-верификация, keep_alive, webhook real-time

- **GPU-статус:** Подтверждено — Ollama использует GPU (37/37 слоёв на CUDA, RTX 5060 Ti). Модель выгружалась по idle-таймауту (5 мин default), что создавало впечатление работы на CPU.
- **Бенчмарк:** 74-77 tokens/sec на GPU (Qwen3:8b). Суммаризация диалога ~12 сек. VRAM: GigaAM 1.4 GB + Ollama 6.1 GB = 7.5 GB из 16 GB (запас 8.3 GB).
- **keep_alive:** Добавлен `OLLAMA_KEEP_ALIVE="30m"` в `config.py`, передаётся per-request через API payload (`llm_analyzer.py`). Без sudo — не требует изменения systemd-сервиса.
- **Webhook real-time:** Заменена заглушка `on_new_call=lambda: None` на `_executor.submit(_worker.process_one, call_id)` в `app.py`. Звонки из webhook обрабатываются сразу, а не ждут polling-цикла (до 10 мин). `ThreadPoolExecutor(max_workers=1)` гарантирует последовательную обработку.
- **Тесты:** 132 passed. 12 failed в `test_gravitel_api.py` — существующая проблема совместимости моков httpx на сервере.
- **Коммиты:** 2 (f007334, 6aa09f1).

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


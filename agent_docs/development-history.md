# История разработки

Правило: хранить только последние 10 записей. При добавлении новой переносить старые в
`agent_docs/development-history-archive.md`. Архив читать при необходимости.

---

Краткий журнал итераций проекта.

## Записи

### 2026-04-17 — Восстановление сервера после power-loss

- **Инцидент:** Отключалось электропитание, сервер не стартовал автоматически (нет BIOS-опции Power-On-AC). После ручного старта кнопкой — зависание на boot (`FAILED openipmi.service` перекрывал `login:` prompt), затем логин прошёл штатно. Снаружи все DNAT-порты молчали.
- **Корень проблемы:** DHCP выдал серверу новый IP `192.168.1.121` вместо прежнего `.108` — у MAC не было static lease. DNAT-правила MikroTik смотрели на `.108` → трафик уходил «в никуда», хотя ARP для `.108 → MAC` остался как static.
- **Фикс сети:** В MikroTik создан static DHCP lease `60:CF:84:62:59:2C → 192.168.1.190` (новый базовый IP). Все DNAT-правила перенастроены с `.108` на `.190`: 16380, 42363–42368, 42370, 42371. Все 8 портов проверены извне — OK.
- **Фикс редиректа ByVoice Portal (`:3200 → DNAT 42370`):** В `.env.production` был `NEXTAUTH_URL=http://212.24.45.138:42370` — Auth.js v5 жёстко редиректил все запросы на внешний URL, ломая доступ из LAN (`.190:3200`). Переменная закомментирована, оставлен `AUTH_TRUST_HOST=true` → Auth.js берёт origin из Host-заголовка. Редиректы теперь относительные, работает и из LAN, и снаружи. Backup: `web-client/.env.production.bak.20260417_162516`.
- **Косметика:** `sudo systemctl mask openipmi.service` + `systemctl reset-failed` — у железа нет IPMI-контроллера, юнит падал при каждом старте. Теперь `systemctl --failed` пуст.
- **TODO:** Включить в BIOS `Restore on AC Power Loss = Power On`, чтобы сервер стартовал сам после отключения питания.
- **Документация:** `agent_docs/guides/server-access.md` обновлён — зафиксированы внутренний IP `.190`, MAC, static lease, порт 42370 → byvoice-portal:3200.

### 2026-04-04 — Улучшения аналитики: тренды, сценарии, переклассификация

- **Cron:** Ежедневный batch `scripts/daily_analytics.py` в 03:00 — агрегация KB + пересчёт профилей клиентов. Настроен в crontab на сервере.
- **Улучшение классификации:** Добавлены категории `продажи/предложение` и `клиентский_бизнес` в `classify.md`. Переклассифицировано 124/177 звонков из «другое». Скрипт `scripts/reclassify_other.py`.
- **Тренды по неделям:** Новый эндпоинт `/api/dashboard/business/trends` + line chart на дашборде (звонки, ср. оценка, негативные по неделям).
- **Knowledge scenarios:** Скрипт `scripts/generate_scenarios.py` — генерация диагностических сценариев через облачный LLM (MiMo-V2-Pro, OpenRouter). 10 сценариев сгенерированы: переадресация, софтфон, обещанный платёж, документы и др. Отображаются на странице KB.
- **Страница базы знаний:** `/api/dashboard/kb` — карточки с фильтрами, бейджами частоты/решаемости, примерами звонков + секция сценариев.
- **Тестовые номера:** Номер 74952301010 — тестовый робот AICall (135 звонков). Операторы 300, 341, 343 — роботы. Учитывать при фильтрации аналитики.

### 2026-04-03 — Аналитическая платформа речевой аналитики

- **Цель:** Превратить pipeline транскрибации в аналитическую платформу с бизнес-инсайтами, базой знаний для голосовых роботов, и дашбордами.
- **Conversation metrics:** Новый модуль `src/analytics/conversation_metrics.py` — talk/silence/interruptions из таймкодов сегментов (без LLM, чистая арифметика). Интегрирован в `pipeline.py`.
- **Классификация (4-й LLM-вызов):** Промпт `classify.md` — category, subcategory, client_intent (8 интентов), sentiment, resolution_status, is_repeat_contact, tags. Добавлен в `analyze_dialogue()`.
- **Script checklist:** Расширен промпт `quality_score.md` — 7 boolean-полей соблюдения скрипта (приветствие, идентификация, решение, прощание).
- **Новые таблицы БД:** `client_profiles` (профили клиентов, risk_level), `knowledge_base` (агрегированные проблемы→решения), `knowledge_scenarios` (эталонные сценарии для роботов), `calls_fts` (FTS5 полнотекстовый поиск).
- **Client profiles:** `src/analytics/client_profiles.py` — инкрементальное обновление при обработке звонка + batch-пересчёт risk_level/sentiment_trend.
- **FTS5 поиск:** `src/analytics/search.py` — индексация и поиск по транскриптам, темам, проблемам.
- **Knowledge base:** `src/analytics/knowledge.py` — batch-агрегация проблем и решений по категориям.
- **Dashboard API:** `src/web/routes/dashboard.py` — 8 эндпоинтов: business KPIs, categories, sentiment, risk-clients, operator ratings, script-checklist, search, HTML-страницы.
- **Dashboard UI:** Два HTML-дашборда в стиле Гравител (шрифт Onest, indigo/teal палитра, Chart.js): обзор бизнеса + контроль операторов.
- **Гибридный LLM:** Ollama/Qwen3-8B (realtime, per-call) + OpenRouter/MiMo-V2-Pro (batch-аналитика). `call_cloud_llm()` в `llm_analyzer.py`.
- **Worker интеграция:** `index_call()` + `update_profile_on_call()` вызываются автоматически после обработки звонка.
- **Backfill:** `scripts/backfill_analytics.py` — ретроспективная классификация + FTS + metrics + profiles для 1703 существующих звонков (~37 мин на GPU).
- **Тесты:** 209 passed (+30 новых: conversation_metrics ×7, db_analytics ×8, client_profiles ×5, search ×5, knowledge ×4, dashboard API ×8, llm_analyzer ×4).
- **Спецификация:** `docs/superpowers/specs/2026-04-03-call-analytics-platform-design.md`.
- **План:** `docs/superpowers/plans/2026-04-03-call-analytics-platform.md`.

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


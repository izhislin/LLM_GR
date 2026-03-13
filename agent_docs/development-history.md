# История разработки

Правило: хранить только последние 10 записей. При добавлении новой переносить старые в
`agent_docs/development-history-archive.md`. Архив читать при необходимости.

---

Краткий журнал итераций проекта.

## Записи

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

### 2026-03-11 — Инициализация проекта и утверждение дизайна

- Определены требования: транскрибация двухканальных телефонных записей (русский) + LLM-обработка
- Выбран стек: GigaAM-v3 (ASR, Сбер) + Qwen3-8B (LLM через Ollama)
- GigaAM-v3 выбран вместо Whisper из-за 2-3x лучшего WER на русской телефонной речи
- Утверждён дизайн-документ: `docs/plans/2026-03-11-transcription-stand-design.md`
- Обновлён блок описания проекта в AGENTS.md

### 2026-03-11 — Audio splitter (Task 3)

- Создан `src/audio_splitter.py`: разделение стерео WAV на два моно-канала (оператор/клиент) через ffmpeg
- Функции: `get_audio_info()` (ffprobe), `split_stereo_to_mono()` (ffmpeg pan filter)
- Адаптация: `-map_channel` удалён в ffmpeg 8.x, заменён на `-af pan=mono|c0=c0/c1`
- Создан `tests/test_audio_splitter.py`: 4 теста (TDD), все проходят
- Создан `.venv` для запуска тестов (pytest)

### 2026-03-11 — Реализация всех модулей (Tasks 2, 4-8)

- `setup_server.sh`: скрипт настройки Ubuntu 22.04 (NVIDIA, CUDA, Ollama, Python deps)
- `src/transcriber.py`: обёртка GigaAM-v3 с lazy-загрузкой модели (singleton)
- `src/dialogue_builder.py`: склейка двух каналов в хронологический диалог
- `src/llm_analyzer.py`: клиент Ollama API с retry-логикой и JSON-парсингом
- `prompts/*.md`: промпты для суммаризации, оценки качества, извлечения данных
- `src/pipeline.py`: оркестратор пайплайна (CLI: `python -m src.pipeline <file>`)
- 16 тестов, все проходят (TDD, моки для GigaAM и Ollama)

### 2026-03-12 — Настройка SSH-доступа к серверу

- Сервер `gravitel-ai-lab`: `212.24.45.138:16380`, пользователь `aiadmin`
- Создан отдельный SSH-ключ `~/.ssh/id_ed25519_ailab` (без passphrase) для автоматизации
- Настроен алиас `ai-lab` в `~/.ssh/config` — подключение: `ssh ai-lab`
- Публичный ключ добавлен в `authorized_keys` на сервере
- Подключение по ключу проверено и работает
- Документация: `agent_docs/guides/server-access.md`

### 2026-03-12 — Развёртывание и настройка сервера

- **GPU:** RTX 5060 Ti 16GB (Blackwell, sm_120), драйвер 590.48, CUDA 13.1
- **PyTorch:** Обновлён с 2.5.1+cu124 до 2.12.0.dev+cu128 (nightly) — стабильные релизы не поддерживают sm_120 (Blackwell). Wheel скачан локально на Mac и передан по SCP (CDN PyTorch таймаутит с сервера)
- **GigaAM v3:** Переустановлен из GitHub (`salute-developers/GigaAM`) — PyPI-пакет (0.1.0) не содержит v3-модели. Установлен с `--no-deps` для обхода ограничения `torch<2.9`
- **Ollama:** v0.17.7, создан systemd-сервис вручную (установщик не довёл до конца). Модель `qwen3:8b` (5.2 GB) скачана
- **Проверено:** PyTorch на GPU (matmul test), GigaAM v3 загружается на cuda:0, Ollama API отвечает
- ADR: `agent_docs/adr.md` — решения по PyTorch nightly и GigaAM из GitHub

### 2026-03-12 — Первый успешный прогон пайплайна

- Тестовый файл: `2026-03-10_14-39-52_o_732-84996860315.mp3` (65 сек, стерео, 8kHz)
- Полный пайплайн: split → transcribe (2 канала) → summarize → quality → extract → JSON
- Время: ~70 сек (транскрибация ~7 сек, LLM ~60 сек)
- Патчи для совместимости: pyannote `use_auth_token→token` (huggingface_hub 1.6.0 несовместим), GigaAM `from_pretrained` с HF-токеном вместо локального пути
- Требуется `HF_TOKEN` для pyannote/segmentation-3.0 (VAD для longform)
- Результат: `data/results/2026-03-10_14-39-52_o_732-84996860315.json`

### 2026-03-12 — Батч-обработка 18 тестовых записей

- Все 18 файлов из `test_recs/` успешно обработаны (1 потребовал ретрай из-за таймаута Ollama)
- Среднее время обработки: 40 сек/файл, RTF 0.37x (в 2.7 раза быстрее реального времени)
- Транскрибация (GigaAM) — ~14% времени, LLM (Qwen3-8B) — ~85% времени
- Средняя оценка качества: 6.4/10 (диапазон 1–8)
- Созданы инструменты просмотра: `src/viewer.py` (CLI) и `src/report_generator.py` (HTML)
- Отчёт по производительности: `data/performance-report-2026-03-12.md`

### 2026-03-12 — Модуль коррекции транскриптов

- Создан `src/text_corrector.py`: двухуровневая коррекция (общий слой + YAML-профиль клиента)
- Общий слой: бренд «Гравител» (regex для 5+ вариантов искажений), телефонные термины (SIP, IP, ВАТС, АТС, IVR, CRM)
- Профиль клиента: `profiles/gravitel.yaml` — паттерны компании, доменные термины, llm_context
- Интеграция в пайплайн: шаг 4.5 между сборкой диалога и LLM-анализом
- CLI: `python -m src.pipeline <файл> --profile gravitel`
- 18 тестов (test_text_corrector.py), всего 34 теста в проекте — все проходят
- Проверено на сервере: «Гривитал» → «Гравител» в реальном транскрипте
# Архитектура

## Обзор

Тестовый стенд пост-обработки телефонных звонков: транскрибация двухканального аудио (русский язык) + интеллектуальный анализ (суммаризация, оценка качества, извлечение данных). Веб-интерфейс для просмотра результатов с аудиоплеером и синхронизацией транскрипта.

## Контекст

- **Для кого:** клиенты Гравител — компании с виртуальной АТС. Каждая компания = домен.
- **Сервер:** Ubuntu 24.04, RTX 5060 Ti 16GB, i5-12400, 64GB RAM.
- **Стек:** GigaAM-v3 (ASR, WER 8.4%) + Qwen3-8B (LLM через Ollama) + FastAPI + SQLite.
- **Режим работы:** пост-обработка завершённых звонков (webhook + polling).

## Ключевые компоненты

### Обработка аудио

| Модуль | Назначение |
|--------|-----------|
| `src/audio_splitter.py` | Разделение стерео на моно через ffmpeg (`pan` filter) |
| `src/transcriber.py` | Транскрибация через GigaAM-v3 (longform, pyannote VAD) |

### Сборка диалога

| Модуль | Назначение |
|--------|-----------|
| `src/dialogue_builder.py` | Хронологическое слияние двух каналов в `list[DialogueTurn]` |
| `src/text_corrector.py` | Двухуровневая коррекция: L1 общие термины + L2 профиль клиента (YAML) |

### Интеллектуальный анализ

| Модуль | Назначение |
|--------|-----------|
| `src/llm_analyzer.py` | HTTP-клиент к Ollama (Qwen3-8B) + OpenRouter (MiMo-V2-Pro). `call_llm()` / `call_cloud_llm()` |
| `src/pipeline.py` | Оркестратор: split → transcribe → dialogue → correct → metrics → LLM × 4 |

Четыре LLM-вызова (промпты в `prompts/`):
- `summarize.md` → тип, тема, исход, ключевые моменты, действия
- `quality_score.md` → оценка 1–10, критерии, IVR-детекция, script_checklist
- `extract_data.md` → имена, отдел, договор, телефон, договорённости
- `classify.md` → category, subcategory, client_intent, sentiment, resolution_status, tags

### Аналитика

| Модуль | Назначение |
|--------|-----------|
| `src/analytics/conversation_metrics.py` | Talk/silence/interruptions из таймкодов (без LLM) |
| `src/analytics/client_profiles.py` | Профили клиентов, risk_level, sentiment_trend |
| `src/analytics/search.py` | FTS5 полнотекстовый поиск по транскриптам |
| `src/analytics/knowledge.py` | Batch-агрегация базы знаний (проблемы → решения) |
| `src/web/routes/dashboard.py` | API дашбордов: KPIs, категории, тренды, операторы, KB, сценарии, поиск |

### Веб-интерфейс

| Модуль | Назначение |
|--------|-----------|
| `src/web/app.py` | FastAPI: lifespan, Basic Auth middleware, шаблоны, фоновый scheduler |
| `src/web/routes/api.py` | REST API: список звонков (фильтры, сортировка, пагинация), детали, аудио |
| `src/web/routes/webhook.py` | Приём webhook от Гравител АТС |
| `src/web/routes/dashboard.py` | API + HTML-страницы дашбордов (business, supervisor) |
| `src/web/static/app.js` | Клиентский JS: таблица, фильтры, аудиоплеер с синхронизацией транскрипта |
| `src/web/static/style.css` | Стили |

### Инфраструктура

| Модуль | Назначение |
|--------|-----------|
| `src/config.py` | Пути, имена моделей, URL Ollama, пороги VAD |
| `src/db.py` | SQLite: таблицы calls, processing, operators, departments, domains |
| `src/domain_config.py` | Загрузка `config/domains.yaml` (домены, фильтры, polling) |
| `src/call_filter.py` | Валидация звонков по фильтрам домена (длительность, тип, наличие записи) |
| `src/gravitel_api.py` | Async HTTP-клиент к Gravitel CRM API (история, запись, справочники) |
| `src/worker.py` | Фоновый обработчик: скачивание, pipeline, retry |
| `src/metrics.py` | Prometheus-метрики (токены, RTF, статусы) |

### Вспомогательные

| Модуль | Назначение |
|--------|-----------|
| `src/viewer.py` | CLI-просмотрщик результатов |
| `src/report_generator.py` | Генерация HTML-отчётов |

## Потоки данных

```
Gravitel АТС
    │
    ├─ Webhook (realtime) ──→ routes/webhook.py ──→ insert_call (db.py)
    │                                                     │
    └─ Polling (каждые 10 мин) → gravitel_api.py ────→ insert_call (db.py)
                                                          │
                                                    call_filter.py
                                                          │
                                              ┌─── pending ───┐
                                              │                │
                                        worker.py         (skipped)
                                              │
                                    download recording
                                              │
                                    audio_splitter.py
                                     (stereo → 2× mono)
                                              │
                                    transcriber.py (GigaAM-v3)
                                     (оператор + клиент)
                                              │
                                    dialogue_builder.py
                                     (хронологическое слияние)
                                              │
                                    text_corrector.py
                                     (L1 общий + L2 профиль)
                                              │
                                    llm_analyzer.py (Qwen3-8B × 3)
                                     ├─ summarize
                                     ├─ quality_score
                                     └─ extract_data
                                              │
                                    result.json + DB update
                                              │
                                    Web UI (FastAPI)
                                     ├─ Список звонков (фильтры, сортировка)
                                     ├─ Детали + аудиоплеер
                                     └─ Синхронизированный транскрипт
```

## Технологии и зависимости

| Компонент | Технология | Версия/Детали |
|-----------|-----------|---------------|
| ASR | GigaAM-v3 | `gigaam[longform]`, pyannote VAD, HF_TOKEN |
| LLM | Qwen3-8B | Ollama, 32k контекст, JSON mode |
| Web | FastAPI + Uvicorn | Jinja2-шаблоны, Basic Auth |
| БД | SQLite | `sqlite3`, `json_extract` для фильтрации |
| HTTP | httpx (async) | Gravitel API |
| Аудио | ffmpeg | `pan` filter (совместимость с ffmpeg 8.x) |
| Метрики | prometheus_client | node_exporter, nvidia_gpu_exporter |
| GPU | RTX 5060 Ti 16GB | CUDA 13.1, PyTorch nightly (sm_120) |

## Структура данных

```
data/
├── audio/{domain}/{call_id}.mp3     — скачанные записи
├── transcripts/{call_id}.txt        — текстовые транскрипты
├── results/{domain}/{call_id}.json  — JSON-результаты анализа
└── calls.db                         — SQLite (звонки, статусы, справочники)

config/
└── domains.yaml                     — конфигурация доменов

profiles/
└── gravitel.yaml                    — профиль коррекции (бренд, термины)

prompts/
├── summarize.md
├── quality_score.md
└── extract_data.md
```

## Нефункциональные требования и ограничения

- **VRAM:** GigaAM 1.4 GB + Ollama 6.1 GB = 7.5 GB из 16 GB (запас 8.3 GB)
- **Производительность LLM:** 74–77 tok/sec на GPU, суммаризация ~12 сек
- **Масштабирование:** `ThreadPoolExecutor(max_workers=1)` — последовательная обработка
- **Keep-alive:** Ollama keep_alive=30m (предотвращает выгрузку модели между звонками)
- **Retry:** до 3 попыток при ошибках, stale detector сбрасывает зависшие >15 мин
- **Авторизация:** HTTP Basic Auth (env: `WEB_USERNAME`, `WEB_PASSWORD`)

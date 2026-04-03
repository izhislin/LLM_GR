# Дизайн: Аналитическая платформа речевой аналитики

**Дата:** 2026-04-03
**Статус:** Черновик

## Цель

Превратить существующий pipeline транскрибации и LLM-обработки звонков в аналитическую платформу, которая:
- Извлекает нормализованные бизнес-инсайты из звонков (категории, интенты, sentiment, resolution)
- Связывает звонки одного клиента в цепочки, выявляет повторные обращения и риски оттока
- Накапливает базу знаний «проблема -> решение» для операторов и голосовых роботов
- Визуализирует аналитику в дашбордах для руководителя и супервизора

## Контекст

- **Проект:** `01_LLM_GR` — тестовый стенд транскрибации и LLM-обработки телефонных звонков
- **Текущее состояние:** 3441 звонков, 1702 обработаны, 1 домен (Гравител), 19 операторов
- **Стек:** GigaAM-v3 (ASR) + Qwen3-8B (LLM через Ollama, realtime) + MiMo-V2-Pro (через OpenRouter, batch) + FastAPI + SQLite
- **Сервер:** RTX 5060 Ti 16GB, i5-12400, 64GB RAM, Ubuntu 24.04
- **Связанный проект:** `01_Gravitel-GENERAL_GPT_1-0` (стратегия Гравител, голосовые роботы) — база знаний станет источником сценариев для роботов

## Решения и ограничения

- **Фокус MVP:** бизнес-инсайты из звонков (контроль качества — второй слой)
- **Аудитория:** супервизор + руководитель (операторы — в будущем)
- **Данные:** то, что есть + справочники ВАТС (отделы, сотрудники)
- **Доставка:** дашборд в Web UI; позже — отчёты и алерты в мессенджеры
- **Домен MVP:** Гравител (собственные записи)
- **Архитектура:** модуль `src/analytics/` внутри текущего проекта (вариант B — изоляция без разделения)

## 0. Гибридный LLM-подход

Два LLM-провайдера для разных задач:

| Задача | Провайдер | Модель | Почему |
|--------|-----------|--------|--------|
| Realtime pipeline (каждый звонок): суммаризация, оценка, извлечение, классификация | Ollama (локальный) | Qwen3-8B | Бесплатно, приватно, ~12 сек/звонок, GPU |
| Batch-аналитика (раз в сутки): генерация scenarios, обобщение трендов, скрипты для роботов | OpenRouter (облачный) | Xiaomi MiMo-V2-Pro | 1M контекст, ~1.6 сек, $1/$3 за 1M токенов |

Реализация:
- `call_llm()` — существующая функция для Ollama (Realtime)
- `call_cloud_llm()` — новая функция для OpenRouter (Batch)
- Конфигурация: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` в `.env`
- Batch-модуль `knowledge.py` использует `call_cloud_llm()` для генерации scenarios

## 1. Расширенное извлечение данных

### 1.1 Новый LLM-вызов: классификация и нормализация

4-й вызов LLM (промпт `prompts/classify.md`), добавляется в pipeline после `extract_data`:

| Поле | Тип | Описание |
|------|-----|----------|
| `category` | enum | Нормализованная категория: `техподдержка/связь`, `финансы/баланс`, `документы/договор`, `настройка/конфигурация`, `информация/консультация`, `жалоба`, `другое` |
| `subcategory` | string | Подкатегория (свободная, LLM подбирает из предложенных) |
| `client_intent` | enum | Интент клиента: `get_info`, `report_problem`, `request_action`, `cancel`, `complaint`, `payment`, `callback_request`, `other` |
| `sentiment` | enum | `positive` / `neutral` / `negative` |
| `resolution_status` | enum | `resolved` / `pending` / `escalated` / `unresolved` |
| `is_repeat_contact` | bool | Клиент упоминает предыдущие обращения |
| `tags` | string[] | Свободные тэги: `VIP`, `угроза_ухода`, `благодарность`, `сложный_вопрос` |

### 1.2 Conversation metrics (без LLM)

Вычисляются из `transcript_segments` чистым Python (в `src/analytics/conversation_metrics.py`):

| Метрика | Тип | Описание |
|---------|-----|----------|
| `operator_talk_sec` | float | Суммарное время речи оператора |
| `client_talk_sec` | float | Суммарное время речи клиента |
| `silence_sec` | float | Суммарные паузы > 2 сек |
| `longest_silence_sec` | float | Самая длинная пауза |
| `interruptions_count` | int | Пересечения сегментов разных спикеров |
| `operator_talk_ratio` | float | Доля оператора (0.0-1.0) |
| `avg_operator_turn_sec` | float | Средняя длина реплики оператора |
| `avg_client_turn_sec` | float | Средняя длина реплики клиента |
| `total_turns` | int | Общее количество реплик |

Сохраняется в `result_json.conversation_metrics`.

### 1.3 Чеклист скрипта

Расширение промпта `quality_score.md` — новая секция `script_checklist`:

```json
{
  "greeted_with_name": true,
  "greeted_with_company": true,
  "identified_client": false,
  "clarified_issue": true,
  "offered_solution": true,
  "summarized_outcome": true,
  "said_goodbye": true
}
```

Boolean-поля для агрегации: «% звонков где оператор не представился».

## 2. Связывание звонков и клиентские цепочки

### 2.1 Таблица `client_profiles`

```sql
CREATE TABLE IF NOT EXISTS client_profiles (
    client_number    TEXT PRIMARY KEY,
    domain           TEXT NOT NULL,
    first_seen       TEXT,
    last_seen        TEXT,
    total_calls      INTEGER DEFAULT 0,
    calls_with_issues INTEGER DEFAULT 0,
    primary_category TEXT,
    sentiment_trend  TEXT,       -- improving / stable / declining
    risk_level       TEXT,       -- low / medium / high
    extracted_name   TEXT,
    extracted_contract TEXT,
    updated_at       TEXT NOT NULL
);
```

### 2.2 Логика цепочек

- При обработке звонка — проверить другие звонки от `client_number` за последние 7 дней
- Тот же `client_number` + та же `category` в пределах 7 дней = повторное обращение
- `risk_level` повышается при: повторных обращениях, `sentiment=negative`, тэге `угроза_ухода`

### 2.3 Обновление профилей

Два режима обновления:
- **При обработке звонка (realtime):** инкрементальное обновление `total_calls`, `last_seen`, `extracted_name/contract` (если извлечены). Быстрая проверка на повторное обращение (тот же client_number + category за 7 дней).
- **Ежедневный batch:** полный пересчёт `primary_category`, `sentiment_trend` (по последним 10 звонкам), `risk_level`, `calls_with_issues`.

## 3. База знаний

### 3.1 Уровень 1: Агрегированная статистика

```sql
CREATE TABLE IF NOT EXISTS knowledge_base (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    domain              TEXT NOT NULL,
    category            TEXT NOT NULL,
    subcategory         TEXT,
    problem_description TEXT NOT NULL,
    solution_description TEXT,
    frequency           INTEGER DEFAULT 1,
    success_rate        REAL,
    example_call_ids    TEXT,       -- JSON array
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
```

### 3.2 Уровень 2: Эталонные сценарии

```sql
CREATE TABLE IF NOT EXISTS knowledge_scenarios (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    domain              TEXT NOT NULL,
    category            TEXT NOT NULL,
    scenario_name       TEXT NOT NULL,
    typical_questions   TEXT,       -- JSON array
    recommended_script  TEXT,
    diagnostic_steps    TEXT,       -- JSON array
    source_call_ids     TEXT,       -- JSON array
    success_rate        REAL,
    auto_generated      BOOLEAN DEFAULT 1,
    approved            BOOLEAN DEFAULT 0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
```

### 3.3 Процесс наполнения (ежедневный batch)

1. Взять звонки за сутки со `status=done`
2. Сгруппировать по `category + subcategory`
3. Для каждой группы:
   - Есть запись в `knowledge_base` -> обновить `frequency`, добавить `call_ids`
   - Нет -> создать новую, LLM обобщает проблему и решение
4. Если `frequency > 10` и нет `scenario` -> LLM генерирует `knowledge_scenario` (`auto_generated=true`)

### 3.4 Выход на голосовых роботов

Таблица `knowledge_scenarios` с `approved=true`:
- `typical_questions` -> распознавание интента роботом
- `recommended_script` -> ответ робота
- `diagnostic_steps` -> дерево диалога
- Экспорт в формате, совместимом с проектом `01_Gravitel-GENERAL_GPT_1-0`

## 4. Полнотекстовый поиск

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS calls_fts USING fts5(
    call_id UNINDEXED,
    transcript,
    topic,
    issues
);
```

- Индексация при завершении обработки звонка
- В Web UI — строка поиска на странице списка звонков
- Поддержка фразового поиска: `"SIP-транк"`, `"обещанный платёж"`

## 5. Дашборды

### 5.1 Дашборд руководителя («Обзор бизнеса»)

**KPI-карточки (верхняя панель):**

| Карточка | Значение | Тренд |
|----------|----------|-------|
| Всего звонков | число за период | vs предыдущий период |
| Пропущенные | число + % | vs предыдущий период |
| Среднее качество | балл | vs предыдущий период |
| Повторные обращения | % | ниже = лучше |
| Клиенты в зоне риска | число | vs предыдущий период |

**Блоки:**

1. **Топ проблем** — bar chart по нормализованным категориям + subcategory, кликабельно -> фильтрация
2. **Тренд обращений по категориям** — line chart по неделям, выявление всплесков
3. **Распределение sentiment** — donut chart + тренд по неделям
4. **Resolution rate** — % решённых с первого звонка, по категориям
5. **Горячий список клиентов** — таблица: имя, номер, обращения, последняя проблема, risk_level

### 5.2 Дашборд супервизора («Контроль операторов»)

**Блоки:**

1. **Рейтинг операторов** — таблица: имя, средний балл, количество звонков, breakdown по 5 критериям
2. **Проблемные звонки** — фильтр: оценка < 5, sentiment=negative, тэг `жалоба`
3. **Нагрузка по операторам** — bar chart: количество + средняя длительность
4. **Тренд качества** — line chart по неделям, общий и per-operator
5. **Talk ratio по операторам** — соотношение речи оператора/клиента (из conversation_metrics)
6. **Чеклист скрипта** — heatmap: % выполнения каждого пункта по операторам

### 5.3 Общие элементы

- Фильтр периода (пресеты: сегодня / неделя / месяц / произвольный)
- Фронтенд: vanilla JS + Chart.js (сохраняем текущий подход без фреймворков)
- Экспорт: кнопка «Скачать отчёт» (HTML)

## 6. Структура кода

```
src/
  analytics/                         # НОВЫЙ пакет
    __init__.py
    classification.py                # 4-й LLM-вызов (classify промпт)
    conversation_metrics.py          # talk/silence/interruptions из segments
    client_profiles.py               # профили клиентов, risk_level
    knowledge.py                     # KB batch-агрегатор
    search.py                        # FTS5 индексация и поиск
  web/
    routes/
      dashboard.py                   # НОВЫЙ роутер для дашбордов
    static/
      dashboard.js                   # НОВЫЙ — графики, виджеты
    templates/
      dashboard_business.html        # шаблон дашборда руководителя
      dashboard_supervisor.html      # шаблон дашборда супервизора

prompts/
  classify.md                        # НОВЫЙ промпт классификации
  quality_score.md                   # РАСШИРЕН секцией script_checklist
```

Существующие модули (`pipeline.py`, `db.py`, `worker.py`) расширяются минимально:
- `pipeline.py` — добавить вызов `conversation_metrics` и `classification` в цепочку
- `db.py` — добавить DDL новых таблиц и функции для `client_profiles`, `knowledge_base`, `knowledge_scenarios`, `calls_fts`
- `worker.py` — вызвать FTS-индексацию после обработки

## 7. Итоговый pipeline

```
Аудиофайл (stereo)
  -> ffmpeg: split на 2 канала
  -> GigaAM-v3: транскрипция + segments с таймкодами
  -> dialogue_builder: хронологический диалог
  -> text_corrector: L1 общий + L2 профиль
  -> conversation_metrics: talk/silence/interruptions     [НОВОЕ]
  -> LLM вызов 1: summarize (тип, тема, исход, actions)
  -> LLM вызов 2: quality_score + script_checklist        [РАСШИРЕН]
  -> LLM вызов 3: extract_data (имена, договор, проблемы)
  -> LLM вызов 4: classify (category, intent, sentiment)  [НОВОЕ]
  -> result.json + DB + FTS5 index

Ежедневный batch:
  -> knowledge_base: агрегация проблем и решений
  -> knowledge_scenarios: генерация эталонных сценариев
  -> client_profiles: обновление профилей и risk_level
```

## 8. Что НЕ входит в MVP

- PII/PCI маскирование (для внутреннего использования избыточно)
- CSAT/NPS опросы (требуют внешней интеграции)
- Multi-tenant архитектура (пока один домен)
- AI Act / GDPR compliance (актуально при выходе на ЕС)
- Интерфейс для операторов (добавить позже)
- Алерты в мессенджеры (следующая итерация после дашбордов)
- Периодические отчёты PDF/HTML (следующая итерация)
- Векторный поиск / embeddings (FTS5 достаточно для MVP)
- Интеграция с CRM клиента

## 9. Обработка существующих данных

1702 уже обработанных звонка не содержат новых полей (`classification`, `conversation_metrics`, `script_checklist`). Варианты:

- **Ретроспективная обработка**: прогнать 1702 звонка через новые этапы (classification + metrics). Для conversation_metrics нужны `transcript_segments` — они есть только у звонков, обработанных после 2026-03-18. Для classification — нужен только транскрипт (есть у всех).
- **Оценка нагрузки**: 1702 LLM-вызова classify x ~12 сек = ~5.7 часов на GPU. Conversation metrics — мгновенно.

# Call Analytics Platform — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить аналитический слой поверх pipeline транскрибации: нормализованную классификацию звонков, conversation metrics, клиентские профили, базу знаний и два дашборда (руководитель + супервизор).

**Architecture:** Новый пакет `src/analytics/` с изолированными модулями. Pipeline расширяется двумя этапами: conversation_metrics (чистый Python) и classification (4-й LLM-вызов). Дашборды — новые FastAPI-роуты + vanilla JS с Chart.js. Все данные в существующей SQLite БД.

**Tech Stack:** Python 3.12, FastAPI, SQLite (FTS5), Chart.js, Ollama/Qwen3-8B, pytest.

**Spec:** `docs/superpowers/specs/2026-04-03-call-analytics-platform-design.md`

---

## Фаза 1: Conversation Metrics (чистый Python, без LLM)

### Task 1: Модуль conversation_metrics

**Files:**
- Create: `src/analytics/__init__.py`
- Create: `src/analytics/conversation_metrics.py`
- Create: `tests/test_analytics/__init__.py`
- Create: `tests/test_analytics/test_conversation_metrics.py`

- [ ] **Step 1: Создать пакет `src/analytics/`**

```python
# src/analytics/__init__.py
"""Аналитический слой: метрики, классификация, профили клиентов, база знаний."""
```

```python
# tests/test_analytics/__init__.py
```

- [ ] **Step 2: Написать тесты для compute_metrics**

```python
# tests/test_analytics/test_conversation_metrics.py
"""Тесты для conversation_metrics — вычисление метрик из transcript_segments."""

import pytest
from src.analytics.conversation_metrics import compute_metrics


@pytest.fixture
def simple_segments():
    """Простой диалог: оператор и клиент по очереди."""
    return [
        {"speaker": "Оператор", "text": "Здравствуйте", "start": 0.0, "end": 3.0},
        {"speaker": "Клиент", "text": "Добрый день", "start": 3.5, "end": 5.0},
        {"speaker": "Оператор", "text": "Чем могу помочь?", "start": 5.5, "end": 8.0},
        {"speaker": "Клиент", "text": "У меня вопрос по тарифу", "start": 8.0, "end": 12.0},
    ]


@pytest.fixture
def segments_with_interruption():
    """Диалог с перебиванием (overlap сегментов)."""
    return [
        {"speaker": "Оператор", "text": "Давайте проверим", "start": 0.0, "end": 5.0},
        {"speaker": "Клиент", "text": "Я уже проверял", "start": 4.0, "end": 7.0},
        {"speaker": "Оператор", "text": "Понял", "start": 7.5, "end": 9.0},
    ]


@pytest.fixture
def segments_with_long_silence():
    """Диалог с длинной паузой (> 2 сек между сегментами)."""
    return [
        {"speaker": "Оператор", "text": "Секунду, проверю", "start": 0.0, "end": 3.0},
        {"speaker": "Оператор", "text": "Нашёл", "start": 15.0, "end": 17.0},
    ]


def test_basic_talk_times(simple_segments):
    """operator_talk_sec и client_talk_sec считаются из длительности сегментов."""
    m = compute_metrics(simple_segments)
    assert m["operator_talk_sec"] == pytest.approx(5.5, abs=0.1)  # 3.0 + 2.5
    assert m["client_talk_sec"] == pytest.approx(5.5, abs=0.1)  # 1.5 + 4.0


def test_talk_ratio(simple_segments):
    """operator_talk_ratio — доля оператора от общего talk time."""
    m = compute_metrics(simple_segments)
    assert m["operator_talk_ratio"] == pytest.approx(0.5, abs=0.05)


def test_total_turns(simple_segments):
    m = compute_metrics(simple_segments)
    assert m["total_turns"] == 4


def test_interruptions(segments_with_interruption):
    """Пересечение сегментов разных спикеров = перебивание."""
    m = compute_metrics(segments_with_interruption)
    assert m["interruptions_count"] == 1


def test_silence(segments_with_long_silence):
    """Паузы > 2 сек считаются как silence."""
    m = compute_metrics(segments_with_long_silence)
    assert m["silence_sec"] == pytest.approx(12.0, abs=0.1)
    assert m["longest_silence_sec"] == pytest.approx(12.0, abs=0.1)


def test_empty_segments():
    """Пустой список сегментов — все метрики нулевые."""
    m = compute_metrics([])
    assert m["operator_talk_sec"] == 0.0
    assert m["client_talk_sec"] == 0.0
    assert m["total_turns"] == 0
    assert m["interruptions_count"] == 0


def test_avg_turn_duration(simple_segments):
    """Средняя длина реплики оператора и клиента."""
    m = compute_metrics(simple_segments)
    assert m["avg_operator_turn_sec"] == pytest.approx(2.75, abs=0.1)  # 5.5 / 2
    assert m["avg_client_turn_sec"] == pytest.approx(2.75, abs=0.1)  # 5.5 / 2
```

- [ ] **Step 3: Запустить тесты, убедиться что они падают**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest tests/test_analytics/test_conversation_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.analytics.conversation_metrics'`

- [ ] **Step 4: Реализовать compute_metrics**

```python
# src/analytics/conversation_metrics.py
"""Вычисление conversation metrics из transcript_segments.

Метрики извлекаются из таймкодов сегментов (чистая арифметика, без LLM).
"""

from __future__ import annotations

SILENCE_THRESHOLD_SEC = 2.0
OPERATOR_SPEAKERS = {"Оператор", "operator"}


def compute_metrics(segments: list[dict]) -> dict:
    """Вычислить метрики разговора из списка сегментов.

    Args:
        segments: список dict с ключами speaker, text, start, end.

    Returns:
        dict с метриками (operator_talk_sec, client_talk_sec, silence_sec,
        longest_silence_sec, interruptions_count, operator_talk_ratio,
        avg_operator_turn_sec, avg_client_turn_sec, total_turns).
    """
    if not segments:
        return {
            "operator_talk_sec": 0.0,
            "client_talk_sec": 0.0,
            "silence_sec": 0.0,
            "longest_silence_sec": 0.0,
            "interruptions_count": 0,
            "operator_talk_ratio": 0.0,
            "avg_operator_turn_sec": 0.0,
            "avg_client_turn_sec": 0.0,
            "total_turns": 0,
        }

    operator_talk = 0.0
    client_talk = 0.0
    operator_turns = 0
    client_turns = 0

    for seg in segments:
        duration = max(0.0, seg["end"] - seg["start"])
        if seg["speaker"] in OPERATOR_SPEAKERS:
            operator_talk += duration
            operator_turns += 1
        else:
            client_talk += duration
            client_turns += 1

    # Silence: gaps > SILENCE_THRESHOLD between consecutive segments
    sorted_segs = sorted(segments, key=lambda s: s["start"])
    silence_sec = 0.0
    longest_silence = 0.0
    for i in range(1, len(sorted_segs)):
        gap = sorted_segs[i]["start"] - sorted_segs[i - 1]["end"]
        if gap > SILENCE_THRESHOLD_SEC:
            silence_sec += gap
            longest_silence = max(longest_silence, gap)

    # Interruptions: overlapping segments from different speakers
    interruptions = 0
    for i in range(1, len(sorted_segs)):
        prev = sorted_segs[i - 1]
        curr = sorted_segs[i]
        if curr["start"] < prev["end"] and curr["speaker"] != prev["speaker"]:
            interruptions += 1

    total_talk = operator_talk + client_talk
    total_turns = operator_turns + client_turns

    return {
        "operator_talk_sec": round(operator_talk, 2),
        "client_talk_sec": round(client_talk, 2),
        "silence_sec": round(silence_sec, 2),
        "longest_silence_sec": round(longest_silence, 2),
        "interruptions_count": interruptions,
        "operator_talk_ratio": round(operator_talk / total_talk, 3) if total_talk > 0 else 0.0,
        "avg_operator_turn_sec": round(operator_talk / operator_turns, 2) if operator_turns > 0 else 0.0,
        "avg_client_turn_sec": round(client_talk / client_turns, 2) if client_turns > 0 else 0.0,
        "total_turns": total_turns,
    }
```

- [ ] **Step 5: Запустить тесты, убедиться что проходят**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest tests/test_analytics/test_conversation_metrics.py -v`
Expected: 8 passed

- [ ] **Step 6: Коммит**

```bash
git add src/analytics/__init__.py src/analytics/conversation_metrics.py tests/test_analytics/__init__.py tests/test_analytics/test_conversation_metrics.py
git commit -m "feat(analytics): add conversation_metrics module — talk/silence/interruptions from segments"
```

---

### Task 2: Интеграция conversation_metrics в pipeline

**Files:**
- Modify: `src/pipeline.py:86-118`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Написать тест для наличия conversation_metrics в результате pipeline**

Добавить в `tests/test_pipeline.py`:

```python
def test_pipeline_includes_conversation_metrics(mock_result):
    """Результат pipeline должен содержать conversation_metrics."""
    # mock_result — результат process_audio_file с замоканными зависимостями
    assert "conversation_metrics" in mock_result
    cm = mock_result["conversation_metrics"]
    assert "operator_talk_sec" in cm
    assert "client_talk_sec" in cm
    assert "interruptions_count" in cm
    assert "total_turns" in cm
```

Примечание: нужно адаптировать к существующим фикстурам и мокам в `test_pipeline.py`.

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest tests/test_pipeline.py -v -k conversation_metrics`
Expected: FAIL — `KeyError: 'conversation_metrics'`

- [ ] **Step 3: Добавить вызов compute_metrics в pipeline.py**

В `src/pipeline.py` после строки 89 (`transcript_segments = [...]`) добавить:

```python
from src.analytics.conversation_metrics import compute_metrics
```

(в начало файла, к импортам)

И после построения `transcript_segments` (строка ~89), перед `# Сохраняем транскрипт`:

```python
    # 4.6. Conversation metrics (из таймкодов, без LLM)
    conversation_metrics = compute_metrics(transcript_segments)
```

В сборку результата (строка ~111, `result = {`), добавить:

```python
        "conversation_metrics": conversation_metrics,
```

- [ ] **Step 4: Запустить тесты**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest tests/test_pipeline.py -v`
Expected: all passed

- [ ] **Step 5: Запустить все тесты для регрессии**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest --ignore=tests/test_transcriber.py -v`
Expected: all passed (test_transcriber пропускаем — требует GPU)

- [ ] **Step 6: Коммит**

```bash
git add src/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): integrate conversation_metrics into processing pipeline"
```

---

## Фаза 2: Классификация звонков (4-й LLM-вызов)

### Task 3: Промпт классификации

**Files:**
- Create: `prompts/classify.md`

- [ ] **Step 1: Создать промпт classify.md**

```markdown
Ты — аналитик данных. Классифицируй телефонный разговор по транскрипту.

Верни JSON со следующей структурой:

{
  "category": "<категория>",
  "subcategory": "<подкатегория>",
  "client_intent": "<интент клиента>",
  "sentiment": "<настроение клиента>",
  "resolution_status": "<статус решения>",
  "is_repeat_contact": <true/false>,
  "tags": ["<тэг1>", "<тэг2>"]
}

Категории (выбери одну):
- "техподдержка/связь" — проблемы со связью, настройкой, подключением, оборудованием
- "финансы/баланс" — оплата, баланс, тарифы, счета, обещанный платёж
- "документы/договор" — договоры, документы, верификация, персональные данные
- "настройка/конфигурация" — настройка сервисов, переадресация, IVR, номера
- "информация/консультация" — общие вопросы, консультация, информирование
- "жалоба" — жалоба на качество обслуживания или сервис
- "другое" — не подходит ни одна из категорий

Подкатегории (выбери подходящую или укажи свою, кратко):
- Для "техподдержка/связь": "нет связи", "не работают исходящие", "не работают входящие", "проблема с переадресацией", "настройка оборудования", "проблема с софтфоном"
- Для "финансы/баланс": "отрицательный баланс", "обещанный платёж", "смена тарифа", "вопрос по счёту"
- Для "документы/договор": "проверка документов", "заключение договора", "изменение данных"
- Для "настройка/конфигурация": "переадресация", "IVR-меню", "добавление номера", "SIP-транк"

Интент клиента (client_intent, выбери один):
- "get_info" — узнать информацию, статус, баланс
- "report_problem" — сообщить о проблеме / неисправности
- "request_action" — попросить выполнить действие (подключить, настроить)
- "cancel" — отменить услугу / расторгнуть договор
- "complaint" — жалоба на качество / сервис
- "payment" — вопрос по оплате / баланс / обещанный платёж
- "callback_request" — просьба перезвонить
- "other" — не классифицируется

Sentiment (настроение клиента по итогу звонка):
- "positive" — клиент доволен, благодарит
- "neutral" — нейтральное общение
- "negative" — клиент раздражён, недоволен

Resolution status (решена ли проблема):
- "resolved" — проблема решена в ходе звонка
- "pending" — нужны дополнительные действия (проверка, обратный звонок)
- "escalated" — вопрос передан другому специалисту/отделу
- "unresolved" — проблема не решена, нет плана действий

is_repeat_contact: true если клиент упоминает предыдущие обращения ("я уже звонил", "опять не работает", "в прошлый раз").

Tags (массив, от 0 до 3 тэгов из списка):
- "VIP" — клиент обозначен как важный, крупный
- "угроза_ухода" — клиент грозит уйти к конкуренту, расторгнуть договор
- "благодарность" — клиент выражает благодарность
- "сложный_вопрос" — нетиповой вопрос, требующий экспертизы

Правила:
- Определяй категорию по основной теме разговора
- Если подходят несколько категорий, выбери основную
- Пиши на русском языке
- Верни ТОЛЬКО валидный JSON, без пояснений
```

- [ ] **Step 2: Коммит**

```bash
git add prompts/classify.md
git commit -m "feat(prompts): add classify.md — call classification prompt"
```

---

### Task 4: Расширение quality_score.md — script_checklist

**Files:**
- Modify: `prompts/quality_score.md`

- [ ] **Step 1: Добавить секцию script_checklist в промпт**

В конец `prompts/quality_score.md`, перед строкой `- Верни ТОЛЬКО валидный JSON`, добавить:

```markdown
Дополнительно добавь секцию "script_checklist" — чеклист соблюдения скрипта:

{
  ...существующие поля...,
  "script_checklist": {
    "greeted_with_name": <true если оператор представился по имени>,
    "greeted_with_company": <true если оператор назвал компанию или отдел>,
    "identified_client": <true если оператор уточнил имя или данные клиента>,
    "clarified_issue": <true если оператор уточнил суть обращения>,
    "offered_solution": <true если оператор предложил решение или следующие шаги>,
    "summarized_outcome": <true если оператор подвёл итог разговора>,
    "said_goodbye": <true если оператор попрощался>
  }
}
```

- [ ] **Step 2: Коммит**

```bash
git add prompts/quality_score.md
git commit -m "feat(prompts): add script_checklist to quality_score prompt"
```

---

### Task 5: Добавить classify в llm_analyzer

**Files:**
- Modify: `src/llm_analyzer.py:119-169`
- Modify: `tests/test_llm_analyzer.py`

- [ ] **Step 1: Написать тест для classify вызова в analyze_dialogue**

Добавить в `tests/test_llm_analyzer.py`:

```python
@patch("src.llm_analyzer.requests.post")
def test_analyze_dialogue_includes_classification(mock_post, sample_dialogue_text, tmp_path):
    """analyze_dialogue должен включать classification в результат."""
    # Подготовить промпт-файлы
    for name in ("summarize.md", "quality_score.md", "extract_data.md", "classify.md"):
        (tmp_path / name).write_text(f"Промпт {name}", encoding="utf-8")

    # Мок ответов для 4 вызовов
    def make_response(content_dict):
        resp = MagicMock()
        resp.json.return_value = {"message": {"content": json.dumps(content_dict, ensure_ascii=False)}}
        resp.raise_for_status = MagicMock()
        return resp

    mock_post.side_effect = [
        make_response({"call_type": "входящий", "topic": "тариф", "outcome": "консультация", "key_points": [], "action_items": []}),
        make_response({"total": 7, "is_ivr": False, "criteria": {}, "script_checklist": {"greeted_with_name": True, "greeted_with_company": True, "identified_client": False, "clarified_issue": True, "offered_solution": True, "summarized_outcome": True, "said_goodbye": True}}),
        make_response({"operator_name": "Наталья", "client_name": None, "department": None, "contract_number": None, "phone_number": None, "agreements": [], "issues": [], "callback_needed": False, "next_steps": []}),
        make_response({"category": "информация/консультация", "subcategory": "вопрос по тарифу", "client_intent": "get_info", "sentiment": "neutral", "resolution_status": "resolved", "is_repeat_contact": False, "tags": []}),
    ]

    result = analyze_dialogue(sample_dialogue_text, tmp_path)

    assert "classification" in result
    assert result["classification"]["category"] == "информация/консультация"
    assert result["classification"]["client_intent"] == "get_info"
    assert mock_post.call_count == 4
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest tests/test_llm_analyzer.py -v -k classification`
Expected: FAIL — `KeyError: 'classification'`

- [ ] **Step 3: Добавить 4-й LLM-вызов в analyze_dialogue**

В `src/llm_analyzer.py`, функция `analyze_dialogue`, после блока извлечения данных (строка ~162) добавить:

```python
    logger.info("Классификация...")
    classify_prompt = load_prompt(prompts_dir / "classify.md")
    results["classification"] = call_llm(
        system_prompt=classify_prompt,
        user_message=user_message,
    )
```

- [ ] **Step 4: Запустить тесты**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest tests/test_llm_analyzer.py -v`
Expected: all passed

Примечание: существующие тесты, которые мокают 3 вызова `requests.post`, потребуют обновления — теперь `mock_post.side_effect` должен содержать 4 ответа вместо 3. Обновить все `test_analyze_dialogue*` тесты, добавив 4-й mock response.

- [ ] **Step 5: Обновить существующие тесты analyze_dialogue для 4 вызовов**

Найти все тесты, вызывающие `analyze_dialogue`, и добавить 4-й мок-ответ в `side_effect`. Шаблон 4-го ответа:

```python
make_response({"category": "другое", "subcategory": "", "client_intent": "other", "sentiment": "neutral", "resolution_status": "resolved", "is_repeat_contact": False, "tags": []})
```

- [ ] **Step 6: Запустить все тесты**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest --ignore=tests/test_transcriber.py -v`
Expected: all passed

- [ ] **Step 7: Коммит**

```bash
git add src/llm_analyzer.py tests/test_llm_analyzer.py
git commit -m "feat(llm): add 4th LLM call — classify (category, intent, sentiment, resolution)"
```

---

## Фаза 3: Схема БД — новые таблицы

### Task 6: Новые таблицы в db.py + FTS5

**Files:**
- Modify: `src/db.py:15-72`
- Create: `tests/test_analytics/test_db_analytics.py`

- [ ] **Step 1: Написать тесты для новых таблиц**

```python
# tests/test_analytics/test_db_analytics.py
"""Тесты для аналитических таблиц в db.py."""

import json
import pytest
from src.db import init_db


@pytest.fixture
def db(tmp_path):
    """Временная БД с полной схемой."""
    return init_db(str(tmp_path / "test.db"))


def test_client_profiles_table_exists(db):
    """Таблица client_profiles должна создаваться при init_db."""
    db.execute("SELECT * FROM client_profiles LIMIT 1")


def test_knowledge_base_table_exists(db):
    """Таблица knowledge_base должна создаваться при init_db."""
    db.execute("SELECT * FROM knowledge_base LIMIT 1")


def test_knowledge_scenarios_table_exists(db):
    """Таблица knowledge_scenarios должна создаваться при init_db."""
    db.execute("SELECT * FROM knowledge_scenarios LIMIT 1")


def test_calls_fts_table_exists(db):
    """Виртуальная FTS5-таблица calls_fts должна создаваться."""
    db.execute("SELECT * FROM calls_fts LIMIT 1")


def test_client_profiles_insert_and_select(db):
    """CRUD для client_profiles."""
    db.execute(
        """INSERT INTO client_profiles
           (client_number, domain, total_calls, updated_at)
           VALUES (?, ?, ?, ?)""",
        ("79001234567", "test.domain", 5, "2026-04-01T00:00:00Z"),
    )
    db.commit()
    row = db.execute(
        "SELECT * FROM client_profiles WHERE client_number = ?",
        ("79001234567",),
    ).fetchone()
    assert row["total_calls"] == 5
    assert row["domain"] == "test.domain"


def test_knowledge_base_insert(db):
    """Вставка в knowledge_base."""
    db.execute(
        """INSERT INTO knowledge_base
           (domain, category, problem_description, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        ("test.domain", "техподдержка/связь", "Не работают исходящие",
         "2026-04-01T00:00:00Z", "2026-04-01T00:00:00Z"),
    )
    db.commit()
    row = db.execute("SELECT * FROM knowledge_base WHERE id = 1").fetchone()
    assert row["category"] == "техподдержка/связь"
    assert row["frequency"] == 1


def test_fts5_search(db):
    """FTS5 поиск по транскрипту."""
    db.execute(
        "INSERT INTO calls_fts (call_id, transcript, topic, issues) VALUES (?, ?, ?, ?)",
        ("c1", "Здравствуйте, не работает SIP-транк", "SIP-транк", "не работает связь"),
    )
    db.commit()
    results = db.execute(
        "SELECT call_id FROM calls_fts WHERE calls_fts MATCH ?",
        ("SIP-транк",),
    ).fetchall()
    assert len(results) == 1
    assert results[0]["call_id"] == "c1"


def test_fts5_no_results(db):
    """FTS5 поиск — ничего не найдено."""
    db.execute(
        "INSERT INTO calls_fts (call_id, transcript, topic, issues) VALUES (?, ?, ?, ?)",
        ("c1", "Здравствуйте, вопрос по тарифу", "тариф", ""),
    )
    db.commit()
    results = db.execute(
        "SELECT call_id FROM calls_fts WHERE calls_fts MATCH ?",
        ("SIP-транк",),
    ).fetchall()
    assert len(results) == 0
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest tests/test_analytics/test_db_analytics.py -v`
Expected: FAIL — `OperationalError: no such table: client_profiles`

- [ ] **Step 3: Добавить DDL новых таблиц в _SCHEMA в db.py**

В `src/db.py`, добавить в строку `_SCHEMA` (после CREATE INDEX, перед `"""`):

```sql
CREATE TABLE IF NOT EXISTS client_profiles (
    client_number    TEXT PRIMARY KEY,
    domain           TEXT NOT NULL,
    first_seen       TEXT,
    last_seen        TEXT,
    total_calls      INTEGER DEFAULT 0,
    calls_with_issues INTEGER DEFAULT 0,
    primary_category TEXT,
    sentiment_trend  TEXT,
    risk_level       TEXT DEFAULT 'low',
    extracted_name   TEXT,
    extracted_contract TEXT,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_base (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    domain              TEXT NOT NULL,
    category            TEXT NOT NULL,
    subcategory         TEXT,
    problem_description TEXT NOT NULL,
    solution_description TEXT,
    frequency           INTEGER DEFAULT 1,
    success_rate        REAL,
    example_call_ids    TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_scenarios (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    domain              TEXT NOT NULL,
    category            TEXT NOT NULL,
    scenario_name       TEXT NOT NULL,
    typical_questions   TEXT,
    recommended_script  TEXT,
    diagnostic_steps    TEXT,
    source_call_ids     TEXT,
    success_rate        REAL,
    auto_generated      INTEGER DEFAULT 1,
    approved            INTEGER DEFAULT 0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS calls_fts USING fts5(
    call_id UNINDEXED,
    transcript,
    topic,
    issues
);

CREATE INDEX IF NOT EXISTS idx_client_profiles_domain ON client_profiles(domain);
CREATE INDEX IF NOT EXISTS idx_knowledge_base_category ON knowledge_base(domain, category);
```

- [ ] **Step 4: Запустить тесты**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest tests/test_analytics/test_db_analytics.py -v`
Expected: all passed

- [ ] **Step 5: Запустить все тесты для регрессии**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest --ignore=tests/test_transcriber.py -v`
Expected: all passed

- [ ] **Step 6: Коммит**

```bash
git add src/db.py tests/test_analytics/test_db_analytics.py
git commit -m "feat(db): add client_profiles, knowledge_base, knowledge_scenarios, calls_fts tables"
```

---

## Фаза 4: Аналитические модули

### Task 7: Модуль client_profiles

**Files:**
- Create: `src/analytics/client_profiles.py`
- Create: `tests/test_analytics/test_client_profiles.py`

- [ ] **Step 1: Написать тесты**

```python
# tests/test_analytics/test_client_profiles.py
"""Тесты для client_profiles — профили клиентов и risk scoring."""

import json
import pytest
from src.db import init_db
from src.analytics.client_profiles import update_profile_on_call, recalculate_profiles


@pytest.fixture
def db(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    # Вставить тестовые звонки
    for i, (direction, client, started) in enumerate([
        ("in", "79001234567", "2026-04-01T10:00:00Z"),
        ("in", "79001234567", "2026-04-02T10:00:00Z"),
        ("in", "79001234567", "2026-04-03T10:00:00Z"),
        ("in", "79009999999", "2026-04-01T10:00:00Z"),
    ]):
        call_id = f"c{i+1}"
        conn.execute(
            """INSERT INTO calls (id, domain, direction, client_number, started_at, source, received_at)
               VALUES (?, 'test.domain', ?, ?, ?, 'test', ?)""",
            (call_id, direction, client, started, started),
        )
        conn.execute(
            "INSERT INTO processing (call_id, status) VALUES (?, 'done')",
            (call_id,),
        )
    conn.commit()
    return conn


def _set_result(db, call_id, classification, extracted_data=None):
    """Хелпер — задать result_json для звонка."""
    result = {
        "classification": classification,
        "extracted_data": extracted_data or {},
    }
    db.execute(
        "UPDATE processing SET result_json = ? WHERE call_id = ?",
        (json.dumps(result, ensure_ascii=False), call_id),
    )
    db.commit()


def test_update_profile_creates_new(db):
    """При первом звонке клиента — создаётся профиль."""
    _set_result(db, "c1", {"category": "техподдержка/связь", "sentiment": "neutral", "resolution_status": "resolved", "is_repeat_contact": False, "tags": []})
    update_profile_on_call(db, "c1")
    row = db.execute("SELECT * FROM client_profiles WHERE client_number = '79001234567'").fetchone()
    assert row is not None
    assert row["total_calls"] == 1


def test_update_profile_increments(db):
    """При повторном звонке — total_calls инкрементируется."""
    _set_result(db, "c1", {"category": "техподдержка/связь", "sentiment": "neutral", "resolution_status": "resolved", "is_repeat_contact": False, "tags": []})
    _set_result(db, "c2", {"category": "техподдержка/связь", "sentiment": "negative", "resolution_status": "unresolved", "is_repeat_contact": True, "tags": ["угроза_ухода"]})
    update_profile_on_call(db, "c1")
    update_profile_on_call(db, "c2")
    row = db.execute("SELECT * FROM client_profiles WHERE client_number = '79001234567'").fetchone()
    assert row["total_calls"] == 2


def test_recalculate_sets_risk_level(db):
    """recalculate_profiles должен установить risk_level."""
    _set_result(db, "c1", {"category": "техподдержка/связь", "sentiment": "negative", "resolution_status": "unresolved", "is_repeat_contact": False, "tags": ["угроза_ухода"]}, {"issues": ["нет связи"]})
    _set_result(db, "c2", {"category": "техподдержка/связь", "sentiment": "negative", "resolution_status": "unresolved", "is_repeat_contact": True, "tags": []}, {"issues": ["нет связи"]})
    _set_result(db, "c3", {"category": "техподдержка/связь", "sentiment": "negative", "resolution_status": "unresolved", "is_repeat_contact": True, "tags": []}, {"issues": ["нет связи"]})
    for cid in ("c1", "c2", "c3"):
        update_profile_on_call(db, cid)
    recalculate_profiles(db, "test.domain")
    row = db.execute("SELECT * FROM client_profiles WHERE client_number = '79001234567'").fetchone()
    assert row["risk_level"] in ("medium", "high")
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest tests/test_analytics/test_client_profiles.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Реализовать client_profiles.py**

```python
# src/analytics/client_profiles.py
"""Профили клиентов — инкрементальное обновление и batch-пересчёт."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def update_profile_on_call(conn: sqlite3.Connection, call_id: str) -> None:
    """Инкрементальное обновление профиля клиента после обработки звонка.

    Создаёт профиль если не существует, обновляет счётчики и last_seen.
    """
    row = conn.execute(
        """SELECT c.client_number, c.domain, c.started_at,
                  p.result_json
           FROM calls c JOIN processing p ON c.id = p.call_id
           WHERE c.id = ? AND c.client_number IS NOT NULL""",
        (call_id,),
    ).fetchone()
    if not row or not row["result_json"]:
        return

    client_number = row["client_number"]
    domain = row["domain"]
    started_at = row["started_at"]
    result = json.loads(row["result_json"])

    classification = result.get("classification", {})
    extracted = result.get("extracted_data", {})
    has_issues = bool(extracted.get("issues"))

    now = _now_iso()

    existing = conn.execute(
        "SELECT * FROM client_profiles WHERE client_number = ?",
        (client_number,),
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE client_profiles SET
                total_calls = total_calls + 1,
                calls_with_issues = calls_with_issues + ?,
                last_seen = MAX(last_seen, ?),
                extracted_name = COALESCE(?, extracted_name),
                extracted_contract = COALESCE(?, extracted_contract),
                updated_at = ?
            WHERE client_number = ?""",
            (
                1 if has_issues else 0,
                started_at,
                extracted.get("client_name"),
                extracted.get("contract_number"),
                now,
                client_number,
            ),
        )
    else:
        conn.execute(
            """INSERT INTO client_profiles
               (client_number, domain, first_seen, last_seen,
                total_calls, calls_with_issues,
                extracted_name, extracted_contract, updated_at)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)""",
            (
                client_number, domain, started_at, started_at,
                1 if has_issues else 0,
                extracted.get("client_name"),
                extracted.get("contract_number"),
                now,
            ),
        )
    conn.commit()


def recalculate_profiles(conn: sqlite3.Connection, domain: str) -> int:
    """Batch-пересчёт risk_level, primary_category, sentiment_trend.

    Returns:
        Количество обновлённых профилей.
    """
    profiles = conn.execute(
        "SELECT client_number FROM client_profiles WHERE domain = ?",
        (domain,),
    ).fetchall()

    updated = 0
    for profile in profiles:
        client_number = profile["client_number"]

        # Последние 10 звонков клиента
        calls = conn.execute(
            """SELECT p.result_json
               FROM calls c JOIN processing p ON c.id = p.call_id
               WHERE c.client_number = ? AND p.result_json IS NOT NULL
               ORDER BY c.started_at DESC LIMIT 10""",
            (client_number,),
        ).fetchall()

        if not calls:
            continue

        categories = []
        sentiments = []
        risk_signals = 0

        for call_row in calls:
            result = json.loads(call_row["result_json"])
            cl = result.get("classification", {})
            categories.append(cl.get("category", "другое"))
            sentiments.append(cl.get("sentiment", "neutral"))
            if cl.get("is_repeat_contact"):
                risk_signals += 1
            if "угроза_ухода" in cl.get("tags", []):
                risk_signals += 2
            if cl.get("sentiment") == "negative":
                risk_signals += 1

        # Primary category — самая частая
        primary_category = max(set(categories), key=categories.count) if categories else None

        # Sentiment trend
        recent = sentiments[:3]
        neg_count = recent.count("negative")
        pos_count = recent.count("positive")
        if neg_count >= 2:
            sentiment_trend = "declining"
        elif pos_count >= 2:
            sentiment_trend = "improving"
        else:
            sentiment_trend = "stable"

        # Risk level
        if risk_signals >= 4:
            risk_level = "high"
        elif risk_signals >= 2:
            risk_level = "medium"
        else:
            risk_level = "low"

        conn.execute(
            """UPDATE client_profiles SET
                primary_category = ?,
                sentiment_trend = ?,
                risk_level = ?,
                updated_at = ?
            WHERE client_number = ?""",
            (primary_category, sentiment_trend, risk_level, _now_iso(), client_number),
        )
        updated += 1

    conn.commit()
    return updated
```

- [ ] **Step 4: Запустить тесты**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest tests/test_analytics/test_client_profiles.py -v`
Expected: all passed

- [ ] **Step 5: Коммит**

```bash
git add src/analytics/client_profiles.py tests/test_analytics/test_client_profiles.py
git commit -m "feat(analytics): add client_profiles — incremental update and batch recalculation"
```

---

### Task 8: Модуль search (FTS5)

**Files:**
- Create: `src/analytics/search.py`
- Create: `tests/test_analytics/test_search.py`

- [ ] **Step 1: Написать тесты**

```python
# tests/test_analytics/test_search.py
"""Тесты для FTS5 поиска по звонкам."""

import json
import pytest
from src.db import init_db
from src.analytics.search import index_call, search_calls


@pytest.fixture
def db(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    # Вставить звонки с результатами
    for i, (transcript, topic, issues) in enumerate([
        ("Здравствуйте, не работает SIP-транк уже второй день", "SIP-транк", "не работает SIP-транк"),
        ("Добрый день, хочу подключить переадресацию на мобильный", "переадресация", ""),
        ("Алло, у нас проблема с обещанным платежом", "обещанный платёж", "не прошёл обещанный платёж"),
    ]):
        call_id = f"c{i+1}"
        result = {"transcript": transcript, "summary": {"topic": topic}, "extracted_data": {"issues": [issues] if issues else []}}
        conn.execute(
            "INSERT INTO calls (id, domain, direction, source, received_at) VALUES (?, 'test.domain', 'in', 'test', '2026-04-01')",
            (call_id,),
        )
        conn.execute(
            "INSERT INTO processing (call_id, status, result_json) VALUES (?, 'done', ?)",
            (call_id, json.dumps(result, ensure_ascii=False)),
        )
    conn.commit()
    return conn


def test_index_and_search(db):
    """Индексация и поиск по ключевому слову."""
    index_call(db, "c1")
    results = search_calls(db, "SIP-транк")
    assert len(results) == 1
    assert results[0]["call_id"] == "c1"


def test_search_no_match(db):
    index_call(db, "c1")
    results = search_calls(db, "баланс")
    assert len(results) == 0


def test_search_multiple(db):
    for cid in ("c1", "c2", "c3"):
        index_call(db, cid)
    results = search_calls(db, "переадресация OR платёж")
    assert len(results) == 2


def test_index_idempotent(db):
    """Повторная индексация не дублирует записи."""
    index_call(db, "c1")
    index_call(db, "c1")
    results = search_calls(db, "SIP-транк")
    assert len(results) == 1
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest tests/test_analytics/test_search.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Реализовать search.py**

```python
# src/analytics/search.py
"""Полнотекстовый поиск по звонкам (SQLite FTS5)."""

from __future__ import annotations

import json
import sqlite3


def index_call(conn: sqlite3.Connection, call_id: str) -> bool:
    """Индексировать звонок в FTS5.

    Извлекает transcript, topic и issues из result_json и добавляет в calls_fts.
    Идемпотентно — удаляет старую запись перед вставкой.

    Returns:
        True если индексация успешна, False если нет result_json.
    """
    row = conn.execute(
        "SELECT result_json FROM processing WHERE call_id = ?",
        (call_id,),
    ).fetchone()

    if not row or not row["result_json"]:
        return False

    result = json.loads(row["result_json"])
    transcript = result.get("transcript", "")
    topic = result.get("summary", {}).get("topic", "")
    issues_list = result.get("extracted_data", {}).get("issues", [])
    issues = " ".join(issues_list) if issues_list else ""

    # Удалить старую запись (идемпотентность)
    conn.execute("DELETE FROM calls_fts WHERE call_id = ?", (call_id,))
    conn.execute(
        "INSERT INTO calls_fts (call_id, transcript, topic, issues) VALUES (?, ?, ?, ?)",
        (call_id, transcript, topic, issues),
    )
    conn.commit()
    return True


def search_calls(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 50,
) -> list[dict]:
    """Поиск звонков по FTS5 запросу.

    Args:
        query: поисковый запрос (FTS5 синтаксис: фразы в кавычках, OR, AND).
        limit: максимум результатов.

    Returns:
        Список dict с call_id и rank.
    """
    cursor = conn.execute(
        """SELECT call_id, rank
           FROM calls_fts
           WHERE calls_fts MATCH ?
           ORDER BY rank
           LIMIT ?""",
        (query, limit),
    )
    return [{"call_id": row["call_id"], "rank": row["rank"]} for row in cursor.fetchall()]
```

- [ ] **Step 4: Запустить тесты**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest tests/test_analytics/test_search.py -v`
Expected: all passed

- [ ] **Step 5: Коммит**

```bash
git add src/analytics/search.py tests/test_analytics/test_search.py
git commit -m "feat(analytics): add FTS5 search module — index and search calls"
```

---

### Task 9: Интеграция analytics в worker

**Files:**
- Modify: `src/worker.py:46-101`
- Modify: `tests/test_web/test_worker.py`

- [ ] **Step 1: Написать тест**

Добавить в `tests/test_web/test_worker.py`:

```python
def test_process_one_calls_analytics(worker, mock_pipeline, mock_download):
    """После обработки звонка должны вызываться index_call и update_profile_on_call."""
    with patch("src.worker.index_call") as mock_index, \
         patch("src.worker.update_profile_on_call") as mock_profile:
        worker.process_one("c1")
        mock_index.assert_called_once_with(worker.db, "c1")
        mock_profile.assert_called_once_with(worker.db, "c1")
```

Примечание: адаптировать к существующим фикстурам в файле.

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest tests/test_web/test_worker.py -v -k analytics`
Expected: FAIL

- [ ] **Step 3: Добавить вызовы analytics в worker.py**

В `src/worker.py`, добавить импорты:

```python
from src.analytics.search import index_call
from src.analytics.client_profiles import update_profile_on_call
```

В методе `process_one`, после `update_processing_status(... status="done" ...)` (строка ~88), добавить:

```python
            # Аналитика: индексация FTS5 + обновление профиля клиента
            try:
                index_call(self.db, call_id)
                update_profile_on_call(self.db, call_id)
            except Exception as e:
                logger.warning("Ошибка аналитики для %s: %s", call_id, e)
```

- [ ] **Step 4: Запустить тесты**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest tests/test_web/test_worker.py -v`
Expected: all passed

- [ ] **Step 5: Коммит**

```bash
git add src/worker.py tests/test_web/test_worker.py
git commit -m "feat(worker): integrate FTS5 indexing and client_profiles update after processing"
```

---

## Фаза 5: Dashboard API

### Task 10: API-эндпоинты для дашбордов

**Files:**
- Create: `src/web/routes/dashboard.py`
- Create: `tests/test_web/test_dashboard.py`

- [ ] **Step 1: Написать тесты**

```python
# tests/test_web/test_dashboard.py
"""Тесты для dashboard API."""

import json
import pytest
from fastapi.testclient import TestClient
from src.db import init_db
from src.web.routes.dashboard import router, set_dependencies


@pytest.fixture
def db(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    # Заполнить тестовые данные
    for i in range(5):
        call_id = f"c{i+1}"
        operator = "732" if i < 3 else "708"
        direction = "in" if i < 4 else "out"
        result = {
            "summary": {"call_type": "входящий", "topic": f"тема {i}"},
            "quality_score": {"total": 6 + i, "is_ivr": False, "criteria": {},
                              "script_checklist": {"greeted_with_name": i % 2 == 0, "greeted_with_company": True,
                                                   "identified_client": False, "clarified_issue": True,
                                                   "offered_solution": True, "summarized_outcome": i < 3,
                                                   "said_goodbye": True}},
            "extracted_data": {"issues": ["проблема"] if i < 2 else [], "operator_name": "Антонина"},
            "classification": {"category": "техподдержка/связь" if i < 3 else "информация/консультация",
                               "subcategory": "нет связи" if i < 3 else "консультация",
                               "client_intent": "report_problem" if i < 3 else "get_info",
                               "sentiment": "negative" if i == 0 else "neutral",
                               "resolution_status": "resolved", "is_repeat_contact": False, "tags": []},
            "conversation_metrics": {"operator_talk_sec": 30.0, "client_talk_sec": 25.0,
                                      "silence_sec": 5.0, "longest_silence_sec": 3.0,
                                      "interruptions_count": 1, "operator_talk_ratio": 0.55,
                                      "avg_operator_turn_sec": 10.0, "avg_client_turn_sec": 8.0,
                                      "total_turns": 6},
        }
        conn.execute(
            """INSERT INTO calls (id, domain, direction, duration, started_at, client_number,
                    operator_extension, source, received_at)
               VALUES (?, 'test.domain', ?, ?, ?, ?, ?, 'test', ?)""",
            (call_id, direction, 60 + i * 10, f"2026-04-0{i+1}T10:00:00Z",
             f"7900{i}", operator, f"2026-04-0{i+1}T10:00:00Z"),
        )
        conn.execute(
            "INSERT INTO processing (call_id, status, result_json) VALUES (?, 'done', ?)",
            (call_id, json.dumps(result, ensure_ascii=False)),
        )
    conn.execute(
        "INSERT INTO operators (domain, extension, name, synced_at) VALUES ('test.domain', '732', 'Антонина Кузьмина', '2026-04-01')"
    )
    conn.execute(
        "INSERT INTO operators (domain, extension, name, synced_at) VALUES ('test.domain', '708', 'Лейла Авсеенко', '2026-04-01')"
    )
    conn.commit()
    return conn


@pytest.fixture
def client(db):
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    set_dependencies(db)
    return TestClient(app)


def test_business_kpis(client):
    """GET /api/dashboard/business/kpis возвращает KPI-карточки."""
    resp = client.get("/api/dashboard/business/kpis", params={"domain": "test.domain"})
    assert resp.status_code == 200
    data = resp.json()
    assert "total_calls" in data
    assert "avg_quality" in data
    assert data["total_calls"] == 5


def test_category_distribution(client):
    """GET /api/dashboard/business/categories возвращает распределение по категориям."""
    resp = client.get("/api/dashboard/business/categories", params={"domain": "test.domain"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(d["category"] == "техподдержка/связь" for d in data)


def test_sentiment_distribution(client):
    resp = client.get("/api/dashboard/business/sentiment", params={"domain": "test.domain"})
    assert resp.status_code == 200
    data = resp.json()
    assert "negative" in data or any(d.get("sentiment") == "negative" for d in data)


def test_operator_ratings(client):
    """GET /api/dashboard/supervisor/operators возвращает рейтинг операторов."""
    resp = client.get("/api/dashboard/supervisor/operators", params={"domain": "test.domain"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "avg_score" in data[0]
    assert "call_count" in data[0]


def test_risk_clients(client):
    """GET /api/dashboard/business/risk-clients возвращает клиентов в зоне риска."""
    resp = client.get("/api/dashboard/business/risk-clients", params={"domain": "test.domain"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_search(client):
    """GET /api/dashboard/search — поиск по FTS5."""
    # Сначала индексируем
    from src.analytics.search import index_call
    from src.web.routes.dashboard import _db
    for i in range(5):
        index_call(_db, f"c{i+1}")
    resp = client.get("/api/dashboard/search", params={"q": "тема"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest tests/test_web/test_dashboard.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Реализовать dashboard.py**

```python
# src/web/routes/dashboard.py
"""API-эндпоинты для дашбордов аналитики."""

import json
import logging
import sqlite3

from fastapi import APIRouter, Query

from src.analytics.search import search_calls

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard")

_db: sqlite3.Connection | None = None


def set_dependencies(db: sqlite3.Connection):
    global _db
    _db = db


def _query_results(domain: str, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    """Получить result_json для звонков с фильтрами."""
    query = """
        SELECT c.id, c.operator_extension, c.client_number, c.started_at,
               c.duration, c.direction, p.result_json
        FROM calls c JOIN processing p ON c.id = p.call_id
        WHERE p.status = 'done' AND p.result_json IS NOT NULL AND c.domain = ?
    """
    params: list = [domain]
    if date_from:
        query += " AND c.started_at >= ?"
        params.append(date_from)
    if date_to:
        query += " AND c.started_at < ?"
        params.append(date_to)
    query += " ORDER BY c.started_at DESC"

    rows = _db.execute(query, params).fetchall()
    results = []
    for row in rows:
        r = dict(row)
        r["result"] = json.loads(r.pop("result_json"))
        results.append(r)
    return results


@router.get("/business/kpis")
def business_kpis(
    domain: str,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """KPI-карточки для дашборда руководителя."""
    rows = _query_results(domain, date_from, date_to)
    if not rows:
        return {"total_calls": 0, "avg_quality": 0, "missed_count": 0,
                "missed_pct": 0, "repeat_pct": 0, "risk_clients": 0}

    total = len(rows)
    scores = [r["result"].get("quality_score", {}).get("total") for r in rows
              if r["result"].get("quality_score", {}).get("total") is not None]
    avg_quality = round(sum(scores) / len(scores), 1) if scores else 0

    missed = _db.execute(
        "SELECT COUNT(*) as cnt FROM calls WHERE domain = ? AND direction = 'missed'",
        (domain,),
    ).fetchone()["cnt"]
    all_calls = _db.execute(
        "SELECT COUNT(*) as cnt FROM calls WHERE domain = ?", (domain,)
    ).fetchone()["cnt"]
    missed_pct = round(missed / all_calls * 100, 1) if all_calls else 0

    repeat_count = sum(
        1 for r in rows
        if r["result"].get("classification", {}).get("is_repeat_contact")
    )
    repeat_pct = round(repeat_count / total * 100, 1) if total else 0

    risk_clients = _db.execute(
        "SELECT COUNT(*) as cnt FROM client_profiles WHERE domain = ? AND risk_level IN ('medium', 'high')",
        (domain,),
    ).fetchone()["cnt"]

    return {
        "total_calls": total,
        "avg_quality": avg_quality,
        "missed_count": missed,
        "missed_pct": missed_pct,
        "repeat_pct": repeat_pct,
        "risk_clients": risk_clients,
    }


@router.get("/business/categories")
def business_categories(
    domain: str,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Распределение по категориям."""
    rows = _query_results(domain, date_from, date_to)
    counts: dict[str, int] = {}
    for r in rows:
        cat = r["result"].get("classification", {}).get("category", "другое")
        counts[cat] = counts.get(cat, 0) + 1

    return sorted(
        [{"category": k, "count": v} for k, v in counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )


@router.get("/business/sentiment")
def business_sentiment(
    domain: str,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Распределение sentiment."""
    rows = _query_results(domain, date_from, date_to)
    counts: dict[str, int] = {"positive": 0, "neutral": 0, "negative": 0}
    for r in rows:
        s = r["result"].get("classification", {}).get("sentiment", "neutral")
        counts[s] = counts.get(s, 0) + 1
    return counts


@router.get("/business/risk-clients")
def business_risk_clients(domain: str):
    """Клиенты в зоне риска."""
    rows = _db.execute(
        """SELECT * FROM client_profiles
           WHERE domain = ? AND risk_level IN ('medium', 'high')
           ORDER BY risk_level DESC, total_calls DESC""",
        (domain,),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/supervisor/operators")
def supervisor_operators(
    domain: str,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Рейтинг операторов: средний балл, количество звонков."""
    rows = _query_results(domain, date_from, date_to)
    operators: dict[str, dict] = {}
    for r in rows:
        ext = r["operator_extension"]
        if not ext:
            continue
        if ext not in operators:
            operators[ext] = {"extension": ext, "scores": [], "call_count": 0, "talk_ratios": []}
        operators[ext]["call_count"] += 1
        score = r["result"].get("quality_score", {}).get("total")
        if score is not None:
            operators[ext]["scores"].append(score)
        tr = r["result"].get("conversation_metrics", {}).get("operator_talk_ratio")
        if tr is not None:
            operators[ext]["talk_ratios"].append(tr)

    # Enrich with operator names
    result = []
    for ext, data in operators.items():
        name_row = _db.execute(
            "SELECT name FROM operators WHERE domain = ? AND extension = ?",
            (domain, ext),
        ).fetchone()
        avg_score = round(sum(data["scores"]) / len(data["scores"]), 1) if data["scores"] else None
        avg_talk_ratio = round(sum(data["talk_ratios"]) / len(data["talk_ratios"]), 2) if data["talk_ratios"] else None
        result.append({
            "extension": ext,
            "name": name_row["name"] if name_row else ext,
            "call_count": data["call_count"],
            "avg_score": avg_score,
            "avg_talk_ratio": avg_talk_ratio,
        })

    return sorted(result, key=lambda x: x["avg_score"] or 0, reverse=True)


@router.get("/search")
def dashboard_search(q: str, limit: int = Query(50, ge=1, le=200)):
    """Полнотекстовый поиск по звонкам."""
    results = search_calls(_db, q, limit=limit)
    return results
```

- [ ] **Step 4: Запустить тесты**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest tests/test_web/test_dashboard.py -v`
Expected: all passed

- [ ] **Step 5: Подключить dashboard router в app.py**

В `src/web/app.py`, добавить импорт:

```python
from src.web.routes import dashboard
```

И в lifespan, после `api.set_dependencies(db, _domain_configs)`:

```python
    dashboard.set_dependencies(_db)
```

И при включении роутеров:

```python
    app.include_router(dashboard.router)
```

- [ ] **Step 6: Запустить все тесты**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest --ignore=tests/test_transcriber.py -v`
Expected: all passed

- [ ] **Step 7: Коммит**

```bash
git add src/web/routes/dashboard.py tests/test_web/test_dashboard.py src/web/app.py
git commit -m "feat(web): add dashboard API — business KPIs, categories, sentiment, operators, search"
```

---

## Фаза 6: Dashboard UI

### Task 11: HTML-шаблоны дашбордов

**Files:**
- Create: `src/web/templates/dashboard_business.html`
- Create: `src/web/templates/dashboard_supervisor.html`
- Modify: `src/web/routes/dashboard.py` (добавить HTML-страницы)

- [ ] **Step 1: Добавить page-роуты для дашбордов**

В `src/web/routes/dashboard.py` добавить:

```python
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/business", response_class=HTMLResponse)
def business_dashboard_page(request: Request, domain: str = "gravitel.ru"):
    return _templates.TemplateResponse("dashboard_business.html", {"request": request, "domain": domain})


@router.get("/supervisor", response_class=HTMLResponse)
def supervisor_dashboard_page(request: Request, domain: str = "gravitel.ru"):
    return _templates.TemplateResponse("dashboard_supervisor.html", {"request": request, "domain": domain})
```

- [ ] **Step 2: Создать dashboard_business.html**

Создать `src/web/templates/dashboard_business.html` — HTML-страница с:
- Фильтр периода (date_from, date_to, пресеты: сегодня/неделя/месяц)
- KPI-карточки (fetch из `/api/dashboard/business/kpis`)
- Bar chart категорий (fetch из `/api/dashboard/business/categories`)
- Donut chart sentiment (fetch из `/api/dashboard/business/sentiment`)
- Таблица клиентов в зоне риска (fetch из `/api/dashboard/business/risk-clients`)
- Строка поиска (fetch из `/api/dashboard/search`)
- Chart.js подключать из CDN: `https://cdn.jsdelivr.net/npm/chart.js`

Подробная верстка определяется при реализации — сохранить стиль существующего UI (`style.css`).

- [ ] **Step 3: Создать dashboard_supervisor.html**

Создать `src/web/templates/dashboard_supervisor.html` — HTML-страница с:
- Таблица рейтинга операторов (fetch из `/api/dashboard/supervisor/operators`)
- Bar chart нагрузки по операторам
- Heatmap чеклиста скрипта (агрегировать из API)

- [ ] **Step 4: Проверить работу вручную**

Запустить сервер локально (если есть тестовые данные) или проверить на сервере после деплоя.

- [ ] **Step 5: Коммит**

```bash
git add src/web/templates/dashboard_business.html src/web/templates/dashboard_supervisor.html src/web/routes/dashboard.py
git commit -m "feat(web): add dashboard HTML pages — business overview and supervisor view"
```

---

## Фаза 7: Batch-процессы (Knowledge Base)

### Task 12: Модуль knowledge — batch-агрегатор

**Files:**
- Create: `src/analytics/knowledge.py`
- Create: `tests/test_analytics/test_knowledge.py`

- [ ] **Step 1: Написать тесты**

```python
# tests/test_analytics/test_knowledge.py
"""Тесты для knowledge — batch-агрегация базы знаний."""

import json
import pytest
from src.db import init_db
from src.analytics.knowledge import aggregate_knowledge


@pytest.fixture
def db(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    # 5 звонков с одинаковой категорией
    for i in range(5):
        call_id = f"c{i+1}"
        result = {
            "summary": {"topic": "нет связи", "outcome": "перезагрузка роутера помогла"},
            "classification": {"category": "техподдержка/связь", "subcategory": "нет связи",
                               "resolution_status": "resolved"},
            "extracted_data": {"issues": ["не работает связь"], "next_steps": ["перезагрузить роутер"]},
        }
        conn.execute(
            """INSERT INTO calls (id, domain, direction, started_at, source, received_at)
               VALUES (?, 'test.domain', 'in', ?, 'test', ?)""",
            (call_id, f"2026-04-0{i+1}T10:00:00Z", f"2026-04-0{i+1}T10:00:00Z"),
        )
        conn.execute(
            "INSERT INTO processing (call_id, status, result_json, completed_at) VALUES (?, 'done', ?, ?)",
            (call_id, json.dumps(result, ensure_ascii=False), f"2026-04-0{i+1}T10:05:00Z"),
        )
    conn.commit()
    return conn


def test_aggregate_creates_kb_entry(db):
    """aggregate_knowledge должен создать запись в knowledge_base."""
    count = aggregate_knowledge(db, "test.domain")
    assert count >= 1
    row = db.execute("SELECT * FROM knowledge_base WHERE category = 'техподдержка/связь'").fetchone()
    assert row is not None
    assert row["frequency"] >= 5


def test_aggregate_idempotent(db):
    """Повторный запуск обновляет frequency, не дублирует записи."""
    aggregate_knowledge(db, "test.domain")
    aggregate_knowledge(db, "test.domain")
    rows = db.execute("SELECT * FROM knowledge_base WHERE category = 'техподдержка/связь'").fetchall()
    assert len(rows) == 1
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest tests/test_analytics/test_knowledge.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Реализовать knowledge.py**

```python
# src/analytics/knowledge.py
"""Batch-агрегация базы знаний из обработанных звонков."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def aggregate_knowledge(conn: sqlite3.Connection, domain: str) -> int:
    """Агрегировать знания из обработанных звонков.

    Группирует звонки по category+subcategory, создаёт или обновляет
    записи в knowledge_base.

    Returns:
        Количество созданных/обновлённых записей.
    """
    rows = conn.execute(
        """SELECT c.id, p.result_json
           FROM calls c JOIN processing p ON c.id = p.call_id
           WHERE c.domain = ? AND p.status = 'done' AND p.result_json IS NOT NULL""",
        (domain,),
    ).fetchall()

    # Группировка по category + subcategory
    groups: dict[tuple[str, str], list] = defaultdict(list)
    for row in rows:
        result = json.loads(row["result_json"])
        cl = result.get("classification", {})
        cat = cl.get("category", "другое")
        subcat = cl.get("subcategory", "")
        groups[(cat, subcat)].append({
            "call_id": row["id"],
            "issues": result.get("extracted_data", {}).get("issues", []),
            "next_steps": result.get("extracted_data", {}).get("next_steps", []),
            "topic": result.get("summary", {}).get("topic", ""),
            "outcome": result.get("summary", {}).get("outcome", ""),
            "resolution": cl.get("resolution_status", ""),
        })

    now = _now_iso()
    updated = 0

    for (cat, subcat), calls in groups.items():
        if not calls:
            continue

        # Обобщённая проблема и решение
        all_issues = []
        all_solutions = []
        call_ids = []
        resolved_count = 0
        for c in calls:
            all_issues.extend(c["issues"])
            all_solutions.extend(c["next_steps"])
            call_ids.append(c["call_id"])
            if c["resolution"] == "resolved":
                resolved_count += 1

        problem_desc = "; ".join(set(filter(None, all_issues)))[:500] or calls[0]["topic"]
        solution_desc = "; ".join(set(filter(None, all_solutions)))[:500] or ""
        success_rate = round(resolved_count / len(calls), 2) if calls else 0

        existing = conn.execute(
            "SELECT id FROM knowledge_base WHERE domain = ? AND category = ? AND subcategory = ?",
            (domain, cat, subcat or ""),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE knowledge_base SET
                    frequency = ?,
                    problem_description = ?,
                    solution_description = ?,
                    success_rate = ?,
                    example_call_ids = ?,
                    updated_at = ?
                WHERE id = ?""",
                (len(calls), problem_desc, solution_desc, success_rate,
                 json.dumps(call_ids[-10:]), now, existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO knowledge_base
                   (domain, category, subcategory, problem_description,
                    solution_description, frequency, success_rate,
                    example_call_ids, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (domain, cat, subcat or "", problem_desc, solution_desc,
                 len(calls), success_rate, json.dumps(call_ids[-10:]), now, now),
            )
        updated += 1

    conn.commit()
    return updated
```

- [ ] **Step 4: Запустить тесты**

Run: `cd /Users/iz/Developer/GR_dev/01_LLM_GR && python -m pytest tests/test_analytics/test_knowledge.py -v`
Expected: all passed

- [ ] **Step 5: Коммит**

```bash
git add src/analytics/knowledge.py tests/test_analytics/test_knowledge.py
git commit -m "feat(analytics): add knowledge base batch aggregator"
```

---

## Фаза 8: Деплой и ретроспектива

### Task 13: Деплой на сервер и ретроспективная обработка

**Files:**
- No new files — deployment steps

- [ ] **Step 1: Деплой кода на сервер**

```bash
ssh ai-lab "cd ~/01_LLM_GR && git pull"
```

- [ ] **Step 2: Перезапустить сервис**

```bash
ssh ai-lab "sudo systemctl restart ai-lab-web"
```

- [ ] **Step 3: Проверить что новые таблицы создались**

```bash
ssh ai-lab 'cd ~/01_LLM_GR && source ~/venv_transcribe/bin/activate && python3 -c "
from src.db import init_db
conn = init_db(\"data/calls.db\")
for table in (\"client_profiles\", \"knowledge_base\", \"knowledge_scenarios\", \"calls_fts\"):
    conn.execute(f\"SELECT * FROM {table} LIMIT 1\")
    print(f\"{table}: OK\")
"'
```

- [ ] **Step 4: Ретроспективная классификация существующих звонков**

Написать одноразовый скрипт `scripts/backfill_classification.py`:
- Пройти по всем `processing` со `status=done` и `result_json IS NOT NULL`
- Для каждого: если в result_json нет ключа `classification` → вызвать classify промпт
- Обновить result_json
- Вызвать `index_call()` и `update_profile_on_call()`

Оценка: ~1702 вызова × ~12 сек = ~5.7 часов.

- [ ] **Step 5: Запустить ретроспективу на сервере**

```bash
ssh ai-lab 'cd ~/01_LLM_GR && source ~/venv_transcribe/bin/activate && nohup python3 scripts/backfill_classification.py > logs/backfill.log 2>&1 &'
```

- [ ] **Step 6: После завершения — запустить batch-агрегацию KB**

```bash
ssh ai-lab 'cd ~/01_LLM_GR && source ~/venv_transcribe/bin/activate && python3 -c "
from src.db import init_db
from src.analytics.knowledge import aggregate_knowledge
from src.analytics.client_profiles import recalculate_profiles
conn = init_db(\"data/calls.db\")
print(f\"KB entries: {aggregate_knowledge(conn, \\\"gravitel.ru\\\")}\")
print(f\"Profiles updated: {recalculate_profiles(conn, \\\"gravitel.ru\\\")}\")
"'
```

- [ ] **Step 7: Проверить дашборды в браузере**

Открыть:
- `http://212.24.45.138:42367/api/dashboard/business?domain=gravitel.ru`
- `http://212.24.45.138:42367/api/dashboard/supervisor?domain=gravitel.ru`

- [ ] **Step 8: Обновить документацию**

Обновить `agent_docs/architecture.md` — добавить секцию Analytics.
Добавить запись в `agent_docs/development-history.md`.

- [ ] **Step 9: Коммит документации**

```bash
git add agent_docs/architecture.md agent_docs/development-history.md scripts/backfill_classification.py
git commit -m "docs: update architecture and history with analytics platform"
```

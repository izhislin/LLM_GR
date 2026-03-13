# Web API Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Забирать записи звонков из доменов ВАТС Гравител по API, обрабатывать через pipeline (GigaAM + Qwen3-8B) и отображать результаты в веб-интерфейсе.

**Architecture:** Монолит FastAPI на AI Lab сервере. Webhook-приёмник + polling каждые 10 мин. SQLite для хранения. Фоновая обработка через asyncio + ThreadPoolExecutor. Jinja2 для UI.

**Tech Stack:** FastAPI, uvicorn, httpx, Jinja2, SQLite (aiosqlite), APScheduler, существующий pipeline (GigaAM + Ollama).

**Design doc:** `docs/plans/2026-03-13-web-api-integration-design.md`

---

## Task 1: Зависимости и структура проекта

**Files:**
- Modify: `requirements.txt`
- Create: `config/domains.yaml`
- Create: `.env.example`
- Create: `src/web/__init__.py`
- Create: `src/web/routes/__init__.py`
- Create: `src/web/templates/.gitkeep`
- Create: `src/web/static/.gitkeep`
- Create: `tests/test_web/__init__.py`
- Modify: `.gitignore`

**Step 1: Обновить requirements.txt**

Добавить в `requirements.txt`:

```
# Web server
fastapi>=0.115
uvicorn[standard]>=0.30
jinja2>=3.1
python-multipart>=0.0.9

# HTTP client (async)
httpx>=0.27

# Database
aiosqlite>=0.20

# Scheduler
apscheduler>=3.10,<4

# Config
pyyaml>=6.0
python-dotenv>=1.0
```

**Step 2: Создать config/domains.yaml**

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

**Step 3: Создать .env.example**

```bash
# Gravitel API keys (один ключ на домен)
GRAVITEL_API_KEY=your-api-key-here

# Web UI basic auth
WEB_USERNAME=admin
WEB_PASSWORD=change-me

# HuggingFace token (для GigaAM/pyannote)
HF_TOKEN=hf_xxx
```

**Step 4: Создать структуру директорий**

```
src/web/__init__.py          (пустой)
src/web/routes/__init__.py   (пустой)
src/web/templates/.gitkeep   (пустой)
src/web/static/.gitkeep      (пустой)
tests/test_web/__init__.py   (пустой)
```

**Step 5: Обновить .gitignore**

Добавить:
```
# Environment
.env

# Audio downloads
data/audio/

# SQLite
*.db
*.db-journal
```

**Step 6: Установить зависимости и коммит**

Run: `cd /home/aiadmin/01_LLM_GR && pip install -r requirements.txt`

```bash
git add requirements.txt config/domains.yaml .env.example .gitignore \
  src/web/__init__.py src/web/routes/__init__.py \
  src/web/templates/.gitkeep src/web/static/.gitkeep \
  tests/test_web/__init__.py
git commit -m "chore: add web dependencies and project structure"
```

---

## Task 2: Модуль конфигурации доменов

**Files:**
- Create: `src/domain_config.py`
- Create: `tests/test_domain_config.py`

**Step 1: Написать тесты**

```python
# tests/test_domain_config.py
"""Тесты для загрузки конфигурации доменов."""

import pytest
from pathlib import Path

from src.domain_config import load_domains_config, DomainConfig, CallFilters


@pytest.fixture
def sample_config(tmp_path):
    """Создать тестовый config/domains.yaml."""
    config_file = tmp_path / "domains.yaml"
    config_file.write_text("""
domains:
  test.aicall.ru:
    api_key_env: "TEST_API_KEY"
    profile: "gravitel"
    enabled: true
    polling_interval_min: 10
    filters:
      min_duration_sec: 20
      max_duration_sec: 1500
      call_types: ["in", "out"]
      only_with_record: true
      results: ["success"]
  disabled.aicall.ru:
    api_key_env: "DISABLED_KEY"
    profile: null
    enabled: false
    polling_interval_min: 30
    filters:
      min_duration_sec: 10
      max_duration_sec: 600
      call_types: ["all"]
      only_with_record: true
      results: ["success", "missed"]
""", encoding="utf-8")
    return config_file


def test_load_domains_config(sample_config):
    """Загрузка конфига возвращает словарь DomainConfig."""
    configs = load_domains_config(sample_config)
    assert "test.aicall.ru" in configs
    assert "disabled.aicall.ru" in configs


def test_domain_config_fields(sample_config):
    """DomainConfig содержит все поля."""
    configs = load_domains_config(sample_config)
    cfg = configs["test.aicall.ru"]
    assert isinstance(cfg, DomainConfig)
    assert cfg.api_key_env == "TEST_API_KEY"
    assert cfg.profile == "gravitel"
    assert cfg.enabled is True
    assert cfg.polling_interval_min == 10


def test_call_filters(sample_config):
    """CallFilters содержит параметры фильтрации."""
    configs = load_domains_config(sample_config)
    filters = configs["test.aicall.ru"].filters
    assert isinstance(filters, CallFilters)
    assert filters.min_duration_sec == 20
    assert filters.max_duration_sec == 1500
    assert filters.call_types == ["in", "out"]
    assert filters.only_with_record is True
    assert filters.results == ["success"]


def test_enabled_domains_only(sample_config):
    """Фильтрация только активных доменов."""
    configs = load_domains_config(sample_config)
    enabled = {k: v for k, v in configs.items() if v.enabled}
    assert "test.aicall.ru" in enabled
    assert "disabled.aicall.ru" not in enabled


def test_missing_config_file():
    """Ошибка при отсутствии конфиг-файла."""
    with pytest.raises(FileNotFoundError):
        load_domains_config(Path("/nonexistent/domains.yaml"))
```

**Step 2: Запустить — убедиться что падает**

Run: `pytest tests/test_domain_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.domain_config'`

**Step 3: Реализация**

```python
# src/domain_config.py
"""Загрузка конфигурации доменов ВАТС."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.config import PROJECT_ROOT


@dataclass
class CallFilters:
    """Фильтры для отбора звонков."""
    min_duration_sec: int = 20
    max_duration_sec: int = 1500
    call_types: list[str] = field(default_factory=lambda: ["in", "out"])
    only_with_record: bool = True
    results: list[str] = field(default_factory=lambda: ["success"])


@dataclass
class DomainConfig:
    """Конфигурация одного домена ВАТС."""
    api_key_env: str
    profile: str | None
    enabled: bool
    polling_interval_min: int
    filters: CallFilters


def load_domains_config(config_path: Path | None = None) -> dict[str, DomainConfig]:
    """Загрузить конфигурацию доменов из YAML.

    Args:
        config_path: Путь к YAML-файлу. По умолчанию — config/domains.yaml.

    Returns:
        Словарь {domain_name: DomainConfig}.
    """
    if config_path is None:
        config_path = PROJECT_ROOT / "config" / "domains.yaml"

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    result = {}
    for domain, cfg in raw.get("domains", {}).items():
        filters_raw = cfg.get("filters", {})
        filters = CallFilters(
            min_duration_sec=filters_raw.get("min_duration_sec", 20),
            max_duration_sec=filters_raw.get("max_duration_sec", 1500),
            call_types=filters_raw.get("call_types", ["in", "out"]),
            only_with_record=filters_raw.get("only_with_record", True),
            results=filters_raw.get("results", ["success"]),
        )
        result[domain] = DomainConfig(
            api_key_env=cfg["api_key_env"],
            profile=cfg.get("profile"),
            enabled=cfg.get("enabled", True),
            polling_interval_min=cfg.get("polling_interval_min", 10),
            filters=filters,
        )

    return result
```

**Step 4: Запустить тесты**

Run: `pytest tests/test_domain_config.py -v`
Expected: all PASS

**Step 5: Коммит**

```bash
git add src/domain_config.py tests/test_domain_config.py
git commit -m "feat: add domain configuration loader with YAML support"
```

---

## Task 3: Модуль базы данных (src/db.py)

**Files:**
- Create: `src/db.py`
- Create: `tests/test_web/test_db.py`

**Step 1: Написать тесты**

```python
# tests/test_web/test_db.py
"""Тесты для модуля базы данных."""

import pytest
import sqlite3

from src.db import (
    init_db,
    insert_call,
    get_call,
    list_calls,
    insert_processing,
    get_processing,
    update_processing_status,
    upsert_operator,
    get_operator_name,
    upsert_department,
    list_operators,
    list_departments,
    get_calls_count,
)


@pytest.fixture
def db(tmp_path):
    """Создать in-memory БД с инициализированной схемой."""
    db_path = tmp_path / "test.db"
    conn = init_db(str(db_path))
    yield conn
    conn.close()


SAMPLE_CALL = {
    "id": "abc123",
    "domain": "test.aicall.ru",
    "direction": "in",
    "result": "success",
    "duration": 120,
    "wait": 5,
    "started_at": "2026-03-13T14:00:00Z",
    "client_number": "79991234567",
    "operator_extension": "701",
    "operator_name": None,
    "phone": "74951112233",
    "record_url": "https://records.aicall.ru/test/abc123.mp3",
    "source": "webhook",
}


def test_init_db_creates_tables(db):
    """init_db создаёт все таблицы."""
    cursor = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row[0] for row in cursor.fetchall()}
    assert "calls" in tables
    assert "processing" in tables
    assert "operators" in tables
    assert "departments" in tables
    assert "domains" in tables


def test_insert_and_get_call(db):
    """Вставка и получение звонка."""
    insert_call(db, SAMPLE_CALL)
    call = get_call(db, "abc123")
    assert call is not None
    assert call["id"] == "abc123"
    assert call["domain"] == "test.aicall.ru"
    assert call["duration"] == 120


def test_insert_duplicate_call_ignored(db):
    """Дублирующий звонок игнорируется (INSERT OR IGNORE)."""
    insert_call(db, SAMPLE_CALL)
    insert_call(db, SAMPLE_CALL)  # не должен упасть
    count = get_calls_count(db, domain="test.aicall.ru")
    assert count == 1


def test_list_calls_with_filters(db):
    """Фильтрация списка звонков."""
    insert_call(db, SAMPLE_CALL)
    call2 = {**SAMPLE_CALL, "id": "def456", "direction": "out"}
    insert_call(db, call2)

    all_calls = list_calls(db, domain="test.aicall.ru")
    assert len(all_calls) == 2

    in_calls = list_calls(db, domain="test.aicall.ru", direction="in")
    assert len(in_calls) == 1
    assert in_calls[0]["id"] == "abc123"


def test_list_calls_pagination(db):
    """Пагинация списка звонков."""
    for i in range(25):
        call = {**SAMPLE_CALL, "id": f"call_{i:03d}"}
        insert_call(db, call)

    page1 = list_calls(db, page=1, per_page=10)
    assert len(page1) == 10

    page3 = list_calls(db, page=3, per_page=10)
    assert len(page3) == 5


def test_insert_and_get_processing(db):
    """Вставка и получение статуса обработки."""
    insert_call(db, SAMPLE_CALL)
    insert_processing(db, "abc123", status="pending")
    proc = get_processing(db, "abc123")
    assert proc["status"] == "pending"


def test_update_processing_status(db):
    """Обновление статуса обработки."""
    insert_call(db, SAMPLE_CALL)
    insert_processing(db, "abc123", status="pending")
    update_processing_status(db, "abc123", status="done", result_json='{"summary": {}}')
    proc = get_processing(db, "abc123")
    assert proc["status"] == "done"
    assert proc["result_json"] == '{"summary": {}}'


def test_upsert_operator(db):
    """UPSERT оператора — вставка и обновление."""
    upsert_operator(db, "test.aicall.ru", "701", "Иванов Пётр")
    name = get_operator_name(db, "test.aicall.ru", "701")
    assert name == "Иванов Пётр"

    # Обновление имени
    upsert_operator(db, "test.aicall.ru", "701", "Иванов П.П.")
    name = get_operator_name(db, "test.aicall.ru", "701")
    assert name == "Иванов П.П."


def test_get_operator_name_unknown(db):
    """Неизвестный оператор → None."""
    name = get_operator_name(db, "test.aicall.ru", "999")
    assert name is None


def test_upsert_department(db):
    """UPSERT отдела."""
    upsert_department(db, "test.aicall.ru", 111, "700", "Отдел продаж")
    deps = list_departments(db, "test.aicall.ru")
    assert len(deps) == 1
    assert deps[0]["name"] == "Отдел продаж"
```

**Step 2: Запустить — убедиться что падает**

Run: `pytest tests/test_web/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.db'`

**Step 3: Реализация**

```python
# src/db.py
"""SQLite база данных для хранения звонков и результатов."""

import sqlite3
from datetime import datetime, timezone


_SCHEMA = """
CREATE TABLE IF NOT EXISTS domains (
    domain TEXT PRIMARY KEY,
    last_polled_at TEXT,
    last_poll_cursor TEXT
);

CREATE TABLE IF NOT EXISTS calls (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    direction TEXT NOT NULL,
    result TEXT,
    duration INTEGER,
    wait INTEGER,
    started_at TEXT,
    client_number TEXT,
    operator_extension TEXT,
    operator_name TEXT,
    phone TEXT,
    record_url TEXT,
    source TEXT NOT NULL,
    received_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processing (
    call_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending',
    audio_path TEXT,
    result_json TEXT,
    error_message TEXT,
    skip_reason TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    completed_at TEXT,
    processing_time_sec REAL,
    FOREIGN KEY (call_id) REFERENCES calls(id)
);

CREATE TABLE IF NOT EXISTS operators (
    domain TEXT NOT NULL,
    extension TEXT NOT NULL,
    name TEXT NOT NULL,
    synced_at TEXT NOT NULL,
    PRIMARY KEY (domain, extension)
);

CREATE TABLE IF NOT EXISTS departments (
    domain TEXT NOT NULL,
    id INTEGER NOT NULL,
    extension TEXT,
    name TEXT NOT NULL,
    synced_at TEXT NOT NULL,
    PRIMARY KEY (domain, id)
);

CREATE INDEX IF NOT EXISTS idx_calls_domain ON calls(domain);
CREATE INDEX IF NOT EXISTS idx_calls_started ON calls(started_at);
CREATE INDEX IF NOT EXISTS idx_processing_status ON processing(status);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    """Инициализировать БД и создать таблицы."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Calls ────────────────────────────────────────────────────────────────────

def insert_call(conn: sqlite3.Connection, call: dict) -> bool:
    """Вставить звонок (игнорирует дубликаты). Возвращает True если вставлен."""
    cursor = conn.execute(
        """INSERT OR IGNORE INTO calls
           (id, domain, direction, result, duration, wait, started_at,
            client_number, operator_extension, operator_name, phone,
            record_url, source, received_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            call["id"], call["domain"], call["direction"], call.get("result"),
            call.get("duration"), call.get("wait"), call.get("started_at"),
            call.get("client_number"), call.get("operator_extension"),
            call.get("operator_name"), call.get("phone"),
            call.get("record_url"), call["source"], _now_iso(),
        ),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_call(conn: sqlite3.Connection, call_id: str) -> dict | None:
    """Получить звонок по ID."""
    row = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
    return dict(row) if row else None


def list_calls(
    conn: sqlite3.Connection,
    domain: str | None = None,
    direction: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    operator: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> list[dict]:
    """Список звонков с фильтрами и пагинацией."""
    query = """
        SELECT c.*, p.status as proc_status, p.skip_reason, p.result_json,
               p.processing_time_sec
        FROM calls c
        LEFT JOIN processing p ON c.id = p.call_id
        WHERE 1=1
    """
    params: list = []

    if domain:
        query += " AND c.domain = ?"
        params.append(domain)
    if direction:
        query += " AND c.direction = ?"
        params.append(direction)
    if status:
        query += " AND p.status = ?"
        params.append(status)
    if date_from:
        query += " AND c.started_at >= ?"
        params.append(date_from)
    if date_to:
        query += " AND c.started_at <= ?"
        params.append(date_to)
    if operator:
        query += " AND c.operator_extension = ?"
        params.append(operator)

    query += " ORDER BY c.started_at DESC LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])

    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_calls_count(
    conn: sqlite3.Connection,
    domain: str | None = None,
    status: str | None = None,
) -> int:
    """Количество звонков с фильтрами."""
    query = """
        SELECT COUNT(*) FROM calls c
        LEFT JOIN processing p ON c.id = p.call_id
        WHERE 1=1
    """
    params: list = []
    if domain:
        query += " AND c.domain = ?"
        params.append(domain)
    if status:
        query += " AND p.status = ?"
        params.append(status)

    return conn.execute(query, params).fetchone()[0]


# ── Processing ───────────────────────────────────────────────────────────────

def insert_processing(
    conn: sqlite3.Connection,
    call_id: str,
    status: str = "pending",
    skip_reason: str | None = None,
) -> None:
    """Создать запись обработки."""
    conn.execute(
        """INSERT OR IGNORE INTO processing (call_id, status, skip_reason)
           VALUES (?, ?, ?)""",
        (call_id, status, skip_reason),
    )
    conn.commit()


def get_processing(conn: sqlite3.Connection, call_id: str) -> dict | None:
    """Получить статус обработки."""
    row = conn.execute(
        "SELECT * FROM processing WHERE call_id = ?", (call_id,)
    ).fetchone()
    return dict(row) if row else None


def update_processing_status(
    conn: sqlite3.Connection,
    call_id: str,
    status: str,
    audio_path: str | None = None,
    result_json: str | None = None,
    error_message: str | None = None,
    processing_time_sec: float | None = None,
) -> None:
    """Обновить статус обработки."""
    now = _now_iso()
    sets = ["status = ?"]
    params: list = [status]

    if audio_path is not None:
        sets.append("audio_path = ?")
        params.append(audio_path)
    if result_json is not None:
        sets.append("result_json = ?")
        params.append(result_json)
    if error_message is not None:
        sets.append("error_message = ?")
        params.append(error_message)
    if processing_time_sec is not None:
        sets.append("processing_time_sec = ?")
        params.append(processing_time_sec)

    if status == "processing":
        sets.append("started_at = ?")
        params.append(now)
    elif status in ("done", "error"):
        sets.append("completed_at = ?")
        params.append(now)

    if status == "error":
        sets.append("retry_count = retry_count + 1")

    params.append(call_id)
    conn.execute(
        f"UPDATE processing SET {', '.join(sets)} WHERE call_id = ?",
        params,
    )
    conn.commit()


def get_pending_calls(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """Получить звонки, ожидающие обработки."""
    rows = conn.execute(
        """SELECT c.*, p.retry_count FROM calls c
           JOIN processing p ON c.id = p.call_id
           WHERE p.status = 'pending'
           ORDER BY c.started_at ASC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_retryable_calls(conn: sqlite3.Connection, max_retries: int = 3) -> list[dict]:
    """Получить звонки с ошибками для повторной обработки."""
    rows = conn.execute(
        """SELECT c.*, p.retry_count FROM calls c
           JOIN processing p ON c.id = p.call_id
           WHERE p.status = 'error' AND p.retry_count < ?
           ORDER BY c.started_at ASC""",
        (max_retries,),
    ).fetchall()
    return [dict(row) for row in rows]


# ── Operators & Departments ──────────────────────────────────────────────────

def upsert_operator(
    conn: sqlite3.Connection, domain: str, extension: str, name: str
) -> None:
    """Вставить или обновить оператора."""
    conn.execute(
        """INSERT INTO operators (domain, extension, name, synced_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(domain, extension) DO UPDATE SET name=?, synced_at=?""",
        (domain, extension, name, _now_iso(), name, _now_iso()),
    )
    conn.commit()


def get_operator_name(
    conn: sqlite3.Connection, domain: str, extension: str
) -> str | None:
    """Получить имя оператора по extension."""
    row = conn.execute(
        "SELECT name FROM operators WHERE domain = ? AND extension = ?",
        (domain, extension),
    ).fetchone()
    return row["name"] if row else None


def list_operators(conn: sqlite3.Connection, domain: str) -> list[dict]:
    """Список операторов домена."""
    rows = conn.execute(
        "SELECT * FROM operators WHERE domain = ? ORDER BY extension",
        (domain,),
    ).fetchall()
    return [dict(row) for row in rows]


def upsert_department(
    conn: sqlite3.Connection, domain: str, dept_id: int, extension: str | None, name: str
) -> None:
    """Вставить или обновить отдел."""
    conn.execute(
        """INSERT INTO departments (domain, id, extension, name, synced_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(domain, id) DO UPDATE SET extension=?, name=?, synced_at=?""",
        (domain, dept_id, extension, name, _now_iso(), extension, name, _now_iso()),
    )
    conn.commit()


def list_departments(conn: sqlite3.Connection, domain: str) -> list[dict]:
    """Список отделов домена."""
    rows = conn.execute(
        "SELECT * FROM departments WHERE domain = ? ORDER BY name",
        (domain,),
    ).fetchall()
    return [dict(row) for row in rows]


# ── Domains ──────────────────────────────────────────────────────────────────

def update_domain_poll_time(conn: sqlite3.Connection, domain: str) -> None:
    """Обновить время последнего polling."""
    conn.execute(
        """INSERT INTO domains (domain, last_polled_at)
           VALUES (?, ?)
           ON CONFLICT(domain) DO UPDATE SET last_polled_at=?""",
        (domain, _now_iso(), _now_iso()),
    )
    conn.commit()
```

**Step 4: Запустить тесты**

Run: `pytest tests/test_web/test_db.py -v`
Expected: all PASS

**Step 5: Коммит**

```bash
git add src/db.py tests/test_web/test_db.py
git commit -m "feat: add SQLite database layer for calls and processing"
```

---

## Task 4: Клиент Gravitel API (src/gravitel_api.py)

**Files:**
- Create: `src/gravitel_api.py`
- Create: `tests/test_web/test_gravitel_api.py`

**Step 1: Написать тесты**

```python
# tests/test_web/test_gravitel_api.py
"""Тесты для клиента Gravitel REST API."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import httpx

from src.gravitel_api import GravitelClient


@pytest.fixture
def client():
    return GravitelClient(domain="test.aicall.ru", api_key="test-key-123")


@pytest.mark.asyncio
async def test_fetch_history(client):
    """Получение истории звонков."""
    mock_response = httpx.Response(
        200,
        json=[
            {
                "id": "abc123",
                "type": "in",
                "account": "701",
                "client": "79991234567",
                "via": "74951112233",
                "start": "2026-03-13T14:00:00Z",
                "wait": 5,
                "duration": 120,
                "record": "https://records.aicall.ru/test/abc123.mp3",
            }
        ],
        request=httpx.Request("POST", "https://crm.aicall.ru/v1/test.aicall.ru/history"),
    )
    with patch.object(client._client, "post", new_callable=AsyncMock, return_value=mock_response):
        calls = await client.fetch_history(period="today")
    assert len(calls) == 1
    assert calls[0]["id"] == "abc123"


@pytest.mark.asyncio
async def test_fetch_history_auth_header(client):
    """Заголовок X-API-KEY передаётся."""
    mock_response = httpx.Response(
        200, json=[],
        request=httpx.Request("POST", "https://crm.aicall.ru/v1/test.aicall.ru/history"),
    )
    with patch.object(client._client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        await client.fetch_history(period="today")
    _, kwargs = mock_post.call_args
    assert kwargs.get("headers", {}).get("X-API-KEY") == "test-key-123"


@pytest.mark.asyncio
async def test_fetch_accounts(client):
    """Получение списка сотрудников."""
    mock_response = httpx.Response(
        200,
        json=[{"extension": "701", "name": "Иванов Пётр"}],
        request=httpx.Request("GET", "https://crm.aicall.ru/v1/test.aicall.ru/accounts"),
    )
    with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_response):
        accounts = await client.fetch_accounts()
    assert len(accounts) == 1
    assert accounts[0]["name"] == "Иванов Пётр"


@pytest.mark.asyncio
async def test_fetch_groups(client):
    """Получение списка отделов."""
    mock_response = httpx.Response(
        200,
        json=[{"id": 111, "extension": "700", "name": "Отдел продаж"}],
        request=httpx.Request("GET", "https://crm.aicall.ru/v1/test.aicall.ru/groups"),
    )
    with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_response):
        groups = await client.fetch_groups()
    assert len(groups) == 1
    assert groups[0]["name"] == "Отдел продаж"


@pytest.mark.asyncio
async def test_download_record(client, tmp_path):
    """Скачивание файла записи."""
    audio_content = b"\xff\xfb\x90\x00" * 100  # fake mp3
    mock_response = httpx.Response(
        200, content=audio_content,
        request=httpx.Request("GET", "https://records.aicall.ru/test/abc.mp3"),
    )
    with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_response):
        path = await client.download_record(
            "https://records.aicall.ru/test/abc.mp3",
            tmp_path / "abc.mp3",
        )
    assert path.exists()
    assert path.read_bytes() == audio_content


@pytest.mark.asyncio
async def test_fetch_history_401_raises(client):
    """401 ошибка при неверном ключе."""
    mock_response = httpx.Response(
        401, text="Unauthorized",
        request=httpx.Request("POST", "https://crm.aicall.ru/v1/test.aicall.ru/history"),
    )
    with patch.object(client._client, "post", new_callable=AsyncMock, return_value=mock_response):
        with pytest.raises(httpx.HTTPStatusError):
            await client.fetch_history(period="today")
```

**Step 2: Запустить — убедиться что падает**

Run: `pytest tests/test_web/test_gravitel_api.py -v`
Expected: FAIL

Примечание: нужен `pytest-asyncio` — добавить в requirements.txt:
```
pytest-asyncio>=0.23
```

**Step 3: Реализация**

```python
# src/gravitel_api.py
"""Клиент для Gravitel REST API (CRM-интеграция)."""

import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://crm.aicall.ru"


class GravitelClient:
    """Клиент для взаимодействия с Gravitel ВАТС API."""

    def __init__(self, domain: str, api_key: str, timeout: float = 30.0):
        self.domain = domain
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self):
        await self._client.aclose()

    def _headers(self) -> dict:
        return {"X-API-KEY": self.api_key}

    async def fetch_history(
        self,
        period: str | None = None,
        start: str | None = None,
        end: str | None = None,
        call_type: str = "all",
        limit: int | None = None,
    ) -> list[dict]:
        """Получить историю звонков домена.

        Args:
            period: today/yesterday/this_week/last_week/this_month/last_month
            start: ISO datetime начала периода
            end: ISO datetime конца периода
            call_type: all/in/out/missed
            limit: Максимум записей
        """
        url = f"{BASE_URL}/v1/{self.domain}/history"
        body: dict = {}
        if period:
            body["period"] = period
        if start:
            body["start"] = start
        if end:
            body["end"] = end
        if call_type != "all":
            body["type"] = call_type
        if limit:
            body["limit"] = limit

        resp = await self._client.post(url, json=body, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def fetch_accounts(self) -> list[dict]:
        """Получить список сотрудников АТС."""
        url = f"{BASE_URL}/v1/{self.domain}/accounts"
        resp = await self._client.get(url, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def fetch_groups(self) -> list[dict]:
        """Получить список отделов АТС."""
        url = f"{BASE_URL}/v1/{self.domain}/groups"
        resp = await self._client.get(url, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def download_record(self, record_url: str, save_path: Path) -> Path:
        """Скачать файл записи разговора.

        Args:
            record_url: URL записи (https://records.aicall.ru/...).
            save_path: Куда сохранить файл.

        Returns:
            Путь к сохранённому файлу.
        """
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        resp = await self._client.get(record_url, headers=self._headers())
        resp.raise_for_status()
        save_path.write_bytes(resp.content)

        logger.info("Скачан: %s → %s (%d bytes)", record_url, save_path, len(resp.content))
        return save_path
```

**Step 4: Запустить тесты**

Run: `pytest tests/test_web/test_gravitel_api.py -v`
Expected: all PASS

**Step 5: Коммит**

```bash
git add src/gravitel_api.py tests/test_web/test_gravitel_api.py requirements.txt
git commit -m "feat: add Gravitel API client for history, accounts, and recordings"
```

---

## Task 5: Фильтр звонков (src/call_filter.py)

**Files:**
- Create: `src/call_filter.py`
- Create: `tests/test_web/test_call_filter.py`

**Step 1: Написать тесты**

```python
# tests/test_web/test_call_filter.py
"""Тесты фильтрации звонков."""

import pytest
from src.call_filter import filter_call
from src.domain_config import CallFilters


@pytest.fixture
def default_filters():
    return CallFilters(
        min_duration_sec=20,
        max_duration_sec=1500,
        call_types=["in", "out"],
        only_with_record=True,
        results=["success"],
    )


SAMPLE_CALL = {
    "duration": 120,
    "direction": "in",
    "result": "success",
    "record_url": "https://records.aicall.ru/test/abc.mp3",
}


def test_call_passes_all_filters(default_filters):
    """Звонок, соответствующий всем фильтрам, проходит."""
    ok, reason = filter_call(SAMPLE_CALL, default_filters)
    assert ok is True
    assert reason is None


def test_call_too_short(default_filters):
    """Короткий звонок отфильтровывается."""
    call = {**SAMPLE_CALL, "duration": 15}
    ok, reason = filter_call(call, default_filters)
    assert ok is False
    assert "too short" in reason


def test_call_too_long(default_filters):
    """Длинный звонок отфильтровывается."""
    call = {**SAMPLE_CALL, "duration": 1800}
    ok, reason = filter_call(call, default_filters)
    assert ok is False
    assert "too long" in reason


def test_call_no_record(default_filters):
    """Звонок без записи отфильтровывается."""
    call = {**SAMPLE_CALL, "record_url": None}
    ok, reason = filter_call(call, default_filters)
    assert ok is False
    assert "no record" in reason


def test_call_empty_record(default_filters):
    """Звонок с пустой записью отфильтровывается."""
    call = {**SAMPLE_CALL, "record_url": ""}
    ok, reason = filter_call(call, default_filters)
    assert ok is False
    assert "no record" in reason


def test_call_wrong_result(default_filters):
    """Звонок с неуспешным результатом отфильтровывается."""
    call = {**SAMPLE_CALL, "result": "missed"}
    ok, reason = filter_call(call, default_filters)
    assert ok is False
    assert "result: missed" in reason


def test_call_wrong_type(default_filters):
    """Звонок неподходящего типа отфильтровывается."""
    filters = CallFilters(
        min_duration_sec=20, max_duration_sec=1500,
        call_types=["in"], only_with_record=True, results=["success"],
    )
    call = {**SAMPLE_CALL, "direction": "out"}
    ok, reason = filter_call(call, filters)
    assert ok is False
    assert "type: out" in reason


def test_call_zero_duration(default_filters):
    """Звонок с нулевой длительностью отфильтровывается."""
    call = {**SAMPLE_CALL, "duration": 0}
    ok, reason = filter_call(call, default_filters)
    assert ok is False
    assert "too short" in reason


def test_call_none_duration(default_filters):
    """Звонок без duration — фильтруется как too short."""
    call = {**SAMPLE_CALL, "duration": None}
    ok, reason = filter_call(call, default_filters)
    assert ok is False
    assert "too short" in reason
```

**Step 2: Запустить — убедиться что падает**

Run: `pytest tests/test_web/test_call_filter.py -v`
Expected: FAIL

**Step 3: Реализация**

```python
# src/call_filter.py
"""Фильтрация звонков по конфигурации домена."""

from src.domain_config import CallFilters


def filter_call(call: dict, filters: CallFilters) -> tuple[bool, str | None]:
    """Проверить звонок на соответствие фильтрам.

    Args:
        call: Данные звонка (duration, direction, result, record_url).
        filters: Настройки фильтрации из конфига домена.

    Returns:
        (True, None) если звонок проходит фильтры.
        (False, reason) если звонок отфильтрован.
    """
    # Запись
    if filters.only_with_record and not call.get("record_url"):
        return False, "no record"

    # Длительность
    duration = call.get("duration") or 0
    if duration < filters.min_duration_sec:
        return False, f"too short ({duration}s < {filters.min_duration_sec}s)"
    if duration > filters.max_duration_sec:
        return False, f"too long ({duration}s > {filters.max_duration_sec}s)"

    # Результат
    result = call.get("result", "")
    if result not in filters.results:
        return False, f"result: {result}"

    # Тип звонка
    direction = call.get("direction", "")
    if "all" not in filters.call_types and direction not in filters.call_types:
        return False, f"type: {direction}"

    return True, None
```

**Step 4: Запустить тесты**

Run: `pytest tests/test_web/test_call_filter.py -v`
Expected: all PASS

**Step 5: Коммит**

```bash
git add src/call_filter.py tests/test_web/test_call_filter.py
git commit -m "feat: add call filter with duration, type, and result checks"
```

---

## Task 6: Webhook-роуты (src/web/routes/webhook.py)

**Files:**
- Create: `src/web/routes/webhook.py`
- Create: `tests/test_web/test_webhook.py`

**Step 1: Написать тесты**

```python
# tests/test_web/test_webhook.py
"""Тесты для webhook-приёмника."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

from src.web.routes.webhook import router, set_dependencies


@pytest.fixture
def app(tmp_path):
    """FastAPI app с webhook-роутами."""
    from src.db import init_db
    from src.domain_config import DomainConfig, CallFilters

    db = init_db(str(tmp_path / "test.db"))
    configs = {
        "test.aicall.ru": DomainConfig(
            api_key_env="TEST_KEY",
            profile="gravitel",
            enabled=True,
            polling_interval_min=10,
            filters=CallFilters(),
        ),
    }

    app = FastAPI()
    app.include_router(router)
    set_dependencies(db=db, domain_configs=configs, api_keys={"test.aicall.ru": "secret-key"})
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


SAMPLE_WEBHOOK = {
    "id": "abc123",
    "when": 1710338400,
    "direction": "in",
    "result": "success",
    "duration": 120,
    "provision": 5,
    "client": "79991234567",
    "extension": "701",
    "phone": "74951112233",
    "record": "https://records.aicall.ru/test/abc123.mp3",
}


def test_webhook_valid_call(client):
    """Валидный webhook сохраняет звонок."""
    resp = client.post(
        "/webhook/test.aicall.ru/history",
        json=SAMPLE_WEBHOOK,
        headers={"X-API-KEY": "secret-key"},
    )
    assert resp.status_code == 200


def test_webhook_invalid_api_key(client):
    """Неверный API-ключ → 401."""
    resp = client.post(
        "/webhook/test.aicall.ru/history",
        json=SAMPLE_WEBHOOK,
        headers={"X-API-KEY": "wrong-key"},
    )
    assert resp.status_code == 401


def test_webhook_missing_api_key(client):
    """Отсутствующий API-ключ → 401."""
    resp = client.post(
        "/webhook/test.aicall.ru/history",
        json=SAMPLE_WEBHOOK,
    )
    assert resp.status_code == 401


def test_webhook_unknown_domain(client):
    """Неизвестный домен → 404."""
    resp = client.post(
        "/webhook/unknown.aicall.ru/history",
        json=SAMPLE_WEBHOOK,
        headers={"X-API-KEY": "secret-key"},
    )
    assert resp.status_code == 404


def test_webhook_duplicate_call_idempotent(client):
    """Повторный webhook для того же звонка — идемпотентен."""
    headers = {"X-API-KEY": "secret-key"}
    resp1 = client.post("/webhook/test.aicall.ru/history", json=SAMPLE_WEBHOOK, headers=headers)
    resp2 = client.post("/webhook/test.aicall.ru/history", json=SAMPLE_WEBHOOK, headers=headers)
    assert resp1.status_code == 200
    assert resp2.status_code == 200


def test_webhook_short_call_skipped(client):
    """Короткий звонок → skipped."""
    short_call = {**SAMPLE_WEBHOOK, "id": "short1", "duration": 5}
    resp = client.post(
        "/webhook/test.aicall.ru/history",
        json=short_call,
        headers={"X-API-KEY": "secret-key"},
    )
    assert resp.status_code == 200
```

**Step 2: Запустить — убедиться что падает**

Run: `pytest tests/test_web/test_webhook.py -v`
Expected: FAIL

**Step 3: Реализация**

```python
# src/web/routes/webhook.py
"""Webhook-приёмник для событий от Гравител АТС."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request

from src.db import insert_call, insert_processing, get_call
from src.call_filter import filter_call
from src.domain_config import DomainConfig

logger = logging.getLogger(__name__)

router = APIRouter()

# Зависимости — инжектятся из app.py
_db = None
_domain_configs: dict[str, DomainConfig] = {}
_api_keys: dict[str, str] = {}  # domain → api_key
_on_new_call = None  # callback для добавления в очередь worker


def set_dependencies(
    db,
    domain_configs: dict[str, DomainConfig],
    api_keys: dict[str, str],
    on_new_call=None,
):
    global _db, _domain_configs, _api_keys, _on_new_call
    _db = db
    _domain_configs = domain_configs
    _api_keys = api_keys
    _on_new_call = on_new_call


@router.post("/webhook/{domain}/history")
async def receive_history(domain: str, request: Request, x_api_key: str = Header(None)):
    """Принять webhook от АТС о завершённом звонке."""
    # Проверка домена
    if domain not in _domain_configs:
        raise HTTPException(status_code=404, detail="Unknown domain")

    # Проверка API-ключа
    expected_key = _api_keys.get(domain)
    if not x_api_key or x_api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    body = await request.json()

    # Преобразование формата webhook → внутренний формат call
    when = body.get("when")
    started_at = (
        datetime.fromtimestamp(when, tz=timezone.utc).isoformat()
        if isinstance(when, (int, float))
        else when
    )

    call = {
        "id": body["id"],
        "domain": domain,
        "direction": body.get("direction", ""),
        "result": body.get("result", ""),
        "duration": body.get("duration", 0),
        "wait": body.get("provision", 0),
        "started_at": started_at,
        "client_number": body.get("client", ""),
        "operator_extension": body.get("extension", ""),
        "operator_name": None,
        "phone": body.get("phone", ""),
        "record_url": body.get("record", ""),
        "source": "webhook",
    }

    # Дедупликация
    if get_call(_db, call["id"]):
        logger.debug("Дубликат webhook: %s", call["id"])
        return {"status": "duplicate"}

    # Сохранение
    insert_call(_db, call)

    # Фильтрация
    config = _domain_configs[domain]
    passed, reason = filter_call(call, config.filters)

    if passed:
        insert_processing(_db, call["id"], status="pending")
        logger.info("Webhook: новый звонок %s → pending", call["id"])
        if _on_new_call:
            _on_new_call(call["id"])
    else:
        insert_processing(_db, call["id"], status="skipped", skip_reason=reason)
        logger.info("Webhook: звонок %s → skipped (%s)", call["id"], reason)

    return {"status": "ok"}
```

**Step 4: Запустить тесты**

Run: `pytest tests/test_web/test_webhook.py -v`
Expected: all PASS

**Step 5: Коммит**

```bash
git add src/web/routes/webhook.py tests/test_web/test_webhook.py
git commit -m "feat: add webhook receiver with auth, dedup, and filtering"
```

---

## Task 7: REST API роуты (src/web/routes/api.py)

**Files:**
- Create: `src/web/routes/api.py`
- Create: `tests/test_web/test_api.py`

**Step 1: Написать тесты**

```python
# tests/test_web/test_api.py
"""Тесты REST API для фронтенда."""

import json
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from src.web.routes.api import router, set_dependencies


@pytest.fixture
def db_with_data(tmp_path):
    """БД с тестовыми данными."""
    from src.db import init_db, insert_call, insert_processing, upsert_operator

    db = init_db(str(tmp_path / "test.db"))

    for i in range(5):
        call = {
            "id": f"call_{i}",
            "domain": "test.aicall.ru",
            "direction": "in" if i % 2 == 0 else "out",
            "result": "success",
            "duration": 60 + i * 10,
            "wait": 5,
            "started_at": f"2026-03-13T14:{i:02d}:00Z",
            "client_number": f"7999{i:07d}",
            "operator_extension": "701",
            "operator_name": None,
            "phone": "74951112233",
            "record_url": f"https://records.aicall.ru/test/call_{i}.mp3",
            "source": "webhook",
        }
        insert_call(db, call)
        if i < 3:
            insert_processing(db, f"call_{i}", status="done")
        else:
            insert_processing(db, f"call_{i}", status="pending")

    upsert_operator(db, "test.aicall.ru", "701", "Иванов Пётр")
    return db


@pytest.fixture
def client(db_with_data):
    app = FastAPI()
    app.include_router(router)
    set_dependencies(db=db_with_data, domain_configs={})
    return TestClient(app)


def test_list_calls(client):
    """GET /api/calls возвращает список звонков."""
    resp = client.get("/api/calls")
    assert resp.status_code == 200
    data = resp.json()
    assert "calls" in data
    assert "total" in data
    assert data["total"] == 5


def test_list_calls_filter_direction(client):
    """Фильтр по направлению."""
    resp = client.get("/api/calls?direction=in")
    data = resp.json()
    assert all(c["direction"] == "in" for c in data["calls"])


def test_list_calls_filter_status(client):
    """Фильтр по статусу обработки."""
    resp = client.get("/api/calls?status=done")
    data = resp.json()
    assert data["total"] == 3


def test_list_calls_pagination(client):
    """Пагинация."""
    resp = client.get("/api/calls?per_page=2&page=1")
    data = resp.json()
    assert len(data["calls"]) == 2


def test_get_call_detail(client):
    """GET /api/calls/{id} — детали звонка."""
    resp = client.get("/api/calls/call_0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "call_0"


def test_get_call_not_found(client):
    """404 для несуществующего звонка."""
    resp = client.get("/api/calls/nonexistent")
    assert resp.status_code == 404


def test_stats(client):
    """GET /api/stats — сводная статистика."""
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_calls" in data
    assert "pending" in data
    assert "done" in data


def test_domains_list(client):
    """GET /api/domains — список доменов."""
    resp = client.get("/api/domains")
    assert resp.status_code == 200
```

**Step 2: Запустить — падает**

Run: `pytest tests/test_web/test_api.py -v`

**Step 3: Реализация**

```python
# src/web/routes/api.py
"""REST API для веб-интерфейса."""

import logging

from fastapi import APIRouter, HTTPException, Query

from src.db import (
    get_call,
    list_calls,
    get_calls_count,
    get_processing,
    list_operators,
    list_departments,
)
from src.domain_config import DomainConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_db = None
_domain_configs: dict[str, DomainConfig] = {}


def set_dependencies(db, domain_configs: dict[str, DomainConfig]):
    global _db, _domain_configs
    _db = db
    _domain_configs = domain_configs


@router.get("/calls")
def api_list_calls(
    domain: str | None = None,
    direction: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    operator: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    """Список звонков с фильтрами и пагинацией."""
    calls = list_calls(
        _db,
        domain=domain,
        direction=direction,
        status=status,
        date_from=date_from,
        date_to=date_to,
        operator=operator,
        page=page,
        per_page=per_page,
    )
    total = get_calls_count(_db, domain=domain, status=status)
    return {"calls": calls, "total": total, "page": page, "per_page": per_page}


@router.get("/calls/{call_id}")
def api_call_detail(call_id: str):
    """Детали одного звонка с результатами анализа."""
    call = get_call(_db, call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    proc = get_processing(_db, call_id)
    return {**call, "processing": dict(proc) if proc else None}


@router.get("/stats")
def api_stats(domain: str | None = None):
    """Сводная статистика."""
    total = get_calls_count(_db, domain=domain)
    pending = get_calls_count(_db, domain=domain, status="pending")
    processing = get_calls_count(_db, domain=domain, status="processing")
    done = get_calls_count(_db, domain=domain, status="done")
    error = get_calls_count(_db, domain=domain, status="error")
    skipped = get_calls_count(_db, domain=domain, status="skipped")

    return {
        "total_calls": total,
        "pending": pending,
        "processing": processing,
        "done": done,
        "error": error,
        "skipped": skipped,
    }


@router.get("/domains")
def api_domains():
    """Список настроенных доменов."""
    result = []
    for domain, cfg in _domain_configs.items():
        total = get_calls_count(_db, domain=domain)
        done = get_calls_count(_db, domain=domain, status="done")
        result.append({
            "domain": domain,
            "enabled": cfg.enabled,
            "profile": cfg.profile,
            "polling_interval_min": cfg.polling_interval_min,
            "total_calls": total,
            "done_calls": done,
        })
    return result


@router.get("/operators/{domain}")
def api_operators(domain: str):
    """Список операторов домена."""
    return list_operators(_db, domain)


@router.get("/departments/{domain}")
def api_departments(domain: str):
    """Список отделов домена."""
    return list_departments(_db, domain)
```

**Step 4: Запустить тесты**

Run: `pytest tests/test_web/test_api.py -v`
Expected: all PASS

**Step 5: Коммит**

```bash
git add src/web/routes/api.py tests/test_web/test_api.py
git commit -m "feat: add REST API routes for calls, stats, and domains"
```

---

## Task 8: Worker — фоновая обработка (src/worker.py)

**Files:**
- Create: `src/worker.py`
- Create: `tests/test_web/test_worker.py`

**Step 1: Написать тесты**

```python
# tests/test_web/test_worker.py
"""Тесты фонового обработчика звонков."""

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path

from src.db import init_db, insert_call, insert_processing, get_processing
from src.worker import CallWorker


SAMPLE_CALL = {
    "id": "abc123",
    "domain": "test.aicall.ru",
    "direction": "in",
    "result": "success",
    "duration": 120,
    "wait": 5,
    "started_at": "2026-03-13T14:00:00Z",
    "client_number": "79991234567",
    "operator_extension": "701",
    "operator_name": None,
    "phone": "74951112233",
    "record_url": "https://records.aicall.ru/test/abc123.mp3",
    "source": "webhook",
}


@pytest.fixture
def db(tmp_path):
    db = init_db(str(tmp_path / "test.db"))
    insert_call(db, SAMPLE_CALL)
    insert_processing(db, "abc123", status="pending")
    return db


@pytest.fixture
def worker(db, tmp_path):
    return CallWorker(
        db=db,
        audio_dir=tmp_path / "audio",
        domain_configs={
            "test.aicall.ru": MagicMock(profile="gravitel"),
        },
        api_clients={},
    )


def test_worker_process_call_success(worker, tmp_path):
    """Успешная обработка звонка."""
    fake_audio = tmp_path / "audio" / "abc123.mp3"
    fake_audio.parent.mkdir(parents=True, exist_ok=True)
    fake_audio.write_bytes(b"\xff\xfb\x90\x00" * 100)

    fake_result = {
        "file": "abc123.mp3",
        "transcript": "Оператор: Здравствуйте.",
        "summary": {"topic": "тест"},
        "quality_score": {"total": 8},
        "extracted_data": {},
    }

    with patch.object(worker, "_download_record", return_value=fake_audio):
        with patch("src.worker.process_audio_file", return_value=fake_result):
            worker.process_one("abc123")

    proc = get_processing(worker.db, "abc123")
    assert proc["status"] == "done"
    assert proc["result_json"] is not None
    result = json.loads(proc["result_json"])
    assert result["quality_score"]["total"] == 8


def test_worker_process_call_download_error(worker):
    """Ошибка скачивания → status=error."""
    with patch.object(worker, "_download_record", side_effect=Exception("Network error")):
        worker.process_one("abc123")

    proc = get_processing(worker.db, "abc123")
    assert proc["status"] == "error"
    assert "Network error" in proc["error_message"]


def test_worker_process_call_pipeline_error(worker, tmp_path):
    """Ошибка в pipeline → status=error."""
    fake_audio = tmp_path / "audio" / "abc123.mp3"
    fake_audio.parent.mkdir(parents=True, exist_ok=True)
    fake_audio.write_bytes(b"\xff\xfb\x90\x00")

    with patch.object(worker, "_download_record", return_value=fake_audio):
        with patch("src.worker.process_audio_file", side_effect=RuntimeError("Ollama timeout")):
            worker.process_one("abc123")

    proc = get_processing(worker.db, "abc123")
    assert proc["status"] == "error"
    assert "Ollama timeout" in proc["error_message"]
```

**Step 2: Запустить — падает**

Run: `pytest tests/test_web/test_worker.py -v`

**Step 3: Реализация**

```python
# src/worker.py
"""Фоновый обработчик звонков — скачивание и запуск pipeline."""

import json
import logging
import time
from pathlib import Path

from src.db import (
    get_call,
    get_pending_calls,
    get_retryable_calls,
    get_processing,
    update_processing_status,
)
from src.pipeline import process_audio_file
from src.config import PROMPTS_DIR, RESULTS_DIR

logger = logging.getLogger(__name__)


class CallWorker:
    """Обработчик звонков: скачивание записей и запуск pipeline."""

    def __init__(self, db, audio_dir: Path, domain_configs: dict, api_clients: dict):
        self.db = db
        self.audio_dir = Path(audio_dir)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.domain_configs = domain_configs
        self.api_clients = api_clients  # domain → GravitelClient

    def _download_record(self, call: dict) -> Path:
        """Скачать запись звонка (синхронно, для ThreadPoolExecutor)."""
        import httpx

        record_url = call["record_url"]
        save_path = self.audio_dir / call["domain"] / f"{call['id']}.mp3"
        save_path.parent.mkdir(parents=True, exist_ok=True)

        resp = httpx.get(record_url, timeout=60.0)
        resp.raise_for_status()
        save_path.write_bytes(resp.content)

        logger.info("Скачан: %s → %s", record_url, save_path)
        return save_path

    def process_one(self, call_id: str) -> None:
        """Обработать один звонок: скачать → pipeline → сохранить результат."""
        call = get_call(self.db, call_id)
        if not call:
            logger.error("Звонок не найден: %s", call_id)
            return

        update_processing_status(self.db, call_id, status="downloading")
        start_time = time.monotonic()

        try:
            # 1. Скачивание
            audio_path = self._download_record(call)
            update_processing_status(
                self.db, call_id, status="processing", audio_path=str(audio_path)
            )

            # 2. Pipeline
            domain = call["domain"]
            config = self.domain_configs.get(domain)
            profile_name = config.profile if config else None

            result = process_audio_file(
                audio_path=audio_path,
                output_dir=RESULTS_DIR / domain,
                prompts_dir=PROMPTS_DIR,
                profile_name=profile_name,
            )

            # 3. Сохранение результата
            processing_time = time.monotonic() - start_time
            update_processing_status(
                self.db,
                call_id,
                status="done",
                result_json=json.dumps(result, ensure_ascii=False),
                processing_time_sec=processing_time,
            )
            logger.info(
                "Обработан: %s (%.1f сек)", call_id, processing_time
            )

        except Exception as e:
            processing_time = time.monotonic() - start_time
            logger.error("Ошибка обработки %s: %s", call_id, e)
            update_processing_status(
                self.db,
                call_id,
                status="error",
                error_message=str(e),
                processing_time_sec=processing_time,
            )

    def process_pending(self) -> int:
        """Обработать все ожидающие звонки. Возвращает количество обработанных."""
        pending = get_pending_calls(self.db)
        retryable = get_retryable_calls(self.db)

        all_to_process = pending + retryable
        if not all_to_process:
            return 0

        logger.info("В очереди: %d звонков", len(all_to_process))
        processed = 0
        for call in all_to_process:
            # Сбросить статус error → pending для retry
            proc = get_processing(self.db, call["id"])
            if proc and proc["status"] == "error":
                update_processing_status(self.db, call["id"], status="pending")

            self.process_one(call["id"])
            processed += 1

        return processed
```

**Step 4: Запустить тесты**

Run: `pytest tests/test_web/test_worker.py -v`
Expected: all PASS

**Step 5: Коммит**

```bash
git add src/worker.py tests/test_web/test_worker.py
git commit -m "feat: add background call worker with download and pipeline processing"
```

---

## Task 9: FastAPI-приложение (src/web/app.py)

**Files:**
- Create: `src/web/app.py`

Этот модуль собирает всё вместе: роуты, scheduler, worker, lifespan.

**Step 1: Реализация**

```python
# src/web/app.py
"""FastAPI-приложение — точка входа веб-сервера."""

import asyncio
import logging
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config import PROJECT_ROOT, DATA_DIR
from src.db import init_db, update_domain_poll_time, upsert_operator, upsert_department
from src.domain_config import load_domains_config
from src.gravitel_api import GravitelClient
from src.worker import CallWorker
from src.web.routes import webhook, api

load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "calls.db"
AUDIO_DIR = DATA_DIR / "audio"
TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

# Глобальные объекты (инициализируются в lifespan)
_db = None
_worker = None
_executor = ThreadPoolExecutor(max_workers=1)
_api_clients: dict[str, GravitelClient] = {}
_domain_configs = {}
_scheduler_task = None


def _resolve_api_keys(configs: dict) -> dict[str, str]:
    """Получить API-ключи из переменных окружения."""
    keys = {}
    for domain, cfg in configs.items():
        key = os.environ.get(cfg.api_key_env, "")
        if not key:
            logger.warning("API-ключ %s не задан для %s", cfg.api_key_env, domain)
        keys[domain] = key
    return keys


async def _sync_directory(domain: str, client: GravitelClient) -> None:
    """Синхронизировать справочники (operators, departments) для домена."""
    try:
        accounts = await client.fetch_accounts()
        for acc in accounts:
            upsert_operator(_db, domain, acc["extension"], acc["name"])
        logger.info("Синхронизировано %d операторов для %s", len(accounts), domain)
    except Exception as e:
        logger.error("Ошибка синхронизации accounts %s: %s", domain, e)

    try:
        groups = await client.fetch_groups()
        for grp in groups:
            upsert_department(_db, domain, grp["id"], grp.get("extension"), grp["name"])
        logger.info("Синхронизировано %d отделов для %s", len(groups), domain)
    except Exception as e:
        logger.error("Ошибка синхронизации groups %s: %s", domain, e)


async def _poll_domain(domain: str, client: GravitelClient) -> None:
    """Опросить историю звонков домена и добавить новые в очередь."""
    from src.db import insert_call, insert_processing, get_call
    from src.call_filter import filter_call

    try:
        calls = await client.fetch_history(period="today")
        new_count = 0
        for raw in calls:
            call = {
                "id": raw["id"],
                "domain": domain,
                "direction": raw.get("type", ""),
                "result": "success" if raw.get("duration", 0) > 0 else "missed",
                "duration": raw.get("duration", 0),
                "wait": raw.get("wait", 0),
                "started_at": raw.get("start", ""),
                "client_number": raw.get("client", ""),
                "operator_extension": raw.get("account", ""),
                "operator_name": None,
                "phone": raw.get("via", ""),
                "record_url": raw.get("record", ""),
                "source": "polling",
            }

            if get_call(_db, call["id"]):
                continue

            insert_call(_db, call)
            config = _domain_configs[domain]
            passed, reason = filter_call(call, config.filters)

            if passed:
                insert_processing(_db, call["id"], status="pending")
                new_count += 1
            else:
                insert_processing(_db, call["id"], status="skipped", skip_reason=reason)

        update_domain_poll_time(_db, domain)
        if new_count:
            logger.info("Polling %s: %d новых звонков", domain, new_count)
    except Exception as e:
        logger.error("Polling ошибка %s: %s", domain, e)


async def _scheduler_loop():
    """Фоновый цикл: polling + обработка + синхронизация справочников."""
    sync_counter = 0
    while True:
        try:
            # Polling всех доменов
            for domain, cfg in _domain_configs.items():
                if not cfg.enabled:
                    continue
                client = _api_clients.get(domain)
                if client:
                    await _poll_domain(domain, client)

            # Обработка в фоновом потоке (не блокируем event loop)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(_executor, _worker.process_pending)

            # Синхронизация справочников каждые 6 циклов (≈60 мин при 10 мин интервале)
            sync_counter += 1
            if sync_counter >= 6:
                sync_counter = 0
                for domain, client in _api_clients.items():
                    await _sync_directory(domain, client)

        except Exception as e:
            logger.error("Scheduler error: %s", e)

        await asyncio.sleep(600)  # 10 мин


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация при старте, очистка при остановке."""
    global _db, _worker, _domain_configs, _api_clients, _scheduler_task

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # БД
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _db = init_db(str(DB_PATH))

    # Конфиг доменов
    _domain_configs = load_domains_config()
    api_keys = _resolve_api_keys(_domain_configs)

    # API-клиенты
    for domain, cfg in _domain_configs.items():
        if cfg.enabled and api_keys.get(domain):
            _api_clients[domain] = GravitelClient(domain, api_keys[domain])

    # Worker
    _worker = CallWorker(
        db=_db,
        audio_dir=AUDIO_DIR,
        domain_configs=_domain_configs,
        api_clients=_api_clients,
    )

    # Инжекция зависимостей в роуты
    webhook.set_dependencies(
        db=_db,
        domain_configs=_domain_configs,
        api_keys=api_keys,
        on_new_call=lambda call_id: None,  # worker подхватит в следующем цикле
    )
    api.set_dependencies(db=_db, domain_configs=_domain_configs)

    # Первичная синхронизация справочников
    for domain, client in _api_clients.items():
        await _sync_directory(domain, client)

    # Запуск scheduler
    _scheduler_task = asyncio.create_task(_scheduler_loop())
    logger.info("AI Lab Web запущен. Доменов: %d", len(_domain_configs))

    yield

    # Cleanup
    _scheduler_task.cancel()
    _executor.shutdown(wait=False)
    for client in _api_clients.values():
        await client.close()
    _db.close()
    logger.info("AI Lab Web остановлен.")


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="AI Lab — Анализ звонков", lifespan=lifespan)

app.include_router(webhook.router)
app.include_router(api.router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Главная страница."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/call/{call_id}", response_class=HTMLResponse)
async def call_detail(request: Request, call_id: str):
    """Страница деталей звонка."""
    return templates.TemplateResponse("call_detail.html", {
        "request": request,
        "call_id": call_id,
    })


@app.post("/api/sync/{domain}")
async def manual_sync(domain: str):
    """Ручной запуск polling для домена."""
    client = _api_clients.get(domain)
    if not client:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Domain not configured")

    await _poll_domain(domain, client)

    loop = asyncio.get_event_loop()
    processed = await loop.run_in_executor(_executor, _worker.process_pending)

    return {"status": "ok", "processed": processed}
```

**Step 2: Коммит**

```bash
git add src/web/app.py
git commit -m "feat: add FastAPI app with lifespan, scheduler, and manual sync"
```

---

## Task 10: Веб-интерфейс (шаблоны и статика)

**Files:**
- Create: `src/web/templates/base.html`
- Create: `src/web/templates/index.html`
- Create: `src/web/templates/call_detail.html`
- Create: `src/web/static/style.css`
- Create: `src/web/static/app.js`

Содержимое шаблонов — реализовать по макетам из дизайн-документа (Секция 4).

`base.html` — общий layout (header, footer, подключение CSS/JS).

`index.html` — таблица звонков:
- Фильтры (домен, период, статус, оператор)
- Таблица: время, направление, клиент, оператор, длительность, оценка, статус
- Пагинация
- Кнопка Sync
- Автообновление через fetch каждые 30 сек

`call_detail.html` — детали звонка:
- Метаданные (домен, дата, направление, длительность, оператор)
- Оценка качества (total + критерии)
- Резюме (topic, outcome, action_items)
- Извлечённые данные
- Транскрипт

`style.css` — минимальные стили: таблица, карточки, цветовая индикация оценок.

`app.js` — vanilla JS:
- Загрузка данных через fetch `/api/calls`
- Обработка фильтров и пагинации
- Автообновление
- Кнопка Sync → POST `/api/sync/{domain}`

**Step 1: Создать все файлы шаблонов и статики**

(Шаблоны создаются по макетам, см. дизайн-документ Секция 4. Код шаблонов ~200-300 строк суммарно.)

**Step 2: Ручная проверка**

Run: `uvicorn src.web.app:app --reload --port 8080`
Открыть: `http://localhost:8080/` — должна отображаться страница.

**Step 3: Коммит**

```bash
git add src/web/templates/ src/web/static/
git commit -m "feat: add web UI templates and static assets"
```

---

## Task 11: Интеграционный тест

**Files:**
- Create: `tests/test_web/test_integration.py`

**Step 1: Написать интеграционный тест**

```python
# tests/test_web/test_integration.py
"""Интеграционный тест: webhook → фильтр → worker → результат."""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.db import init_db, get_call, get_processing
from src.domain_config import DomainConfig, CallFilters
from src.call_filter import filter_call
from src.worker import CallWorker


@pytest.fixture
def full_setup(tmp_path):
    """Полный setup: БД + конфиг + worker."""
    db = init_db(str(tmp_path / "test.db"))
    config = DomainConfig(
        api_key_env="TEST_KEY",
        profile="gravitel",
        enabled=True,
        polling_interval_min=10,
        filters=CallFilters(min_duration_sec=20, max_duration_sec=1500),
    )
    worker = CallWorker(
        db=db,
        audio_dir=tmp_path / "audio",
        domain_configs={"test.aicall.ru": config},
        api_clients={},
    )
    return db, config, worker


def test_full_cycle_webhook_to_result(full_setup, tmp_path):
    """Полный цикл: звонок → фильтр → обработка → результат в БД."""
    db, config, worker = full_setup

    # 1. Имитация webhook
    from src.db import insert_call, insert_processing

    call = {
        "id": "integration_test_001",
        "domain": "test.aicall.ru",
        "direction": "in",
        "result": "success",
        "duration": 120,
        "wait": 5,
        "started_at": "2026-03-13T14:00:00Z",
        "client_number": "79991234567",
        "operator_extension": "701",
        "operator_name": None,
        "phone": "74951112233",
        "record_url": "https://records.aicall.ru/test/integration.mp3",
        "source": "webhook",
    }
    insert_call(db, call)

    # 2. Фильтрация
    passed, reason = filter_call(call, config.filters)
    assert passed is True
    insert_processing(db, call["id"], status="pending")

    # 3. Обработка с моками
    fake_result = {
        "file": "integration.mp3",
        "transcript": "[00:01] Оператор: Здравствуйте.\n[00:03] Клиент: Привет.",
        "summary": {"topic": "консультация", "outcome": "решено"},
        "quality_score": {"total": 8, "is_ivr": False},
        "extracted_data": {"operator_name": "Иванов"},
    }

    fake_audio = tmp_path / "audio" / "integration.mp3"
    fake_audio.parent.mkdir(parents=True, exist_ok=True)
    fake_audio.write_bytes(b"\xff" * 100)

    with patch.object(worker, "_download_record", return_value=fake_audio):
        with patch("src.worker.process_audio_file", return_value=fake_result):
            worker.process_one("integration_test_001")

    # 4. Проверка результата
    proc = get_processing(db, "integration_test_001")
    assert proc["status"] == "done"
    result = json.loads(proc["result_json"])
    assert result["quality_score"]["total"] == 8
    assert proc["processing_time_sec"] > 0


def test_short_call_skipped_in_full_cycle(full_setup):
    """Короткий звонок пропускается в полном цикле."""
    db, config, worker = full_setup

    from src.db import insert_call, insert_processing

    call = {
        "id": "short_call_001",
        "domain": "test.aicall.ru",
        "direction": "in",
        "result": "success",
        "duration": 10,
        "wait": 2,
        "started_at": "2026-03-13T14:00:00Z",
        "client_number": "79991234567",
        "operator_extension": "701",
        "operator_name": None,
        "phone": "74951112233",
        "record_url": "https://records.aicall.ru/test/short.mp3",
        "source": "webhook",
    }
    insert_call(db, call)

    passed, reason = filter_call(call, config.filters)
    assert passed is False
    assert "too short" in reason

    insert_processing(db, call["id"], status="skipped", skip_reason=reason)
    proc = get_processing(db, "short_call_001")
    assert proc["status"] == "skipped"
```

**Step 2: Запустить**

Run: `pytest tests/test_web/test_integration.py -v`
Expected: all PASS

**Step 3: Запустить все тесты проекта**

Run: `pytest tests/ -v`
Expected: all PASS (старые + новые)

**Step 4: Коммит**

```bash
git add tests/test_web/test_integration.py
git commit -m "test: add integration test for full webhook-to-result cycle"
```

---

## Task 12: Документация и финализация

**Files:**
- Modify: `agent_docs/development-history.md`
- Modify: `agent_docs/architecture.md`

**Step 1: Обновить development-history.md**

Добавить запись о реализации web API integration.

**Step 2: Обновить architecture.md**

Добавить секции о новых компонентах: web server, webhook, polling, worker.

**Step 3: Финальная проверка**

Run: `pytest tests/ -v` — все тесты проходят
Run: `uvicorn src.web.app:app --port 8080` — приложение стартует

**Step 4: Коммит**

```bash
git add agent_docs/
git commit -m "docs: update architecture and development history for web integration"
```

---

## Порядок зависимостей между тасками

```
Task 1 (deps/structure)
  └→ Task 2 (domain_config)
       └→ Task 3 (db)
            ├→ Task 4 (gravitel_api)
            ├→ Task 5 (call_filter) — зависит от Task 2
            ├→ Task 6 (webhook) — зависит от Tasks 3, 5
            ├→ Task 7 (api routes) — зависит от Task 3
            └→ Task 8 (worker) — зависит от Tasks 3, 4
                 └→ Task 9 (app.py) — зависит от Tasks 6, 7, 8
                      └→ Task 10 (templates) — зависит от Task 9
                           └→ Task 11 (integration) — зависит от всего
                                └→ Task 12 (docs)
```

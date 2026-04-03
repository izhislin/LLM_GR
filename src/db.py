"""Модуль базы данных (SQLite).

Управляет хранением звонков, статусов обработки, операторов и отделов.
Используется синхронный sqlite3 для простоты; при необходимости
можно обернуть в aiosqlite для async-контекста.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

# ── SQL-схема ────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS domains (
    domain          TEXT PRIMARY KEY,
    last_polled_at  TEXT,
    last_poll_cursor TEXT
);

CREATE TABLE IF NOT EXISTS calls (
    id                  TEXT PRIMARY KEY,
    domain              TEXT NOT NULL,
    direction           TEXT NOT NULL,
    result              TEXT,
    duration            INTEGER,
    wait                INTEGER,
    started_at          TEXT,
    client_number       TEXT,
    operator_extension  TEXT,
    operator_name       TEXT,
    phone               TEXT,
    record_url          TEXT,
    source              TEXT NOT NULL,
    received_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processing (
    call_id             TEXT PRIMARY KEY REFERENCES calls(id),
    status              TEXT NOT NULL DEFAULT 'pending',
    audio_path          TEXT,
    result_json         TEXT,
    error_message       TEXT,
    skip_reason         TEXT,
    retry_count         INTEGER NOT NULL DEFAULT 0,
    started_at          TEXT,
    completed_at        TEXT,
    processing_time_sec REAL
);

CREATE TABLE IF NOT EXISTS operators (
    domain      TEXT,
    extension   TEXT,
    name        TEXT NOT NULL,
    synced_at   TEXT NOT NULL,
    PRIMARY KEY (domain, extension)
);

CREATE TABLE IF NOT EXISTS departments (
    domain      TEXT,
    id          INTEGER,
    extension   TEXT,
    name        TEXT NOT NULL,
    synced_at   TEXT NOT NULL,
    PRIMARY KEY (domain, id)
);

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

CREATE INDEX IF NOT EXISTS idx_calls_domain ON calls(domain);
CREATE INDEX IF NOT EXISTS idx_calls_started ON calls(started_at);
CREATE INDEX IF NOT EXISTS idx_processing_status ON processing(status);
CREATE INDEX IF NOT EXISTS idx_client_profiles_domain ON client_profiles(domain);
CREATE INDEX IF NOT EXISTS idx_knowledge_base_category ON knowledge_base(domain, category);
"""


def _now_iso() -> str:
    """Текущее UTC-время в ISO-формате."""
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """Конвертация sqlite3.Row в обычный dict (или None)."""
    if row is None:
        return None
    return dict(row)


# ── Инициализация ────────────────────────────────────────────────────────────


def init_db(db_path: str) -> sqlite3.Connection:
    """Инициализировать БД: создать таблицы и индексы.

    Args:
        db_path: путь к файлу SQLite.

    Returns:
        Соединение с установленным row_factory = sqlite3.Row.
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


# ── Звонки (calls) ───────────────────────────────────────────────────────────


def insert_call(conn: sqlite3.Connection, call: dict) -> bool:
    """Вставить звонок (INSERT OR IGNORE).

    Args:
        conn: соединение с БД.
        call: словарь с данными звонка.

    Returns:
        True если звонок вставлен, False если дубликат (уже существует).
    """
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO calls
            (id, domain, direction, result, duration, wait, started_at,
             client_number, operator_extension, operator_name, phone,
             record_url, source, received_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            call.get("id"),
            call.get("domain"),
            call.get("direction"),
            call.get("result"),
            call.get("duration"),
            call.get("wait"),
            call.get("started_at"),
            call.get("client_number"),
            call.get("operator_extension"),
            call.get("operator_name"),
            call.get("phone"),
            call.get("record_url"),
            call.get("source"),
            call.get("received_at"),
        ),
    )
    conn.commit()
    return cursor.rowcount > 0


def update_call_from_polling(conn: sqlite3.Connection, call_id: str, data: dict) -> bool:
    """Обновить звонок данными из polling (record_url, duration и т.д.).

    Обновляет только если текущий record_url пуст (звонок создан webhook-ом
    без полных данных). Это предотвращает повторное обновление уже заполненных записей.

    Args:
        conn: соединение с БД.
        call_id: ID звонка.
        data: словарь с полями для обновления (record_url, duration, result,
              wait, operator_extension, operator_name).

    Returns:
        True если обновление произошло, False если record_url уже заполнен
        или звонок не найден.
    """
    cursor = conn.execute(
        """
        UPDATE calls
        SET record_url = ?,
            duration = ?,
            result = ?,
            wait = ?,
            operator_extension = COALESCE(NULLIF(?, ''), operator_extension),
            operator_name = COALESCE(?, operator_name)
        WHERE id = ? AND (record_url IS NULL OR record_url = '')
        """,
        (
            data.get("record_url", ""),
            data.get("duration", 0),
            data.get("result", ""),
            data.get("wait", 0),
            data.get("operator_extension", ""),
            data.get("operator_name"),
            call_id,
        ),
    )
    conn.commit()
    return cursor.rowcount > 0


def reopen_processing(conn: sqlite3.Connection, call_id: str) -> bool:
    """Перевести processing из skipped в pending.

    Используется когда polling обновил данные звонка (record_url, duration)
    и он теперь проходит фильтры.

    Args:
        conn: соединение с БД.
        call_id: ID звонка.

    Returns:
        True если статус изменён, False если запись не skipped.
    """
    cursor = conn.execute(
        """
        UPDATE processing
        SET status = 'pending', skip_reason = NULL
        WHERE call_id = ? AND status = 'skipped'
        """,
        (call_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_call(conn: sqlite3.Connection, call_id: str) -> dict | None:
    """Получить звонок по ID.

    Returns:
        Словарь с данными звонка или None.
    """
    cursor = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,))
    return _row_to_dict(cursor.fetchone())


def list_calls(
    conn: sqlite3.Connection,
    domain: str | None = None,
    direction: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    operator: str | None = None,
    client_search: str | None = None,
    score_min: float | None = None,
    score_max: float | None = None,
    sort_by: str = "started_at",
    sort_order: str = "desc",
    page: int = 1,
    per_page: int = 50,
) -> list[dict]:
    """Список звонков с фильтрами и пагинацией (JOIN с processing).

    Args:
        domain: фильтр по домену.
        direction: фильтр по направлению (in/out).
        status: фильтр по статусу обработки.
        date_from: начало диапазона дат (включительно).
        date_to: конец диапазона дат (не включая).
        operator: фильтр по добавочному оператора.
        client_search: LIKE-поиск по номеру клиента.
        score_min: минимальная оценка качества.
        score_max: максимальная оценка качества.
        sort_by: столбец сортировки (started_at, duration, score).
        sort_order: направление сортировки (asc, desc).
        page: номер страницы (начиная с 1).
        per_page: количество записей на странице.

    Returns:
        Список словарей с данными звонков.
    """
    query = """
        SELECT c.id, c.domain, c.direction, c.result, c.duration, c.wait,
               c.started_at, c.client_number, c.operator_extension,
               c.phone, c.record_url, c.source, c.received_at,
               COALESCE(c.operator_name, o.name) AS operator_name,
               p.status AS processing_status, p.retry_count, p.error_message,
               p.result_json
        FROM calls c
        LEFT JOIN processing p ON c.id = p.call_id
        LEFT JOIN operators o ON c.domain = o.domain AND c.operator_extension = o.extension
        WHERE 1=1
    """
    params: list = []

    if domain is not None:
        query += " AND c.domain = ?"
        params.append(domain)
    if direction is not None:
        query += " AND c.direction = ?"
        params.append(direction)
    if status is not None:
        query += " AND p.status = ?"
        params.append(status)
    if date_from is not None:
        query += " AND c.started_at >= ?"
        params.append(date_from)
    if date_to is not None:
        query += " AND c.started_at < ?"
        params.append(date_to)
    if operator is not None:
        query += " AND c.operator_extension = ?"
        params.append(operator)
    if client_search is not None:
        query += " AND c.client_number LIKE ?"
        params.append(f"%{client_search}%")
    if score_min is not None:
        query += " AND json_extract(p.result_json, '$.quality_score.total') >= ?"
        params.append(score_min)
    if score_max is not None:
        query += " AND json_extract(p.result_json, '$.quality_score.total') <= ?"
        params.append(score_max)

    allowed_sorts = {
        "started_at": "c.started_at",
        "duration": "c.duration",
        "score": "json_extract(p.result_json, '$.quality_score.total')",
    }
    sort_col = allowed_sorts.get(sort_by, "c.started_at")
    order = "ASC" if sort_order == "asc" else "DESC"
    query += f" ORDER BY {sort_col} {order}"
    query += " LIMIT ? OFFSET ?"
    params.append(per_page)
    params.append((page - 1) * per_page)

    cursor = conn.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def get_calls_count(
    conn: sqlite3.Connection,
    domain: str | None = None,
    status: str | None = None,
    direction: str | None = None,
    operator: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    client_search: str | None = None,
    score_min: float | None = None,
    score_max: float | None = None,
) -> int:
    """Подсчёт звонков с опциональными фильтрами.

    Args:
        domain: фильтр по домену.
        status: фильтр по статусу обработки.
        direction: фильтр по направлению (in/out).
        operator: фильтр по добавочному оператора.
        date_from: начало диапазона дат (включительно).
        date_to: конец диапазона дат (не включая).
        client_search: LIKE-поиск по номеру клиента.
        score_min: минимальная оценка качества.
        score_max: максимальная оценка качества.

    Returns:
        Количество звонков.
    """
    query = """
        SELECT COUNT(*) AS cnt
        FROM calls c
        LEFT JOIN processing p ON c.id = p.call_id
        LEFT JOIN operators o ON c.domain = o.domain AND c.operator_extension = o.extension
        WHERE 1=1
    """
    params: list = []

    if domain is not None:
        query += " AND c.domain = ?"
        params.append(domain)
    if status is not None:
        query += " AND p.status = ?"
        params.append(status)
    if direction is not None:
        query += " AND c.direction = ?"
        params.append(direction)
    if operator is not None:
        query += " AND c.operator_extension = ?"
        params.append(operator)
    if date_from is not None:
        query += " AND c.started_at >= ?"
        params.append(date_from)
    if date_to is not None:
        query += " AND c.started_at < ?"
        params.append(date_to)
    if client_search is not None:
        query += " AND c.client_number LIKE ?"
        params.append(f"%{client_search}%")
    if score_min is not None:
        query += " AND json_extract(p.result_json, '$.quality_score.total') >= ?"
        params.append(score_min)
    if score_max is not None:
        query += " AND json_extract(p.result_json, '$.quality_score.total') <= ?"
        params.append(score_max)

    cursor = conn.execute(query, params)
    return cursor.fetchone()["cnt"]


# ── Обработка (processing) ───────────────────────────────────────────────────


def insert_processing(
    conn: sqlite3.Connection,
    call_id: str,
    status: str = "pending",
    skip_reason: str | None = None,
) -> None:
    """Создать запись обработки для звонка.

    Args:
        conn: соединение с БД.
        call_id: ID звонка.
        status: начальный статус (по умолчанию 'pending').
        skip_reason: причина пропуска (если status='skipped').
    """
    conn.execute(
        """
        INSERT INTO processing (call_id, status, skip_reason)
        VALUES (?, ?, ?)
        """,
        (call_id, status, skip_reason),
    )
    conn.commit()


def get_processing(conn: sqlite3.Connection, call_id: str) -> dict | None:
    """Получить запись обработки по ID звонка.

    Returns:
        Словарь с данными обработки или None.
    """
    cursor = conn.execute(
        "SELECT * FROM processing WHERE call_id = ?", (call_id,)
    )
    return _row_to_dict(cursor.fetchone())


def update_processing_status(
    conn: sqlite3.Connection,
    call_id: str,
    status: str,
    audio_path: str | None = None,
    result_json: str | None = None,
    error_message: str | None = None,
    processing_time_sec: float | None = None,
) -> None:
    """Обновить статус обработки звонка.

    Автоматически управляет временными метками:
    - status='processing' -> устанавливает started_at
    - status='done' или 'error' -> устанавливает completed_at
    - status='error' -> инкрементирует retry_count

    Args:
        conn: соединение с БД.
        call_id: ID звонка.
        status: новый статус.
        audio_path: путь к аудиофайлу.
        result_json: JSON-результат обработки.
        error_message: сообщение об ошибке.
        processing_time_sec: время обработки в секундах.
    """
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

    # Автоматические временные метки
    if status == "processing":
        sets.append("started_at = ?")
        params.append(now)
    if status in ("done", "error"):
        sets.append("completed_at = ?")
        params.append(now)
    if status == "error":
        sets.append("retry_count = retry_count + 1")

    query = f"UPDATE processing SET {', '.join(sets)} WHERE call_id = ?"
    params.append(call_id)

    conn.execute(query, params)
    conn.commit()


def get_pending_calls(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """Получить звонки со статусом 'pending' для обработки.

    Args:
        limit: максимальное количество записей.

    Returns:
        Список словарей с данными processing.
    """
    cursor = conn.execute(
        "SELECT * FROM processing WHERE status = 'pending' LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]


def reset_stale_processing(conn: sqlite3.Connection, stale_minutes: int = 15) -> int:
    """Сбросить записи, зависшие в processing/downloading дольше N минут.

    Args:
        conn: соединение с БД.
        stale_minutes: порог в минутах.

    Returns:
        Количество сброшенных записей.
    """
    cursor = conn.execute(
        """
        UPDATE processing
        SET status = 'pending', error_message = 'stale reset'
        WHERE status IN ('processing', 'downloading')
          AND started_at < datetime('now', ? || ' minutes')
        """,
        (f"-{stale_minutes}",),
    )
    conn.commit()
    return cursor.rowcount


def get_retryable_calls(
    conn: sqlite3.Connection, max_retries: int = 3
) -> list[dict]:
    """Получить звонки с ошибкой, доступные для повторной обработки.

    Args:
        max_retries: максимальное количество попыток.

    Returns:
        Список словарей processing со status='error' и retry_count < max_retries.
    """
    cursor = conn.execute(
        "SELECT * FROM processing WHERE status = 'error' AND retry_count < ?",
        (max_retries,),
    )
    return [dict(row) for row in cursor.fetchall()]


# ── Операторы ────────────────────────────────────────────────────────────────


def upsert_operator(
    conn: sqlite3.Connection, domain: str, extension: str, name: str
) -> None:
    """Вставить или обновить оператора.

    Args:
        conn: соединение с БД.
        domain: домен компании-клиента.
        extension: добавочный номер.
        name: имя оператора.
    """
    conn.execute(
        """
        INSERT INTO operators (domain, extension, name, synced_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(domain, extension)
        DO UPDATE SET name = excluded.name, synced_at = excluded.synced_at
        """,
        (domain, extension, name, _now_iso()),
    )
    conn.commit()


def get_operator_name(
    conn: sqlite3.Connection, domain: str, extension: str
) -> str | None:
    """Получить имя оператора по домену и добавочному.

    Returns:
        Имя оператора или None, если не найден.
    """
    cursor = conn.execute(
        "SELECT name FROM operators WHERE domain = ? AND extension = ?",
        (domain, extension),
    )
    row = cursor.fetchone()
    return row["name"] if row else None


def list_operators(conn: sqlite3.Connection, domain: str) -> list[dict]:
    """Список операторов домена.

    Args:
        domain: домен компании-клиента.

    Returns:
        Список словарей с данными операторов.
    """
    cursor = conn.execute(
        "SELECT * FROM operators WHERE domain = ? ORDER BY extension",
        (domain,),
    )
    return [dict(row) for row in cursor.fetchall()]


# ── Отделы ───────────────────────────────────────────────────────────────────


def upsert_department(
    conn: sqlite3.Connection,
    domain: str,
    dept_id: int,
    extension: str,
    name: str,
) -> None:
    """Вставить или обновить отдел.

    Args:
        conn: соединение с БД.
        domain: домен компании-клиента.
        dept_id: идентификатор отдела.
        extension: добавочный номер.
        name: название отдела.
    """
    conn.execute(
        """
        INSERT INTO departments (domain, id, extension, name, synced_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(domain, id)
        DO UPDATE SET extension = excluded.extension,
                      name = excluded.name,
                      synced_at = excluded.synced_at
        """,
        (domain, dept_id, extension, name, _now_iso()),
    )
    conn.commit()


def list_departments(conn: sqlite3.Connection, domain: str) -> list[dict]:
    """Список отделов домена.

    Args:
        domain: домен компании-клиента.

    Returns:
        Список словарей с данными отделов.
    """
    cursor = conn.execute(
        "SELECT * FROM departments WHERE domain = ? ORDER BY id",
        (domain,),
    )
    return [dict(row) for row in cursor.fetchall()]


# ── Домены ───────────────────────────────────────────────────────────────────


def update_domain_poll_time(conn: sqlite3.Connection, domain: str) -> None:
    """Обновить время последнего поллинга домена (UPSERT).

    Args:
        conn: соединение с БД.
        domain: домен компании-клиента.
    """
    conn.execute(
        """
        INSERT INTO domains (domain, last_polled_at)
        VALUES (?, ?)
        ON CONFLICT(domain)
        DO UPDATE SET last_polled_at = excluded.last_polled_at
        """,
        (domain, _now_iso()),
    )
    conn.commit()

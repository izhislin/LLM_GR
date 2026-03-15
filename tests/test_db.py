"""Тесты для db.py (SQLite, без внешних зависимостей)."""

import sqlite3

import pytest

from src.db import (
    init_db,
    insert_processing,
    update_processing_status,
    reset_stale_processing,
    get_processing,
)


@pytest.fixture
def db(tmp_path):
    """Создать временную in-memory БД с инициализированной схемой."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    # Вставим фиктивный звонок для FK
    conn.execute(
        """
        INSERT INTO calls (id, domain, direction, source, received_at)
        VALUES ('c1', 'test.domain', 'in', 'test', '2026-01-01T00:00:00')
        """
    )
    conn.execute(
        """
        INSERT INTO calls (id, domain, direction, source, received_at)
        VALUES ('c2', 'test.domain', 'in', 'test', '2026-01-01T00:00:00')
        """
    )
    conn.execute(
        """
        INSERT INTO calls (id, domain, direction, source, received_at)
        VALUES ('c3', 'test.domain', 'in', 'test', '2026-01-01T00:00:00')
        """
    )
    conn.commit()
    return conn


def test_reset_stale_processing_resets_old_records(db):
    """Записи в processing/downloading старше N минут должны сброситься."""
    insert_processing(db, "c1", status="pending")
    insert_processing(db, "c2", status="pending")

    # Переводим c1 в processing со старым started_at
    db.execute(
        """
        UPDATE processing
        SET status = 'processing', started_at = datetime('now', '-30 minutes')
        WHERE call_id = 'c1'
        """
    )
    # Переводим c2 в downloading со старым started_at
    db.execute(
        """
        UPDATE processing
        SET status = 'downloading', started_at = datetime('now', '-20 minutes')
        WHERE call_id = 'c2'
        """
    )
    db.commit()

    count = reset_stale_processing(db, stale_minutes=15)

    assert count == 2
    p1 = get_processing(db, "c1")
    p2 = get_processing(db, "c2")
    assert p1["status"] == "pending"
    assert p1["error_message"] == "stale reset"
    assert p2["status"] == "pending"


def test_reset_stale_processing_ignores_recent(db):
    """Недавние записи в processing не должны сбрасываться."""
    insert_processing(db, "c1", status="pending")
    # Переводим в processing с текущим started_at
    db.execute(
        """
        UPDATE processing
        SET status = 'processing', started_at = datetime('now', '-5 minutes')
        WHERE call_id = 'c1'
        """
    )
    db.commit()

    count = reset_stale_processing(db, stale_minutes=15)

    assert count == 0
    p1 = get_processing(db, "c1")
    assert p1["status"] == "processing"


def test_reset_stale_processing_ignores_other_statuses(db):
    """Записи со статусами done/error/pending не затрагиваются."""
    insert_processing(db, "c1", status="pending")
    insert_processing(db, "c2", status="pending")
    insert_processing(db, "c3", status="pending")

    update_processing_status(db, "c2", status="done")
    update_processing_status(db, "c3", status="error", error_message="fail")

    count = reset_stale_processing(db, stale_minutes=15)

    assert count == 0

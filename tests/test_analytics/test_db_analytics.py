"""Тесты для аналитических таблиц в db.py."""

import json
import pytest
from src.db import init_db


@pytest.fixture
def db(tmp_path):
    """Временная БД с полной схемой."""
    return init_db(str(tmp_path / "test.db"))


def test_client_profiles_table_exists(db):
    db.execute("SELECT * FROM client_profiles LIMIT 1")


def test_knowledge_base_table_exists(db):
    db.execute("SELECT * FROM knowledge_base LIMIT 1")


def test_knowledge_scenarios_table_exists(db):
    db.execute("SELECT * FROM knowledge_scenarios LIMIT 1")


def test_calls_fts_table_exists(db):
    db.execute("SELECT * FROM calls_fts LIMIT 1")


def test_client_profiles_insert_and_select(db):
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
    db.execute(
        "INSERT INTO calls_fts (call_id, transcript, topic, issues) VALUES (?, ?, ?, ?)",
        ("c1", "Здравствуйте, не работает SIP-транк", "SIP-транк", "не работает связь"),
    )
    db.commit()
    results = db.execute(
        "SELECT call_id FROM calls_fts WHERE calls_fts MATCH ?",
        ('"SIP-транк"',),
    ).fetchall()
    assert len(results) == 1
    assert results[0]["call_id"] == "c1"


def test_fts5_no_results(db):
    db.execute(
        "INSERT INTO calls_fts (call_id, transcript, topic, issues) VALUES (?, ?, ?, ?)",
        ("c1", "Здравствуйте, вопрос по тарифу", "тариф", ""),
    )
    db.commit()
    results = db.execute(
        "SELECT call_id FROM calls_fts WHERE calls_fts MATCH ?",
        ('"SIP-транк"',),
    ).fetchall()
    assert len(results) == 0

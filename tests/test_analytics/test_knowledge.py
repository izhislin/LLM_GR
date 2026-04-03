"""Тесты для knowledge — batch-агрегация базы знаний."""

import json
import pytest
from src.db import init_db
from src.analytics.knowledge import aggregate_knowledge


@pytest.fixture
def db(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
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
    count = aggregate_knowledge(db, "test.domain")
    assert count >= 1
    row = db.execute("SELECT * FROM knowledge_base WHERE category = 'техподдержка/связь'").fetchone()
    assert row is not None
    assert row["frequency"] >= 5


def test_aggregate_idempotent(db):
    aggregate_knowledge(db, "test.domain")
    aggregate_knowledge(db, "test.domain")
    rows = db.execute("SELECT * FROM knowledge_base WHERE category = 'техподдержка/связь'").fetchall()
    assert len(rows) == 1


def test_aggregate_empty_domain(db):
    count = aggregate_knowledge(db, "nonexistent.domain")
    assert count == 0


def test_aggregate_success_rate(db):
    aggregate_knowledge(db, "test.domain")
    row = db.execute("SELECT * FROM knowledge_base WHERE category = 'техподдержка/связь'").fetchone()
    assert row["success_rate"] == 1.0  # all resolved

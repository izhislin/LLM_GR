"""Тесты для FTS5 поиска по звонкам."""

import json
import pytest
from src.db import init_db
from src.analytics.search import index_call, search_calls


@pytest.fixture
def db(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    for i, (transcript, topic, issues) in enumerate([
        ("Здравствуйте, не работает переадресация уже второй день", "переадресация", "не работает переадресация"),
        ("Добрый день, хочу подключить переадресацию на мобильный", "переадресация", ""),
        ("Алло, у нас проблема с обещанным платежом", "обещанный платёж", "не прошёл обещанный платёж"),
    ]):
        call_id = f"c{i+1}"
        result = {"transcript": transcript, "summary": {"topic": topic},
                  "extracted_data": {"issues": [issues] if issues else []}}
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
    index_call(db, "c1")
    results = search_calls(db, "переадресация")
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
    assert len(results) >= 2


def test_index_idempotent(db):
    index_call(db, "c1")
    index_call(db, "c1")
    results = search_calls(db, "переадресация")
    assert len(results) == 1


def test_index_returns_false_for_missing(db):
    assert index_call(db, "nonexistent") is False

"""Тесты для client_profiles — профили клиентов и risk scoring."""

import json
import pytest
from src.db import init_db
from src.analytics.client_profiles import update_profile_on_call, recalculate_profiles


@pytest.fixture
def db(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    for i, (client, started) in enumerate([
        ("79001234567", "2026-04-01T10:00:00Z"),
        ("79001234567", "2026-04-02T10:00:00Z"),
        ("79001234567", "2026-04-03T10:00:00Z"),
        ("79009999999", "2026-04-01T10:00:00Z"),
    ]):
        call_id = f"c{i+1}"
        conn.execute(
            """INSERT INTO calls (id, domain, direction, client_number, started_at, source, received_at)
               VALUES (?, 'test.domain', 'in', ?, ?, 'test', ?)""",
            (call_id, client, started, started),
        )
        conn.execute(
            "INSERT INTO processing (call_id, status) VALUES (?, 'done')",
            (call_id,),
        )
    conn.commit()
    return conn


def _set_result(db, call_id, classification, extracted_data=None):
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
    _set_result(db, "c1", {"category": "техподдержка/связь", "sentiment": "neutral",
                            "resolution_status": "resolved", "is_repeat_contact": False, "tags": []})
    update_profile_on_call(db, "c1")
    row = db.execute("SELECT * FROM client_profiles WHERE client_number = '79001234567'").fetchone()
    assert row is not None
    assert row["total_calls"] == 1


def test_update_profile_increments(db):
    _set_result(db, "c1", {"category": "техподдержка/связь", "sentiment": "neutral",
                            "resolution_status": "resolved", "is_repeat_contact": False, "tags": []})
    _set_result(db, "c2", {"category": "техподдержка/связь", "sentiment": "negative",
                            "resolution_status": "unresolved", "is_repeat_contact": True, "tags": ["угроза_ухода"]})
    update_profile_on_call(db, "c1")
    update_profile_on_call(db, "c2")
    row = db.execute("SELECT * FROM client_profiles WHERE client_number = '79001234567'").fetchone()
    assert row["total_calls"] == 2


def test_update_profile_extracts_name(db):
    _set_result(db, "c1", {"category": "другое", "sentiment": "neutral",
                            "resolution_status": "resolved", "is_repeat_contact": False, "tags": []},
                {"client_name": "Иванов Иван", "issues": []})
    update_profile_on_call(db, "c1")
    row = db.execute("SELECT * FROM client_profiles WHERE client_number = '79001234567'").fetchone()
    assert row["extracted_name"] == "Иванов Иван"


def test_recalculate_sets_risk_level(db):
    for cid in ("c1", "c2", "c3"):
        _set_result(db, cid, {"category": "техподдержка/связь", "sentiment": "negative",
                                "resolution_status": "unresolved", "is_repeat_contact": cid != "c1",
                                "tags": ["угроза_ухода"] if cid == "c1" else []},
                    {"issues": ["нет связи"]})
        update_profile_on_call(db, cid)
    recalculate_profiles(db, "test.domain")
    row = db.execute("SELECT * FROM client_profiles WHERE client_number = '79001234567'").fetchone()
    assert row["risk_level"] in ("medium", "high")
    assert row["primary_category"] == "техподдержка/связь"


def test_recalculate_stable_sentiment(db):
    for cid in ("c1", "c2", "c3"):
        _set_result(db, cid, {"category": "информация/консультация", "sentiment": "neutral",
                                "resolution_status": "resolved", "is_repeat_contact": False, "tags": []})
        update_profile_on_call(db, cid)
    recalculate_profiles(db, "test.domain")
    row = db.execute("SELECT * FROM client_profiles WHERE client_number = '79001234567'").fetchone()
    assert row["sentiment_trend"] == "stable"
    assert row["risk_level"] == "low"

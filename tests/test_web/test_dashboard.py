"""Тесты для dashboard API."""

import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.db import init_db
from src.analytics.search import index_call
from src.web.routes.dashboard import router, set_dependencies


@pytest.fixture
def db(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    for i in range(5):
        call_id = f"c{i+1}"
        operator = "732" if i < 3 else "708"
        direction = "in" if i < 4 else "out"
        result = {
            "transcript": f"Транскрипт звонка {i}",
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
    app = FastAPI()
    app.include_router(router)
    set_dependencies(db)
    return TestClient(app)


def test_business_kpis(client):
    resp = client.get("/api/dashboard/business/kpis", params={"domain": "test.domain"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_calls"] == 5
    assert data["avg_quality"] > 0


def test_business_kpis_empty_domain(client):
    resp = client.get("/api/dashboard/business/kpis", params={"domain": "nonexistent"})
    assert resp.status_code == 200
    assert resp.json()["total_calls"] == 0


def test_category_distribution(client):
    resp = client.get("/api/dashboard/business/categories", params={"domain": "test.domain"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(d["category"] == "техподдержка/связь" for d in data)


def test_sentiment_distribution(client):
    resp = client.get("/api/dashboard/business/sentiment", params={"domain": "test.domain"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["negative"] >= 1
    assert data["neutral"] >= 1


def test_operator_ratings(client):
    resp = client.get("/api/dashboard/supervisor/operators", params={"domain": "test.domain"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert "avg_score" in data[0]
    assert "name" in data[0]


def test_script_checklist(client):
    resp = client.get("/api/dashboard/supervisor/script-checklist", params={"domain": "test.domain"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    first_operator = list(data.values())[0]
    assert "greeted_with_name" in first_operator


def test_risk_clients(client):
    resp = client.get("/api/dashboard/business/risk-clients", params={"domain": "test.domain"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_search(client, db):
    for i in range(5):
        index_call(db, f"c{i+1}")
    resp = client.get("/api/dashboard/search", params={"q": "Транскрипт"})
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

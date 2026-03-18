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
            "received_at": f"2026-03-13T14:{i:02d}:05Z",
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


@pytest.fixture
def db_with_audio(tmp_path):
    """БД с тестовыми данными и аудиофайлом."""
    from src.db import init_db, insert_call, insert_processing, update_processing_status, upsert_operator
    db = init_db(str(tmp_path / "test.db"))
    call = {
        "id": "call_0", "domain": "test.aicall.ru", "direction": "in",
        "result": "success", "duration": 60, "wait": 5,
        "started_at": "2026-03-13T14:00:00Z",
        "client_number": "79990000000", "operator_extension": "701",
        "operator_name": None, "phone": "74951112233",
        "record_url": "https://records.aicall.ru/test/call_0.mp3",
        "source": "webhook", "received_at": "2026-03-13T14:00:05Z",
    }
    insert_call(db, call)
    insert_processing(db, "call_0", status="done")
    audio_file = tmp_path / "call_0.mp3"
    audio_file.write_bytes(b"fake-mp3-data")
    update_processing_status(db, "call_0", "done", audio_path=str(audio_file))
    return db


@pytest.fixture
def client_with_audio(db_with_audio):
    app = FastAPI()
    app.include_router(router)
    set_dependencies(db=db_with_audio, domain_configs={})
    return TestClient(app)


def test_audio_endpoint(client_with_audio):
    """GET /api/audio/{call_id} — отдача аудиофайла."""
    resp = client_with_audio.get("/api/audio/call_0")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.content == b"fake-mp3-data"


def test_audio_endpoint_not_found(client):
    """404 если аудиофайл не найден."""
    resp = client.get("/api/audio/nonexistent")
    assert resp.status_code == 404

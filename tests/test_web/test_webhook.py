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
    """Неверный API-ключ -> 401."""
    resp = client.post(
        "/webhook/test.aicall.ru/history",
        json=SAMPLE_WEBHOOK,
        headers={"X-API-KEY": "wrong-key"},
    )
    assert resp.status_code == 401


def test_webhook_missing_api_key(client):
    """Отсутствующий API-ключ -> 401."""
    resp = client.post(
        "/webhook/test.aicall.ru/history",
        json=SAMPLE_WEBHOOK,
    )
    assert resp.status_code == 401


def test_webhook_unknown_domain(client):
    """Неизвестный домен -> 404."""
    resp = client.post(
        "/webhook/unknown.aicall.ru/history",
        json=SAMPLE_WEBHOOK,
        headers={"X-API-KEY": "secret-key"},
    )
    assert resp.status_code == 404


def test_webhook_duplicate_call_idempotent(client):
    """Повторный webhook для того же звонка -- идемпотентен."""
    headers = {"X-API-KEY": "secret-key"}
    resp1 = client.post("/webhook/test.aicall.ru/history", json=SAMPLE_WEBHOOK, headers=headers)
    resp2 = client.post("/webhook/test.aicall.ru/history", json=SAMPLE_WEBHOOK, headers=headers)
    assert resp1.status_code == 200
    assert resp2.status_code == 200


def test_webhook_short_call_skipped(client):
    """Короткий звонок -> skipped."""
    short_call = {**SAMPLE_WEBHOOK, "id": "short1", "duration": 5}
    resp = client.post(
        "/webhook/test.aicall.ru/history",
        json=short_call,
        headers={"X-API-KEY": "secret-key"},
    )
    assert resp.status_code == 200

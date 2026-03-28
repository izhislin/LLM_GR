"""Тесты OpenAI-совместимого API (/v1/chat/completions)."""

import json
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.web.routes.openai_compat import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def client_with_auth(monkeypatch):
    """Клиент с включённой авторизацией."""
    monkeypatch.setattr("src.web.routes.openai_compat._API_KEY", "test-secret-key")
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ── /v1/models ───────────────────────────────────────────────────────────────


def test_list_models(client):
    """GET /v1/models возвращает список моделей."""
    resp = client.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    assert len(data["data"]) >= 1
    assert data["data"][0]["id"] == "qwen3:8b"


# ── Auth ─────────────────────────────────────────────────────────────────────


def test_auth_required_when_key_set(client_with_auth):
    """401 если Bearer-токен отсутствует при заданном LLM_API_KEY."""
    resp = client_with_auth.get("/v1/models")
    assert resp.status_code == 401


def test_auth_wrong_key(client_with_auth):
    """401 при неверном ключе."""
    resp = client_with_auth.get(
        "/v1/models", headers={"Authorization": "Bearer wrong-key"}
    )
    assert resp.status_code == 401


def test_auth_correct_key(client_with_auth):
    """200 при правильном ключе."""
    resp = client_with_auth.get(
        "/v1/models", headers={"Authorization": "Bearer test-secret-key"}
    )
    assert resp.status_code == 200


# ── /v1/chat/completions (sync) ─────────────────────────────────────────────


def _mock_ollama_sync():
    """Mock для синхронного ответа Ollama."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message": {"role": "assistant", "content": "Привет! Чем могу помочь?"},
        "done": True,
        "prompt_eval_count": 10,
        "eval_count": 8,
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


@patch("src.web.routes.openai_compat.requests.post")
def test_chat_completions_sync(mock_post, client):
    """POST /v1/chat/completions (stream=false) — синхронный ответ."""
    mock_post.return_value = _mock_ollama_sync()

    resp = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Привет"}],
            "stream": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["object"] == "chat.completion"
    assert len(data["choices"]) == 1
    assert data["choices"][0]["message"]["content"] == "Привет! Чем могу помочь?"
    assert data["choices"][0]["finish_reason"] == "stop"
    assert data["usage"]["prompt_tokens"] == 10
    assert data["usage"]["completion_tokens"] == 8


@patch("src.web.routes.openai_compat.requests.post")
def test_chat_completions_passes_options(mock_post, client):
    """Параметры temperature, top_p, max_tokens передаются в Ollama."""
    mock_post.return_value = _mock_ollama_sync()

    client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": False,
            "temperature": 0.7,
            "top_p": 0.9,
            "max_tokens": 100,
        },
    )

    call_args = mock_post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert payload["options"]["temperature"] == 0.7
    assert payload["options"]["top_p"] == 0.9
    assert payload["options"]["num_predict"] == 100


def test_chat_completions_no_messages(client):
    """400 если messages пустой."""
    resp = client.post("/v1/chat/completions", json={"messages": []})
    assert resp.status_code == 400


# ── /v1/chat/completions (stream) ───────────────────────────────────────────


def _mock_ollama_stream():
    """Mock для стримингового ответа Ollama."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()

    lines = [
        json.dumps({"message": {"content": "При"}, "done": False}).encode(),
        json.dumps({"message": {"content": "вет"}, "done": False}).encode(),
        json.dumps({"message": {"content": "!"}, "done": True}).encode(),
    ]
    mock_resp.iter_lines.return_value = lines
    return mock_resp


@patch("src.web.routes.openai_compat.requests.post")
def test_chat_completions_stream(mock_post, client):
    """POST /v1/chat/completions (stream=true) — SSE формат OpenAI."""
    mock_post.return_value = _mock_ollama_stream()

    resp = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Привет"}],
            "stream": True,
        },
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    # Парсим SSE-чанки
    chunks = []
    for line in resp.text.strip().split("\n\n"):
        if line.startswith("data: ") and line != "data: [DONE]":
            chunk = json.loads(line[6:])
            chunks.append(chunk)

    assert len(chunks) == 3
    assert chunks[0]["object"] == "chat.completion.chunk"
    assert chunks[0]["choices"][0]["delta"]["content"] == "При"
    assert chunks[2]["choices"][0]["finish_reason"] == "stop"

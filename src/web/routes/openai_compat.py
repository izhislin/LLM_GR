"""OpenAI-совместимый API для внешних клиентов.

Реализует POST /v1/chat/completions — минимальный subset OpenAI Chat API,
проксируя запросы к Ollama. Позволяет подключить любой OpenAI SDK клиент.
"""

import json
import logging
import os
import secrets
import time
import uuid

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src.config import OLLAMA_MODEL, OLLAMA_NUM_CTX, OLLAMA_KEEP_ALIVE, OLLAMA_TIMEOUT

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")

# API-ключ для внешнего доступа (из .env)
_API_KEY = os.environ.get("LLM_API_KEY", "")


def _check_auth(request: Request) -> None:
    """Проверить Bearer-токен. Пропускает если LLM_API_KEY не задан."""
    if not _API_KEY:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = auth[7:]
    if not secrets.compare_digest(token, _API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key")


@router.get("/models")
async def list_models(request: Request):
    """GET /v1/models — список доступных моделей (OpenAI-совместимый)."""
    _check_auth(request)
    return {
        "object": "list",
        "data": [
            {
                "id": OLLAMA_MODEL,
                "object": "model",
                "created": 0,
                "owned_by": "local",
            }
        ],
    }


@router.post("/chat/completions")
async def chat_completions(request: Request):
    """POST /v1/chat/completions — OpenAI-совместимый чат.

    Поддерживает:
    - messages: список {role, content}
    - model: название модели (опционально, по умолчанию из конфига)
    - stream: true/false
    - temperature, top_p, max_tokens
    """
    _check_auth(request)

    body = await request.json()
    messages = body.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="messages is required")

    model = body.get("model", OLLAMA_MODEL)
    stream = body.get("stream", False)
    request_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    # Опции для Ollama
    options = {"num_ctx": OLLAMA_NUM_CTX}
    if body.get("temperature") is not None:
        options["temperature"] = body["temperature"]
    if body.get("top_p") is not None:
        options["top_p"] = body["top_p"]
    if body.get("max_tokens") is not None:
        options["num_predict"] = body["max_tokens"]

    ollama_payload = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "options": options,
        "keep_alive": OLLAMA_KEEP_ALIVE,
    }

    if stream:
        return StreamingResponse(
            _stream_response(ollama_payload, request_id, model),
            media_type="text/event-stream",
        )
    else:
        return _sync_response(ollama_payload, request_id, model)


def _sync_response(ollama_payload: dict, request_id: str, model: str) -> JSONResponse:
    """Синхронный (не стриминговый) ответ."""
    try:
        resp = requests.post(
            "http://localhost:11434/api/chat",
            json=ollama_payload,
            timeout=OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error("Ollama error: %s", e)
        raise HTTPException(status_code=502, detail=f"LLM backend error: {e}")

    content = data.get("message", {}).get("content", "")
    prompt_tokens = data.get("prompt_eval_count", 0)
    completion_tokens = data.get("eval_count", 0)

    return JSONResponse({
        "id": request_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    })


def _stream_response(ollama_payload: dict, request_id: str, model: str):
    """Генератор SSE-чанков в формате OpenAI."""
    try:
        resp = requests.post(
            "http://localhost:11434/api/chat",
            json=ollama_payload,
            stream=True,
            timeout=OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()

        for line in resp.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            token = data.get("message", {}).get("content", "")
            done = data.get("done", False)

            chunk = {
                "id": request_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": token} if token else {},
                        "finish_reason": "stop" if done else None,
                    }
                ],
            }
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

        yield "data: [DONE]\n\n"

    except requests.RequestException as e:
        logger.error("Ollama streaming error: %s", e)
        error_chunk = {
            "error": {"message": str(e), "type": "server_error"},
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"

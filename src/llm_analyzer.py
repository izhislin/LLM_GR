"""Клиент для LLM API — Ollama (локальный) и OpenRouter (облачный)."""

import json
import logging
from pathlib import Path

import requests

from src.config import (
    OLLAMA_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_NUM_CTX, OLLAMA_KEEP_ALIVE,
    OPENROUTER_API_KEY, OPENROUTER_URL, OPENROUTER_MODEL, OPENROUTER_TIMEOUT,
)
from src.metrics import PROMETHEUS_AVAILABLE

if PROMETHEUS_AVAILABLE:
    from src.metrics import (
        OLLAMA_PROMPT_TOKENS,
        OLLAMA_GENERATED_TOKENS,
        OLLAMA_TOKENS_PER_SECOND,
        OLLAMA_RETRIES,
    )

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


def load_prompt(prompt_path: Path) -> str:
    """Загрузить текст промпта из файла."""
    return Path(prompt_path).read_text(encoding="utf-8").strip()


def _update_ollama_metrics(response_data: dict) -> None:
    """Извлечь метаданные из ответа Ollama и обновить Prometheus-счётчики."""
    if not PROMETHEUS_AVAILABLE:
        return

    eval_count = response_data.get("eval_count", 0)
    eval_duration_ns = response_data.get("eval_duration", 0)
    prompt_eval_count = response_data.get("prompt_eval_count", 0)

    if prompt_eval_count:
        OLLAMA_PROMPT_TOKENS.inc(prompt_eval_count)
    if eval_count:
        OLLAMA_GENERATED_TOKENS.inc(eval_count)
    if eval_count and eval_duration_ns > 0:
        tokens_per_sec = eval_count / (eval_duration_ns / 1e9)
        OLLAMA_TOKENS_PER_SECOND.set(tokens_per_sec)


def call_llm(
    system_prompt: str,
    user_message: str,
    response_schema: dict | None = None,
) -> dict:
    """Отправить запрос в Ollama и получить JSON-ответ.

    Args:
        system_prompt: Системный промпт (роль, инструкции).
        user_message: Пользовательское сообщение (диалог).
        response_schema: JSON Schema для структурированного ответа.

    Returns:
        Распарсенный JSON-словарь.

    Raises:
        RuntimeError: Если не удалось получить валидный JSON после ретраев.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_ctx": OLLAMA_NUM_CTX},
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "format": "json",
    }
    if response_schema:
        payload["format"] = response_schema

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info("Ollama вызов (попытка %d/%d)...", attempt, MAX_RETRIES)

        resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()

        response_data = resp.json()
        content = response_data["message"]["content"]

        try:
            parsed = json.loads(content)
            _update_ollama_metrics(response_data)
            return parsed
        except json.JSONDecodeError:
            logger.warning(
                "Попытка %d: невалидный JSON от LLM: %s", attempt, content[:200]
            )
            if PROMETHEUS_AVAILABLE:
                OLLAMA_RETRIES.inc()

    raise RuntimeError(
        f"Не удалось получить валидный JSON от LLM после {MAX_RETRIES} попыток"
    )


def call_cloud_llm(
    system_prompt: str,
    user_message: str,
) -> dict:
    """Отправить запрос в облачный LLM (OpenRouter) и получить JSON-ответ.

    Используется для batch-аналитики: генерация сценариев, обобщение трендов.
    Формат OpenAI-совместимый.

    Args:
        system_prompt: Системный промпт.
        user_message: Пользовательское сообщение.

    Returns:
        Распарсенный JSON-словарь.

    Raises:
        RuntimeError: Если API-ключ не задан или не удалось получить ответ.
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY не задан. Установите в .env для использования облачного LLM."
        )

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info("OpenRouter вызов (попытка %d/%d, модель %s)...", attempt, MAX_RETRIES, OPENROUTER_MODEL)

        resp = requests.post(
            OPENROUTER_URL, json=payload, headers=headers, timeout=OPENROUTER_TIMEOUT,
        )
        resp.raise_for_status()

        response_data = resp.json()
        content = response_data["choices"][0]["message"]["content"]

        try:
            parsed = json.loads(content)
            usage = response_data.get("usage", {})
            logger.info(
                "OpenRouter: %d prompt + %d completion tokens",
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
            )
            return parsed
        except json.JSONDecodeError:
            logger.warning(
                "Попытка %d: невалидный JSON от OpenRouter: %s", attempt, content[:200]
            )

    raise RuntimeError(
        f"Не удалось получить валидный JSON от OpenRouter после {MAX_RETRIES} попыток"
    )


def _correct_llm_output(obj, profile):
    """Рекурсивно применить text_corrector к строкам в LLM-ответе."""
    from src.text_corrector import correct_text

    if isinstance(obj, str):
        return correct_text(obj, profile)
    if isinstance(obj, dict):
        return {k: _correct_llm_output(v, profile) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_correct_llm_output(item, profile) for item in obj]
    return obj


def analyze_dialogue(
    dialogue_text: str,
    prompts_dir: Path,
    llm_context: str | None = None,
    profile: dict | None = None,
) -> dict:
    """Выполнить полный анализ диалога: суммаризация, оценка, извлечение.

    Args:
        dialogue_text: Текст диалога с таймкодами и метками.
        prompts_dir: Директория с промпт-файлами.
        llm_context: Контекст компании из профиля (добавляется перед диалогом).
        profile: Загруженный профиль коррекции (для пост-обработки LLM-ответов).

    Returns:
        Словарь с ключами: summary, quality_score, extracted_data.
    """
    if llm_context:
        user_message = f"Контекст: {llm_context.strip()}\n\n---\n\n{dialogue_text}"
    else:
        user_message = dialogue_text

    results = {}

    logger.info("Суммаризация...")
    summary_prompt = load_prompt(prompts_dir / "summarize.md")
    results["summary"] = call_llm(
        system_prompt=summary_prompt,
        user_message=user_message,
    )

    logger.info("Оценка качества...")
    quality_prompt = load_prompt(prompts_dir / "quality_score.md")
    results["quality_score"] = call_llm(
        system_prompt=quality_prompt,
        user_message=user_message,
    )

    logger.info("Извлечение данных...")
    extract_prompt = load_prompt(prompts_dir / "extract_data.md")
    results["extracted_data"] = call_llm(
        system_prompt=extract_prompt,
        user_message=user_message,
    )

    logger.info("Классификация...")
    classify_prompt = load_prompt(prompts_dir / "classify.md")
    results["classification"] = call_llm(
        system_prompt=classify_prompt,
        user_message=user_message,
    )

    # Пост-обработка: коррекция текста в LLM-ответах (Gravital → Гравител и т.д.)
    if profile:
        for key in results:
            results[key] = _correct_llm_output(results[key], profile)

    return results

"""Клиент для Ollama API — отправка диалога на LLM-анализ."""

import json
import logging
from pathlib import Path

import requests

from src.config import OLLAMA_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT

logger = logging.getLogger(__name__)

MAX_RETRIES = 2


def load_prompt(prompt_path: Path) -> str:
    """Загрузить текст промпта из файла."""
    return Path(prompt_path).read_text(encoding="utf-8").strip()


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
        "options": {"temperature": 0},
    }
    if response_schema:
        payload["format"] = response_schema

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info("Ollama вызов (попытка %d/%d)...", attempt, MAX_RETRIES)

        resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()

        content = resp.json()["message"]["content"]

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning(
                "Попытка %d: невалидный JSON от LLM: %s", attempt, content[:200]
            )

    raise RuntimeError(
        f"Не удалось получить валидный JSON от LLM после {MAX_RETRIES} попыток"
    )


def analyze_dialogue(
    dialogue_text: str, prompts_dir: Path
) -> dict:
    """Выполнить полный анализ диалога: суммаризация, оценка, извлечение.

    Args:
        dialogue_text: Текст диалога с таймкодами и метками.
        prompts_dir: Директория с промпт-файлами.

    Returns:
        Словарь с ключами: summary, quality_score, extracted_data.
    """
    results = {}

    logger.info("Суммаризация...")
    summary_prompt = load_prompt(prompts_dir / "summarize.md")
    results["summary"] = call_llm(
        system_prompt=summary_prompt,
        user_message=dialogue_text,
    )

    logger.info("Оценка качества...")
    quality_prompt = load_prompt(prompts_dir / "quality_score.md")
    results["quality_score"] = call_llm(
        system_prompt=quality_prompt,
        user_message=dialogue_text,
    )

    logger.info("Извлечение данных...")
    extract_prompt = load_prompt(prompts_dir / "extract_data.md")
    results["extracted_data"] = call_llm(
        system_prompt=extract_prompt,
        user_message=dialogue_text,
    )

    return results

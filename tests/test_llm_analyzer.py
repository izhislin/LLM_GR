"""Тесты для llm_analyzer (с моками Ollama API)."""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.llm_analyzer import call_llm, analyze_dialogue, load_prompt


@pytest.fixture
def sample_dialogue_text():
    return (
        "[00:00:00] Оператор: Добрый день, компания Гравител.\n"
        "[00:00:03] Клиент: Здравствуйте, хочу узнать про тариф.\n"
        "[00:00:08] Оператор: Конечно, какой тариф вас интересует?\n"
    )


@patch("src.llm_analyzer.requests.post")
def test_call_llm_returns_parsed_json(mock_post):
    """call_llm должен вернуть распарсенный JSON из ответа Ollama."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "message": {"content": '{"topic": "тариф", "outcome": "консультация"}'}
    }
    mock_response.raise_for_status = MagicMock()
    mock_post.return_value = mock_response

    result = call_llm(
        system_prompt="Ты аналитик.",
        user_message="Текст диалога.",
        response_schema={"type": "object", "properties": {"topic": {"type": "string"}}},
    )

    assert result["topic"] == "тариф"


@patch("src.llm_analyzer.requests.post")
def test_call_llm_retries_on_invalid_json(mock_post):
    """При невалидном JSON должен быть повторный вызов."""
    bad_response = MagicMock()
    bad_response.json.return_value = {
        "message": {"content": "это не json"}
    }
    bad_response.raise_for_status = MagicMock()

    good_response = MagicMock()
    good_response.json.return_value = {
        "message": {"content": '{"topic": "тариф"}'}
    }
    good_response.raise_for_status = MagicMock()

    mock_post.side_effect = [bad_response, good_response]

    result = call_llm(
        system_prompt="Ты аналитик.",
        user_message="Текст.",
    )

    assert result["topic"] == "тариф"
    assert mock_post.call_count == 2


def test_load_prompt(tmp_path):
    """load_prompt должен загрузить текст промпта из файла."""
    prompt_file = tmp_path / "test_prompt.md"
    prompt_file.write_text("Ты аналитик колл-центра.\nАнализируй диалог.")

    result = load_prompt(prompt_file)

    assert "Ты аналитик колл-центра." in result

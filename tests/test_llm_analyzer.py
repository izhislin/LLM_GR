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


@patch("src.llm_analyzer.requests.post")
def test_analyze_dialogue_passes_llm_context(mock_post, tmp_path):
    """analyze_dialogue должен добавлять llm_context перед диалогом."""
    # Создаём промпт-файлы
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    for name in ["summarize.md", "quality_score.md", "extract_data.md"]:
        (prompts_dir / name).write_text("Анализируй.")

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "message": {"content": '{"topic": "тест"}'}
    }
    mock_response.raise_for_status = MagicMock()
    mock_post.return_value = mock_response

    analyze_dialogue(
        "[00:00:00] Оператор: Привет.",
        prompts_dir,
        llm_context="Звонок в компании Гравител.",
    )

    # Проверяем, что контекст был в user_message первого вызова
    first_call_payload = mock_post.call_args_list[0][1]["json"]
    user_msg = first_call_payload["messages"][1]["content"]
    assert "Контекст: Звонок в компании Гравител." in user_msg
    assert "[00:00:00] Оператор: Привет." in user_msg


@patch("src.llm_analyzer.requests.post")
def test_analyze_dialogue_without_context(mock_post, tmp_path):
    """Без llm_context диалог передаётся как есть."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    for name in ["summarize.md", "quality_score.md", "extract_data.md"]:
        (prompts_dir / name).write_text("Анализируй.")

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "message": {"content": '{"topic": "тест"}'}
    }
    mock_response.raise_for_status = MagicMock()
    mock_post.return_value = mock_response

    dialogue = "[00:00:00] Оператор: Привет."
    analyze_dialogue(dialogue, prompts_dir)

    first_call_payload = mock_post.call_args_list[0][1]["json"]
    user_msg = first_call_payload["messages"][1]["content"]
    assert user_msg == dialogue
    assert "Контекст:" not in user_msg

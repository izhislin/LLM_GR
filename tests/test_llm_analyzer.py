"""Тесты для llm_analyzer (с моками Ollama и OpenRouter API)."""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.llm_analyzer import call_llm, call_cloud_llm, analyze_dialogue, load_prompt


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
    """При невалидном JSON должен быть повторный вызов (MAX_RETRIES=3)."""
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

    mock_post.side_effect = [bad_response, bad_response, good_response]

    result = call_llm(
        system_prompt="Ты аналитик.",
        user_message="Текст.",
    )

    assert result["topic"] == "тариф"
    assert mock_post.call_count == 3


@patch("src.llm_analyzer.requests.post")
def test_call_llm_sends_num_ctx_and_json_format(mock_post):
    """call_llm должен передавать num_ctx в options и format='json'."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "message": {"content": '{"ok": true}'}
    }
    mock_response.raise_for_status = MagicMock()
    mock_post.return_value = mock_response

    call_llm(system_prompt="Тест.", user_message="Текст.")

    payload = mock_post.call_args[1]["json"]
    assert payload["options"]["num_ctx"] == 32768
    assert payload["format"] == "json"
    assert payload["think"] is False


@patch("src.llm_analyzer.requests.post")
def test_call_llm_schema_overrides_json_format(mock_post):
    """response_schema должен перезаписать format='json'."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "message": {"content": '{"ok": true}'}
    }
    mock_response.raise_for_status = MagicMock()
    mock_post.return_value = mock_response

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    call_llm(system_prompt="Тест.", user_message="Текст.", response_schema=schema)

    payload = mock_post.call_args[1]["json"]
    assert payload["format"] == schema


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
    for name in ["summarize.md", "quality_score.md", "extract_data.md", "classify.md"]:
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
    for name in ["summarize.md", "quality_score.md", "extract_data.md", "classify.md"]:
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


@patch("src.llm_analyzer.requests.post")
def test_analyze_dialogue_includes_classification(mock_post, sample_dialogue_text, tmp_path):
    """analyze_dialogue должен включать classification в результат (4 LLM-вызова)."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    for name in ["summarize.md", "quality_score.md", "extract_data.md", "classify.md"]:
        (prompts_dir / name).write_text("Анализируй.")

    def make_response(content_dict):
        resp = MagicMock()
        resp.json.return_value = {"message": {"content": json.dumps(content_dict, ensure_ascii=False)}}
        resp.raise_for_status = MagicMock()
        return resp

    mock_post.side_effect = [
        make_response({"call_type": "входящий", "topic": "тариф"}),
        make_response({"total": 7, "is_ivr": False, "criteria": {}, "script_checklist": {}}),
        make_response({"operator_name": "Наталья", "issues": [], "callback_needed": False}),
        make_response({"category": "информация/консультация", "client_intent": "get_info",
                        "sentiment": "neutral", "resolution_status": "resolved",
                        "is_repeat_contact": False, "tags": []}),
    ]

    result = analyze_dialogue(sample_dialogue_text, prompts_dir)

    assert "classification" in result
    assert result["classification"]["category"] == "информация/консультация"
    assert result["classification"]["client_intent"] == "get_info"
    assert mock_post.call_count == 4


# ── Тесты для call_cloud_llm (OpenRouter) ─────────────────────────────────


@patch("src.llm_analyzer.OPENROUTER_API_KEY", "test-key-123")
@patch("src.llm_analyzer.requests.post")
def test_call_cloud_llm_returns_parsed_json(mock_post):
    """call_cloud_llm должен вернуть распарсенный JSON из ответа OpenRouter."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"result": "ok"}'}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    mock_response.raise_for_status = MagicMock()
    mock_post.return_value = mock_response

    result = call_cloud_llm(
        system_prompt="Ты аналитик.",
        user_message="Обобщи тренды.",
    )

    assert result["result"] == "ok"
    # Проверяем что отправлен правильный формат OpenAI
    payload = mock_post.call_args[1]["json"]
    assert "choices" not in payload  # это payload запроса, не ответа
    assert payload["messages"][0]["role"] == "system"
    assert payload["response_format"] == {"type": "json_object"}
    # Проверяем заголовок авторизации
    headers = mock_post.call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer test-key-123"


@patch("src.llm_analyzer.OPENROUTER_API_KEY", "")
def test_call_cloud_llm_raises_without_api_key():
    """call_cloud_llm должен выбросить RuntimeError без API-ключа."""
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY не задан"):
        call_cloud_llm(system_prompt="Тест.", user_message="Текст.")


@patch("src.llm_analyzer.OPENROUTER_API_KEY", "test-key-123")
@patch("src.llm_analyzer.requests.post")
def test_call_cloud_llm_retries_on_invalid_json(mock_post):
    """При невалидном JSON должен быть повторный вызов."""
    bad_response = MagicMock()
    bad_response.json.return_value = {
        "choices": [{"message": {"content": "не json"}}],
    }
    bad_response.raise_for_status = MagicMock()

    good_response = MagicMock()
    good_response.json.return_value = {
        "choices": [{"message": {"content": '{"ok": true}'}}],
        "usage": {},
    }
    good_response.raise_for_status = MagicMock()

    mock_post.side_effect = [bad_response, good_response]

    result = call_cloud_llm(system_prompt="Тест.", user_message="Текст.")
    assert result["ok"] is True
    assert mock_post.call_count == 2

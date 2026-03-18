"""Тесты для pipeline (интеграция модулей с моками)."""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.pipeline import process_audio_file


@pytest.fixture
def mock_prompts(tmp_path):
    """Создать минимальные промпт-файлы."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "summarize.md").write_text("Суммаризируй.")
    (prompts_dir / "quality_score.md").write_text("Оцени.")
    (prompts_dir / "extract_data.md").write_text("Извлеки.")
    return prompts_dir


@patch("src.pipeline.analyze_dialogue")
@patch("src.pipeline.transcribe_channel")
@patch("src.pipeline.split_stereo_to_mono")
@patch("src.pipeline.get_audio_info")
def test_process_audio_file_full_pipeline(
    mock_info, mock_split, mock_transcribe, mock_analyze, tmp_path, mock_prompts
):
    """process_audio_file должен пройти весь пайплайн и вернуть результат."""
    mock_info.return_value = {"channels": 2, "sample_rate": 16000, "duration_sec": 30.0}

    operator_wav = tmp_path / "call_operator.wav"
    client_wav = tmp_path / "call_client.wav"
    operator_wav.touch()
    client_wav.touch()
    mock_split.return_value = (operator_wav, client_wav)

    from src.transcriber import Utterance
    mock_transcribe.side_effect = [
        [Utterance(text="Добрый день.", start=0.0, end=1.5)],
        [Utterance(text="Привет.", start=2.0, end=3.0)],
    ]

    mock_analyze.return_value = {
        "summary": {"topic": "тест", "outcome": "ок", "key_points": []},
        "quality_score": {"total": 8, "criteria": {}},
        "extracted_data": {"client_name": None},
    }

    audio_file = tmp_path / "call.wav"
    audio_file.touch()

    result = process_audio_file(
        audio_path=audio_file,
        output_dir=tmp_path / "results",
        prompts_dir=mock_prompts,
    )

    assert result["file"] == "call.wav"
    assert result["duration_sec"] == 30.0
    assert "transcript" in result
    assert "summary" in result
    assert "quality_score" in result
    assert "extracted_data" in result


@patch("src.pipeline.analyze_dialogue")
@patch("src.pipeline.transcribe_channel")
@patch("src.pipeline.split_stereo_to_mono")
@patch("src.pipeline.get_audio_info")
def test_process_audio_file_saves_json(
    mock_info, mock_split, mock_transcribe, mock_analyze, tmp_path, mock_prompts
):
    """Результат должен сохраниться в JSON-файл."""
    mock_info.return_value = {"channels": 2, "sample_rate": 16000, "duration_sec": 10.0}
    mock_split.return_value = (tmp_path / "op.wav", tmp_path / "cl.wav")
    (tmp_path / "op.wav").touch()
    (tmp_path / "cl.wav").touch()
    mock_transcribe.return_value = []
    mock_analyze.return_value = {
        "summary": {}, "quality_score": {}, "extracted_data": {},
    }

    audio_file = tmp_path / "test_call.wav"
    audio_file.touch()
    output_dir = tmp_path / "results"

    process_audio_file(audio_file, output_dir, mock_prompts)

    result_file = output_dir / "test_call.json"
    assert result_file.exists()
    data = json.loads(result_file.read_text())
    assert data["file"] == "test_call.wav"


@patch("src.pipeline.analyze_dialogue")
@patch("src.pipeline.transcribe_channel")
@patch("src.pipeline.split_stereo_to_mono")
@patch("src.pipeline.get_audio_info")
def test_result_contains_transcript_segments(
    mock_info, mock_split, mock_transcribe, mock_analyze, tmp_path, mock_prompts
):
    """Результат содержит transcript_segments со структурированными данными."""
    mock_info.return_value = {"channels": 2, "sample_rate": 16000, "duration_sec": 30.0}
    operator_wav = tmp_path / "call_operator.wav"
    client_wav = tmp_path / "call_client.wav"
    operator_wav.touch()
    client_wav.touch()
    mock_split.return_value = (operator_wav, client_wav)

    from src.transcriber import Utterance
    mock_transcribe.side_effect = [
        [Utterance(text="Добрый день.", start=0.0, end=1.5)],
        [Utterance(text="Привет.", start=2.0, end=3.0)],
    ]

    mock_analyze.return_value = {
        "summary": {"topic": "тест"}, "quality_score": {"total": 8}, "extracted_data": {},
    }

    audio_file = tmp_path / "call.wav"
    audio_file.touch()
    result = process_audio_file(audio_file, output_dir=tmp_path / "results", prompts_dir=mock_prompts)

    assert "transcript_segments" in result
    assert isinstance(result["transcript_segments"], list)
    assert len(result["transcript_segments"]) == 2

    seg0 = result["transcript_segments"][0]
    assert seg0["speaker"] == "Оператор"
    assert seg0["text"] == "Добрый день."
    assert seg0["start"] == 0.0
    assert seg0["end"] == 1.5

    seg1 = result["transcript_segments"][1]
    assert seg1["speaker"] == "Клиент"
    assert seg1["start"] == 2.0

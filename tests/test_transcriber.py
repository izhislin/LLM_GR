"""Тесты для transcriber (с моками GigaAM)."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.transcriber import transcribe_channel, Utterance


def _mock_utterances():
    """Имитация ответа GigaAM transcribe_longform."""
    return [
        {"transcription": "Добрый день, компания Гравител.", "boundaries": (0.0, 2.5)},
        {"transcription": "Меня зовут Анна.", "boundaries": (2.5, 4.0)},
    ]


@patch("src.transcriber._get_model")
def test_transcribe_channel_returns_utterances(mock_get_model, tmp_path):
    """transcribe_channel должен вернуть список Utterance."""
    mock_model = MagicMock()
    mock_model.transcribe_longform.return_value = _mock_utterances()
    mock_get_model.return_value = mock_model

    fake_audio = tmp_path / "test.wav"
    fake_audio.touch()

    result = transcribe_channel(fake_audio)

    assert len(result) == 2
    assert isinstance(result[0], Utterance)
    assert result[0].text == "Добрый день, компания Гравител."
    assert result[0].start == 0.0
    assert result[0].end == 2.5


@patch("src.transcriber._get_model")
def test_transcribe_channel_empty_audio(mock_get_model, tmp_path):
    """Пустое аудио должно вернуть пустой список."""
    mock_model = MagicMock()
    mock_model.transcribe_longform.return_value = []
    mock_get_model.return_value = mock_model

    fake_audio = tmp_path / "empty.wav"
    fake_audio.touch()

    result = transcribe_channel(fake_audio)
    assert result == []

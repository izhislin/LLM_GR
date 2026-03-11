"""Тесты для dialogue_builder."""

import pytest
from src.dialogue_builder import build_dialogue, dialogue_to_text, DialogueTurn
from src.transcriber import Utterance


def test_build_dialogue_interleaves_speakers():
    """Фразы из двух каналов должны чередоваться по времени."""
    operator = [
        Utterance(text="Добрый день.", start=0.0, end=1.5),
        Utterance(text="Чем могу помочь?", start=3.0, end=4.5),
    ]
    client = [
        Utterance(text="Здравствуйте.", start=1.5, end=2.8),
        Utterance(text="У меня вопрос по тарифу.", start=5.0, end=7.0),
    ]

    dialogue = build_dialogue(operator, client)

    assert len(dialogue) == 4
    assert dialogue[0].speaker == "Оператор"
    assert dialogue[0].text == "Добрый день."
    assert dialogue[1].speaker == "Клиент"
    assert dialogue[1].text == "Здравствуйте."
    assert dialogue[2].speaker == "Оператор"
    assert dialogue[3].speaker == "Клиент"


def test_build_dialogue_empty_channels():
    """Пустые каналы — пустой диалог."""
    dialogue = build_dialogue([], [])
    assert dialogue == []


def test_build_dialogue_one_channel_empty():
    """Если один канал пуст — диалог из одного спикера."""
    operator = [Utterance(text="Алло?", start=0.0, end=1.0)]

    dialogue = build_dialogue(operator, [])

    assert len(dialogue) == 1
    assert dialogue[0].speaker == "Оператор"


def test_build_dialogue_formats_to_text():
    """Диалог должен форматироваться в читаемый текст."""
    operator = [Utterance(text="Добрый день.", start=0.0, end=1.5)]
    client = [Utterance(text="Привет.", start=2.0, end=3.0)]

    dialogue = build_dialogue(operator, client)
    text = dialogue_to_text(dialogue)

    assert "[00:00:00]" in text
    assert "Оператор:" in text
    assert "Клиент:" in text


def test_dialogue_turn_str_format():
    """DialogueTurn.__str__ должен выдавать формат [HH:MM:SS] Спикер: Текст."""
    turn = DialogueTurn(speaker="Оператор", text="Добрый день.", start=65.5, end=67.0)
    assert str(turn) == "[00:01:05] Оператор: Добрый день."

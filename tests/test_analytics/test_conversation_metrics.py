"""Тесты для conversation_metrics — вычисление метрик из transcript_segments."""

import pytest
from src.analytics.conversation_metrics import compute_metrics


@pytest.fixture
def simple_segments():
    """Простой диалог: оператор и клиент по очереди."""
    return [
        {"speaker": "Оператор", "text": "Здравствуйте", "start": 0.0, "end": 3.0},
        {"speaker": "Клиент", "text": "Добрый день", "start": 3.5, "end": 5.0},
        {"speaker": "Оператор", "text": "Чем могу помочь?", "start": 5.5, "end": 8.0},
        {"speaker": "Клиент", "text": "У меня вопрос по тарифу", "start": 8.0, "end": 12.0},
    ]


@pytest.fixture
def segments_with_interruption():
    """Диалог с перебиванием (overlap сегментов)."""
    return [
        {"speaker": "Оператор", "text": "Давайте проверим", "start": 0.0, "end": 5.0},
        {"speaker": "Клиент", "text": "Я уже проверял", "start": 4.0, "end": 7.0},
        {"speaker": "Оператор", "text": "Понял", "start": 7.5, "end": 9.0},
    ]


@pytest.fixture
def segments_with_long_silence():
    """Диалог с длинной паузой (> 2 сек между сегментами)."""
    return [
        {"speaker": "Оператор", "text": "Секунду, проверю", "start": 0.0, "end": 3.0},
        {"speaker": "Оператор", "text": "Нашёл", "start": 15.0, "end": 17.0},
    ]


def test_basic_talk_times(simple_segments):
    """operator_talk_sec и client_talk_sec считаются из длительности сегментов."""
    m = compute_metrics(simple_segments)
    assert m["operator_talk_sec"] == pytest.approx(5.5, abs=0.1)
    assert m["client_talk_sec"] == pytest.approx(5.5, abs=0.1)


def test_talk_ratio(simple_segments):
    """operator_talk_ratio — доля оператора от общего talk time."""
    m = compute_metrics(simple_segments)
    assert m["operator_talk_ratio"] == pytest.approx(0.5, abs=0.05)


def test_total_turns(simple_segments):
    m = compute_metrics(simple_segments)
    assert m["total_turns"] == 4


def test_interruptions(segments_with_interruption):
    """Пересечение сегментов разных спикеров = перебивание."""
    m = compute_metrics(segments_with_interruption)
    assert m["interruptions_count"] == 1


def test_silence(segments_with_long_silence):
    """Паузы > 2 сек считаются как silence."""
    m = compute_metrics(segments_with_long_silence)
    assert m["silence_sec"] == pytest.approx(12.0, abs=0.1)
    assert m["longest_silence_sec"] == pytest.approx(12.0, abs=0.1)


def test_empty_segments():
    """Пустой список сегментов — все метрики нулевые."""
    m = compute_metrics([])
    assert m["operator_talk_sec"] == 0.0
    assert m["client_talk_sec"] == 0.0
    assert m["total_turns"] == 0
    assert m["interruptions_count"] == 0


def test_avg_turn_duration(simple_segments):
    """Средняя длина реплики оператора и клиента."""
    m = compute_metrics(simple_segments)
    assert m["avg_operator_turn_sec"] == pytest.approx(2.75, abs=0.1)
    assert m["avg_client_turn_sec"] == pytest.approx(2.75, abs=0.1)

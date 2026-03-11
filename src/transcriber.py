"""Транскрибация аудио через GigaAM-v3."""

import logging
from dataclasses import dataclass
from pathlib import Path

from src.config import GIGAAM_MODEL, GIGAAM_DEVICE

logger = logging.getLogger(__name__)

_model = None


@dataclass
class Utterance:
    """Одна фраза с таймкодами."""
    text: str
    start: float
    end: float


def _get_model():
    """Загрузить модель GigaAM (singleton, первый вызов скачивает модель)."""
    global _model
    if _model is None:
        import gigaam
        logger.info("Загружаю GigaAM модель %s...", GIGAAM_MODEL)
        _model = gigaam.load_model(
            GIGAAM_MODEL,
            fp16_encoder=True,
            device=GIGAAM_DEVICE,
        )
        logger.info("GigaAM загружена.")
    return _model


def transcribe_channel(audio_path: Path) -> list[Utterance]:
    """Транскрибировать моно-аудиофайл.

    Args:
        audio_path: Путь к моно WAV-файлу (16kHz).

    Returns:
        Список Utterance с текстом и таймкодами.
    """
    audio_path = Path(audio_path)
    model = _get_model()

    raw_utterances = model.transcribe_longform(str(audio_path))

    utterances = []
    for item in raw_utterances:
        start, end = item["boundaries"]
        utterances.append(Utterance(
            text=item["transcription"],
            start=start,
            end=end,
        ))

    logger.info(
        "Транскрибировано %d фраз из %s", len(utterances), audio_path.name
    )
    return utterances


def reset_model():
    """Выгрузить модель из памяти (для тестов и переключения моделей)."""
    global _model
    _model = None

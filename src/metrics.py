"""Prometheus-метрики пайплайна обработки звонков."""

import logging
import time
from contextlib import contextmanager

from src.config import METRICS_PORT

logger = logging.getLogger(__name__)

try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        start_http_server,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

# --- Определения метрик (создаются только если библиотека доступна) ---

if PROMETHEUS_AVAILABLE:
    # Время выполнения каждого этапа пайплайна
    STAGE_SECONDS = Histogram(
        "pipeline_stage_seconds",
        "Время выполнения этапа пайплайна (секунды)",
        labelnames=["stage"],
    )

    # Полное время обработки файла
    PROCESSING_SECONDS = Histogram(
        "pipeline_processing_seconds",
        "Полное время обработки одного файла (секунды)",
    )

    # Последний RTF (Real-Time Factor)
    PIPELINE_RTF = Gauge(
        "pipeline_rtf",
        "Real-Time Factor последней обработки (processing_time / audio_duration)",
    )

    # Счётчик обработанных файлов
    FILES_TOTAL = Counter(
        "pipeline_files_total",
        "Количество обработанных файлов",
        labelnames=["status"],
    )

    # Ollama: скорость генерации
    OLLAMA_TOKENS_PER_SECOND = Gauge(
        "ollama_tokens_per_second",
        "Скорость генерации Ollama (tokens/sec), последний вызов",
    )

    # Ollama: суммарные токены
    OLLAMA_PROMPT_TOKENS = Counter(
        "ollama_prompt_tokens",
        "Суммарное количество prompt-токенов (Ollama)",
    )
    OLLAMA_GENERATED_TOKENS = Counter(
        "ollama_generated_tokens",
        "Суммарное количество сгенерированных токенов (Ollama)",
    )

    # Ollama: ретраи
    OLLAMA_RETRIES = Counter(
        "ollama_retries_total",
        "Количество ретраев Ollama (невалидный JSON)",
    )


def start_metrics_server(port: int = METRICS_PORT) -> None:
    """Запустить HTTP-сервер метрик в daemon-потоке.

    Безопасно вызывать несколько раз — повторный запуск игнорируется.
    Если prometheus_client не установлен — просто логируем предупреждение.
    """
    if not PROMETHEUS_AVAILABLE:
        logger.warning(
            "prometheus_client не установлен — метрики недоступны. "
            "Установите: pip install prometheus_client"
        )
        return

    try:
        start_http_server(port)
        logger.info("Prometheus-метрики доступны на :%d/metrics", port)
    except OSError as exc:
        logger.warning("Не удалось запустить сервер метрик на :%d — %s", port, exc)


@contextmanager
def track_stage(stage_name: str):
    """Замерить время выполнения этапа пайплайна.

    Использование:
        with track_stage("split"):
            split_stereo_to_mono(...)
    """
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        if PROMETHEUS_AVAILABLE:
            STAGE_SECONDS.labels(stage=stage_name).observe(elapsed)
        logger.debug("Этап '%s': %.2f сек", stage_name, elapsed)

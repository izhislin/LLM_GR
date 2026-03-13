"""Тесты для модуля Prometheus-метрик."""

import time
import pytest
from unittest.mock import patch, MagicMock

from src.metrics import (
    PROMETHEUS_AVAILABLE,
    track_stage,
    start_metrics_server,
)

# Тесты пропускаются если prometheus_client не установлен
pytestmark = pytest.mark.skipif(
    not PROMETHEUS_AVAILABLE,
    reason="prometheus_client не установлен",
)


class TestTrackStage:
    """Тесты context manager track_stage."""

    def test_track_stage_records_histogram(self):
        """track_stage должен записать время в Histogram."""
        from src.metrics import STAGE_SECONDS

        # Сохраняем текущий count для label
        before = STAGE_SECONDS.labels(stage="test_stage")._sum.get()

        with track_stage("test_stage"):
            time.sleep(0.05)

        after = STAGE_SECONDS.labels(stage="test_stage")._sum.get()
        elapsed = after - before

        assert elapsed >= 0.04  # допуск на погрешность таймера

    def test_track_stage_passes_through_exceptions(self):
        """track_stage не должен глотать исключения."""
        with pytest.raises(ValueError, match="test error"):
            with track_stage("error_stage"):
                raise ValueError("test error")

    def test_track_stage_records_time_even_on_exception(self):
        """Время записывается даже при ошибке внутри блока."""
        from src.metrics import STAGE_SECONDS

        before = STAGE_SECONDS.labels(stage="exc_stage")._sum.get()

        with pytest.raises(RuntimeError):
            with track_stage("exc_stage"):
                time.sleep(0.02)
                raise RuntimeError("boom")

        after = STAGE_SECONDS.labels(stage="exc_stage")._sum.get()
        assert after - before >= 0.01


class TestStartMetricsServer:
    """Тесты запуска HTTP-сервера метрик."""

    @patch("src.metrics.start_http_server")
    def test_start_metrics_server_calls_http_server(self, mock_start):
        """start_metrics_server вызывает start_http_server с правильным портом."""
        start_metrics_server(port=9999)
        mock_start.assert_called_once_with(9999)

    @patch("src.metrics.start_http_server", side_effect=OSError("Address in use"))
    def test_start_metrics_server_handles_port_conflict(self, mock_start):
        """При занятом порте не должно быть исключения — только warning."""
        # Не должно бросить исключение
        start_metrics_server(port=9999)
        mock_start.assert_called_once()


class TestOllamaMetrics:
    """Тесты обновления Ollama-метрик из llm_analyzer."""

    def test_update_ollama_metrics_increments_counters(self):
        """_update_ollama_metrics обновляет счётчики токенов."""
        from src.llm_analyzer import _update_ollama_metrics
        from src.metrics import (
            OLLAMA_PROMPT_TOKENS,
            OLLAMA_GENERATED_TOKENS,
            OLLAMA_TOKENS_PER_SECOND,
        )

        prompt_before = OLLAMA_PROMPT_TOKENS._value.get()
        gen_before = OLLAMA_GENERATED_TOKENS._value.get()

        _update_ollama_metrics({
            "prompt_eval_count": 100,
            "eval_count": 50,
            "eval_duration": 2_000_000_000,  # 2 секунды в наносекундах
        })

        assert OLLAMA_PROMPT_TOKENS._value.get() - prompt_before == 100
        assert OLLAMA_GENERATED_TOKENS._value.get() - gen_before == 50
        assert OLLAMA_TOKENS_PER_SECOND._value.get() == pytest.approx(25.0)

    def test_update_ollama_metrics_handles_missing_fields(self):
        """При отсутствии полей метаданных не должно быть ошибки."""
        from src.llm_analyzer import _update_ollama_metrics

        # Не должно бросить исключение
        _update_ollama_metrics({})
        _update_ollama_metrics({"message": {"content": "{}"}})

    @patch("src.llm_analyzer.requests.post")
    def test_call_llm_updates_metrics_on_success(self, mock_post):
        """call_llm обновляет метрики при успешном ответе."""
        from src.llm_analyzer import call_llm
        from src.metrics import OLLAMA_GENERATED_TOKENS

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": '{"result": "ok"}'},
            "eval_count": 30,
            "eval_duration": 1_000_000_000,
            "prompt_eval_count": 60,
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        gen_before = OLLAMA_GENERATED_TOKENS._value.get()

        call_llm("prompt", "message")

        assert OLLAMA_GENERATED_TOKENS._value.get() - gen_before == 30

    @patch("src.llm_analyzer.requests.post")
    def test_call_llm_increments_retries_on_bad_json(self, mock_post):
        """При невалидном JSON инкрементируется ollama_retries_total."""
        from src.llm_analyzer import call_llm
        from src.metrics import OLLAMA_RETRIES

        retries_before = OLLAMA_RETRIES._value.get()

        bad_response = MagicMock()
        bad_response.json.return_value = {"message": {"content": "not json"}}
        bad_response.raise_for_status = MagicMock()

        good_response = MagicMock()
        good_response.json.return_value = {
            "message": {"content": '{"ok": true}'},
            "eval_count": 10,
            "eval_duration": 500_000_000,
        }
        good_response.raise_for_status = MagicMock()

        mock_post.side_effect = [bad_response, good_response]

        call_llm("prompt", "message")

        assert OLLAMA_RETRIES._value.get() - retries_before == 1

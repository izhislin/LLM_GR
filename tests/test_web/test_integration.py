"""Интеграционный тест: webhook -> фильтр -> worker -> результат."""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.db import init_db, get_call, get_processing
from src.domain_config import DomainConfig, CallFilters
from src.call_filter import filter_call
from src.worker import CallWorker


@pytest.fixture
def full_setup(tmp_path):
    """Полный setup: БД + конфиг + worker."""
    db = init_db(str(tmp_path / "test.db"))
    config = DomainConfig(
        api_key_env="TEST_KEY",
        profile="gravitel",
        enabled=True,
        polling_interval_min=10,
        filters=CallFilters(min_duration_sec=20, max_duration_sec=1500),
    )
    worker = CallWorker(
        db=db,
        audio_dir=tmp_path / "audio",
        domain_configs={"test.aicall.ru": config},
        api_clients={},
    )
    return db, config, worker


def test_full_cycle_webhook_to_result(full_setup, tmp_path):
    """Полный цикл: звонок -> фильтр -> обработка -> результат в БД."""
    db, config, worker = full_setup

    from src.db import insert_call, insert_processing

    call = {
        "id": "integration_test_001",
        "domain": "test.aicall.ru",
        "direction": "in",
        "result": "success",
        "duration": 120,
        "wait": 5,
        "started_at": "2026-03-13T14:00:00Z",
        "client_number": "79991234567",
        "operator_extension": "701",
        "operator_name": None,
        "phone": "74951112233",
        "record_url": "https://records.aicall.ru/test/integration.mp3",
        "source": "webhook",
        "received_at": "2026-03-13T14:00:05Z",
    }
    insert_call(db, call)

    passed, reason = filter_call(call, config.filters)
    assert passed is True
    insert_processing(db, call["id"], status="pending")

    fake_result = {
        "file": "integration.mp3",
        "transcript": "[00:01] Оператор: Здравствуйте.\n[00:03] Клиент: Привет.",
        "summary": {"topic": "консультация", "outcome": "решено"},
        "quality_score": {"total": 8, "is_ivr": False},
        "extracted_data": {"operator_name": "Иванов"},
    }

    fake_audio = tmp_path / "audio" / "integration.mp3"
    fake_audio.parent.mkdir(parents=True, exist_ok=True)
    fake_audio.write_bytes(b"\xff" * 100)

    with patch.object(worker, "_download_record", return_value=fake_audio):
        with patch("src.worker.process_audio_file", return_value=fake_result):
            worker.process_one("integration_test_001")

    proc = get_processing(db, "integration_test_001")
    assert proc["status"] == "done"
    result = json.loads(proc["result_json"])
    assert result["quality_score"]["total"] == 8
    assert proc["processing_time_sec"] > 0


def test_short_call_skipped_in_full_cycle(full_setup):
    """Короткий звонок пропускается в полном цикле."""
    db, config, worker = full_setup

    from src.db import insert_call, insert_processing

    call = {
        "id": "short_call_001",
        "domain": "test.aicall.ru",
        "direction": "in",
        "result": "success",
        "duration": 10,
        "wait": 2,
        "started_at": "2026-03-13T14:00:00Z",
        "client_number": "79991234567",
        "operator_extension": "701",
        "operator_name": None,
        "phone": "74951112233",
        "record_url": "https://records.aicall.ru/test/short.mp3",
        "source": "webhook",
        "received_at": "2026-03-13T14:00:05Z",
    }
    insert_call(db, call)

    passed, reason = filter_call(call, config.filters)
    assert passed is False
    assert "too short" in reason

    insert_processing(db, call["id"], status="skipped", skip_reason=reason)
    proc = get_processing(db, "short_call_001")
    assert proc["status"] == "skipped"

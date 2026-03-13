"""Тесты фонового обработчика звонков."""

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path

from src.db import init_db, insert_call, insert_processing, get_processing
from src.worker import CallWorker


SAMPLE_CALL = {
    "id": "abc123",
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
    "record_url": "https://records.aicall.ru/test/abc123.mp3",
    "source": "webhook",
    "received_at": "2026-03-13T14:00:05Z",
}


@pytest.fixture
def db(tmp_path):
    db = init_db(str(tmp_path / "test.db"))
    insert_call(db, SAMPLE_CALL)
    insert_processing(db, "abc123", status="pending")
    return db


@pytest.fixture
def worker(db, tmp_path):
    return CallWorker(
        db=db,
        audio_dir=tmp_path / "audio",
        domain_configs={
            "test.aicall.ru": MagicMock(profile="gravitel"),
        },
        api_clients={},
    )


def test_worker_process_call_success(worker, tmp_path):
    """Успешная обработка звонка."""
    fake_audio = tmp_path / "audio" / "abc123.mp3"
    fake_audio.parent.mkdir(parents=True, exist_ok=True)
    fake_audio.write_bytes(b"\xff\xfb\x90\x00" * 100)

    fake_result = {
        "file": "abc123.mp3",
        "transcript": "Оператор: Здравствуйте.",
        "summary": {"topic": "тест"},
        "quality_score": {"total": 8},
        "extracted_data": {},
    }

    with patch.object(worker, "_download_record", return_value=fake_audio):
        with patch("src.worker.process_audio_file", return_value=fake_result):
            worker.process_one("abc123")

    proc = get_processing(worker.db, "abc123")
    assert proc["status"] == "done"
    assert proc["result_json"] is not None
    result = json.loads(proc["result_json"])
    assert result["quality_score"]["total"] == 8


def test_worker_process_call_download_error(worker):
    """Ошибка скачивания → status=error."""
    with patch.object(worker, "_download_record", side_effect=Exception("Network error")):
        worker.process_one("abc123")

    proc = get_processing(worker.db, "abc123")
    assert proc["status"] == "error"
    assert "Network error" in proc["error_message"]


def test_worker_process_call_pipeline_error(worker, tmp_path):
    """Ошибка в pipeline → status=error."""
    fake_audio = tmp_path / "audio" / "abc123.mp3"
    fake_audio.parent.mkdir(parents=True, exist_ok=True)
    fake_audio.write_bytes(b"\xff\xfb\x90\x00")

    with patch.object(worker, "_download_record", return_value=fake_audio):
        with patch("src.worker.process_audio_file", side_effect=RuntimeError("Ollama timeout")):
            worker.process_one("abc123")

    proc = get_processing(worker.db, "abc123")
    assert proc["status"] == "error"
    assert "Ollama timeout" in proc["error_message"]

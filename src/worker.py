"""Фоновый обработчик звонков — скачивание и запуск pipeline."""

import json
import logging
import time
from pathlib import Path

from src.db import (
    get_call,
    get_pending_calls,
    get_retryable_calls,
    get_processing,
    update_processing_status,
)
from src.pipeline import process_audio_file
from src.config import PROMPTS_DIR, RESULTS_DIR

logger = logging.getLogger(__name__)


class CallWorker:
    """Обработчик звонков: скачивание записей и запуск pipeline."""

    def __init__(self, db, audio_dir: Path, domain_configs: dict, api_clients: dict):
        self.db = db
        self.audio_dir = Path(audio_dir)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.domain_configs = domain_configs
        self.api_clients = api_clients

    def _download_record(self, call: dict) -> Path:
        """Скачать запись звонка (синхронно, для ThreadPoolExecutor)."""
        import httpx

        record_url = call["record_url"]
        save_path = self.audio_dir / call["domain"] / f"{call['id']}.mp3"
        save_path.parent.mkdir(parents=True, exist_ok=True)

        resp = httpx.get(record_url, timeout=60.0)
        resp.raise_for_status()
        save_path.write_bytes(resp.content)

        logger.info("Скачан: %s → %s", record_url, save_path)
        return save_path

    def process_one(self, call_id: str) -> None:
        """Обработать один звонок: скачать → pipeline → сохранить результат."""
        call = get_call(self.db, call_id)
        if not call:
            logger.error("Звонок не найден: %s", call_id)
            return

        start_time = time.monotonic()

        try:
            # Пропустить скачивание если файл уже есть на диске
            proc = get_processing(self.db, call_id)
            existing_path = proc.get("audio_path") if proc else None

            if existing_path and Path(existing_path).exists():
                audio_path = Path(existing_path)
                logger.info("Аудио уже скачано: %s", audio_path)
            else:
                update_processing_status(self.db, call_id, status="downloading")
                audio_path = self._download_record(call)

            update_processing_status(
                self.db, call_id, status="processing", audio_path=str(audio_path)
            )

            domain = call["domain"]
            config = self.domain_configs.get(domain)
            profile_name = config.profile if config else None

            result = process_audio_file(
                audio_path=audio_path,
                output_dir=RESULTS_DIR / domain,
                prompts_dir=PROMPTS_DIR,
                profile_name=profile_name,
            )

            processing_time = time.monotonic() - start_time
            update_processing_status(
                self.db,
                call_id,
                status="done",
                result_json=json.dumps(result, ensure_ascii=False),
                processing_time_sec=processing_time,
            )
            logger.info("Обработан: %s (%.1f сек)", call_id, processing_time)

        except Exception as e:
            processing_time = time.monotonic() - start_time
            logger.error("Ошибка обработки %s: %s", call_id, e)
            update_processing_status(
                self.db,
                call_id,
                status="error",
                error_message=str(e),
                processing_time_sec=processing_time,
            )

    def process_pending(self) -> int:
        """Обработать все ожидающие звонки."""
        pending = get_pending_calls(self.db)
        retryable = get_retryable_calls(self.db)

        all_to_process = pending + retryable
        if not all_to_process:
            return 0

        logger.info("В очереди: %d звонков", len(all_to_process))
        processed = 0
        for item in all_to_process:
            call_id = item["call_id"]
            proc = get_processing(self.db, call_id)
            if proc and proc["status"] == "error":
                update_processing_status(self.db, call_id, status="pending")

            self.process_one(call_id)
            processed += 1

        return processed

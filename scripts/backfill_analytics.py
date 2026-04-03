"""Ретроспективная обработка: классификация + FTS5 + профили для существующих звонков.

Прогоняет 4-й LLM-вызов (classify) для звонков, у которых нет classification.
Также индексирует транскрипты в FTS5 и обновляет профили клиентов.

Использование:
    cd ~/01_LLM_GR
    source ~/venv_transcribe/bin/activate
    python scripts/backfill_analytics.py [--limit N] [--dry-run]
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import PROMPTS_DIR
from src.db import init_db
from src.llm_analyzer import call_llm, load_prompt
from src.analytics.search import index_call
from src.analytics.client_profiles import update_profile_on_call
from src.analytics.conversation_metrics import compute_metrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "calls.db"


def backfill(limit: int = 0, dry_run: bool = False):
    conn = init_db(str(DB_PATH))
    classify_prompt = load_prompt(PROMPTS_DIR / "classify.md")

    # Найти звонки без classification
    query = """
        SELECT p.call_id, p.result_json
        FROM processing p
        WHERE p.status = 'done' AND p.result_json IS NOT NULL
        ORDER BY p.completed_at DESC
    """
    rows = conn.execute(query).fetchall()
    logger.info("Всего обработанных звонков: %d", len(rows))

    needs_classify = []
    needs_fts = []
    needs_profile = []

    for row in rows:
        result = json.loads(row["result_json"])
        call_id = row["call_id"]

        if "classification" not in result:
            needs_classify.append(call_id)
        # FTS и profiles — для всех
        needs_fts.append(call_id)
        needs_profile.append(call_id)

    logger.info("Нужна классификация: %d", len(needs_classify))
    logger.info("FTS индексация: %d", len(needs_fts))
    logger.info("Обновление профилей: %d", len(needs_profile))

    if dry_run:
        logger.info("Dry run — выход")
        return

    # 1. FTS индексация (быстро)
    logger.info("=== FTS5 индексация ===")
    fts_count = 0
    for call_id in needs_fts:
        if index_call(conn, call_id):
            fts_count += 1
    logger.info("FTS: проиндексировано %d звонков", fts_count)

    # 2. Conversation metrics (быстро, для тех у кого есть transcript_segments)
    logger.info("=== Conversation metrics ===")
    metrics_count = 0
    for row in rows:
        result = json.loads(row["result_json"])
        if "conversation_metrics" not in result and "transcript_segments" in result:
            cm = compute_metrics(result["transcript_segments"])
            result["conversation_metrics"] = cm
            conn.execute(
                "UPDATE processing SET result_json = ? WHERE call_id = ?",
                (json.dumps(result, ensure_ascii=False), row["call_id"]),
            )
            metrics_count += 1
    if metrics_count:
        conn.commit()
    logger.info("Metrics: добавлены для %d звонков", metrics_count)

    # 3. Classification (долго — LLM вызовы)
    classify_list = needs_classify[:limit] if limit > 0 else needs_classify
    logger.info("=== Классификация: %d звонков ===", len(classify_list))

    for i, call_id in enumerate(classify_list):
        row = conn.execute(
            "SELECT result_json FROM processing WHERE call_id = ?",
            (call_id,),
        ).fetchone()
        if not row:
            continue

        result = json.loads(row["result_json"])
        transcript = result.get("transcript", "")
        if not transcript:
            logger.warning("Пропуск %s: нет транскрипта", call_id)
            continue

        try:
            start = time.monotonic()
            classification = call_llm(
                system_prompt=classify_prompt,
                user_message=transcript,
            )
            elapsed = time.monotonic() - start

            result["classification"] = classification
            conn.execute(
                "UPDATE processing SET result_json = ? WHERE call_id = ?",
                (json.dumps(result, ensure_ascii=False), call_id),
            )
            conn.commit()

            logger.info(
                "[%d/%d] %s → %s (%s) %.1fs",
                i + 1, len(classify_list), call_id,
                classification.get("category", "?"),
                classification.get("sentiment", "?"),
                elapsed,
            )
        except Exception as e:
            logger.error("[%d/%d] %s: ошибка: %s", i + 1, len(classify_list), call_id, e)
            continue

    # 4. Профили клиентов
    logger.info("=== Обновление профилей клиентов ===")
    profile_count = 0
    for call_id in needs_profile:
        try:
            update_profile_on_call(conn, call_id)
            profile_count += 1
        except Exception as e:
            logger.warning("Профиль %s: %s", call_id, e)
    logger.info("Профили: обновлено %d", profile_count)

    logger.info("=== Готово ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill analytics for existing calls")
    parser.add_argument("--limit", type=int, default=0, help="Max calls to classify (0=all)")
    parser.add_argument("--dry-run", action="store_true", help="Only count, don't process")
    args = parser.parse_args()
    backfill(limit=args.limit, dry_run=args.dry_run)

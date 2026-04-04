"""Переклассифицировать звонки с category='другое' улучшенным промптом.

Использование:
    cd ~/01_LLM_GR
    source ~/venv_transcribe/bin/activate
    python scripts/reclassify_other.py [--limit N] [--dry-run]
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "calls.db"


def reclassify(limit: int = 0, dry_run: bool = False):
    conn = init_db(str(DB_PATH))
    classify_prompt = load_prompt(PROMPTS_DIR / "classify.md")

    rows = conn.execute(
        """SELECT p.call_id, p.result_json
           FROM processing p
           WHERE p.status = 'done' AND p.result_json IS NOT NULL
             AND json_extract(p.result_json, '$.classification.category') = 'другое'
           ORDER BY p.completed_at DESC"""
    ).fetchall()

    logger.info("Звонков с category='другое': %d", len(rows))
    if dry_run:
        return

    to_process = rows[:limit] if limit > 0 else rows
    changed = 0

    for i, row in enumerate(to_process):
        result = json.loads(row["result_json"])
        transcript = result.get("transcript", "")
        if not transcript:
            continue

        try:
            start = time.monotonic()
            classification = call_llm(
                system_prompt=classify_prompt,
                user_message=transcript,
            )
            elapsed = time.monotonic() - start

            old_cat = result["classification"]["category"]
            new_cat = classification.get("category", "другое")

            result["classification"] = classification
            conn.execute(
                "UPDATE processing SET result_json = ? WHERE call_id = ?",
                (json.dumps(result, ensure_ascii=False), row["call_id"]),
            )
            conn.commit()

            if new_cat != old_cat:
                changed += 1
                logger.info(
                    "[%d/%d] %s: %s -> %s (%.1fs)",
                    i + 1, len(to_process), row["call_id"], old_cat, new_cat, elapsed,
                )
            else:
                logger.info(
                    "[%d/%d] %s: остался %s (%.1fs)",
                    i + 1, len(to_process), row["call_id"], new_cat, elapsed,
                )
        except Exception as e:
            logger.error("[%d/%d] %s: %s", i + 1, len(to_process), row["call_id"], e)

    logger.info("Переклассифицировано: %d из %d", changed, len(to_process))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    reclassify(limit=args.limit, dry_run=args.dry_run)

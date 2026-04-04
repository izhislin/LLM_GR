"""Ежедневный batch: агрегация базы знаний + пересчёт профилей клиентов.

Запускать через cron:
    0 3 * * * cd /home/aiadmin/01_LLM_GR && /home/aiadmin/venv_transcribe/bin/python scripts/daily_analytics.py >> logs/daily_analytics.log 2>&1
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import init_db
from src.analytics.knowledge import aggregate_knowledge
from src.analytics.client_profiles import recalculate_profiles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "calls.db"


def main():
    conn = init_db(str(DB_PATH))

    # Определить домены
    domains = conn.execute(
        "SELECT DISTINCT domain FROM calls WHERE domain IS NOT NULL"
    ).fetchall()

    for row in domains:
        domain = row["domain"]
        logger.info("=== Домен: %s ===", domain)

        kb_count = aggregate_knowledge(conn, domain)
        logger.info("KB: %d записей обновлено", kb_count)

        profile_count = recalculate_profiles(conn, domain)
        logger.info("Профили: %d пересчитано", profile_count)

    logger.info("=== Готово ===")


if __name__ == "__main__":
    main()

"""Генерация knowledge_scenarios из топ-записей KB через облачный LLM.

Берёт записи knowledge_base с frequency >= порога и без существующего сценария,
генерирует диагностические скрипты через MiMo-V2-Pro (OpenRouter).

Использование:
    cd ~/01_LLM_GR
    source ~/venv_transcribe/bin/activate
    python scripts/generate_scenarios.py [--min-freq 10] [--limit 10] [--dry-run]
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import init_db
from src.llm_analyzer import call_cloud_llm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "calls.db"

SCENARIO_PROMPT = """Ты — эксперт по созданию сценариев для операторов колл-центра и голосовых роботов.

На основе данных о типовой проблеме, типичных решениях и примерах из реальных звонков — создай подробный сценарий обработки таких обращений.

Верни JSON:

{
  "scenario_name": "Краткое название сценария (1 строка)",
  "typical_questions": ["Вопрос 1, который задаёт клиент", "Вопрос 2", "..."],
  "recommended_script": "Рекомендуемый скрипт ответа оператора/робота (2-4 предложения)",
  "diagnostic_steps": ["Шаг 1 диагностики", "Шаг 2", "Шаг 3", "..."]
}

Правила:
- typical_questions: 3-5 формулировок, как клиент описывает эту проблему
- recommended_script: конкретный текст для оператора/робота, вежливый и профессиональный
- diagnostic_steps: пошаговая инструкция для решения (3-7 шагов)
- Пиши на русском
- Верни ТОЛЬКО валидный JSON
"""


def generate_scenarios(min_freq: int = 10, limit: int = 10, dry_run: bool = False):
    conn = init_db(str(DB_PATH))

    # KB записи с высокой частотой, для которых нет сценария
    rows = conn.execute(
        """SELECT kb.id, kb.domain, kb.category, kb.subcategory,
                  kb.problem_description, kb.solution_description,
                  kb.frequency, kb.success_rate
           FROM knowledge_base kb
           LEFT JOIN knowledge_scenarios ks
             ON kb.domain = ks.domain AND kb.category = ks.category
                AND COALESCE(kb.subcategory, '') = COALESCE(ks.scenario_name, '')
           WHERE kb.frequency >= ? AND ks.id IS NULL
           ORDER BY kb.frequency DESC
           LIMIT ?""",
        (min_freq, limit),
    ).fetchall()

    logger.info("KB записей для генерации сценариев: %d (min_freq=%d)", len(rows), min_freq)

    if dry_run:
        for r in rows:
            logger.info("  [%dx] %s / %s", r["frequency"], r["category"], r["subcategory"] or "\u2014")
        return

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    generated = 0
    for i, r in enumerate(rows):
        user_msg = (
            f"Категория: {r['category']}\n"
            f"Подкатегория: {r['subcategory'] or 'общая'}\n"
            f"Частота: {r['frequency']} звонков\n"
            f"Решаемость: {int((r['success_rate'] or 0) * 100)}%\n\n"
            f"Типичные проблемы:\n{r['problem_description']}\n\n"
            f"Типичные решения:\n{r['solution_description'] or 'Не зафиксированы'}"
        )

        try:
            start = time.monotonic()
            scenario = call_cloud_llm(
                system_prompt=SCENARIO_PROMPT,
                user_message=user_msg,
            )
            elapsed = time.monotonic() - start

            conn.execute(
                """INSERT INTO knowledge_scenarios
                   (domain, category, scenario_name, typical_questions,
                    recommended_script, diagnostic_steps, source_call_ids,
                    success_rate, auto_generated, approved, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?)""",
                (
                    r["domain"],
                    r["category"],
                    scenario.get("scenario_name", r["subcategory"] or r["category"]),
                    json.dumps(scenario.get("typical_questions", []), ensure_ascii=False),
                    scenario.get("recommended_script", ""),
                    json.dumps(scenario.get("diagnostic_steps", []), ensure_ascii=False),
                    "[]",
                    r["success_rate"],
                    now, now,
                ),
            )
            conn.commit()
            generated += 1

            logger.info(
                "[%d/%d] %s / %s -> \"%s\" (%.1fs)",
                i + 1, len(rows), r["category"], r["subcategory"] or "\u2014",
                scenario.get("scenario_name", "?"), elapsed,
            )
        except Exception as e:
            logger.error("[%d/%d] %s: %s", i + 1, len(rows), r["category"], e)

    logger.info("Сгенерировано сценариев: %d", generated)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-freq", type=int, default=10)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    generate_scenarios(min_freq=args.min_freq, limit=args.limit, dry_run=args.dry_run)

"""Показать содержимое базы знаний."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import init_db

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "calls.db"

conn = init_db(str(DB_PATH))
total = conn.execute("SELECT COUNT(*) FROM knowledge_base").fetchone()[0]
print(f"Всего записей в базе знаний: {total}")
print("=" * 80)

rows = conn.execute(
    """SELECT category, subcategory, problem_description, solution_description,
              frequency, success_rate
       FROM knowledge_base ORDER BY frequency DESC"""
).fetchall()

for r in rows:
    cat, sub, prob, sol, freq, rate = r[0], r[1], r[2], r[3], r[4], r[5]
    pct = int((rate or 0) * 100)
    print(f"\n[{freq}x | решено {pct}%] {cat} / {sub or '—'}")
    print(f"  Проблема: {(prob or '—')[:150]}")
    print(f"  Решение:  {(sol or '—')[:150]}")

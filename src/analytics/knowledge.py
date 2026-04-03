"""Batch-агрегация базы знаний из обработанных звонков."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def aggregate_knowledge(conn: sqlite3.Connection, domain: str) -> int:
    """Агрегировать знания из обработанных звонков.

    Группирует звонки по category+subcategory, создаёт или обновляет
    записи в knowledge_base.

    Returns:
        Количество созданных/обновлённых записей.
    """
    rows = conn.execute(
        """SELECT c.id, p.result_json
           FROM calls c JOIN processing p ON c.id = p.call_id
           WHERE c.domain = ? AND p.status = 'done' AND p.result_json IS NOT NULL""",
        (domain,),
    ).fetchall()

    groups: dict[tuple[str, str], list] = defaultdict(list)
    for row in rows:
        result = json.loads(row["result_json"])
        cl = result.get("classification", {})
        cat = cl.get("category", "другое")
        subcat = cl.get("subcategory", "")
        groups[(cat, subcat)].append({
            "call_id": row["id"],
            "issues": result.get("extracted_data", {}).get("issues", []),
            "next_steps": result.get("extracted_data", {}).get("next_steps", []),
            "topic": result.get("summary", {}).get("topic", ""),
            "outcome": result.get("summary", {}).get("outcome", ""),
            "resolution": cl.get("resolution_status", ""),
        })

    now = _now_iso()
    updated = 0

    for (cat, subcat), calls in groups.items():
        if not calls:
            continue

        all_issues = []
        all_solutions = []
        call_ids = []
        resolved_count = 0
        for c in calls:
            all_issues.extend(c["issues"])
            all_solutions.extend(c["next_steps"])
            call_ids.append(c["call_id"])
            if c["resolution"] == "resolved":
                resolved_count += 1

        problem_desc = "; ".join(set(filter(None, all_issues)))[:500] or calls[0]["topic"]
        solution_desc = "; ".join(set(filter(None, all_solutions)))[:500] or ""
        success_rate = round(resolved_count / len(calls), 2) if calls else 0

        existing = conn.execute(
            "SELECT id FROM knowledge_base WHERE domain = ? AND category = ? AND subcategory = ?",
            (domain, cat, subcat or ""),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE knowledge_base SET
                    frequency = ?,
                    problem_description = ?,
                    solution_description = ?,
                    success_rate = ?,
                    example_call_ids = ?,
                    updated_at = ?
                WHERE id = ?""",
                (len(calls), problem_desc, solution_desc, success_rate,
                 json.dumps(call_ids[-10:]), now, existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO knowledge_base
                   (domain, category, subcategory, problem_description,
                    solution_description, frequency, success_rate,
                    example_call_ids, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (domain, cat, subcat or "", problem_desc, solution_desc,
                 len(calls), success_rate, json.dumps(call_ids[-10:]), now, now),
            )
        updated += 1

    conn.commit()
    return updated

"""Полнотекстовый поиск по звонкам (SQLite FTS5)."""

from __future__ import annotations

import json
import sqlite3


def index_call(conn: sqlite3.Connection, call_id: str) -> bool:
    """Индексировать звонок в FTS5.

    Извлекает transcript, topic и issues из result_json и добавляет в calls_fts.
    Идемпотентно — удаляет старую запись перед вставкой.

    Returns:
        True если индексация успешна, False если нет result_json.
    """
    row = conn.execute(
        "SELECT result_json FROM processing WHERE call_id = ?",
        (call_id,),
    ).fetchone()

    if not row or not row["result_json"]:
        return False

    result = json.loads(row["result_json"])
    transcript = result.get("transcript", "")
    topic = result.get("summary", {}).get("topic", "")
    issues_list = result.get("extracted_data", {}).get("issues", [])
    issues = " ".join(issues_list) if issues_list else ""

    # Удалить старую запись (идемпотентность)
    conn.execute("DELETE FROM calls_fts WHERE call_id = ?", (call_id,))
    conn.execute(
        "INSERT INTO calls_fts (call_id, transcript, topic, issues) VALUES (?, ?, ?, ?)",
        (call_id, transcript, topic, issues),
    )
    conn.commit()
    return True


def search_calls(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 50,
) -> list[dict]:
    """Поиск звонков по FTS5 запросу.

    Args:
        query: поисковый запрос (FTS5 синтаксис: фразы в кавычках, OR, AND).
        limit: максимум результатов.

    Returns:
        Список dict с call_id и rank.
    """
    cursor = conn.execute(
        """SELECT call_id, rank
           FROM calls_fts
           WHERE calls_fts MATCH ?
           ORDER BY rank
           LIMIT ?""",
        (query, limit),
    )
    return [{"call_id": row["call_id"], "rank": row["rank"]} for row in cursor.fetchall()]

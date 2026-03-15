#!/usr/bin/env python3
"""Сброс статуса звонков для повторной обработки.

Использование:
    python scripts/reprocess_calls.py <call_id1> <call_id2> ...
    python scripts/reprocess_calls.py --search <подстрока>

Примеры:
    python scripts/reprocess_calls.py 1351939 1351961 1352020 1352048
    python scripts/reprocess_calls.py --search 1351939
"""

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "calls.db"


def get_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        print(f"БД не найдена: {DB_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def search_calls(conn: sqlite3.Connection, pattern: str) -> list[dict]:
    """Поиск звонков по подстроке в call_id."""
    cursor = conn.execute(
        """
        SELECT p.call_id, p.status, p.retry_count, p.error_message,
               p.audio_path, p.processing_time_sec
        FROM processing p
        WHERE p.call_id LIKE ?
        ORDER BY p.call_id
        """,
        (f"%{pattern}%",),
    )
    return [dict(row) for row in cursor.fetchall()]


def show_status(conn: sqlite3.Connection, call_ids: list[str]) -> list[str]:
    """Показать текущий статус и вернуть найденные call_id."""
    found = []
    for cid in call_ids:
        # Точное совпадение
        cursor = conn.execute(
            "SELECT call_id, status, retry_count, error_message FROM processing WHERE call_id = ?",
            (cid,),
        )
        row = cursor.fetchone()
        if row:
            found.append(row["call_id"])
            print(f"  {row['call_id']}: {row['status']} (retries: {row['retry_count']}, error: {row['error_message'] or '-'})")
            continue

        # Поиск по подстроке
        matches = search_calls(conn, cid)
        if matches:
            for m in matches:
                found.append(m["call_id"])
                print(f"  {m['call_id']}: {m['status']} (retries: {m['retry_count']}, error: {m['error_message'] or '-'})")
        else:
            print(f"  {cid}: НЕ НАЙДЕН")

    return found


def reset_to_pending(conn: sqlite3.Connection, call_ids: list[str]) -> int:
    """Сбросить статус на pending для переобработки."""
    count = 0
    for cid in call_ids:
        cursor = conn.execute(
            """
            UPDATE processing
            SET status = 'pending',
                error_message = 'manual reprocess',
                retry_count = 0,
                result_json = NULL,
                completed_at = NULL,
                started_at = NULL,
                processing_time_sec = NULL
            WHERE call_id = ?
            """,
            (cid,),
        )
        count += cursor.rowcount
    conn.commit()
    return count


def main():
    parser = argparse.ArgumentParser(description="Переобработка звонков")
    parser.add_argument("call_ids", nargs="*", help="ID звонков (точные или подстроки)")
    parser.add_argument("--search", help="Поиск по подстроке")
    parser.add_argument("--dry-run", action="store_true", help="Только показать статус, не менять")
    args = parser.parse_args()

    if not args.call_ids and not args.search:
        parser.print_help()
        sys.exit(1)

    conn = get_db()

    if args.search:
        results = search_calls(conn, args.search)
        if not results:
            print(f"Ничего не найдено по '{args.search}'")
            sys.exit(1)
        for r in results:
            print(f"  {r['call_id']}: {r['status']} (retries: {r['retry_count']})")
        conn.close()
        return

    ids = args.call_ids
    print(f"Поиск {len(ids)} звонков...")
    found = show_status(conn, ids)

    if not found:
        print("Ни один звонок не найден.")
        conn.close()
        sys.exit(1)

    if args.dry_run:
        print(f"\n[dry-run] Найдено {len(found)} звонков, без изменений.")
        conn.close()
        return

    print(f"\nСброс {len(found)} звонков в pending...")
    count = reset_to_pending(conn, found)
    print(f"Сброшено: {count}")

    # Показать новый статус
    print("\nНовый статус:")
    show_status(conn, found)

    conn.close()
    print("\nЗвонки будут обработаны в следующем цикле scheduler (~10 мин)")
    print("Или запустите: curl -X POST http://localhost:8080/api/sync/<domain>")


if __name__ == "__main__":
    main()

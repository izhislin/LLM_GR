"""Профили клиентов — инкрементальное обновление и batch-пересчёт."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def update_profile_on_call(conn: sqlite3.Connection, call_id: str) -> None:
    """Инкрементальное обновление профиля клиента после обработки звонка.

    Создаёт профиль если не существует, обновляет счётчики и last_seen.
    """
    row = conn.execute(
        """SELECT c.client_number, c.domain, c.started_at,
                  p.result_json
           FROM calls c JOIN processing p ON c.id = p.call_id
           WHERE c.id = ? AND c.client_number IS NOT NULL""",
        (call_id,),
    ).fetchone()
    if not row or not row["result_json"]:
        return

    client_number = row["client_number"]
    domain = row["domain"]
    started_at = row["started_at"]
    result = json.loads(row["result_json"])

    extracted = result.get("extracted_data", {})
    has_issues = bool(extracted.get("issues"))

    now = _now_iso()

    existing = conn.execute(
        "SELECT * FROM client_profiles WHERE client_number = ?",
        (client_number,),
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE client_profiles SET
                total_calls = total_calls + 1,
                calls_with_issues = calls_with_issues + ?,
                last_seen = MAX(last_seen, ?),
                extracted_name = COALESCE(?, extracted_name),
                extracted_contract = COALESCE(?, extracted_contract),
                updated_at = ?
            WHERE client_number = ?""",
            (
                1 if has_issues else 0,
                started_at,
                extracted.get("client_name"),
                extracted.get("contract_number"),
                now,
                client_number,
            ),
        )
    else:
        conn.execute(
            """INSERT INTO client_profiles
               (client_number, domain, first_seen, last_seen,
                total_calls, calls_with_issues,
                extracted_name, extracted_contract, updated_at)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)""",
            (
                client_number, domain, started_at, started_at,
                1 if has_issues else 0,
                extracted.get("client_name"),
                extracted.get("contract_number"),
                now,
            ),
        )
    conn.commit()


def recalculate_profiles(conn: sqlite3.Connection, domain: str) -> int:
    """Batch-пересчёт risk_level, primary_category, sentiment_trend.

    Returns:
        Количество обновлённых профилей.
    """
    profiles = conn.execute(
        "SELECT client_number FROM client_profiles WHERE domain = ?",
        (domain,),
    ).fetchall()

    updated = 0
    for profile in profiles:
        client_number = profile["client_number"]

        calls = conn.execute(
            """SELECT p.result_json
               FROM calls c JOIN processing p ON c.id = p.call_id
               WHERE c.client_number = ? AND p.result_json IS NOT NULL
               ORDER BY c.started_at DESC LIMIT 10""",
            (client_number,),
        ).fetchall()

        if not calls:
            continue

        categories = []
        sentiments = []
        risk_signals = 0

        for call_row in calls:
            result = json.loads(call_row["result_json"])
            cl = result.get("classification", {})
            categories.append(cl.get("category", "другое"))
            sentiments.append(cl.get("sentiment", "neutral"))
            if cl.get("is_repeat_contact"):
                risk_signals += 1
            if "угроза_ухода" in cl.get("tags", []):
                risk_signals += 2
            if cl.get("sentiment") == "negative":
                risk_signals += 1

        primary_category = max(set(categories), key=categories.count) if categories else None

        recent = sentiments[:3]
        neg_count = recent.count("negative")
        pos_count = recent.count("positive")
        if neg_count >= 2:
            sentiment_trend = "declining"
        elif pos_count >= 2:
            sentiment_trend = "improving"
        else:
            sentiment_trend = "stable"

        if risk_signals >= 4:
            risk_level = "high"
        elif risk_signals >= 2:
            risk_level = "medium"
        else:
            risk_level = "low"

        conn.execute(
            """UPDATE client_profiles SET
                primary_category = ?,
                sentiment_trend = ?,
                risk_level = ?,
                updated_at = ?
            WHERE client_number = ?""",
            (primary_category, sentiment_trend, risk_level, _now_iso(), client_number),
        )
        updated += 1

    conn.commit()
    return updated

"""API-эндпоинты для дашбордов аналитики."""

import json
import logging
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.analytics.search import search_calls

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard")

_db: sqlite3.Connection | None = None
_templates_dir = Path(__file__).parent.parent / "templates"


def set_dependencies(db: sqlite3.Connection):
    global _db
    _db = db


def _query_results(domain: str, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    """Получить result_json для звонков с фильтрами."""
    query = """
        SELECT c.id, c.operator_extension, c.client_number, c.started_at,
               c.duration, c.direction, p.result_json
        FROM calls c JOIN processing p ON c.id = p.call_id
        WHERE p.status = 'done' AND p.result_json IS NOT NULL AND c.domain = ?
    """
    params: list = [domain]
    if date_from:
        query += " AND c.started_at >= ?"
        params.append(date_from)
    if date_to:
        query += " AND c.started_at < ?"
        params.append(date_to)
    query += " ORDER BY c.started_at DESC"

    rows = _db.execute(query, params).fetchall()
    results = []
    for row in rows:
        r = dict(row)
        r["result"] = json.loads(r.pop("result_json"))
        results.append(r)
    return results


# ── Дашборд руководителя ─────────────────────────────────────────────────


@router.get("/business/kpis")
def business_kpis(
    domain: str,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """KPI-карточки для дашборда руководителя."""
    rows = _query_results(domain, date_from, date_to)
    if not rows:
        return {"total_calls": 0, "avg_quality": 0, "missed_count": 0,
                "missed_pct": 0, "repeat_pct": 0, "risk_clients": 0}

    total = len(rows)
    scores = [r["result"].get("quality_score", {}).get("total") for r in rows
              if r["result"].get("quality_score", {}).get("total") is not None]
    avg_quality = round(sum(scores) / len(scores), 1) if scores else 0

    missed = _db.execute(
        "SELECT COUNT(*) as cnt FROM calls WHERE domain = ? AND direction = 'missed'",
        (domain,),
    ).fetchone()["cnt"]
    all_calls = _db.execute(
        "SELECT COUNT(*) as cnt FROM calls WHERE domain = ?", (domain,)
    ).fetchone()["cnt"]
    missed_pct = round(missed / all_calls * 100, 1) if all_calls else 0

    repeat_count = sum(
        1 for r in rows
        if r["result"].get("classification", {}).get("is_repeat_contact")
    )
    repeat_pct = round(repeat_count / total * 100, 1) if total else 0

    risk_clients = _db.execute(
        "SELECT COUNT(*) as cnt FROM client_profiles WHERE domain = ? AND risk_level IN ('medium', 'high')",
        (domain,),
    ).fetchone()["cnt"]

    return {
        "total_calls": total,
        "avg_quality": avg_quality,
        "missed_count": missed,
        "missed_pct": missed_pct,
        "repeat_pct": repeat_pct,
        "risk_clients": risk_clients,
    }


@router.get("/business/categories")
def business_categories(
    domain: str,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Распределение по категориям."""
    rows = _query_results(domain, date_from, date_to)
    counts: dict[str, int] = {}
    for r in rows:
        cat = r["result"].get("classification", {}).get("category", "другое")
        counts[cat] = counts.get(cat, 0) + 1

    return sorted(
        [{"category": k, "count": v} for k, v in counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )


@router.get("/business/sentiment")
def business_sentiment(
    domain: str,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Распределение sentiment."""
    rows = _query_results(domain, date_from, date_to)
    counts: dict[str, int] = {"positive": 0, "neutral": 0, "negative": 0}
    for r in rows:
        s = r["result"].get("classification", {}).get("sentiment", "neutral")
        counts[s] = counts.get(s, 0) + 1
    return counts


@router.get("/business/risk-clients")
def business_risk_clients(domain: str):
    """Клиенты в зоне риска."""
    rows = _db.execute(
        """SELECT * FROM client_profiles
           WHERE domain = ? AND risk_level IN ('medium', 'high')
           ORDER BY risk_level DESC, total_calls DESC""",
        (domain,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Дашборд супервизора ──────────────────────────────────────────────────


@router.get("/supervisor/operators")
def supervisor_operators(
    domain: str,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Рейтинг операторов: средний балл, количество звонков."""
    rows = _query_results(domain, date_from, date_to)
    operators: dict[str, dict] = {}
    for r in rows:
        ext = r["operator_extension"]
        if not ext:
            continue
        if ext not in operators:
            operators[ext] = {"extension": ext, "scores": [], "call_count": 0, "talk_ratios": []}
        operators[ext]["call_count"] += 1
        score = r["result"].get("quality_score", {}).get("total")
        if score is not None:
            operators[ext]["scores"].append(score)
        tr = r["result"].get("conversation_metrics", {}).get("operator_talk_ratio")
        if tr is not None:
            operators[ext]["talk_ratios"].append(tr)

    result = []
    for ext, data in operators.items():
        name_row = _db.execute(
            "SELECT name FROM operators WHERE domain = ? AND extension = ?",
            (domain, ext),
        ).fetchone()
        avg_score = round(sum(data["scores"]) / len(data["scores"]), 1) if data["scores"] else None
        avg_talk_ratio = round(sum(data["talk_ratios"]) / len(data["talk_ratios"]), 2) if data["talk_ratios"] else None
        result.append({
            "extension": ext,
            "name": name_row["name"] if name_row else ext,
            "call_count": data["call_count"],
            "avg_score": avg_score,
            "avg_talk_ratio": avg_talk_ratio,
        })

    return sorted(result, key=lambda x: x["avg_score"] or 0, reverse=True)


@router.get("/supervisor/script-checklist")
def supervisor_script_checklist(
    domain: str,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Агрегация чеклиста скрипта по операторам."""
    rows = _query_results(domain, date_from, date_to)
    operators: dict[str, dict] = {}
    checklist_fields = [
        "greeted_with_name", "greeted_with_company", "identified_client",
        "clarified_issue", "offered_solution", "summarized_outcome", "said_goodbye",
    ]

    for r in rows:
        ext = r["operator_extension"]
        if not ext:
            continue
        checklist = r["result"].get("quality_score", {}).get("script_checklist", {})
        if not checklist:
            continue
        if ext not in operators:
            operators[ext] = {field: {"true": 0, "total": 0} for field in checklist_fields}
        for field in checklist_fields:
            if field in checklist:
                operators[ext][field]["total"] += 1
                if checklist[field]:
                    operators[ext][field]["true"] += 1

    result = {}
    for ext, fields in operators.items():
        name_row = _db.execute(
            "SELECT name FROM operators WHERE domain = ? AND extension = ?",
            (domain, ext),
        ).fetchone()
        result[name_row["name"] if name_row else ext] = {
            field: round(data["true"] / data["total"] * 100) if data["total"] > 0 else 0
            for field, data in fields.items()
        }
    return result


# ── Поиск ─────────────────────────────────────────────────────────────────


@router.get("/search")
def dashboard_search(q: str, limit: int = Query(50, ge=1, le=200)):
    """Полнотекстовый поиск по звонкам."""
    return search_calls(_db, q, limit=limit)


# ── HTML-страницы дашбордов ───────────────────────────────────────────────


@router.get("/business", response_class=HTMLResponse)
def business_dashboard_page(request: Request, domain: str = "gravitel.ru"):
    templates = Jinja2Templates(directory=str(_templates_dir))
    return templates.TemplateResponse("dashboard_business.html", {"request": request, "domain": domain})


@router.get("/supervisor", response_class=HTMLResponse)
def supervisor_dashboard_page(request: Request, domain: str = "gravitel.ru"):
    templates = Jinja2Templates(directory=str(_templates_dir))
    return templates.TemplateResponse("dashboard_supervisor.html", {"request": request, "domain": domain})

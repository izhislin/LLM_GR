"""REST API для веб-интерфейса."""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from src.config import DATA_DIR
from src.db import (
    get_call,
    list_calls,
    get_calls_count,
    get_processing,
    get_operator_name,
    list_operators,
    list_departments,
)
from src.domain_config import DomainConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_db = None
_domain_configs: dict[str, DomainConfig] = {}


def set_dependencies(db, domain_configs: dict[str, DomainConfig]):
    """Установить зависимости (БД-соединение и конфигурации доменов)."""
    global _db, _domain_configs
    _db = db
    _domain_configs = domain_configs


@router.get("/calls")
def api_list_calls(
    domain: str | None = None,
    direction: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    operator: str | None = None,
    client_search: str | None = None,
    score_min: float | None = None,
    score_max: float | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    """Список звонков с фильтрами и пагинацией."""
    calls = list_calls(
        _db,
        domain=domain,
        direction=direction,
        status=status,
        date_from=date_from,
        date_to=date_to,
        operator=operator,
        client_search=client_search,
        score_min=score_min,
        score_max=score_max,
        sort_by=sort_by or "started_at",
        sort_order=sort_order or "desc",
        page=page,
        per_page=per_page,
    )
    total = get_calls_count(
        _db,
        domain=domain,
        status=status,
        direction=direction,
        operator=operator,
        date_from=date_from,
        date_to=date_to,
        client_search=client_search,
        score_min=score_min,
        score_max=score_max,
    )
    return {"calls": calls, "total": total, "page": page, "per_page": per_page}


@router.get("/calls/{call_id}")
def api_call_detail(call_id: str):
    """Детали одного звонка с результатами анализа."""
    call = get_call(_db, call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    # Подставить имя оператора из справочника, если не задано в звонке
    if not call.get("operator_name") and call.get("operator_extension"):
        name = get_operator_name(_db, call["domain"], call["operator_extension"])
        if name:
            call["operator_name"] = name

    proc = get_processing(_db, call_id)
    return {**call, "processing": dict(proc) if proc else None}


@router.get("/stats")
def api_stats(domain: str | None = None):
    """Сводная статистика."""
    total = get_calls_count(_db, domain=domain)
    pending = get_calls_count(_db, domain=domain, status="pending")
    processing = get_calls_count(_db, domain=domain, status="processing")
    done = get_calls_count(_db, domain=domain, status="done")
    error = get_calls_count(_db, domain=domain, status="error")
    skipped = get_calls_count(_db, domain=domain, status="skipped")

    return {
        "total_calls": total,
        "pending": pending,
        "processing": processing,
        "done": done,
        "error": error,
        "skipped": skipped,
    }


@router.get("/domains")
def api_domains():
    """Список настроенных доменов."""
    result = []
    for domain, cfg in _domain_configs.items():
        total = get_calls_count(_db, domain=domain)
        done = get_calls_count(_db, domain=domain, status="done")
        result.append({
            "domain": domain,
            "enabled": cfg.enabled,
            "profile": cfg.profile,
            "polling_interval_min": cfg.polling_interval_min,
            "total_calls": total,
            "done_calls": done,
        })
    return result


@router.get("/operators/{domain}")
def api_operators(domain: str):
    """Список операторов домена."""
    return list_operators(_db, domain)


@router.get("/departments/{domain}")
def api_departments(domain: str):
    """Список отделов домена."""
    return list_departments(_db, domain)


@router.get("/audio/{call_id}")
def api_audio(call_id: str):
    """Отдать аудиофайл звонка."""
    proc = get_processing(_db, call_id)
    if not proc or not proc.get("audio_path"):
        raise HTTPException(status_code=404, detail="Audio not found")
    audio_path = Path(proc["audio_path"]).resolve()
    if not audio_path.is_relative_to(Path(DATA_DIR).resolve()):
        raise HTTPException(status_code=404, detail="Audio not found")
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file missing")
    return FileResponse(audio_path, media_type="audio/mpeg")

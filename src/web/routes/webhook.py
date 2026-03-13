"""Webhook-приёмник для событий от Гравител АТС."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request

from src.db import insert_call, insert_processing, get_call
from src.call_filter import filter_call
from src.domain_config import DomainConfig

logger = logging.getLogger(__name__)

router = APIRouter()

_db = None
_domain_configs: dict[str, DomainConfig] = {}
_api_keys: dict[str, str] = {}
_on_new_call = None


def set_dependencies(
    db,
    domain_configs: dict[str, DomainConfig],
    api_keys: dict[str, str],
    on_new_call=None,
):
    """Установить зависимости для webhook-роутов.

    Args:
        db: соединение с SQLite БД.
        domain_configs: конфигурации доменов {домен: DomainConfig}.
        api_keys: API-ключи {домен: ключ}.
        on_new_call: callback при новом звонке (опционально).
    """
    global _db, _domain_configs, _api_keys, _on_new_call
    _db = db
    _domain_configs = domain_configs
    _api_keys = api_keys
    _on_new_call = on_new_call


@router.post("/webhook/{domain}/history")
async def receive_history(domain: str, request: Request, x_api_key: str = Header(None)):
    """Принять webhook от АТС о завершённом звонке.

    Маршрут: POST /webhook/{domain}/history

    Проверки:
    1. Домен должен быть в конфигурации.
    2. API-ключ должен совпадать с ожидаемым.
    3. Дубликат (по call ID) — идемпотентный ответ.
    4. Фильтрация по правилам домена (длительность, тип, наличие записи).
    """
    # 1. Проверка домена
    if domain not in _domain_configs:
        raise HTTPException(status_code=404, detail="Unknown domain")

    # 2. Проверка API-ключа
    expected_key = _api_keys.get(domain)
    if not x_api_key or x_api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    body = await request.json()

    # Конвертация Unix-таймстампа в ISO-формат
    when = body.get("when")
    started_at = (
        datetime.fromtimestamp(when, tz=timezone.utc).isoformat()
        if isinstance(when, (int, float))
        else when
    )

    now_iso = datetime.now(timezone.utc).isoformat()

    call = {
        "id": body["id"],
        "domain": domain,
        "direction": body.get("direction", ""),
        "result": body.get("result", ""),
        "duration": body.get("duration", 0),
        "wait": body.get("provision", 0),
        "started_at": started_at,
        "client_number": body.get("client", ""),
        "operator_extension": body.get("extension", ""),
        "operator_name": None,
        "phone": body.get("phone", ""),
        "record_url": body.get("record", ""),
        "source": "webhook",
        "received_at": now_iso,
    }

    # 3. Дедупликация — повторный webhook для того же звонка
    if get_call(_db, call["id"]):
        logger.debug("Дубликат webhook: %s", call["id"])
        return {"status": "duplicate"}

    insert_call(_db, call)

    # 4. Фильтрация по правилам домена
    config = _domain_configs[domain]
    passed, reason = filter_call(call, config.filters)

    if passed:
        insert_processing(_db, call["id"], status="pending")
        logger.info("Webhook: новый звонок %s -> pending", call["id"])
        if _on_new_call:
            _on_new_call(call["id"])
    else:
        insert_processing(_db, call["id"], status="skipped", skip_reason=reason)
        logger.info("Webhook: звонок %s -> skipped (%s)", call["id"], reason)

    return {"status": "ok"}

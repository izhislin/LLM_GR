"""FastAPI-приложение — точка входа веб-сервера."""

import asyncio
import logging
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from src.config import PROJECT_ROOT, DATA_DIR
from src.db import init_db, update_domain_poll_time, upsert_operator, upsert_department, reset_stale_processing
from src.metrics import start_metrics_server
from src.domain_config import load_domains_config
from src.gravitel_api import GravitelClient
from src.worker import CallWorker
from src.web.routes import webhook, api, openai_compat

load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "calls.db"
AUDIO_DIR = DATA_DIR / "audio"
TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

# Глобальные объекты (инициализируются в lifespan)
_db = None
_worker = None
_executor = ThreadPoolExecutor(max_workers=1)
_api_clients: dict[str, GravitelClient] = {}
_domain_configs = {}
_scheduler_task = None


def _resolve_api_keys(configs: dict) -> dict[str, str]:
    """Получить API-ключи из переменных окружения."""
    keys = {}
    for domain, cfg in configs.items():
        key = os.environ.get(cfg.api_key_env, "")
        if not key:
            logger.warning("API-ключ %s не задан для %s", cfg.api_key_env, domain)
        keys[domain] = key
    return keys


def _resolve_webhook_keys(configs: dict) -> dict[str, str]:
    """Получить webhook-ключи из переменных окружения."""
    keys = {}
    for domain, cfg in configs.items():
        env_name = cfg.webhook_key_env
        if not env_name:
            continue
        key = os.environ.get(env_name, "")
        if not key:
            logger.warning("Webhook-ключ %s не задан для %s", env_name, domain)
        keys[domain] = key
    return keys


async def _sync_directory(domain: str, client: GravitelClient) -> None:
    """Синхронизировать справочники (operators, departments) для домена."""
    try:
        accounts = await client.fetch_accounts()
        for acc in accounts:
            upsert_operator(_db, domain, acc.get("extension", ""), acc.get("name", ""))
        logger.info("Синхронизировано %d операторов для %s", len(accounts), domain)
    except Exception as e:
        logger.error("Ошибка синхронизации accounts %s: %s", domain, e)

    try:
        groups = await client.fetch_groups()
        for grp in groups:
            upsert_department(
                _db, domain, grp.get("id", 0), grp.get("extension", ""), grp.get("name", "")
            )
        logger.info("Синхронизировано %d отделов для %s", len(groups), domain)
    except Exception as e:
        logger.error("Ошибка синхронизации groups %s: %s", domain, e)


async def _poll_domain(
    domain: str,
    client: GravitelClient,
    *,
    start: str | None = None,
    end: str | None = None,
) -> None:
    """Опросить историю звонков домена и добавить новые / обновить существующие.

    Если звонок уже есть в БД (создан webhook-ом) но без record_url —
    обновляет его данными из polling и переводит в pending при прохождении фильтров.

    Args:
        domain: домен компании-клиента.
        client: HTTP-клиент Gravitel API.
        start: начало диапазона дат (ISO). Если не задан — используется period='today'.
        end: конец диапазона дат (ISO). Если не задан — используется period='today'.
    """
    from src.db import (
        insert_call, insert_processing, get_call,
        update_call_from_polling, reopen_processing,
    )
    from src.call_filter import filter_call

    try:
        if start and end:
            calls = await client.fetch_history(start=start, end=end)
        else:
            calls = await client.fetch_history(period="today")

        new_count = 0
        updated_count = 0
        for raw in calls:
            call_id = str(raw.get("id", ""))
            if not call_id:
                continue

            call = {
                "id": call_id,
                "domain": domain,
                "direction": raw.get("type", ""),
                "result": "success" if raw.get("duration", 0) > 0 else "missed",
                "duration": raw.get("duration", 0),
                "wait": raw.get("wait", 0),
                "started_at": raw.get("start", ""),
                "client_number": raw.get("client", ""),
                "operator_extension": raw.get("account", ""),
                "operator_name": None,
                "phone": raw.get("via", ""),
                "record_url": raw.get("record", ""),
                "source": "polling",
                "received_at": raw.get("start", ""),
            }

            existing = get_call(_db, call_id)
            if existing:
                # Обновить звонок, если record_url ещё пуст (webhook создал без записи)
                if not existing["record_url"] and call["record_url"]:
                    update_call_from_polling(_db, call_id, call)
                    config = _domain_configs[domain]
                    passed, _reason = filter_call(call, config.filters)
                    if passed and reopen_processing(_db, call_id):
                        updated_count += 1
                continue

            insert_call(_db, call)
            config = _domain_configs[domain]
            passed, reason = filter_call(call, config.filters)

            if passed:
                insert_processing(_db, call["id"], status="pending")
                new_count += 1
            else:
                insert_processing(_db, call["id"], status="skipped", skip_reason=reason)

        update_domain_poll_time(_db, domain)
        if new_count or updated_count:
            logger.info(
                "Polling %s: %d новых, %d обновлено", domain, new_count, updated_count
            )
    except Exception as e:
        logger.error("Polling ошибка %s: %s", domain, e)


async def _scheduler_loop():
    """Фоновый цикл: polling + обработка + синхронизация справочников."""
    sync_counter = 0
    while True:
        try:
            for domain, cfg in _domain_configs.items():
                if not cfg.enabled:
                    continue
                client = _api_clients.get(domain)
                if client:
                    await _poll_domain(domain, client)

            stale = reset_stale_processing(_db)
            if stale:
                logger.info("Сброшено %d зависших записей", stale)

            # Обрабатывать пачками пока есть pending, без 10-мин паузы между ними
            loop = asyncio.get_event_loop()
            while True:
                processed = await loop.run_in_executor(_executor, _worker.process_pending)
                if not processed:
                    break

            sync_counter += 1
            if sync_counter >= 6:
                sync_counter = 0
                for domain, client in _api_clients.items():
                    await _sync_directory(domain, client)

        except Exception as e:
            logger.error("Scheduler error: %s", e)

        await asyncio.sleep(600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация при старте, очистка при остановке."""
    global _db, _worker, _domain_configs, _api_clients, _scheduler_task

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _db = init_db(str(DB_PATH))

    start_metrics_server()

    _domain_configs = load_domains_config()
    api_keys = _resolve_api_keys(_domain_configs)
    webhook_keys = _resolve_webhook_keys(_domain_configs)

    for domain, cfg in _domain_configs.items():
        if cfg.enabled and api_keys.get(domain):
            _api_clients[domain] = GravitelClient(domain, api_keys[domain])

    _worker = CallWorker(
        db=_db,
        audio_dir=AUDIO_DIR,
        domain_configs=_domain_configs,
        api_clients=_api_clients,
    )

    def _on_new_call(call_id: str):
        """Запустить обработку звонка в фоне сразу после webhook."""
        _executor.submit(_worker.process_one, call_id)
        logger.info("Webhook → обработка %s запущена в фоне", call_id)

    webhook.set_dependencies(
        db=_db,
        domain_configs=_domain_configs,
        api_keys=webhook_keys,
        on_new_call=_on_new_call,
    )
    api.set_dependencies(db=_db, domain_configs=_domain_configs)

    for domain, client in _api_clients.items():
        await _sync_directory(domain, client)

    # Одноразовый бэкфилл: обновить звонки за последние 7 дней,
    # чтобы подтянуть record_url для webhook-звонков, пропущенных ранее.
    async def _backfill():
        from datetime import datetime, timedelta, timezone
        today = datetime.now(timezone.utc).date()
        for days_ago in range(7, 0, -1):
            day = today - timedelta(days=days_ago)
            start = day.isoformat()
            end = (day + timedelta(days=1)).isoformat()
            for domain, client in _api_clients.items():
                if _domain_configs[domain].enabled:
                    await _poll_domain(domain, client, start=start, end=end)
        logger.info("Бэкфилл завершён: 7 дней обновлено")

    asyncio.create_task(_backfill())

    _scheduler_task = asyncio.create_task(_scheduler_loop())
    logger.info("AI Lab Web запущен. Доменов: %d", len(_domain_configs))

    yield

    _scheduler_task.cancel()
    _executor.shutdown(wait=False)
    for client in _api_clients.values():
        await client.close()
    _db.close()
    logger.info("AI Lab Web остановлен.")


# ── Basic Auth Middleware ─────────────────────────────────────────────────────

_OPEN_PREFIXES = ("/webhook/", "/metrics", "/v1/")


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """HTTP Basic Auth для всех маршрутов, кроме webhook и metrics."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Webhook и metrics — без basic auth
        for prefix in _OPEN_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        username = os.environ.get("WEB_USERNAME", "")
        password = os.environ.get("WEB_PASSWORD", "")

        # Если пароль не настроен — пропускаем auth
        if not username or not password:
            return await call_next(request)

        import base64
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8")
                req_user, req_pass = decoded.split(":", 1)
                if (secrets.compare_digest(req_user, username)
                        and secrets.compare_digest(req_pass, password)):
                    return await call_next(request)
            except Exception:
                pass

        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="AI Lab"'},
            content="Unauthorized",
        )


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="AI Lab — Анализ звонков", lifespan=lifespan)

app.add_middleware(BasicAuthMiddleware)
app.include_router(webhook.router)
app.include_router(api.router)
app.include_router(openai_compat.router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Главная страница."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/call/{call_id}", response_class=HTMLResponse)
async def call_detail(request: Request, call_id: str):
    """Страница деталей звонка."""
    return templates.TemplateResponse("call_detail.html", {
        "request": request,
        "call_id": call_id,
    })


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """Страница чата с LLM."""
    return templates.TemplateResponse("chat.html", {"request": request})


@app.post("/api/sync/{domain}")
async def manual_sync(domain: str):
    """Ручной запуск polling для домена."""
    client = _api_clients.get(domain)
    if not client:
        raise HTTPException(status_code=404, detail="Domain not configured")

    await _poll_domain(domain, client)

    loop = asyncio.get_event_loop()
    processed = await loop.run_in_executor(_executor, _worker.process_pending)

    return {"status": "ok", "processed": processed}

"""FastAPI-приложение — точка входа веб-сервера."""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config import PROJECT_ROOT, DATA_DIR
from src.db import init_db, update_domain_poll_time, upsert_operator, upsert_department
from src.metrics import start_metrics_server
from src.domain_config import load_domains_config
from src.gravitel_api import GravitelClient
from src.worker import CallWorker
from src.web.routes import webhook, api

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


async def _poll_domain(domain: str, client: GravitelClient) -> None:
    """Опросить историю звонков домена и добавить новые в очередь."""
    from src.db import insert_call, insert_processing, get_call
    from src.call_filter import filter_call

    try:
        calls = await client.fetch_history(period="today")
        new_count = 0
        for raw in calls:
            call_id = str(raw.get("id", ""))
            if not call_id or get_call(_db, call_id):
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

            insert_call(_db, call)
            config = _domain_configs[domain]
            passed, reason = filter_call(call, config.filters)

            if passed:
                insert_processing(_db, call["id"], status="pending")
                new_count += 1
            else:
                insert_processing(_db, call["id"], status="skipped", skip_reason=reason)

        update_domain_poll_time(_db, domain)
        if new_count:
            logger.info("Polling %s: %d новых звонков", domain, new_count)
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

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(_executor, _worker.process_pending)

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

    webhook.set_dependencies(
        db=_db,
        domain_configs=_domain_configs,
        api_keys=webhook_keys,
        on_new_call=lambda call_id: None,
    )
    api.set_dependencies(db=_db, domain_configs=_domain_configs)

    for domain, client in _api_clients.items():
        await _sync_directory(domain, client)

    _scheduler_task = asyncio.create_task(_scheduler_loop())
    logger.info("AI Lab Web запущен. Доменов: %d", len(_domain_configs))

    yield

    _scheduler_task.cancel()
    _executor.shutdown(wait=False)
    for client in _api_clients.values():
        await client.close()
    _db.close()
    logger.info("AI Lab Web остановлен.")


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="AI Lab — Анализ звонков", lifespan=lifespan)

app.include_router(webhook.router)
app.include_router(api.router)

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

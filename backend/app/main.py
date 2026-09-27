import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import json
import aiosqlite
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from app.api.auth import router as auth_router
from app.api.bots import router as bots_router
from app.api.flows import router as flows_router
from app.api.fonts import router as fonts_router
from app.api.i18n import router as i18n_router
from app.api.plugins import router as plugins_router
from app.api.simulator import router as simulator_router
from app.api.system import router as system_router
from app.api.webhook import router as webhook_router
from app.config import settings
from app.core.i18n import language_from_request, t
from app.core.security import decode_access_token, is_public_path
from app.database import init_db
from app.bot_worker import start_bot_worker, stop_bot_worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("MyBot")

ACTIVE_WORKERS: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting MyBot Engine...")
    await init_db()
    # Startup: register long-polling workers for every active bot
    try:
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT id, token, settings FROM bots WHERE is_active = 1")
            rows = await cursor.fetchall()
            for row in rows:
                st = json.loads(row["settings"]) if row["settings"] else {}
                task = start_bot_worker(int(row["id"]), row["token"], st)
                ACTIVE_WORKERS[int(row["id"])] = task
    except Exception as e:
        logger.warning(f"Could not start bot workers at startup: {e}")

    yield

    # Shutdown: cancel all polling workers gracefully
    for task in list(ACTIVE_WORKERS.values()):
        if not task.done():
            task.cancel()
    for t in ACTIVE_WORKERS.values():
        try:
            await t
        except Exception:
            pass
    ACTIVE_WORKERS.clear()
    logger.info("MyBot Engine shutting down.")

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url=None
)

# Auth guard for the whole panel API.
#
# A JWT used to be minted at login and then ignored: every /api route, including
# the one that shells out to deploy/update.sh, answered anonymous callers. Admin
# routers also carry an explicit `require_admin` dependency; this middleware is
# the default-deny net that catches routes added later. Registered before CORS
# so CORS ends up outermost and its headers reach these 401 responses.
@app.middleware("http")
async def guard_admin_api(request: Request, call_next):
    path, method = request.url.path, request.method
    if not path.startswith("/api") or is_public_path(path, method):
        return await call_next(request)

    lang = language_from_request(request)
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header[:7].lower() == "bearer " else ""
    try:
        if not token:
            raise HTTPException(status_code=401, detail=t("api.auth.required", lang))
        decode_access_token(token, lang)
    except HTTPException as error:
        return JSONResponse(
            status_code=error.status_code,
            content={"detail": error.detail},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await call_next(request)

# CORS
#
# `allow_origins=["*"]` combined with `allow_credentials=True` is rejected by
# every browser and lets any site issue credentialed requests; the panel is a
# single-tenant install, so the origins are configured explicitly (CORS_ORIGINS).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Routers
app.include_router(auth_router)
app.include_router(bots_router)
app.include_router(flows_router)
app.include_router(simulator_router)
app.include_router(webhook_router)
app.include_router(plugins_router)
app.include_router(system_router)
app.include_router(i18n_router)
app.include_router(fonts_router)

# Serve uploaded bot photos
from pathlib import Path
_UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
_UPLOAD_DIR.mkdir(exist_ok=True)
app.mount("/media", StaticFiles(directory=_UPLOAD_DIR), name="uploads")

@app.get("/")
async def health_check():
    """Liveness probe.

    This endpoint used to hand out `admin_secret_path`, which made the "secret"
    panel path public to anyone who opened the root URL.
    """
    return {
        "status": "online",
        "app": settings.APP_NAME,
        "version": settings.VERSION,
    }

import json
import os
import subprocess
import time
from typing import Any, Dict
import aiosqlite
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.config import settings
from app.core.i18n import language_from_request, t
from app.core.net import UrlPolicyError, validate_outbound_url
from app.core.security import require_admin
from app.database import get_db

router = APIRouter(prefix="/api/system", tags=["system"])

GITHUB_REPO = "mybot-engine/mybot"


class ProxyConfigRequest(BaseModel):
    cf_worker_url: str = ""
    http_proxy: str = ""
    proxy_mode: str = "all"  # 'all', 'selected', 'none'


@router.get("/info")
async def get_system_info(request: Request, admin: str = Depends(require_admin)) -> Dict[str, Any]:
    """Diagnostics for the settings screen.

    `admin_secret_path` used to be served here without authentication, which
    handed out the one thing protecting the panel. It is only ever returned by
    a successful login response now.
    """
    lang = language_from_request(request)
    return {
        "app_name": settings.APP_NAME,
        "version": settings.VERSION,
        "is_docker": os.path.exists("/.dockerenv"),
        "debug": settings.DEBUG,
        "role": settings.ROLE,
        "self_update_enabled": settings.ENABLE_SELF_UPDATE,
    }


@router.get("/proxy")
async def get_proxy_config(
    admin: str = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute("SELECT value FROM system_settings WHERE key = 'proxy_config'")
    row = await cursor.fetchone()
    if row and row["value"]:
        return json.loads(row["value"])
    return {
        "cf_worker_url": settings.CF_PROXY_URL,
        "http_proxy": settings.HTTP_PROXY,
        "proxy_mode": "all"
    }


@router.post("/proxy")
async def save_proxy_config(
    req: ProxyConfigRequest,
    admin: str = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    val = req.model_dump()
    if val.get("cf_worker_url"):
        try:
            validate_outbound_url(val["cf_worker_url"])
        except UrlPolicyError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    await db.execute("""
        INSERT INTO system_settings (key, value, updated_at)
        VALUES ('proxy_config', ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
    """, (json.dumps(val),))
    await db.commit()

    # If proxy_mode is 'all', update all bots settings
    if req.proxy_mode == "all":
        cursor = await db.execute("SELECT id, settings FROM bots")
        bots = await cursor.fetchall()
        for b in bots:
            st = json.loads(b["settings"]) if b["settings"] else {}
            st["cf_worker_url"] = req.cf_worker_url
            st["custom_proxy"] = req.http_proxy
            await db.execute("UPDATE bots SET settings = ? WHERE id = ?", (json.dumps(st), b["id"]))
        await db.commit()

    return {"success": True, "config": val}


@router.post("/proxy/test")
async def test_proxy_latency(
    req: ProxyConfigRequest,
    request: Request,
    admin: str = Depends(require_admin),
):
    """Tests latency to Cloudflare worker or Telegram API.

    The fetched target used to be whatever the browser sent, so anyone reaching
    the panel could make it request internal URLs through the supplied proxy
    (SSRF). Only public http(s) endpoints are accepted now.
    """
    lang = language_from_request(request)
    target_url = (req.cf_worker_url or "").strip().rstrip("/") or "https://api.telegram.org"
    try:
        validate_outbound_url(target_url)
    except UrlPolicyError as error:
        raise HTTPException(
            status_code=400, detail=t("api.net.blocked", lang, reason=str(error))
        ) from error

    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=6.0, proxy=req.http_proxy or None) as client:
            resp = await client.get(target_url)
            latency = round((time.time() - start) * 1000, 1)
            return {
                "success": True,
                "status_code": resp.status_code,
                "latency_ms": latency,
                "url": target_url,
                "message": t("api.net.ok", lang, ms=latency),
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "url": target_url,
            "message": t("api.net.failed", lang, error=str(e)),
        }

@router.get("/check-update")
async def check_update(request: Request, admin: str = Depends(require_admin)) -> Dict[str, Any]:
    return {
        "current_version": settings.VERSION,
        "latest_version": settings.VERSION,
        "has_update": False,
        "release_notes": t("api.system.up_to_date", language_from_request(request)),
        "self_update_enabled": settings.ENABLE_SELF_UPDATE,
    }

@router.post("/update")
async def trigger_update(request: Request, admin: str = Depends(require_admin)):
    """Runs deploy/update.sh — but only for a signed-in admin who opted in.

    This endpoint used to be unauthenticated and ran a bash script as soon as it
    existed, i.e. unauthenticated remote code execution on every VPS install.
    """
    lang = language_from_request(request)
    if not settings.ENABLE_SELF_UPDATE:
        raise HTTPException(status_code=403, detail=t("api.system.update_disabled", lang))

    update_script = os.environ.get("UPDATE_SCRIPT_PATH", "/app/deploy/update.sh")
    if not os.path.exists(update_script):
        raise HTTPException(status_code=404, detail=t("api.system.update_script_missing", lang))

    subprocess.Popen([
        "bash", update_script
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return {"success": True, "message": t("api.system.update_started", lang)}

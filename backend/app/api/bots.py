import json
import logging
import uuid
from io import BytesIO
from PIL import Image, ImageOps, UnidentifiedImageError
from aiogram import Bot
from aiogram.types import BufferedInputFile, InputProfilePhotoStatic
from pathlib import Path
from typing import Any, Dict, List
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request, status, UploadFile, File

from app.core.i18n import language_from_request, t
from app.database import get_db
from app.database_bots import AVAILABLE_USER_FIELDS, DEFAULT_TRACKED_FIELDS, get_bot_db, get_bot_db_path
from app.models.schemas import BotCreateRequest, BotResponse, BotSettingsUpdate
from app.telegram.bot_manager import bot_manager

logger = logging.getLogger("MyBot.BotsAPI")

router = APIRouter(prefix="/api/bots", tags=["bots"])

# Telegram profile pictures are small; the cap exists so a 2 GB upload cannot
# turn into a 2 GB in-memory PIL decode.
MAX_AVATAR_BYTES = 10 * 1024 * 1024

@router.get("", response_model=List[Dict[str, Any]])
async def list_bots(db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute("""
        SELECT id, name, username, telegram_bot_id, is_active, settings, created_at
        FROM bots ORDER BY id DESC
    """)
    rows = await cursor.fetchall()
    bots = []
    for r in rows:
        s = json.loads(r["settings"]) if r["settings"] else {}
        s.pop("token", None)
        bots.append({
            "id": r["id"],
            "name": r["name"],
            "username": r["username"],
            "telegram_bot_id": r["telegram_bot_id"],
            "is_active": bool(r["is_active"]),
            "settings": s,
            "photo_url": s.get("photo_url") or "/media/default-bot.png",
            "default_photo_url": "/media/default-bot.png",
            "created_at": str(r["created_at"])
        })
    return bots

@router.post("", response_model=Dict[str, Any])
async def create_bot(req: BotCreateRequest, db: aiosqlite.Connection = Depends(get_db)):
    try:
        new_bot = await bot_manager.register_new_bot(
            token=req.token.strip(),
            db=db,
            custom_proxy=req.custom_proxy,
            cf_worker_url=req.cf_worker_url
        )
        new_bot["photo_url"] = "/media/default-bot.png"
        try:
            default_file = Path(__file__).resolve().parent.parent.parent / "uploads" / "default-bot.png"
            with default_file.open("rb") as image:
                photo = await upload_bot_avatar(new_bot["id"], UploadFile(filename="default.png", file=image), db)
            new_bot["photo_url"] = photo["photo_url"]
            new_bot["telegram_photo_synced"] = True
        except Exception:
            # Registration has committed: never report it as failed or invite duplicate creation.
            new_bot["telegram_photo_synced"] = False
        return {"success": True, "bot": new_bot}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/{bot_id}")
async def get_bot(bot_id: int, request: Request, db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute(
        "SELECT id, name, username, telegram_bot_id, is_active, settings, created_at FROM bots WHERE id = ?",
        (bot_id,)
    )
    bot = await cursor.fetchone()
    if not bot:
        raise HTTPException(status_code=404, detail=t("api.bot.not_found", language_from_request(request)))
    settings_dict = json.loads(bot["settings"]) if bot["settings"] else {}
    settings_dict.pop("token", None)
    return {
        "id": bot["id"],
        "name": bot["name"],
        "username": bot["username"],
        "telegram_bot_id": bot["telegram_bot_id"],
        "is_active": bool(bot["is_active"]),
        "settings": settings_dict,
        "photo_url": settings_dict.get("photo_url") or "/media/default-bot.png",
        "default_photo_url": "/media/default-bot.png",
        "created_at": str(bot["created_at"])
    }

@router.put("/{bot_id}/settings")
async def update_bot_settings(bot_id: int, req: BotSettingsUpdate, request: Request, db: aiosqlite.Connection = Depends(get_db)):
    lang = language_from_request(request)
    cursor = await db.execute("SELECT id, name, username, is_active, settings, token FROM bots WHERE id = ?", (bot_id,))
    bot = await cursor.fetchone()
    if not bot:
        raise HTTPException(status_code=404, detail=t("api.bot.not_found", lang))
        
    current = json.loads(bot["settings"]) if bot["settings"] else {}
    current.pop("token", None)
    update_data = req.model_dump(exclude_unset=True)
    
    name_val = update_data.pop("name", None)
    username_val = update_data.pop("username", None)
    token_val = update_data.pop("token", None)
    is_active_val = update_data.pop("is_active", None)
    current.update(update_data)
    
    new_name = name_val if name_val is not None else bot["name"]
    # Bot API cannot rename usernames. Only verified Telegram identity may change it.
    if username_val is not None and username_val != bot["username"]:
        raise HTTPException(status_code=400, detail="bot_username_read_only")
    new_username = bot["username"]
    new_token = bot["token"]
    new_bot_id = None

    if token_val and token_val.strip() and token_val.strip() != bot["token"]:
        clean_tok = token_val.strip()
        try:
            verif = await bot_manager.verify_token(
                clean_tok,
                current.get("cf_worker_url"),
                current.get("custom_proxy"),
                db=db
            )
        except Exception:
            raise HTTPException(status_code=400, detail="bot_token_verification_failed") from None
        if not verif.get("valid") or not verif.get("id") or not verif.get("username"):
            raise HTTPException(status_code=400, detail="bot_token_verification_failed")
        new_token = clean_tok
        new_bot_id = verif["id"]
        if verif.get("first_name") and name_val is None:
            new_name = verif["first_name"]
        new_username = verif["username"]

    new_active = int(is_active_val) if is_active_val is not None else bot["is_active"]

    if new_bot_id:
        await db.execute(
            "UPDATE bots SET name = ?, username = ?, token = ?, telegram_bot_id = ?, is_active = ?, settings = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_name, new_username, new_token, new_bot_id, new_active, json.dumps(current), bot_id)
        )
    else:
        await db.execute(
            "UPDATE bots SET name = ?, username = ?, is_active = ?, settings = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_name, new_username, new_active, json.dumps(current), bot_id)
        )
    await db.commit()

    # Local save succeeds independently of Telegram profile synchronization.
    requested_presence = {key: value for key, value in {
        "name": name_val, "bio": update_data.get("bio"),
        "description": update_data.get("description")
    }.items() if value is not None}
    telegram_sync = {key: False for key in requested_presence}
    try:
        if new_token and requested_presence:
            sync_result = await bot_manager.sync_bot_presence(
                token=new_token,
                settings_dict=current,
                name=name_val,
                bio=update_data.get("bio"),
                description=update_data.get("description")
            )
            telegram_sync = {key: bool(sync_result.get(key)) for key in requested_presence}
    except Exception:
        logger.warning("Could not push presence to Telegram for bot %s", bot_id)

    return {
        "success": True,
        "telegram_sync": telegram_sync,
        "name": new_name,
        "username": new_username,
        "is_active": bool(new_active),
        "settings": current
    }

@router.post("/{bot_id}/toggle-active")
async def toggle_bot_active(bot_id: int, request: Request, db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute("SELECT is_active FROM bots WHERE id = ?", (bot_id,))
    bot = await cursor.fetchone()
    if not bot:
        raise HTTPException(status_code=404, detail=t("api.bot.not_found", language_from_request(request)))
    new_state = 0 if bot["is_active"] else 1
    await db.execute("UPDATE bots SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_state, bot_id))
    await db.commit()
    return {"success": True, "is_active": bool(new_state)}

@router.delete("/{bot_id}")
async def delete_bot(bot_id: int, db: aiosqlite.Connection = Depends(get_db)):
    await db.execute("DELETE FROM bots WHERE id = ?", (bot_id,))
    await db.commit()
    return {"success": True, "deleted_id": bot_id}

@router.post("/{bot_id}/sync-commands")
async def sync_commands(bot_id: int, request: Request, db: aiosqlite.Connection = Depends(get_db)):
    await bot_manager.sync_bot_commands(bot_id, db)
    return {"success": True, "message": t("api.bot.commands_synced", language_from_request(request))}


@router.post("/{bot_id}/refresh")
async def refresh_bot(bot_id: int, db: aiosqlite.Connection = Depends(get_db)):
    try:
        updated = await bot_manager.refresh_bot_info(bot_id, db)
        return {"status": "ok", "bot": updated}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{bot_id}/avatar")
async def upload_bot_avatar(
    bot_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: aiosqlite.Connection = Depends(get_db),
) -> Dict[str, Any]:
    """Upload a static JPG using Telegram setMyProfilePhoto, then save preview."""
    lang = language_from_request(request)
    cursor = await db.execute("SELECT token, settings FROM bots WHERE id = ?", (bot_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=t("api.bot.not_found", lang))
    content = await file.read(MAX_AVATAR_BYTES + 1)
    if len(content) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail=t("api.bot.avatar_too_large", lang))
    try:
        with Image.open(BytesIO(content)) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError("image too large")
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((2048, 2048))
            encoded = BytesIO()
            image.save(encoded, format="JPEG", quality=90)
            content = encoded.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(status_code=400, detail=t("api.bot.avatar_invalid", lang)) from None
    settings_dict = json.loads(row["settings"]) if row["settings"] else {}
    proxy = None
    try:
        cursor = await db.execute("SELECT value FROM system_settings WHERE key = 'proxy_config'")
        proxy_row = await cursor.fetchone()
        if proxy_row and proxy_row["value"]:
            proxy = json.loads(proxy_row["value"]).get("http_proxy")
    except aiosqlite.OperationalError:
        pass
    session = bot_manager.get_api_session(settings_dict.get("cf_worker_url"), settings_dict.get("custom_proxy"), db_proxy_url=proxy)
    bot = Bot(token=row["token"], session=session)
    try:
        success = await bot.set_my_profile_photo(photo=InputProfilePhotoStatic(
            photo=BufferedInputFile(content, filename="avatar.jpg")), request_timeout=30)
        if success is not True:
            raise HTTPException(status_code=502, detail=t("api.bot.photo_rejected", lang))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail=t("api.bot.photo_failed", lang)) from None
    finally:
        await bot.session.close()
    upload_dir = Path(__file__).resolve().parent.parent.parent / "uploads"
    upload_dir.mkdir(exist_ok=True)
    fname = f"bot_{bot_id}_{uuid.uuid4().hex}.jpg"
    dest = upload_dir / fname
    dest.write_bytes(content)
    photo_url = f"/media/{fname}"
    settings_dict["photo_url"] = photo_url
    await db.execute("UPDATE bots SET settings = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                     (json.dumps(settings_dict), bot_id))
    await db.commit()
    return {"status": "ok", "photo_url": photo_url, "telegram_synced": True}


@router.get("/{bot_id}/database-schema")
async def get_bot_database_schema(bot_id: int, request: Request, db: aiosqlite.Connection = Depends(get_db)) -> Dict[str, Any]:
    """Returns database configuration for this specific bot: isolated DB path, active tracked fields, and available fields."""
    cursor = await db.execute("SELECT settings FROM bots WHERE id = ?", (bot_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=t("api.bot.not_found", language_from_request(request)))

    settings_dict = json.loads(row["settings"]) if row["settings"] else {}
    tracked = settings_dict.get("tracked_user_fields")
    if not isinstance(tracked, list):
        tracked = DEFAULT_TRACKED_FIELDS

    # Query subscriber count from this bot's own dedicated database
    sub_count = 0
    try:
        bot_db = await get_bot_db(bot_id)
        c = await bot_db.execute("SELECT COUNT(*) AS total FROM subscribers")
        r = await c.fetchone()
        sub_count = r["total"] if r else 0
        await bot_db.close()
    except Exception as e:
        logger.warning(f"Could not read subscriber count from bot_{bot_id}.db: {e}")

    return {
        "bot_id": bot_id,
        "database_file": str(get_bot_db_path(bot_id).name),
        "database_absolute_path": str(get_bot_db_path(bot_id)),
        "subscribers_count": sub_count,
        "tracked_fields": tracked,
        "available_fields": AVAILABLE_USER_FIELDS
    }


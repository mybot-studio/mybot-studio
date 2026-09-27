import json
import logging
from typing import Any, Dict
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from aiogram import Bot, types
from aiogram.enums import ParseMode

from app.core.i18n import language_from_request, t
from app.database import get_db
from app.engine.dag_runner import DAGRunner
from app.telegram.bot_manager import bot_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhook", tags=["webhook"])

@router.post("/{bot_id}/{secret}")
async def handle_telegram_webhook(
    bot_id: int,
    secret: str,
    request: Request,
    db: aiosqlite.Connection = Depends(get_db)
):
    """
    Receives Telegram updates via Webhook, executes the DAG flow,
    and replies back using Telegram Bot API.
    """
    cursor = await db.execute(
        "SELECT id, token, webhook_secret, settings FROM bots WHERE id = ? AND is_active = 1",
        (bot_id,)
    )
    bot_row = await cursor.fetchone()
    if not bot_row or bot_row["webhook_secret"] != secret:
        raise HTTPException(status_code=403, detail=t("api.webhook.denied", language_from_request(request)))

    raw_data = await request.json()
    token = bot_row["token"]
    settings_dict = json.loads(bot_row["settings"]) if bot_row["settings"] else {}

    # Extract update info
    event_type = "message"
    payload = ""
    user_info = {}
    chat_id = 0

    if "message" in raw_data:
        msg = raw_data["message"]
        chat_id = msg.get("chat", {}).get("id", 0)
        from_user = msg.get("from", {})
        user_info = {
            "id": from_user.get("id"),
            "username": from_user.get("username", ""),
            "first_name": from_user.get("first_name", ""),
            "last_name": from_user.get("last_name", ""),
            "language_code": from_user.get("language_code", "fa")
        }
        text = msg.get("text", "")
        if text.startswith("/"):
            event_type = "command"
            payload = text
        else:
            event_type = "message"
            payload = text

    elif "callback_query" in raw_data:
        cb = raw_data["callback_query"]
        event_type = "callback"
        payload = cb.get("data", "")
        chat_id = cb.get("message", {}).get("chat", {}).get("id", 0)
        from_user = cb.get("from", {})
        user_info = {
            "id": from_user.get("id"),
            "username": from_user.get("username", ""),
            "first_name": from_user.get("first_name", ""),
            "last_name": from_user.get("last_name", ""),
            "language_code": from_user.get("language_code", "fa")
        }

    # Setup Bot Client
    session = bot_manager.get_api_session(
        settings_dict.get("cf_worker_url"), settings_dict.get("custom_proxy")
    )
    bot = Bot(token=token, session=session)

    try:
        runner = DAGRunner(bot_id=bot_id, db=db)
        result = await runner.execute_flow(
            event_type=event_type,
            payload=payload,
            user_info=user_info,
            bot_client=bot,
            chat_id=chat_id
        )

        # Send produced messages to Telegram
        for m in result.get("messages", []):
            text = m.get("text", "")
            markup = m.get("reply_markup")
            mtype = m.get("media_type", "text")
            murl = m.get("media_url", "")

            # Telegram Bot API formatting
            reply_markup = None
            if markup and "inline_keyboard" in markup:
                reply_markup = types.InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            types.InlineKeyboardButton(
                                text=b["text"],
                                callback_data=b.get("callback_data"),
                                url=b.get("url")
                            )
                            for b in row
                        ]
                        for row in markup["inline_keyboard"]
                    ]
                )

            if mtype == "text":
                await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            elif mtype == "photo" and murl:
                await bot.send_photo(chat_id=chat_id, photo=murl, caption=text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            elif mtype == "video" and murl:
                await bot.send_video(chat_id=chat_id, video=murl, caption=text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            elif mtype == "voice" and murl:
                await bot.send_voice(chat_id=chat_id, voice=murl, caption=text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            elif mtype == "document" and murl:
                await bot.send_document(chat_id=chat_id, document=murl, caption=text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

        # Answer callbacks if any
        if event_type == "callback" and "callback_query" in raw_data:
            cb_id = raw_data["callback_query"].get("id")
            alerts = result.get("alerts", [])
            alert_text = alerts[0]["text"] if alerts else None
            show_alert = alerts[0].get("show_alert", False) if alerts else False
            await bot.answer_callback_query(callback_query_id=cb_id, text=alert_text, show_alert=show_alert)

    except Exception as e:
        logger.error(f"Error handling webhook for bot {bot_id}: {e}")
    finally:
        await bot.session.close()

    return Response(status_code=200)

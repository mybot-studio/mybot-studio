import logging

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.i18n import language_from_request, t
from app.database import get_db
from app.models.schemas import SimulatorEventRequest, SimulatorResponse
from app.telegram.emulator import run_simulation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/simulator", tags=["simulator"])

@router.post("/dispatch", response_model=SimulatorResponse)
async def dispatch_simulation_event(
    req: SimulatorEventRequest,
    request: Request,
    db: aiosqlite.Connection = Depends(get_db)
):
    """
    Executes a simulated event through the DAG engine for live testing inside the floating mockup.
    """
    lang = language_from_request(request)
    user_info = {
        "id": req.user_id or 99999999,
        "username": req.username or "tester",
        "first_name": req.first_name or "Tester",
        "language_code": lang
    }

    try:
        result = await run_simulation(
            bot_id=req.bot_id,
            event_type=req.event_type,
            payload=req.payload,
            user_info=user_info,
            db=db
        )

        alerts_list = []
        for a in result.get("alerts", []):
            if isinstance(a, dict):
                alerts_list.append(a.get("text", ""))
            else:
                alerts_list.append(str(a))

        return SimulatorResponse(
            success=result.get("success", False),
            messages=result.get("messages", []),
            alerts=alerts_list,
            chat_actions=result.get("chat_actions", []),
            user_state=result.get("user_state", {}),
            logs=[t("api.simulator.executed_steps", lang, steps=result.get("steps_executed", []))]
        )
    except Exception as error:
        # The traceback belongs in the server log; the panel gets a translated
        # sentence so a broken flow cannot leak Python internals to the browser.
        logger.exception("Simulation failed for bot %s", req.bot_id)
        raise HTTPException(
            status_code=500,
            detail=t("api.simulator.failed", lang)
        ) from error

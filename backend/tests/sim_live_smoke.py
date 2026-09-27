"""Manual live smoke for the simulator DAG path.

Run from `backend/` against a dev database::

    .venv/Scripts/python tests/sim_live_smoke.py          # backend/data/mybot.db
    SIM_LIVE_DB=/path/to/bot.db .venv/Scripts/python tests/sim_live_smoke.py

It dispatches a couple of simulated events through the DAG engine, mirroring
what the floating preview's ``/api/simulator/dispatch`` endpoint does. This is a
live, out-of-ASGI harness, so it builds a ``Request``-shaped object for the
language resolver. It is deliberately NOT collected by pytest (see the
``launcher_live_smoke.py`` convention): the ``test_`` prefix is reserved for
real unit tests.
"""

import asyncio
import os
import sys
from types import SimpleNamespace

# `app` lives in the backend/ directory, two levels above this file.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiosqlite

from app.api.simulator import dispatch_simulation_event
from app.models.schemas import SimulatorEventRequest

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "mybot.db")


def fake_request(lang: str = "en") -> SimpleNamespace:
    """A ``Request``-shaped stand-in for the language resolver, out of ASGI.

    ``language_from_request`` only reads ``request.query_params`` and
    ``request.headers``; that is all a live harness needs.
    """
    return SimpleNamespace(query_params={}, headers={"accept-language": lang})


async def main() -> None:
    db_path = os.environ.get("SIM_LIVE_DB", DEFAULT_DB)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        for event_type, payload in (("command", "/start"), ("callback", "btn_claim")):
            req = SimulatorEventRequest(bot_id=1, event_type=event_type, payload=payload)
            res = await dispatch_simulation_event(req, fake_request(), db)
            print("OK", event_type, "msgs:", len(res.messages), "state:", res.user_state)


if __name__ == "__main__":
    asyncio.run(main())

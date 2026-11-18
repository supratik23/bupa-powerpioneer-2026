"""
GET /nudges/next - one supportive on-screen nudge (drink water, stretch, breathe...) for the logged-in employee.

Called by PowerPioneer-Frontend on a timer (every minute). The response options are display-only:
skip / acknowledge is handled in the browser and is NOT sent back (nothing is stored).
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException

from .checkin import resolve_caller   # also puts app/ on sys.path for `services.*`
from services.nudge_service import next_nudge, refill_in_background  # noqa: E402

logger = logging.getLogger(__name__)
nudge_router = APIRouter()


@nudge_router.get("/next")
def get_next_nudge(employee_id: UUID | None = None, authorization: str | None = Header(default=None)) -> dict:
    """Return the next supportive nudge. `employee_id` is only used when AGENT_REQUIRE_AUTH=false and no token is sent."""
    caller = resolve_caller(authorization, employee_id)
    try:
        nudge, start_refill = next_nudge(caller)
    except Exception as e:
        logger.exception("next nudge failed")
        raise HTTPException(500, f"Could not create a nudge: {e}") from e
    if start_refill:
        refill_in_background(caller)
    return nudge
